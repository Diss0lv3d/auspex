"""S26 — replay S25's refusal cell with S25's EXACT method.

`probe_refusal_cause.py` got 0 refusals in 12 attempts, but it drove the model
through `AgentLoop.run_stream` — streaming, and the loop's token budget. S25's
observation came from a different call shape: a NON-streaming `client.chat()`,
two messages, `max_tokens=600`. Before a documented conclusion is overturned it
gets replayed with the method that produced it, not with an approximation.

This is S25's cell, byte-for-byte: the same system message, the same prompt, the
same `chat()` call with the same arguments, repeated. The only thing added is
the repetition — which is the whole point, because the original ran once.

**Re-run 2026-10-10 on glm-4.5-air (D-034)** — Scout is gone, so this now asks
whether the NEW model refuses under S25's method, not whether S25 was right.
On a thinking model `max_tokens=600` covers the thinking too (billed inside
`completion_tokens`), so `finish=length` with no content is a budget outcome,
not a refusal; reasoning length is printed so the two cannot be confused.

Run:  .venv/bin/python docs/probes/s26-step0/probe_s25_refusal_replay.py
"""

import asyncio
import sys

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.agent.capabilities import build_capability_registry
from auspex.config import Settings
from auspex.enrich import EnrichmentService
from auspex.kb import KnowledgeService
from auspex.llm.client import LLMClient

REPEATS = 6

# All three verbatim from docs/probes/s25-step0/probe_tool_choice.py.
SYSTEM = (
    "You are a security co-analyst. Use the available tools to gather evidence "
    "before answering. If no tool applies, just answer."
)
PROMPT = "Write me a status update for my manager about this week."
MAX_TOKENS = 600

REFUSAL_MARKERS = ("insufficient", "unable to fulfill", "cannot fulfill",
                   "unable to fulfil", "functions provided", "no function")


def refused(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in REFUSAL_MARKERS)


async def main() -> None:
    s = Settings()
    # S25 used EMPTY services here — only the specs matter, no handler runs.
    registry = build_capability_registry(
        enrichment=EnrichmentService(providers=[]), kb=KnowledgeService(base_url="")
    )
    specs = registry.specs()
    names = sorted(t["function"]["name"] for t in specs)
    assert names == ["enrich_observable", "lookup_cve", "search_knowledge"], names

    client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
    print("S26 — replaying S25's refusal cell with S25's exact method")
    print("=" * 78)
    print(f"model: {s.llm_model}")
    print(f"method: non-streaming chat(), tools={names}, max_tokens={MAX_TOKENS}, temperature=0")
    print(f"prompt: {PROMPT!r}")
    print(f"repeats: {REPEATS}\n")

    refusals = 0
    try:
        for i in range(1, REPEATS + 1):
            res = await client.chat(
                [{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": PROMPT}],
                tools=specs,
                max_tokens=MAX_TOKENS,
                temperature=0,
            )
            called = [c.name for c in res.tool_calls]
            is_refusal = refused(res.content)
            refusals += is_refusal
            print(f"  run {i}: finish={res.finish_reason} calls={called} "
                  f"reasoning_chars={len(res.reasoning)} "
                  f"content_chars={len(res.content)} refusal={is_refusal}")
            print(f"      {res.content[:400]!r}")
    finally:
        await client.aclose()

    print(f"\n  => refused {refusals}/{REPEATS} with S25's exact method")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
