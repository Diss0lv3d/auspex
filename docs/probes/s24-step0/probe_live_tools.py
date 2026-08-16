"""S24 — the capability tools against the REAL services, in the container.

The unit tests use duck-typed fakes (`FakeKnowledgeService`,
`FakeEnrichmentService`). A fake that has drifted from the class it stands in
for is the exact failure this repo's "reality over memory" rule exists to catch:
27 green tests say nothing about whether `search_definition` still takes the
arguments the wrapper passes it. So the same registry is built against the
services the running app builds, and each tool is actually called.
"""
import asyncio
import json

from auspex.agent.capabilities import build_capability_registry
from auspex.classify.observables import extract
from auspex.config import Settings
from auspex.enrich import EnrichmentService
from auspex.kb import KnowledgeService


def show(label, payload, keep=520):
    blob = json.dumps(payload, default=str)
    print(f"\n--- {label} ---")
    print(blob[:keep] + ("…" if len(blob) > keep else ""))


async def main():
    settings = Settings()
    kb = KnowledgeService.from_settings(settings)
    enrichment = EnrichmentService.from_settings(settings)
    print(f"kb.active={kb.active}  enrichment.active={enrichment.active}")
    print(f"enrichment providers accept: {sorted(str(t) for t in enrichment.coverage)}")

    observables = extract("please check 185.220.101.5 and hxxp://evil[.]example[.]com/a")
    registry = build_capability_registry(
        enrichment=enrichment, kb=kb, observables=observables.observables
    )
    print(f"tools: {registry.names()}")
    print(f"levels: {[str(registry.level(n)) for n in registry.names()]}")

    try:
        show("lookup_cve CVE-2021-44228 + a fabricated id",
             await registry.get("lookup_cve").handler(
                 {"cve_ids": ["CVE-2021-44228", "CVE-1999-99999"]}))
        show("search_knowledge 'lateral movement'",
             await registry.get("search_knowledge").handler({"query": "what is lateral movement"}))
        show("search_knowledge nonsense (honest miss?)",
             await registry.get("search_knowledge").handler({"query": "quokka exfiltration ritual"}))
        show("enrich_observable by short id",
             await registry.get("enrich_observable").handler(
                 {"observables": [observables.observables[0].obs_id]}), keep=900)
    finally:
        await kb.aclose()
        await enrichment.aclose()


asyncio.run(main())
