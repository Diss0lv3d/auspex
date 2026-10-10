"""S26 — what actually caused S25's refusal: the tool offer, or the wording?

S25 measured Scout refusing a question no tool answers — "I am unable to fulfill
this request as the functions provided are insufficient" — and concluded that
**offering tools changes what the model does with questions the tools do not
cover**. That conclusion became the reason the routing question exists at all,
and it is written into STATE.md standing follow-up 10 and NEXT-SESSION's goal 1.

The S25 probe offered tools in every single case. It therefore established that
the refusal HAPPENS; it could not establish what CAUSED it. And it used its own
system message:

    "You are a security co-analyst. Use the available tools to gather evidence
     before answering. If no tool applies, just answer."

which is NOT the message `AgentLoop` composes. The route will send the loop's.

This is the 2x2 that separates the two variables, each cell repeated so a
one-shot fluke cannot decide a routing rule:

              tools ON            tools OFF
    S25 msg   [the S25 cell]      [is it the wording alone?]
    loop msg  [what the route     [today's conversational
               would actually do]  deep path]

`temperature=0`, but no endpoint is bit-deterministic, so REPEATS is the control:
a cell that refuses once and answers twice is not a property of anything.

**Re-run 2026-10-10 on glm-4.5-air (D-034).** Written against Scout, which is
gone. Two things a thinking model changes, both now printed per run rather than
assumed: the reasoning budget (thinking is billed inside `max_tokens`, so a run
can end `empty_answer` — a non-answer, which is not a refusal either), and
TD-036 (prose precedes a tool call on this endpoint, so the content of a
tool-calling step is narration, not the answer). The KB and enrichment are now
pinned live from the host, so a spurious tool call runs for real instead of
failing on a compose hostname.

Run:  .venv/bin/python docs/probes/s26-step0/probe_refusal_cause.py
"""

import asyncio
import os
import sys

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
os.environ["KB_ENABLED"] = "true"
os.environ["ENRICHMENT_ENABLED"] = "true"

from auspex.agent.capabilities import build_capability_registry
from auspex.agent.loop import DEFAULT_SYSTEM_PROMPT, AgentLoop
from auspex.config import Settings
from auspex.enrich import EnrichmentService
from auspex.kb import KnowledgeService
from auspex.llm.client import LLMClient

WORKSPACE = "00000000-0000-0000-0000-000000000001"
REPEATS = 3

# S25's control prompt, verbatim, so this is comparable to that measurement
# rather than merely similar.
PROMPT = "Write me a status update for my manager about this week."

S25_SYSTEM = (
    "You are a security co-analyst. Use the available tools to gather evidence "
    "before answering. If no tool applies, just answer."
)

REFUSAL_MARKERS = ("insufficient", "unable to fulfill", "cannot fulfill",
                   "unable to fulfil", "functions provided", "no function",
                   "do not have the function", "don't have the function")


def refused(answer: str) -> bool:
    low = answer.lower()
    return any(m in low for m in REFUSAL_MARKERS)


class _Store:
    async def create(self, **kw):
        return {"id": "probe", "card": {}}


async def one(client, registry, system, with_tools):
    loop = AgentLoop(registry, _Store(), mode="native_tools",
                     workspace_id=WORKSPACE, system_prompt=system, max_steps=2)
    tool_names = None if with_tools else []
    calls, reasoning, done = [], 0, None
    tool_steps: set[int] = set()
    content_by_step: dict[int, list[str]] = {}
    async for ev in loop.run_stream(client, PROMPT, tool_names=tool_names):
        if ev.kind == "content":
            content_by_step.setdefault(ev.step, []).append(ev.text)
        elif ev.kind == "reasoning":
            reasoning += len(ev.text)
        elif ev.kind == "tool":
            calls.append(ev.invocation.name)
            tool_steps.add(ev.step)
        elif ev.kind == "done":
            done = ev
    offered = len(loop.wire_specs(tool_names))
    expected = 3 if with_tools else 0
    assert offered == expected, (
        f"CONTROL FAILED: expected {expected} tools on the wire, got {offered}"
    )
    narration = sum(len("".join(v)) for k, v in content_by_step.items() if k in tool_steps)
    return {
        # The ANSWER is the done event's text (the last call's content) — what
        # the route would persist. Narration from tool-calling steps is TD-036's.
        "answer": (done.text or "").strip(),
        "calls": calls,
        "stop": done.stop_reason,
        "finish": done.finish_reason,
        "reasoning_chars": reasoning,
        "narration_chars": narration,
    }


async def main() -> None:
    s = Settings()
    enrichment = EnrichmentService.from_settings(s)
    kb = KnowledgeService.from_settings(s)
    registry = build_capability_registry(enrichment=enrichment, kb=kb)
    client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)

    print("S26 — what caused the S25 refusal?")
    print("=" * 78)
    print(f"model: {s.llm_model}   kb.active={kb.active} enrichment.active={enrichment.active}")
    print(f"prompt (S25's control, verbatim): {PROMPT!r}")
    print(f"repeats per cell: {REPEATS}\n")

    cells = [
        ("S25 message ", "tools ON ", S25_SYSTEM, True),
        ("S25 message ", "tools OFF", S25_SYSTEM, False),
        ("loop message", "tools ON ", DEFAULT_SYSTEM_PROMPT, True),
        ("loop message", "tools OFF", DEFAULT_SYSTEM_PROMPT, False),
    ]
    table = {}
    try:
        for msg_label, tool_label, system, with_tools in cells:
            refusals = 0
            print(f"  {msg_label} / {tool_label}:")
            for i in range(1, REPEATS + 1):
                r = await one(client, registry, system, with_tools)
                is_refusal = refused(r["answer"])
                refusals += is_refusal
                # The tool calls are the point, not an aside: a spurious call is
                # how "offering tools changes what the model does" shows up.
                print(f"    run {i}: calls={r['calls'] or None} stop={r['stop']} "
                      f"finish={r['finish']} reasoning={r['reasoning_chars']} "
                      f"narration={r['narration_chars']} answer={len(r['answer'])} "
                      f"refusal={is_refusal}")
                print(f"        {r['answer'][:400]!r}")
            table[(msg_label, tool_label)] = refusals
            print(f"    => refused {refusals}/{REPEATS}")
    finally:
        await client.aclose()

    print("\n" + "-" * 78)
    print("  RESULT")
    print(f"    S25 message,  tools ON : {table[('S25 message ', 'tools ON ')]}/{REPEATS}")
    print(f"    S25 message,  tools OFF: {table[('S25 message ', 'tools OFF')]}/{REPEATS}")
    print(f"    loop message, tools ON : {table[('loop message', 'tools ON ')]}/{REPEATS}")
    print(f"    loop message, tools OFF: {table[('loop message', 'tools OFF')]}/{REPEATS}")
    on = table[("S25 message ", "tools ON ")] + table[("loop message", "tools ON ")]
    off = table[("S25 message ", "tools OFF")] + table[("loop message", "tools OFF")]
    s25 = table[("S25 message ", "tools ON ")] + table[("S25 message ", "tools OFF")]
    lp = table[("loop message", "tools ON ")] + table[("loop message", "tools OFF")]
    print(f"\n    refusals with tools ON: {on}   with tools OFF: {off}")
    print(f"    refusals on S25 wording: {s25}   on loop wording: {lp}")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
