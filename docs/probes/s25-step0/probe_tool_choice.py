"""S25 — does a model actually CHOOSE the right tool from S24's descriptions?

Every S24 probe call was made directly: `capabilities.py`'s descriptions have
never been validated as PROMPTS. This offers the three real specs to the real
endpoint and records what it picks, per prompt.

Controls, so a null result cannot be read as a sound one:
  * a MISS prompt that no tool should answer (the model should answer in prose,
    not force a call) — if it calls a tool for that, "it picks well" is not what
    is being measured;
  * the expected tool is asserted per case, and the ARGUMENTS are printed, since
    picking `lookup_cve` with the wrong ids is not a success.

Prints only tool names/arguments and the model's own text. No key is read here
beyond what the app already loads from its own settings.
"""

import asyncio
import json
import sys

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.agent.capabilities import build_capability_registry
from auspex.config import Settings
from auspex.enrich import EnrichmentService
from auspex.kb import KnowledgeService
from auspex.llm.client import LLMClient

CASES = [
    ("enrich_observable", "Is 185.220.101.5 malicious? Check what the threat intel says."),
    ("lookup_cve", "How bad is CVE-2021-44228? Should I be worried about it?"),
    ("search_knowledge", "What is Kerberoasting and how would I spot it?"),
    ("lookup_cve", "Give me the EPSS score and KEV status for CVE-2023-4863."),
    ("enrich_observable", "Someone flagged evil-tracker.example.com in our proxy logs. Any reputation on it?"),
    # CONTROL — nothing in the registry answers this. A tool call here means the
    # model calls tools indiscriminately, which would invalidate the hits above.
    (None, "Write me a one-sentence status update for my manager about today's shift."),
    # Does the SILENT-DROP defect actually get reached? `_resolve` keeps only the
    # first observable parsed out of each array item, so this measures whether a
    # real model packs several indicators into ONE string (defect reached) or
    # sends them as separate items (defect latent on this endpoint).
    ("enrich_observable",
     "Check these three for me: 185.220.101.5, 45.83.64.1 and 91.219.236.166."),
    ("enrich_observable",
     "Are any of 8.8.8.8, 1.1.1.1, 9.9.9.9 associated with malicious activity?"),
]

SYSTEM = (
    "You are a security co-analyst. Use the available tools to gather evidence "
    "before answering. If no tool applies, just answer."
)


async def main() -> None:
    s = Settings()
    if not s.llm_base_url or not s.llm_model:
        print("no endpoint configured — STOP")
        return
    print(f"endpoint model: {s.llm_model}")

    # Only the SPECS matter here — this measures the descriptions as prompts, and
    # no handler is ever invoked (one chat call, no loop). Empty services keep
    # the probe from touching a provider or the KB.
    registry = build_capability_registry(
        enrichment=EnrichmentService(providers=[]), kb=KnowledgeService(base_url="")
    )
    specs = registry.specs()
    names = [t["function"]["name"] for t in specs]
    assert sorted(names) == ["enrich_observable", "lookup_cve", "search_knowledge"], names
    print(f"tools offered: {names}\n")

    client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
    hits = misses = 0
    try:
        for expected, prompt in CASES:
            try:
                res = await client.chat(
                    [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
                    tools=specs,
                    max_tokens=600,
                    temperature=0,
                )
            except Exception as err:
                print(f"[{expected}] {prompt[:55]!r} -> ERROR {type(err).__name__}: {err}")
                continue
            called = [(c.name, c.arguments) for c in res.tool_calls]
            got = called[0][0] if called else None
            ok = got == expected
            hits += ok
            misses += not ok
            print(f"{'OK ' if ok else 'XX '} expected={expected!r} got={got!r}")
            for name, raw in called:
                print(f"      call: {name}({raw})")
            if not called:
                print(f"      no call; content: {res.content[:120]!r}")
            print(f"      finish_reason={res.finish_reason} content_chars={len(res.content)}")
    finally:
        await client.aclose()
    print(f"\n{hits} expected / {hits + misses} cases")
    print(json.dumps({"hits": hits, "misses": misses}))


asyncio.run(main())
