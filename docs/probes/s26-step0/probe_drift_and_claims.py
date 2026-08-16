"""S26 Step 0 — two questions the S25 tests do not answer.

(1) **Does the anti-drift test measure what it reads?**
    `test_run_and_run_stream_compose_the_same_messages` compares only
    `calls[0]["messages"]`. The two loop bodies are DUPLICATED code (only
    `wire_specs`/`_initial_messages` are shared), so they could diverge on the
    second step or the synthesis pass and the test would stay green. This drives
    both paths through 2 tool steps + a synthesis pass and compares EVERY call.

(2) **What does a failed call cost?** The claim is taken before the call and
    `UsageLimiter` has no refund path. Measure claims-vs-calls-served when the
    endpoint dies, so the review can say whether this is TD-030's ratified shape
    or a new one.

Discipline: the drift comparison is arithmetic — it asserts the two paths made
the SAME NUMBER of calls first, since a comparison of `zip`ped lists silently
passes when one side is shorter.

Run:  .venv/bin/python docs/probes/s26-step0/probe_drift_and_claims.py
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
from auspex.llm.client import ChatResult, LLMError, StreamEvent, ToolCall  # noqa: E402

WORKSPACE = "00000000-0000-0000-0000-000000000001"
ARGS = '{"ip": "203.0.113.99"}'


def registry():
    reg = ToolRegistry()

    async def lookup_ip(args: dict) -> dict:
        return {"ip": args.get("ip"), "reputation": "malicious", "score": 88}

    reg.add(
        name="lookup_ip", description="Look up an IP.",
        parameters={"ip": {"type": "string", "description": "the IP"}},
        required=["ip"], level=ToolLevel.READ, handler=lookup_ip,
    )
    return reg


def loop(**over):
    return AgentLoop(
        registry(), InMemoryProposalStore(), mode="native_tools",
        workspace_id=WORKSPACE, **over
    )


class Streaming:
    def __init__(self, scripts):
        self._scripts = [list(s) for s in scripts]
        self.calls = []

    async def chat_stream(self, messages, **kwargs):
        idx = len(self.calls)
        self.calls.append({"messages": [dict(m) for m in messages], "kwargs": kwargs})
        for event in self._scripts[idx] if idx < len(self._scripts) else []:
            if isinstance(event, Exception):
                raise event
            yield event


class Blocking:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    async def chat(self, messages, **kwargs):
        idx = len(self.calls)
        self.calls.append({"messages": [dict(m) for m in messages], "kwargs": kwargs})
        return self._results[idx] if idx < len(self._results) else ChatResult()


def tool_step_stream(call_id):
    return [
        StreamEvent(kind="tool_call", tool_index=0,
                    tool_delta={"id": call_id, "function": {"name": "lookup_ip", "arguments": ""}}),
        StreamEvent(kind="tool_call", tool_index=0,
                    tool_delta={"function": {"arguments": ARGS}}),
        StreamEvent(kind="finish", finish_reason="tool_calls"),
    ]


def tool_step_blocking(call_id):
    return ChatResult(
        content="", finish_reason="tool_calls",
        tool_calls=[ToolCall(id=call_id, name="lookup_ip", arguments=ARGS)],
    )


async def drift_across_every_call():
    """Two tool steps then the step-cap synthesis pass — 3 model calls each."""
    scripts = [tool_step_stream("call_a"), tool_step_stream("call_b"),
               [StreamEvent(kind="content", text="summary."),
                StreamEvent(kind="finish", finish_reason="stop")]]
    results = [tool_step_blocking("call_a"), tool_step_blocking("call_b"),
               ChatResult(content="summary.", finish_reason="stop")]

    streaming, blocking = Streaming(scripts), Blocking(results)
    async for _ in loop(max_steps=2).run_stream(streaming, "check 203.0.113.99"):
        pass
    await loop(max_steps=2).run(blocking, "check 203.0.113.99")

    print(f"  calls: stream={len(streaming.calls)} blocking={len(blocking.calls)}")
    assert len(streaming.calls) == len(blocking.calls) == 3, (
        "CONTROL FAILED: the two paths did not make 3 calls each, so a "
        "per-call comparison would be comparing different turns"
    )

    verdicts = []
    for i, (s, b) in enumerate(zip(streaming.calls, blocking.calls, strict=True)):
        same_msgs = s["messages"] == b["messages"]
        verdicts.append(same_msgs)
        label = "IDENTICAL" if same_msgs else "DIVERGED"
        print(f"  call {i}: messages {label}  (stream kwargs={sorted(s['kwargs'])}, "
              f"blocking kwargs={sorted(b['kwargs'])})")
        if not same_msgs:
            for j, (sm, bm) in enumerate(zip(s["messages"], b["messages"], strict=False)):
                if sm != bm:
                    print(f"      msg {j} stream:   {json.dumps(sm)[:220]}")
                    print(f"      msg {j} blocking: {json.dumps(bm)[:220]}")
            if len(s["messages"]) != len(b["messages"]):
                print(f"      LENGTHS DIFFER: {len(s['messages'])} vs {len(b['messages'])}")
    print(f"  => all three calls identical: {all(verdicts)}")

    # The S25 test's actual reach, stated arithmetically.
    print(f"  => the shipped test compares 1 of {len(streaming.calls)} calls")


async def what_a_failed_call_costs():
    claims = []

    async def claim() -> bool:
        claims.append(1)
        return True

    # Call 1 serves a tool step; call 2 dies after the claim.
    streaming = Streaming([tool_step_stream("call_a"),
                           [LLMError(500, "endpoint died")]])
    served = 0
    error = None
    try:
        async for _ in loop().run_stream(streaming, "check 203.0.113.99", claim=claim):
            pass
    except LLMError as err:
        error = str(err)
    served = len(streaming.calls)
    print(f"  claims taken: {len(claims)}   calls attempted: {served}   "
          f"calls that produced a result: {served - 1}")
    print(f"  raised: {error}")
    print(f"  => charged {len(claims)} for {served - 1} served")


async def main():
    print("S26 Step 0 — drift across every call, and what a failed call costs")
    print("=" * 78)
    print("\n[1] run vs run_stream — EVERY call, not just the first")
    await drift_across_every_call()
    print("\n[2] the claim when the endpoint dies mid-turn")
    await what_a_failed_call_costs()
    print("\n" + "=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
