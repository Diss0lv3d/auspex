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
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from auspex.agent.permissions import PermissionOutcome, ProposalStore, gate
from auspex.agent.registry import ToolRegistry

if TYPE_CHECKING:
    # Type-only: auspex.actions imports auspex.agent.permissions for the gate, so
    # importing it here at runtime would close a cycle. The loop only ever reads
    # the manifest's rendered text and calls the proposer it was handed.
    from collections.abc import AsyncIterator, Awaitable, Callable

    from auspex.actions import ActionManifest

    # Files a proposal for one action call and returns the stored row (which
    # carries `id` and the rendered `card`). A callable rather than the
    # settlement class so the loop keeps depending on a seam, not on Postgres —
    # the same reason `ProposalStore` is a Protocol.
    ActionProposer = Callable[..., Awaitable[dict]]
from auspex.llm.capability import PROBE_MAX_TOKENS
from auspex.llm.client import (
    ChatResult,
    ToolCall,
    Usage,
    fold_stream_event,
    seal_stream_result,
)

# Loop step cap — chosen consciously, not copied from the harness (which capped
# per-task at 8 for scoring). The S2 task battery's deepest real chains need 4
# tool calls plus a synthesis turn; 8 leaves headroom for one self-correction
# without letting a confused weak model burn the endpoint indefinitely.
DEFAULT_MAX_STEPS = 8

# TD-036: how much of a step's content is held back before it is streamed as
# answer. An endpoint that narrates before a tool call ("I'll check that IP…")
# would otherwise put that sentence in front of the tool result. MEASURED, not
# chosen: the longest narration on glm-4.5-air was 201 chars across 9
# tool-calling steps (docs/probes/2026-10-10-s26-routing-glm.md, Finding 5), so
# this is about twice that. It is a calibrated number like SHINGLE_WORDS: to
# change it, re-run docs/probes/s26-step0/probe_routing.py instead of editing it.
NARRATION_HOLD_CHARS = 400

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
    # S18: for a proposed ACTION, the card a human will decide on — compiled from
    # the spec and the action's own dry run (auspex/actions/proposal.py). Carried
    # on the invocation so the surface streams what was RENDERED rather than
    # re-deriving it from the model's sentence.
    card: dict[str, Any] | None = None


@dataclass
class AgentResult:
    content: str
    steps: int
    invocations: list[ToolInvocation]
    # "final_answer" | "step_cap" | "empty_answer" (see `_terminal_reason`)
    stopped_reason: str
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


@dataclass
class AgentStreamEvent:
    """One event from a streaming agent turn (`AgentLoop.run_stream`).

    Deliberately transport-agnostic: the loop does not know about SSE, and the
    route decides how each kind is rendered and which OUTPUT-RAIL CHANNEL it
    belongs to. D-031 decision 5 makes that a real distinction rather than
    tidiness — a tool result is data on its own channel, so a shingle spanning a
    tool result and the answer is not a leak.

    kind:
      'reasoning' — a thinking-pane delta.
      'content'   — an answer delta. Held for up to NARRATION_HOLD_CHARS while
                    NATIVE tools are on the wire (TD-036), then streamed as it
                    arrives. Prompted-mode tool tags arrive IN content and are
                    not held — that channel is not wired to a streaming
                    surface (D-031, D-037) and needs tag-aware holding first.
      'narration' — prose from a step that turned out to call tools: the
                    model saying what it is about to do, never the answer and
                    never part of `done.text`. Shown as process, not answer.
      'tool'      — one tool step RESOLVED; carries the ToolInvocation, which is
                    what the route narrates. Emitted after the handler ran, so
                    it reports what happened rather than what was requested.
      'usage'     — one model call's usage, per call rather than per turn.
      'done'      — the turn ended; `text` is the final answer, `stop_reason`
                    says why it ended. `empty_answer` means there is no answer
                    to render or persist — see `_terminal_reason`.
    """

    kind: str
    text: str = ""
    invocation: ToolInvocation | None = None
    usage: Usage | None = None
    finish_reason: str | None = None
    # "final_answer" | "step_cap" | "empty_answer" | "usage_refused"
    stop_reason: str = ""
    step: int = 0
    invocations: list[ToolInvocation] = field(default_factory=list)


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


def _terminal_reason(content: str, *, at_step_cap: bool = False) -> str:
    """Which terminal state a finished turn is actually in.

    Shared by `run` and `run_stream` so the two cannot hold two opinions about
    what counts as an answer — the same reason `fold_stream_event` exists.

    **A turn that ends with blank text did not answer**, and calling that
    `final_answer` is *nothing happened* rendering as *the answer is nothing*:
    the route persists the final text as the assistant turn, so an empty string
    becomes a stored, rendered reply, and the terminal state gives the route
    nothing to notice it by. Measured (S26 Step 0, docs/probes/s26-step0/): a
    thinking model that spends its whole `max_tokens` budget on reasoning emits
    reasoning deltas, `finish_reason="length"` and no content at all — and the
    terminal state was byte-identical to a complete answer's.

    Emptiness outranks `step_cap` because both `final_answer` and `step_cap`
    claim *here is the answer*. Nothing is lost by saying so: `step` still
    carries whether the cap was reached, and the invocations still carry what
    was gathered. `usage_refused` is untouched — it is the more specific fact
    (we never asked the endpoint at all).
    """
    if not (content or "").strip():
        return "empty_answer"
    return "step_cap" if at_step_cap else "final_answer"


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
        action_proposer: "ActionProposer | None" = None,
    ):
        self.registry = registry
        self.proposal_store = proposal_store
        self.mode = mode
        self.channel = channel_for(mode)
        # S17: the action surface, as a DESCRIPTION. See `_actions_prefix`.
        # S18: plus the one thing calling an action may do — file a proposal.
        self.actions = actions
        self.action_proposer = action_proposer
        _refuse_shadowed_actions(registry, actions)
        self.workspace_id = workspace_id
        self.session_id = session_id
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.temperature = temperature

    def wire_specs(self, tool_names: Sequence[str] | None = None) -> list[dict]:
        """The tool envelopes this turn will actually offer the endpoint."""
        specs = [] if not self.channel.offers_tools else self.registry.specs(tool_names)
        # S18: actions join the wire array only when this runtime can actually
        # file a proposal for one. Offering a callable name with no proposer
        # behind it is the failure S17 refused to ship — the model would call it,
        # get an error, and be tempted to narrate success anyway.
        if self.channel.offers_tools and self.actions is not None and self.action_proposer:
            specs = [*specs, *self.actions.wire_specs()]
        return specs

    def system_message(self, specs: list[dict]) -> str:
        """The system message this turn composes, exactly as it goes on the wire.

        Public because the OUTPUT RAIL needs it. D-030 decision 2 indexes only
        configuration WE issued; D-031 decision 5 observes that with a loop that
        set is composed at runtime rather than being four fixed strings, so the
        route builds its leak index from THIS string. A route that re-assembled
        the pieces itself would index something the endpoint never saw.
        """
        return (
            self.system_prompt + self.channel.system_prefix(specs) + self._actions_prefix()
        )

    def issued_instructions(self, specs: list[dict]) -> list[str]:
        """Everything this turn may send the endpoint as configuration, for the
        output rail's index (D-031 decision 5): the composed system message,
        every function and parameter description on the wire — which on
        native_tools travel in the `tools` parameter, not the system message —
        and the step-cap nudge (TD-038). Calibrated before it was indexed:
        docs/probes/2026-10-10-s26-rail-calibration-glm.md."""
        issued = [self.system_message(specs)]
        for spec in specs:
            fn = spec.get("function") or {}
            if fn.get("description"):
                issued.append(fn["description"])
            for prop in ((fn.get("parameters") or {}).get("properties") or {}).values():
                if isinstance(prop, dict) and prop.get("description"):
                    issued.append(prop["description"])
        issued.append(_SYNTHESIS_NUDGE)
        return issued

    def _initial_messages(
        self, specs: list[dict], user_message: str, history: Sequence[dict] | None
    ) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": self.system_message(specs)}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_message})
        return messages

    async def run(
        self,
        client: Any,
        user_message: str,
        *,
        history: Sequence[dict] | None = None,
        tool_names: Sequence[str] | None = None,
    ) -> AgentResult:
        specs = self.wire_specs(tool_names)
        messages = self._initial_messages(specs, user_message, history)

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
                return AgentResult(
                    result.content, step, invocations, _terminal_reason(result.content), self.mode
                )

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
        return AgentResult(
            final.content, self.max_steps, invocations,
            _terminal_reason(final.content, at_step_cap=True), self.mode,
        )

    async def run_stream(
        self,
        client: Any,
        user_message: str,
        *,
        history: Sequence[dict] | None = None,
        tool_names: Sequence[str] | None = None,
        claim: "Callable[[], Awaitable[bool]] | None" = None,
    ) -> "AsyncIterator[AgentStreamEvent]":
        """The same loop as `run`, emitting events as they happen (D-031).

        Same messages, same channel, same `_dispatch` — `run` and this share
        `wire_specs`/`_initial_messages` precisely so the streaming turn and the
        blocking turn cannot answer differently. What differs is only WHEN the
        caller learns things.

        **The answer streams after the tool steps, and the tool steps are
        narrated.** Measured on real Scout (D-031 decision 1, re-confirmed S25):
        a tool-calling turn emits its tool-call deltas with `content chars: 0`
        before them. glm-4.5-air does not: one sentence of prose precedes every
        tool call (TD-036). So while tools are on the wire a step's content is
        held until the step shows what it is. A tool call turns the held text
        into `narration`; the end of the stream, or passing
        NARRATION_HOLD_CHARS, releases it as answer.

        **Arguments are never parsed mid-stream** (decision 2). Folding is
        `fold_stream_event`, the same code `accumulate_stream` uses; one IP was
        measured arriving as nine fragments split mid-token.

        **`finish_reason` is not the step signal — the presence of tool calls
        is** (decision 3, in its spirit). The channel decides what counts as a
        call, so prompted-mode's tag parsing and native mode's `tool_calls`
        array are read the same way here as in `run`.

        **The usage claim is per model call** (decision 4). `claim` is called
        before EVERY call including the synthesis pass, so a loop cannot make
        nine calls against a claim of one. It is a callable rather than a
        limiter because metering policy belongs to the route; the loop only
        needs to know whether it may make one more call. A refusal ends the turn
        with `stop_reason="usage_refused"` and whatever was gathered so far —
        the tool results already streamed as `tool` events, so the analyst sees
        the evidence even when the answer cannot be written.
        """
        specs = self.wire_specs(tool_names)
        messages = self._initial_messages(specs, user_message, history)
        chat_kwargs = self.channel.chat_kwargs(specs)
        invocations: list[ToolInvocation] = []

        async def _stream_call(
            call_messages: list[dict], sealed: list[ChatResult], at_step: int, **extra
        ):
            """One model call: yields each delta AS IT ARRIVES, folds alongside.

            An async generator rather than a coroutine returning the result,
            because a coroutine would have to buffer the deltas until the call
            finished — which is not streaming at all. The sealed ChatResult is
            handed back through `sealed` once the stream ends, since that is the
            first moment `arguments` may be parsed.
            """
            result = ChatResult()
            by_index: dict[int, ToolCall] = {}
            # TD-036. While tools are on the wire, content is held until the
            # step shows what it is: a tool call turns it into narration, the
            # end of the stream or passing NARRATION_HOLD_CHARS releases it as
            # answer. With no tools on the wire no tool call can follow, so
            # nothing waits.
            tools_on_wire = "tools" in extra
            holding = tools_on_wire
            held: list[str] = []
            # Separate from `holding`: a step that released its hold and THEN
            # called a tool still called one, so what follows the call is
            # narration, not answer (review of 39f1afc).
            calls_tools = False

            def _text(kind: str, text: str) -> AgentStreamEvent:
                return AgentStreamEvent(kind=kind, text=text, step=at_step)

            # `aclosing`: a turn closed early (the route's rail tripped) closes
            # the endpoint's stream NOW, so it stops generating — not whenever
            # the abandoned generator is collected.
            async with aclosing(
                client.chat_stream(
                    call_messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    **extra,
                )
            ) as stream:
                async for ev in stream:
                    fold_stream_event(result, by_index, ev)
                    if ev.kind == "tool_call" and tools_on_wire and not calls_tools:
                        calls_tools = True
                        holding = False
                        if "".join(held).strip():
                            yield _text("narration", "".join(held))
                        held.clear()
                    elif ev.kind == "content" and ev.text:
                        if calls_tools:
                            yield _text("narration", ev.text)
                        elif holding:
                            held.append(ev.text)
                            if sum(map(len, held)) > NARRATION_HOLD_CHARS:
                                # Long enough to be the answer: stream from here on.
                                # The bound TD-036 keeps — a tool call after this
                                # point follows prose the analyst already read.
                                holding = False
                                yield _text("content", "".join(held))
                                held.clear()
                        else:
                            yield _text("content", ev.text)
                    elif ev.kind == "reasoning" and ev.text:
                        yield _text("reasoning", ev.text)
                    elif ev.kind == "usage" and ev.usage:
                        yield AgentStreamEvent(kind="usage", usage=ev.usage, step=at_step)
            if held:
                yield _text("content", "".join(held))
            sealed.append(seal_stream_result(result, by_index))

        for step in range(1, self.max_steps + 1):
            if claim is not None and not await claim():
                yield AgentStreamEvent(
                    kind="done", stop_reason="usage_refused", step=step - 1,
                    invocations=list(invocations),
                )
                return
            sealed: list[ChatResult] = []
            async with aclosing(_stream_call(messages, sealed, step, **chat_kwargs)) as outs:
                async for out in outs:
                    yield out
            result = sealed[0]

            calls = self.channel.extract_calls(result)
            if not calls:
                yield AgentStreamEvent(
                    kind="done", text=result.content,
                    stop_reason=_terminal_reason(result.content),
                    finish_reason=result.finish_reason, step=step,
                    invocations=list(invocations),
                )
                return

            for idx, call in enumerate(calls):
                if not call.id:
                    call.id = f"call_{step}_{idx}"
            messages.append(self.channel.assistant_message(result, calls))
            for call in calls:
                invocation = await self._dispatch(call)
                invocations.append(invocation)
                yield AgentStreamEvent(kind="tool", invocation=invocation, step=step)
                messages.append(self.channel.tool_result_message(call, invocation.feedback))

        # Step cap: one final tool-free pass, and it is a model call like any
        # other, so it is claimed like any other.
        if claim is not None and not await claim():
            yield AgentStreamEvent(
                kind="done", stop_reason="usage_refused", step=self.max_steps,
                invocations=list(invocations),
            )
            return
        sealed = []
        async with aclosing(
            _stream_call(
                [*messages, {"role": "user", "content": _SYNTHESIS_NUDGE}], sealed, self.max_steps
            )
        ) as outs:
            async for out in outs:
                yield out
        final = sealed[0]
        yield AgentStreamEvent(
            kind="done", text=final.content,
            stop_reason=_terminal_reason(final.content, at_step_cap=True),
            finish_reason=final.finish_reason, step=self.max_steps,
            invocations=list(invocations),
        )

    def _actions_prefix(self) -> str:
        """The action surface, described to the planner.

        The manifest says what the actions ARE; this says what this runtime can
        do with them. The two are separate because exactly this half changed at
        S18: S17 could only describe actions, because dispatch without a proposal
        round-trip would have offered a callable name resolving to "unknown
        tool", inviting the model to believe it acted. With a proposer wired in,
        calling an action is meaningful and still not an execution — it files a
        request for a human. Without one, the honest sentence is the S17 one.
        """
        if self.actions is None or not self.actions.actions:
            return ""
        if self.action_proposer is None:
            return (
                "\n\n"
                + self.actions.directive()
                + "\n\nYou cannot invoke these yourself in this turn — no mechanism here "
                "will run one. Name the action and its arguments in your answer so a "
                "human can approve it."
            )
        return (
            "\n\n"
            + self.actions.directive()
            + "\n\nCalling one of these FILES A PROPOSAL for a human to approve. It "
            "does not perform the action, and nothing in this turn can: the result "
            "you get back is a proposal id, never an outcome. Say that you have "
            "proposed it and what it would do — never that it is done."
        )

    async def _dispatch(self, call: ToolCall) -> ToolInvocation:
        # S18: an action name resolves HERE, before the tool registry, and never
        # to an execution. S17 kept actions off the wire entirely because a
        # callable name that resolved to "unknown tool" would invite the model to
        # believe it acted; the answer was always going to be this round-trip
        # rather than silence. The model may now CALL an action, and calling one
        # produces a dry run and a proposal — a request for a human, not a side
        # effect. `_refuse_shadowed_actions` guarantees the two namespaces are
        # disjoint, so this ordering cannot hide a tool.
        if self._action_spec(call.name) is not None:
            return await self._propose_action(call)

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

    # ── the action round-trip (S18) ──────────────────────────────────────────

    def _action_spec(self, name: str):
        """The spec for a name the model called, if it is an action at all."""
        if self.actions is None:
            return None
        for spec in self.actions.actions:
            if spec.name == name:
                return spec
        return None

    async def _propose_action(self, call: ToolCall) -> ToolInvocation:
        """Dry-run the action and file a proposal. Never executes.

        The dry run happens HERE rather than at approval time on purpose: the
        card a human reads has to say what this action would do with THESE
        arguments, and computing it later would describe a world that has since
        moved. It also means a model that calls an action with nonsense arguments
        finds out now, in the turn, instead of wasting a human's decision.
        """
        spec = self._action_spec(call.name)
        try:
            args = call.parse_arguments()
        except ValueError:
            return ToolInvocation(
                call.name, {}, "error", {"error": "action arguments were not valid JSON"}
            )
        missing = [p for p in spec.required if p not in args]
        if missing:
            return ToolInvocation(
                call.name, args, "error",
                {"error": f"missing required parameter(s): {missing}"},
                level=spec.risk.value,
            )
        if self.action_proposer is None:
            # Told about actions, given no way to file one: say so honestly
            # rather than let the model narrate a proposal that does not exist.
            return ToolInvocation(
                call.name, args, "error",
                {"error": f"'{call.name}' cannot be proposed in this context"},
                level=spec.risk.value,
            )
        try:
            proposal = await self.action_proposer(
                spec=spec,
                arguments=args,
                workspace_id=self.workspace_id,
                session_id=self.session_id,
            )
        except Exception as err:
            # A proposer may DECLINE with a sentence written for the model (D-045:
            # a dry run that would change nothing is not filed). Only that
            # deliberate attribute crosses over; an arbitrary exception's message
            # can carry anything, so it is reported by class alone.
            declined = getattr(err, "model_feedback", None)
            return ToolInvocation(
                call.name, args, "error",
                {"error": declined if isinstance(declined, str)
                 else f"proposing raised {type(err).__name__}"},
                level=spec.risk.value,
            )
        # The stored row's id is a UUID object; everything fed back to the model
        # is JSON on the wire, and the loop's own test doubles returned strings,
        # so this went unexercised until the chat path used the real proposer
        # (D-045).
        proposal_id = str(proposal["id"])
        feedback = {
            "status": "pending_approval",
            "proposal_id": proposal_id,
            "would": proposal["card"]["summary"],
            "note": (
                f"'{call.name}' was PROPOSED and requires human approval. It has NOT "
                "been performed, and nothing you say can perform it — do not report "
                "it as done."
            ),
        }
        return ToolInvocation(
            call.name, args, "proposed", feedback,
            level=spec.risk.value, proposal_id=proposal_id, card=proposal["card"],
        )
