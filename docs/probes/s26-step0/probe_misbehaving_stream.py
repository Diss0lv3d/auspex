"""S26 Step 0 — drive `AgentLoop.run_stream` with streams that MISBEHAVE.

Every S25 test scripts a well-formed sequence: tool_call deltas, a finish, then
an answer. Nothing has ever driven the streaming turn with a stream that stops
early, contradicts itself, or dies. The route S26 is about to build consumes
exactly this generator, so what it does when the endpoint misbehaves is not a
curiosity — it is the route's error contract.

Discipline (docs/probes/2026-08-16-s25-step0-review.md §"The measurement
discipline"): assert the REASON, and make the controls arithmetic. Each case
asserts a property of its own INPUT before running the loop, so a surprising
result cannot be blamed on a malformed script.

Run:  .venv/bin/python docs/probes/s26-step0/probe_misbehaving_stream.py
"""

import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from _fakes import InMemoryProposalStore  # noqa: E402

from auspex.agent.loop import AgentLoop  # noqa: E402
from auspex.agent.registry import ToolLevel, ToolRegistry  # noqa: E402
from auspex.llm.client import LLMError, StreamEvent, Usage  # noqa: E402

WORKSPACE = "00000000-0000-0000-0000-000000000001"


class ScriptedStream:
    """Like SequencedStreamingFakeLLMClient but a script entry may be an
    Exception INSTANCE, which is raised at that point mid-stream — the one shape
    the shipped fake cannot express (`raise_on_call` raises before the first
    yield, so nothing has ever been delivered before the failure)."""

    def __init__(self, scripts):
        self._scripts = [list(s) for s in scripts]
        self.stream_calls = []

    async def chat_stream(self, messages, **kwargs):
        idx = len(self.stream_calls)
        self.stream_calls.append({"messages": [dict(m) for m in messages], "kwargs": kwargs})
        script = self._scripts[idx] if idx < len(self._scripts) else []
        for event in script:
            if isinstance(event, Exception):
                raise event
            yield event

    @property
    def turns(self):
        return len(self.stream_calls)


def registry():
    seen = []
    reg = ToolRegistry()

    async def lookup_ip(args: dict) -> dict:
        seen.append(args)
        return {"ip": args.get("ip"), "reputation": "malicious", "score": 88}

    async def boom(args: dict) -> dict:
        seen.append(args)
        raise RuntimeError("provider exploded")

    reg.add(
        name="lookup_ip", description="Look up an IP.",
        parameters={"ip": {"type": "string", "description": "the IP"}},
        required=["ip"], level=ToolLevel.READ, handler=lookup_ip,
    )
    reg.add(
        name="boom", description="Always raises.",
        parameters={"ip": {"type": "string", "description": "the IP"}},
        required=["ip"], level=ToolLevel.READ, handler=boom,
    )
    return reg, seen


def loop(reg, **over):
    return AgentLoop(
        reg, InMemoryProposalStore(), mode="native_tools", workspace_id=WORKSPACE, **over
    )


def tool_deltas(name, args, index=0, call_id="call_a"):
    out = [StreamEvent(kind="tool_call", tool_index=index,
                       tool_delta={"id": call_id, "function": {"name": name, "arguments": ""}})]
    if args:
        out.append(StreamEvent(kind="tool_call", tool_index=index,
                               tool_delta={"function": {"arguments": args}}))
    return out


def answer(text="done."):
    return [StreamEvent(kind="content", text=text),
            StreamEvent(kind="finish", finish_reason="stop")]


async def drain(lp, client, message="check 203.0.113.99", **over):
    """Collect events; report an exception rather than letting it kill the run."""
    events, error = [], None
    try:
        async for ev in lp.run_stream(client, message, **over):
            events.append(ev)
    except Exception as err:  # noqa: BLE001 — the point is to observe it
        error = f"{type(err).__name__}: {err}"
    return events, error


def render(events, error):
    kinds = [e.kind for e in events]
    last = events[-1] if events else None
    parts = [f"events={kinds}"]
    if last is not None and last.kind == "done":
        parts.append(f"done(stop_reason={last.stop_reason!r}, text={last.text!r}, "
                     f"finish_reason={last.finish_reason!r}, invocations={len(last.invocations)})")
    for e in events:
        if e.kind == "tool":
            i = e.invocation
            parts.append(
                f"tool({i.name}, status={i.status}, feedback={json.dumps(i.feedback)[:110]})"
            )
    if error:
        parts.append(f"RAISED {error}")
    return "\n      ".join(parts)


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# ── 1. a stream that ends mid-tool-call ──────────────────────────────────────


@case
async def mid_tool_call():
    """The endpoint dies after half the argument JSON. No `finish`, no closing brace."""
    partial = '{"ip": "203.0.'
    try:
        json.loads(partial)
        raise AssertionError("CONTROL FAILED: the fragment is valid JSON, so this "
                             "case is not testing a truncated argument")
    except ValueError:
        pass  # arithmetic control: the input really is unparseable
    reg, seen = registry()
    client = ScriptedStream([tool_deltas("lookup_ip", partial), answer()])
    events, error = await drain(loop(reg), client)
    return render(events, error) + f"\n      handler saw: {seen}  turns={client.turns}"


# ── 2. a tool_call delta with a name but no arguments at all ─────────────────


@case
async def name_without_arguments():
    reg, seen = registry()
    script = tool_deltas("lookup_ip", "") + [StreamEvent(kind="finish", finish_reason="tool_calls")]
    assert all("arguments" not in (e.tool_delta.get("function") or {}) or
               not (e.tool_delta["function"]["arguments"])
               for e in script if e.kind == "tool_call"), "CONTROL FAILED: an argument leaked in"
    client = ScriptedStream([script, answer()])
    events, error = await drain(loop(reg), client)
    return render(events, error) + f"\n      handler saw: {seen}  turns={client.turns}"


# ── 3. two tool calls in one step, the FIRST handler raises ──────────────────


@case
async def two_calls_first_raises():
    reg, seen = registry()
    script = (
        tool_deltas("boom", '{"ip": "1.1.1.1"}', index=0, call_id="call_0")
        + tool_deltas("lookup_ip", '{"ip": "2.2.2.2"}', index=1, call_id="call_1")
        + [StreamEvent(kind="finish", finish_reason="tool_calls")]
    )
    indices = {e.tool_index for e in script if e.kind == "tool_call"}
    assert indices == {0, 1}, f"CONTROL FAILED: expected two tool indices, got {indices}"
    client = ScriptedStream([script, answer()])
    events, error = await drain(loop(reg), client)
    tools = [e for e in events if e.kind == "tool"]
    return (render(events, error)
            + f"\n      tool events: {len(tools)} (both must appear)"
            + f"\n      handlers saw: {seen}  turns={client.turns}")


# ── 4. an endpoint that emits usage and NOTHING else ─────────────────────────


@case
async def usage_only():
    reg, seen = registry()
    script = [StreamEvent(kind="usage", usage=Usage(10, 0, 10))]
    assert not [e for e in script if e.kind in ("content", "tool_call")], "CONTROL FAILED"
    client = ScriptedStream([script])
    events, error = await drain(loop(reg), client)
    return render(events, error) + f"\n      turns={client.turns}"


# ── 5. a completely empty stream ─────────────────────────────────────────────


@case
async def empty_stream():
    reg, _ = registry()
    client = ScriptedStream([[]])
    events, error = await drain(loop(reg), client)
    return render(events, error) + f"\n      turns={client.turns}"


# ── 6. the stream raises AFTER delivering deltas ─────────────────────────────


@case
async def raises_after_deltas():
    """`sealed[0]` assumes the generator completed. Two content deltas reach the
    analyst, then the endpoint 500s."""
    reg, _ = registry()
    script = [StreamEvent(kind="content", text="203.0.113.99 is "),
              StreamEvent(kind="content", text="probably "),
              LLMError(500, "simulated mid-stream failure")]
    assert sum(1 for e in script if isinstance(e, StreamEvent)) == 2, "CONTROL FAILED"
    client = ScriptedStream([script])
    events, error = await drain(loop(reg), client)
    content = "".join(e.text for e in events if e.kind == "content")
    return render(events, error) + f"\n      analyst already read: {content!r}"


# ── 7. the stream raises after a tool call, before the tool ran ──────────────


@case
async def raises_after_tool_deltas():
    reg, seen = registry()
    script = tool_deltas("lookup_ip", '{"ip": "203.0.113.99"}') + [
        LLMError(503, "simulated failure after the tool call was announced")
    ]
    client = ScriptedStream([script])
    events, error = await drain(loop(reg), client)
    return render(events, error) + f"\n      handler saw: {seen} (did the tool run?)"


# ── 8. prose BEFORE the tool call in the same model call (TD-036's shape) ────


@case
async def prose_before_tool_call():
    """TD-036 names this as an ASSUMPTION about the endpoint, not a guarantee.
    Recorded, not fixed — what does the analyst read if it is ever false?"""
    reg, _ = registry()
    script = (
        [StreamEvent(kind="content", text="This IP looks benign to me. ")]
        + tool_deltas("lookup_ip", '{"ip": "203.0.113.99"}')
        + [StreamEvent(kind="finish", finish_reason="tool_calls")]
    )
    client = ScriptedStream([script, answer("Actually it is MALICIOUS (score 88).")])
    events, error = await drain(loop(reg), client)
    streamed = "".join(e.text for e in events if e.kind == "content")
    done = events[-1]
    return (render(events, error)
            + f"\n      analyst READ:      {streamed!r}"
            + f"\n      route PERSISTS:    {done.text!r}")


async def main():
    print("S26 Step 0 — run_stream against misbehaving streams\n" + "=" * 78)
    for fn in CASES:
        print(f"\n[{fn.__name__}]")
        try:
            print("      " + await fn())
        except AssertionError as err:
            print(f"      CONTROL FAILED — {err}")
    print("\n" + "=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
