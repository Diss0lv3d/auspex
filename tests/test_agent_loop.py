"""ReACT agent loop v1 tests (S3 step 1) — all against a FAKE client, no live
LLM, no DB. Includes the D-014 pinned regression (step 3)."""

import json
from pathlib import Path

from _fakes import FakeLLMClient, InMemoryProposalStore

from auspex.agent.loop import AgentLoop
from auspex.agent.registry import ToolLevel, ToolRegistry
from auspex.llm.client import ChatResult, ToolCall

WORKSPACE = "00000000-0000-0000-0000-000000000001"
FIXTURES = Path(__file__).parent / "fixtures" / "agent"

_IP_INTEL = {
    "203.0.113.99": {"reputation": "malicious", "score": 88, "country": "XZ", "tags": ["phishing"]},
    "192.0.2.10": {"reputation": "benign", "score": 2, "country": "US", "tags": []},
}


def _make_registry() -> tuple[ToolRegistry, list]:
    """Registry with one READ tool (lookup_ip) and one WRITE tool (create_ticket).
    The write handler is a tripwire: if the gate ever executes it, `executed_writes`
    records it and the D-014 tests fail loudly."""
    executed_writes: list = []
    reg = ToolRegistry()

    async def lookup_ip(args: dict) -> dict:
        ip = str(args.get("ip", ""))
        return {"ip": ip, **_IP_INTEL.get(ip, {"reputation": "unknown", "score": 0})}

    async def create_ticket(args: dict) -> dict:
        executed_writes.append(args)  # must never happen in v1 (writes gate)
        return {"ticket_id": "TCK-9999", "status": "open"}

    reg.add("lookup_ip", "Look up IP reputation.",
            {"ip": {"type": "string"}}, ["ip"], ToolLevel.READ, lookup_ip)
    reg.add("create_ticket", "Open an incident ticket.",
            {"title": {"type": "string"}, "severity": {"type": "string"}},
            ["title", "severity"], ToolLevel.WRITE, create_ticket)
    return reg, executed_writes


def _tool_call_result(name: str, args: dict, call_id: str = "call_1") -> ChatResult:
    return ChatResult(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=json.dumps(args))],
        finish_reason="tool_calls",
    )


def _loop(registry, store, *, mode="native_tools", **kw) -> AgentLoop:
    return AgentLoop(registry, store, mode=mode, workspace_id=WORKSPACE, **kw)


# -- native happy path -------------------------------------------------------


async def test_native_read_chain_executes_and_feeds_result_back():
    reg, _ = _make_registry()
    store = InMemoryProposalStore()
    client = FakeLLMClient([
        _tool_call_result("lookup_ip", {"ip": "203.0.113.99"}),
        ChatResult(content="203.0.113.99 is malicious (score 88).", finish_reason="stop"),
    ])
    result = await _loop(reg, store).run(client, "Is 203.0.113.99 a threat?")

    assert result.stopped_reason == "final_answer"
    assert result.steps == 2
    assert [i.name for i in result.executed] == ["lookup_ip"]
    assert result.executed[0].feedback["reputation"] == "malicious"
    # the tool result was fed back as a role:tool message paired to the call id
    replayed = client.last_messages()
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in replayed)
    tool_msgs = [m for m in replayed if m.get("role") == "tool"]
    assert tool_msgs and tool_msgs[0]["tool_call_id"] == "call_1"
    assert json.loads(tool_msgs[0]["content"])["reputation"] == "malicious"


async def test_conversational_turn_offers_no_tools():
    """Design input: conversational turns get no tools; tools=None passes cleanly."""
    reg, _ = _make_registry()
    client = FakeLLMClient([ChatResult(content="C2 beaconing is malware calling home.",
                                       finish_reason="stop")])
    result = await _loop(reg, InMemoryProposalStore()).run(
        client, "What is C2 beaconing?", tool_names=[]
    )
    assert result.stopped_reason == "final_answer"
    assert result.invocations == []
    assert "tools" not in client.calls[0]["kwargs"]  # i.e. tools=None on the wire


# -- D-014: writes gate on real execution, never on model claims -------------


async def test_write_tool_is_proposed_never_executed():
    reg, executed_writes = _make_registry()
    store = InMemoryProposalStore()
    client = FakeLLMClient([
        _tool_call_result("create_ticket", {"title": "Malicious IP", "severity": "high"}),
        ChatResult(content="I filed a proposal; it awaits approval.", finish_reason="stop"),
    ])
    result = await _loop(reg, store).run(client, "Open a high sev ticket for 203.0.113.99.")

    assert executed_writes == []  # the handler NEVER ran
    assert result.performed("create_ticket") is False
    assert [i.name for i in result.proposed] == ["create_ticket"]
    assert len(store.proposals) == 1
    assert store.proposals[0]["tool_level"] == "write"
    # the feedback to the model states plainly nothing was performed
    fed_back = result.proposed[0].feedback
    assert fed_back["status"] == "pending_approval"
    assert "NOT been performed" in fed_back["note"]
    assert fed_back["proposal_id"] == "prop-1"


async def test_d014_pinned_regression_fabricated_ticket():
    """D-014 pinned fixture: the exact llama3.1:8b C206 output that CLAIMED a
    ticket was opened while only calling lookup_ip. The loop must treat the
    claim as text — no execution, no proposal, create_ticket NOT performed."""
    fx = json.loads((FIXTURES / "c206_fabricated_ticket.json").read_text())
    assert fx["calls_made"] == ["lookup_ip"]  # the model never called create_ticket

    reg, executed_writes = _make_registry()
    store = InMemoryProposalStore()
    # Replay exactly what the 8B model did: one lookup_ip call, then the
    # fabricated "ticket has been opened" answer with NO create_ticket call.
    client = FakeLLMClient([
        _tool_call_result("lookup_ip", {"ip": "203.0.113.99"}),
        ChatResult(content=fx["fabricated_final_answer"], finish_reason="stop"),
    ])
    result = await _loop(reg, store).run(client, fx["prompt"])

    # The model's prose says a ticket was opened...
    assert "ticket has been opened" in result.content.lower()
    # ...but structurally nothing happened: no execution, no proposal.
    assert result.performed("create_ticket") is False
    assert executed_writes == []
    assert store.proposals == []
    assert [i.name for i in result.executed] == ["lookup_ip"]


# -- dispatch error handling -------------------------------------------------


async def test_unknown_tool_is_reported_not_crashed():
    reg, _ = _make_registry()
    client = FakeLLMClient([
        _tool_call_result("delete_everything", {"scope": "all"}),
        ChatResult(content="That tool does not exist.", finish_reason="stop"),
    ])
    result = await _loop(reg, InMemoryProposalStore()).run(client, "nuke it")
    err = result.invocations[0]
    assert err.status == "error" and "unknown tool" in err.feedback["error"]


async def test_malformed_arguments_reported():
    reg, _ = _make_registry()
    bad = ChatResult(
        tool_calls=[ToolCall(id="c1", name="lookup_ip", arguments='{"ip": ')],  # truncated JSON
        finish_reason="tool_calls",
    )
    client = FakeLLMClient([bad, ChatResult(content="sorry", finish_reason="stop")])
    result = await _loop(reg, InMemoryProposalStore()).run(client, "look up something")
    assert result.invocations[0].status == "error"
    assert "not valid JSON" in result.invocations[0].feedback["error"]


async def test_missing_required_parameter_reported():
    reg, _ = _make_registry()
    client = FakeLLMClient([
        _tool_call_result("lookup_ip", {}),  # missing required "ip"
        ChatResult(content="need an ip", finish_reason="stop"),
    ])
    result = await _loop(reg, InMemoryProposalStore()).run(client, "look up")
    assert result.invocations[0].status == "error"
    assert "missing required" in result.invocations[0].feedback["error"]


# -- step cap ----------------------------------------------------------------


async def test_step_cap_triggers_synthesis_pass():
    reg, _ = _make_registry()
    # Model keeps calling tools forever; cap=2 → 2 tool turns + 1 synthesis turn.
    client = FakeLLMClient([
        _tool_call_result("lookup_ip", {"ip": "192.0.2.10"}, call_id="a"),
        _tool_call_result("lookup_ip", {"ip": "203.0.113.99"}, call_id="b"),
        ChatResult(content="Synthesised answer from partial results.", finish_reason="stop"),
    ])
    result = await _loop(reg, InMemoryProposalStore(), max_steps=2).run(client, "loop please")
    assert result.stopped_reason == "step_cap"
    assert result.steps == 2
    assert len(result.executed) == 2
    assert client.turns == 3  # two loop turns + one synthesis turn
    # the synthesis turn offered no tools
    assert "tools" not in client.calls[-1]["kwargs"]
    assert result.content == "Synthesised answer from partial results."


# -- prompted-tools fallback (same loop, gate, proposals behind it) ----------


async def test_prompted_mode_parses_tool_call_blocks():
    reg, _ = _make_registry()
    blob = '<tool_call>{"name": "lookup_ip", "arguments": {"ip": "203.0.113.99"}}</tool_call>'
    client = FakeLLMClient([
        ChatResult(content=f"Let me check.\n{blob}", finish_reason="stop"),
        ChatResult(content="203.0.113.99 is malicious.", finish_reason="stop"),
    ])
    result = await _loop(reg, InMemoryProposalStore(), mode="prompted_tools").run(
        client, "Is 203.0.113.99 malicious?"
    )
    assert result.mode == "prompted_tools"
    assert [i.name for i in result.executed] == ["lookup_ip"]
    # prompted mode never puts tools on the wire; it describes them in the system prompt
    assert "tools" not in client.calls[0]["kwargs"]
    assert "<tool_call>" in client.calls[0]["messages"][0]["content"]
    # tool result was fed back as a <tool_result> user message
    assert any("<tool_result" in m.get("content", "")
               for m in client.last_messages() if m.get("role") == "user")


async def test_prompted_mode_write_still_proposed():
    reg, executed_writes = _make_registry()
    store = InMemoryProposalStore()
    blob = ('<tool_call>{"name": "create_ticket", "arguments": '
            '{"title": "x", "severity": "high"}}</tool_call>')
    client = FakeLLMClient([
        ChatResult(content=blob, finish_reason="stop"),
        ChatResult(content="proposal filed", finish_reason="stop"),
    ])
    result = await _loop(reg, store, mode="prompted_tools").run(client, "open a ticket")
    assert executed_writes == []
    assert [i.name for i in result.proposed] == ["create_ticket"]
    assert len(store.proposals) == 1


# -- plan_only mode ----------------------------------------------------------


async def test_plan_only_never_offers_tools_and_returns_first_answer():
    reg, _ = _make_registry()
    # Even if the model emitted a tool_call block, plan_only ignores it.
    client = FakeLLMClient([
        ChatResult(content="Plan: 1) look up the IP 2) check the asset.", finish_reason="stop"),
    ])
    result = await _loop(reg, InMemoryProposalStore(), mode="plan_only").run(client, "triage this")
    assert result.mode == "plan_only"
    assert result.stopped_reason == "final_answer"
    assert result.invocations == []
    assert client.turns == 1
    assert "tools" not in client.calls[0]["kwargs"]


async def test_unknown_mode_fails_safe_to_plan_only():
    reg, _ = _make_registry()
    client = FakeLLMClient([ChatResult(content="a plan", finish_reason="stop")])
    loop = _loop(reg, InMemoryProposalStore(), mode="some_future_mode")
    result = await loop.run(client, "hi")
    # unknown mode must not assume native tool calling
    assert loop.channel.offers_tools is False
    assert result.invocations == []


# ── the S17 action surface, as a description (planner manifest integration) ──


def _manifest(mode="native_tools"):
    from auspex.actions import (
        ActionParam,
        ActionRegistry,
        ActionRisk,
        ActionScope,
        ParamType,
        UndoSpec,
        action,
    )

    async def would(**kw):
        return None

    async def never(**kw):
        raise AssertionError("the loop must not execute an action in S17")

    @action(
        name="isolate_host",
        description="Isolate a host at the EDR",
        risk=ActionRisk.DESTRUCTIVE,
        scope=[ActionScope("edr", writes=True)],
        params=[ActionParam("host_id", ParamType.STRING, "Short host id")],
        dry_run=would,
        undo=UndoSpec("Release the host", never, restores="network connectivity"),
    )
    async def isolate_host(host_id: str):
        raise AssertionError("the loop must not execute an action in S17")

    reg = ActionRegistry()
    reg.register(isolate_host)
    return reg.manifest(mode)


async def test_the_planner_is_told_what_it_may_propose():
    """S17: how an action becomes visible to the loop. The manifest's own text,
    compiled from the specs (D-007), reaches the system prompt."""
    registry, _ = _make_registry()
    store = InMemoryProposalStore()
    client = FakeLLMClient([ChatResult(content="noted")])
    loop = _loop(registry, store, actions=_manifest())
    await loop.run(client, "isolate host h-1")

    system = client.calls[0]["messages"][0]["content"]
    assert "isolate_host(host_id: string)" in system
    assert "RISK destructive: requires human approval" in system
    assert "Undo: Release the host" in system


async def test_actions_are_described_but_never_offered_as_callable_tools():
    """The S17 line, held in code: an action's dispatch is the proposal
    round-trip S18 owns, so nothing here puts one on the wire. A tool the model
    can call that resolves to 'unknown tool' would invite it to believe it
    acted."""
    registry, _ = _make_registry()
    client = FakeLLMClient([ChatResult(content="noted")])
    loop = _loop(registry, InMemoryProposalStore(), actions=_manifest())
    await loop.run(client, "isolate host h-1")

    offered = {s["function"]["name"] for s in (client.calls[0]["kwargs"].get("tools") or [])}
    assert offered == {"lookup_ip", "create_ticket"}  # the ToolRegistry only
    assert "isolate_host" not in offered
    system = client.calls[0]["messages"][0]["content"]
    assert "cannot invoke these yourself" in system


async def test_a_model_that_calls_an_action_anyway_is_told_it_did_not_run():
    """The rough edge, made explicit rather than left to chance: an action name
    is not in the ToolRegistry, so it dispatches as an unknown tool — an error,
    never a silent success and never an execution."""
    registry, executed = _make_registry()
    client = FakeLLMClient(
        [
            ChatResult(content=None, tool_calls=[
                ToolCall(id="c1", name="isolate_host", arguments='{"host_id": "h-1"}')
            ]),
            ChatResult(content="I could not do that myself."),
        ]
    )
    loop = _loop(registry, InMemoryProposalStore(), actions=_manifest())
    result = await loop.run(client, "isolate host h-1")

    assert [i.status for i in result.invocations] == ["error"]
    assert "unknown tool" in result.invocations[0].feedback["error"]
    assert executed == []


async def test_no_action_surface_adds_nothing_to_the_prompt():
    registry, _ = _make_registry()
    client = FakeLLMClient([ChatResult(content="hi")])
    await _loop(registry, InMemoryProposalStore()).run(client, "hello")
    assert "propose" not in client.calls[0]["messages"][0]["content"].lower()
