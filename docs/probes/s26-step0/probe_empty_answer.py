"""S26 Step 0, FINDING — a turn that produced no answer reports `final_answer`.

`run_stream` ends a turn with `stop_reason="final_answer"` whenever the model
call yielded no tool calls. It does not ask whether there was an ANSWER. An
endpoint that streams nothing, or streams only reasoning and then hits its token
ceiling, therefore ends the turn with:

    done(stop_reason='final_answer', text='', finish_reason=...)

which is the same terminal state a complete answer produces. The route S26 is
about to build persists `done.text` as the assistant turn (NEXT-SESSION goal 2),
so *nothing happened* would be stored and rendered as *the answer is nothing*.

The realistic path is not an exotic endpoint. It is a THINKING MODEL: reasoning
tokens count against `max_tokens`, so a model that thinks past its budget emits
reasoning deltas, `finish_reason="length"`, and no content at all. STATE.md
standing follow-up 9 records that the default endpoint takes the two-pass path,
and the local dev model (qwen3:14b) is a thinking model.

The control is arithmetic: the same script with ONE content delta added must
produce a non-empty answer, so the empty result is attributable to the missing
content rather than to the harness.

Run:  .venv/bin/python docs/probes/s26-step0/probe_empty_answer.py
"""

import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from _fakes import InMemoryProposalStore  # noqa: E402

from auspex.agent.loop import AgentLoop  # noqa: E402
from auspex.agent.registry import ToolLevel, ToolRegistry  # noqa: E402
from auspex.llm.client import ChatResult, StreamEvent  # noqa: E402

WORKSPACE = "00000000-0000-0000-0000-000000000001"


def loop(**over):
    reg = ToolRegistry()

    async def lookup_ip(args: dict) -> dict:
        return {"ip": args.get("ip"), "reputation": "malicious"}

    reg.add(
        name="lookup_ip", description="Look up an IP.",
        parameters={"ip": {"type": "string", "description": "the IP"}},
        required=["ip"], level=ToolLevel.READ, handler=lookup_ip,
    )
    return AgentLoop(
        reg, InMemoryProposalStore(), mode="native_tools", workspace_id=WORKSPACE, **over
    )


class Streaming:
    def __init__(self, scripts):
        self._scripts = [list(s) for s in scripts]
        self.calls = []

    async def chat_stream(self, messages, **kwargs):
        idx = len(self.calls)
        self.calls.append(messages)
        for event in self._scripts[idx] if idx < len(self._scripts) else []:
            yield event


class Blocking:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    async def chat(self, messages, **kwargs):
        idx = len(self.calls)
        self.calls.append(messages)
        return self._results[idx] if idx < len(self._results) else ChatResult()


THINKING_PAST_BUDGET = [
    StreamEvent(kind="reasoning", text="The user asked about 203.0.113.99. Let me "),
    StreamEvent(kind="reasoning", text="consider what the indicators might mean, and "),
    StreamEvent(kind="reasoning", text="whether enrichment would help here, and also "),
    StreamEvent(kind="finish", finish_reason="length"),
]


async def run_case(label, script, expect_content):
    events = [ev async for ev in loop().run_stream(Streaming([script]), "check 203.0.113.99")]
    done = events[-1]
    reasoning = "".join(e.text for e in events if e.kind == "reasoning")
    content = "".join(e.text for e in events if e.kind == "content")
    assert bool(content) is expect_content, (
        f"CONTROL FAILED for {label}: expected content={expect_content}, got {content!r}"
    )
    print(f"  [{label}]")
    print(f"      analyst saw reasoning: {len(reasoning)} chars, content: {len(content)} chars")
    print(f"      done(stop_reason={done.stop_reason!r}, text={done.text!r}, "
          f"finish_reason={done.finish_reason!r})")
    return done


async def main():
    print("S26 Step 0 — the empty answer that calls itself a final answer")
    print("=" * 78)

    print("\n[subject] a thinking model that spends its whole budget on reasoning")
    subject = await run_case("reasoning only, finish_reason=length", THINKING_PAST_BUDGET, False)

    print("\n[control] the SAME script with one content delta added")
    with_content = [
        *THINKING_PAST_BUDGET[:-1],
        StreamEvent(kind="content", text="203.0.113.99 is malicious."),
        StreamEvent(kind="finish", finish_reason="stop"),
    ]
    control = await run_case("reasoning + one content delta", with_content, True)

    print("\n[the collapse]")
    print(f"      subject stop_reason: {subject.stop_reason!r}  text={subject.text!r}")
    print(f"      control stop_reason: {control.stop_reason!r}  text={control.text!r}")
    same = subject.stop_reason == control.stop_reason
    print("      => a turn with NO answer and a turn WITH an answer are reported")
    print(f"         with the same stop_reason: {same}")
    print(f"      => the route persists {subject.text!r} as the assistant turn")

    print("\n[does the blocking path share the shape?] (a fix must not create drift)")
    blocking = Blocking([ChatResult(content="", finish_reason="length", reasoning="...")])
    result = await loop().run(blocking, "check 203.0.113.99")
    print(f"      run() -> AgentResult(content={result.content!r}, "
          f"stopped_reason={result.stopped_reason!r})")

    print("\n" + "=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
