"""ReACT agent loop v1 (S3 step 1).

Drives an `LLMClient` in a tool-use loop, in the mode the capability probe
persisted for the endpoint (native_tools / prompted_tools / plan_only). The
caller passes that persisted mode straight through — the loop never calls
`decide_agent_mode` itself, because the thresholds may have drifted from what
was ratified when the endpoint was probed (NEXT-SESSION S3 guidance).

The mode selects a `ToolChannel` — the one seam that differs between modes:
how tools are offered and how tool calls are read back. Everything else (the
step loop, the permission gate, proposal filing) is identical across modes.

D-014 is enforced structurally here: every action record comes from a real
tool call routed through `_dispatch` → the gate. READ executes; WRITE/
DESTRUCTIVE file a proposal and DO NOT execute. Text the model writes claiming
an action happened produces no invocation and no proposal.

SARA pattern reference (reused, not copied): sara/core/agent_loop.py:59-.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from auspex.agent.permissions import PermissionOutcome, ProposalStore, gate
from auspex.agent.registry import ToolRegistry

if TYPE_CHECKING:
    # Type-only: auspex.actions imports auspex.agent.permissions for the gate, so
    # importing it here at runtime would close a cycle. The loop only ever reads
    # the manifest's rendered text.
    from auspex.actions import ActionManifest
from auspex.llm.capability import PROBE_MAX_TOKENS
from auspex.llm.client import ChatResult, ToolCall

# Loop step cap — chosen consciously, not copied from the harness (which capped
# per-task at 8 for scoring). The S2 task battery's deepest real chains need 4
# tool calls plus a synthesis turn; 8 leaves headroom for one self-correction
# without letting a confused weak model burn the endpoint indefinitely.
DEFAULT_MAX_STEPS = 8

DEFAULT_SYSTEM_PROMPT = (
    "You are Auspex, a security operations co-analyst. Use the provided tools to "
    "gather facts before answering. Never invent tool output, and never claim an "
    "action was performed unless a tool call actually performed it. When you have "
    "enough information, give a concise final answer."
)

_SYNTHESIS_NUDGE = (
    "You have reached the tool-use limit for this turn. Stop calling tools and give "
    "your best final answer using the results gathered so far."
)

# Prompted-mode wire protocol. One JSON object per tool call, fenced by the tags.
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


@dataclass
class ToolInvocation:
    """One tool call the loop actually acted on. `status` is the D-014 truth:
    'executed' (read handler ran), 'proposed' (write/destructive gated — NOT
    performed), or 'error' (unknown tool / bad args / handler raised)."""

    name: str
    arguments: dict[str, Any]
    status: str  # "executed" | "proposed" | "error"
    feedback: dict[str, Any]  # exactly what was fed back to the model
    level: str | None = None
    proposal_id: str | None = None


@dataclass
class AgentResult:
    content: str
    steps: int
    invocations: list[ToolInvocation]
    stopped_reason: str  # "final_answer" | "step_cap"
    mode: str = ""

    @property
    def executed(self) -> list[ToolInvocation]:
        return [i for i in self.invocations if i.status == "executed"]

    @property
    def proposed(self) -> list[ToolInvocation]:
        return [i for i in self.invocations if i.status == "proposed"]

    def performed(self, tool_name: str) -> bool:
        """D-014: a tool counts as PERFORMED only if a real call executed it.
        A model sentence like 'the ticket was created' never makes this true."""
        return any(i.name == tool_name and i.status == "executed" for i in self.invocations)


# --- Tool channels: the per-mode seam ---------------------------------------


class ToolChannel:
    """Base: native mode. Presents tools via the wire `tools` param and reads
    `result.tool_calls` back — the shape every probed endpoint uses natively."""

    offers_tools = True

    def system_prefix(self, specs: list[dict]) -> str:
        return ""

    def chat_kwargs(self, specs: list[dict]) -> dict[str, Any]:
        # tools=None on conversational turns (no specs) — the API takes it cleanly.
        return {"tools": specs} if specs else {}

    def extract_calls(self, result: ChatResult) -> list[ToolCall]:
        return list(result.tool_calls)

    def assistant_message(self, result: ChatResult, calls: list[ToolCall]) -> dict:
        return {
            "role": "assistant",
            "content": result.content or None,
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in calls
            ],
        }

    def tool_result_message(self, call: ToolCall, feedback: dict) -> dict:
        return {"role": "tool", "tool_call_id": call.id, "content": json.dumps(feedback)}


class PromptedToolChannel(ToolChannel):
    """Fallback for endpoints without reliable native tool calling: describe the
    tools in the system prompt and parse `<tool_call>{...}</tool_call>` blocks
    out of the model's text. Minimal but functional — the same loop, gate, and
    proposal path run unchanged behind it."""

    def system_prefix(self, specs: list[dict]) -> str:
        if not specs:
            return ""
        lines = ["", "", "You do not have native tool calling. To call a tool, emit one line:",
                 '<tool_call>{"name": "<tool>", "arguments": {<args>}}</tool_call>',
                 "You may emit several such lines. After each, I reply with a matching",
                 "<tool_result> block. When you are done, answer in plain text with no",
                 "<tool_call> lines. Available tools:"]
        for spec in specs:
            fn = spec["function"]
            params = ", ".join(fn["parameters"].get("properties", {}))
            lines.append(f"- {fn['name']}({params}): {fn['description']}")
        return "\n".join(lines)

    def chat_kwargs(self, specs: list[dict]) -> dict[str, Any]:
        return {}  # never put tools on the wire in prompted mode

    def extract_calls(self, result: ChatResult) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for blob in _TOOL_CALL_RE.findall(result.content or ""):
            try:
                obj = json.loads(blob)
            except ValueError:
                continue  # a malformed block is not a call — ignore, don't crash
            if isinstance(obj, dict) and obj.get("name"):
                calls.append(
                    ToolCall(name=str(obj["name"]), arguments=json.dumps(obj.get("arguments", {})))
                )
        return calls

    def assistant_message(self, result: ChatResult, calls: list[ToolCall]) -> dict:
        return {"role": "assistant", "content": result.content or ""}

    def tool_result_message(self, call: ToolCall, feedback: dict) -> dict:
        return {
            "role": "user",
            "content": f'<tool_result name="{call.name}">{json.dumps(feedback)}</tool_result>',
        }


class PlanOnlyChannel(ToolChannel):
    """Endpoint can't be trusted to call tools at all: never offer any, ask for
    a plan, and treat the first response as final."""

    offers_tools = False

    def system_prefix(self, specs: list[dict]) -> str:
        return (
            "\n\nYou cannot call tools on this endpoint. Produce a concise, step-by-step "
            "PLAN of the lookups an analyst should run, and what each would confirm."
        )

    def chat_kwargs(self, specs: list[dict]) -> dict[str, Any]:
        return {}

    def extract_calls(self, result: ChatResult) -> list[ToolCall]:
        return []


def channel_for(mode: str) -> ToolChannel:
    """Map a persisted scorecard mode to its channel. An unknown mode fails safe
    to plan_only — we never *assume* an endpoint can call tools."""
    if mode == "native_tools":
        return ToolChannel()
    if mode == "prompted_tools":
        return PromptedToolChannel()
    return PlanOnlyChannel()


# --- The loop ----------------------------------------------------------------


def _refuse_shadowed_actions(
    registry: ToolRegistry, actions: "ActionManifest | None"
) -> None:
    """An action's name and a tool's name live in one namespace as far as the
    MODEL is concerned — and in two as far as the code is concerned.

    S18 Step 0, executed. `ActionRegistry` and `ToolRegistry` never consult each
    other, so an action `isolate_host` (risk DESTRUCTIVE, "requires human
    approval") could coexist with a tool of the same name. The model is told the
    action's `planner_description`, names `isolate_host`, and `_dispatch`
    resolves that name in the ToolRegistry — running the TOOL, gated by the
    TOOL's level. A read-level tool auto-executes. The action's declared risk is
    bypassed entirely by name shadowing, and the D-014 gate never sees it.

    This is the moment the two namespaces meet, so this is where it is refused —
    at construction, before a single token is sent, and regardless of the order
    the two registries were filled in. Raising is right rather than renaming:
    silently preferring one would leave the model told about an action that is
    not the thing it can call, which is the confusion the S17 loop integration
    was arranged to avoid in the first place.
    """
    if actions is None or not actions.actions:
        return
    shadowed = sorted({a.name for a in actions.actions if a.name in registry})
    if shadowed:
        raise ValueError(
            "action names collide with tool names: "
            + ", ".join(shadowed)
            + " — the model resolves one namespace, so an approval-gated action "
            "would silently dispatch the tool of the same name (D-014)"
        )


class AgentLoop:
    """One instance per conversation turn context. `run()` takes the client so a
    loop can be exercised against a fake LLM in tests (no live endpoint)."""

    def __init__(
        self,
        registry: ToolRegistry,
        proposal_store: ProposalStore,
        *,
        mode: str,
        workspace_id: UUID | str,
        session_id: UUID | str | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_tokens: int = PROBE_MAX_TOKENS,
        temperature: float = 0.0,
        actions: "ActionManifest | None" = None,
    ):
        self.registry = registry
        self.proposal_store = proposal_store
        self.mode = mode
        self.channel = channel_for(mode)
        # S17: the action surface, as a DESCRIPTION. See `_actions_prefix`.
        self.actions = actions
        _refuse_shadowed_actions(registry, actions)
        self.workspace_id = workspace_id
        self.session_id = session_id
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def run(
        self,
        client: Any,
        user_message: str,
        *,
        history: Sequence[dict] | None = None,
        tool_names: Sequence[str] | None = None,
    ) -> AgentResult:
        specs = [] if not self.channel.offers_tools else self.registry.specs(tool_names)
        messages: list[dict] = [
            {
                "role": "system",
                "content": self.system_prompt
                + self.channel.system_prefix(specs)
                + self._actions_prefix(),
            }
        ]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_message})

        invocations: list[ToolInvocation] = []
        for step in range(1, self.max_steps + 1):
            result = await client.chat(
                messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                **self.channel.chat_kwargs(specs),
            )
            calls = self.channel.extract_calls(result)
            if not calls:
                return AgentResult(result.content, step, invocations, "final_answer", self.mode)

            # Pair assistant tool_calls with their tool results by id; synthesise
            # ids the endpoint omitted so the replay stays well-formed.
            for idx, call in enumerate(calls):
                if not call.id:
                    call.id = f"call_{step}_{idx}"
            messages.append(self.channel.assistant_message(result, calls))
            for call in calls:
                invocation = await self._dispatch(call)
                invocations.append(invocation)
                messages.append(self.channel.tool_result_message(call, invocation.feedback))

        # Step cap tripped: one final tool-free pass to synthesise an answer from
        # whatever was gathered, rather than dumping a raw cap error.
        final = await client.chat(
            [*messages, {"role": "user", "content": _SYNTHESIS_NUDGE}],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        return AgentResult(final.content, self.max_steps, invocations, "step_cap", self.mode)

    def _actions_prefix(self) -> str:
        """The action surface, described to the planner (S17).

        The manifest says what the actions ARE; this says what this runtime can
        do with them, and the two are separate because only the second changes
        when S18 lands. Today: nothing. Actions are NOT offered as callable tools
        — `specs` above comes from the ToolRegistry alone, and `_dispatch`
        resolves names there — because an action's dispatch is the proposal
        round-trip S18 owns. Offering a name the model can call that resolves to
        "unknown tool" would be a worse failure than one it can only recommend:
        it invites the model to believe it acted.
        """
        if self.actions is None or not self.actions.actions:
            return ""
        return (
            "\n\n"
            + self.actions.directive()
            + "\n\nYou cannot invoke these yourself in this turn — no mechanism here "
            "will run one. Name the action and its arguments in your answer so a "
            "human can approve it."
        )

    async def _dispatch(self, call: ToolCall) -> ToolInvocation:
        tool = self.registry.get(call.name)
        if tool is None:
            return ToolInvocation(call.name, {}, "error", {"error": f"unknown tool '{call.name}'"})
        try:
            args = call.parse_arguments()
        except ValueError:
            return ToolInvocation(call.name, {}, "error",
                                  {"error": "tool arguments were not valid JSON"})
        missing = [p for p in tool.required if p not in args]
        if missing:
            return ToolInvocation(
                call.name, args, "error",
                {"error": f"missing required parameter(s): {missing}"}, level=tool.level.value,
            )

        decision = gate(tool.level)
        if decision.outcome is PermissionOutcome.ALLOW:
            try:
                output = await tool.handler(args)
            except Exception as err:  # a tool blowing up must degrade, not kill the turn
                return ToolInvocation(
                    call.name, args, "error",
                    {"error": f"tool raised {type(err).__name__}"}, level=tool.level.value,
                )
            return ToolInvocation(call.name, args, "executed", output, level=tool.level.value)

        # PROPOSE: D-014 — never execute a write/destructive tool here. File a
        # proposal and tell the model, in no uncertain terms, that nothing ran.
        proposal_id = await self.proposal_store.create(
            workspace_id=self.workspace_id,
            tool_name=call.name,
            tool_level=tool.level.value,
            tool_input=args,
            session_id=self.session_id,
        )
        feedback = {
            "status": "pending_approval",
            "proposal_id": proposal_id,
            "note": (
                f"'{call.name}' requires human approval; a proposal was filed. "
                "The action has NOT been performed."
            ),
        }
        return ToolInvocation(
            call.name, args, "proposed", feedback,
            level=tool.level.value, proposal_id=proposal_id,
        )
