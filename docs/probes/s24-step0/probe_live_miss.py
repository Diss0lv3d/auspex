"""S24 — the two HONEST-MISS paths, probed with controls that are actually off-corpus.

The first attempt used "quokka exfiltration ritual", which contains a real ATT&CK
term and duly returned TA0010. That measured the KB's recall, not the miss path.
A control for a miss must be off-corpus in every token that carries meaning.
"""
import asyncio
import json

from auspex.agent.capabilities import build_capability_registry
from auspex.config import Settings
from auspex.enrich import EnrichmentService
from auspex.kb import KnowledgeService


async def main():
    settings = Settings()
    kb, enrichment = KnowledgeService.from_settings(settings), EnrichmentService.from_settings(settings)
    reg = build_capability_registry(enrichment=enrichment, kb=kb)
    try:
        for q in ["how do I bake sourdough bread",
                  "what is the capital of Portugal",
                  "what is lateral movement"]:            # the positive control
            r = await reg.get("search_knowledge").handler({"query": q})
            got = r.get("miss") or (r["results"][0]["title"] if r.get("results") else "?")
            print(f"search_knowledge {q!r:38} -> {'MISS: ' + r['miss'] if r.get('miss') else got}")

        r = await reg.get("lookup_cve").handler(
            {"cve_ids": ["CVE-2021-44228", "CVE-1999-99999", "CVE-2049-00001"]})
        print(f"\nlookup_cve found    : {list(r['found'])}")
        print(f"lookup_cve not_found: {r['not_found']}")
        print(f"(control: a real id resolves AND fabricated ids miss, in the same call)")

        r = await reg.get("enrich_observable").handler({"observables": ["10.0.0.1"]})
        print(f"\nprivate address -> {json.dumps(r['results'][0].get('not_checked'))}")
    finally:
        await kb.aclose(); await enrichment.aclose()


asyncio.run(main())
