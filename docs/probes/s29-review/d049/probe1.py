import asyncio, json, sys
sys.path.insert(0, "/home/burhan/auspex-new")
sys.path.insert(0, "/home/burhan/auspex-new/tests")
from auspex.agent.capabilities import build_capability_registry, SNIPPET_CHARS
from auspex.classify.observables import extract, ObservableType
from auspex.enrich.service import EnrichmentService
from auspex.enrich.providers.base import Provider
from auspex.enrich.types import ProviderSignal, VerdictLabel
from auspex.enrich.verdict import synthesize
from auspex.kb.types import KBHit
from _fakes import FakeKnowledgeService

class FakeProv(Provider):
    name = "FakeSrc"
    accepts = frozenset({ObservableType.IPV4, ObservableType.IPV6, ObservableType.DOMAIN, ObservableType.URL})
    def __init__(self, sig=None): self.sig = sig; self.asked = []
    async def lookup(self, client, obs):
        self.asked.append(obs.value)
        return self.sig

async def main():
    # --- 1. KB snippet truncation manufactures a new, allowed indicator ---
    pad = "x " * ((SNIPPET_CHARS - len("C2 server at ")) // 2)
    text = pad + "C2 server at " + "185.220.101.45 and badsite.com observed"
    text = text[:SNIPPET_CHARS-1] + text[SNIPPET_CHARS-1:]  # unchanged
    # position so that the cut lands inside the IP
    prefix = "y" * (SNIPPET_CHARS - len("185.220.101.4")) 
    text = prefix + " "[:0] + "185.220.101.45 is the C2"
    text = "z" * (SNIPPET_CHARS - len(" 185.220.101.4")) + " 185.220.101.45 is the C2"
    hit = KBHit(chunk_id="c", doc_id="d", title="T1071", text=text, doc_type="technique",
                source="mitre", source_ref="", ids=(), severity="", cvss_score=None, score=1.0)
    prov = FakeProv()
    svc = EnrichmentService([prov])
    rec = []
    async def record(o):
        rec.append([i.observable.value for i in o.enriched]); return 0
    reg = build_capability_registry(enrichment=svc, kb=FakeKnowledgeService([hit]),
                                    observables=(), supplied=(), record=record)
    r = await reg.get("search_knowledge").handler({"query": "c2"})
    shown = r["results"][0]["text"]
    print("1. snippet tail:", repr(shown[-16:]), "truncated:", r["results"][0]["text_truncated"])
    r2 = await reg.get("enrich_observable").handler({"observables": ["185.220.101.4"]})
    print("   provider asked:", prov.asked, "recorded:", rec, "result.recorded:", r2.get("recorded"))
    r3 = await reg.get("enrich_observable").handler({"observables": ["185.220.101.45"]})
    print("   the REAL indicator:", r3["results"][0].get("not_checked", "looked up")[:40])

    # --- 2. recorded:true with no verdict possible, plus mixed not_checked items ---
    prov2 = FakeProv(sig=None)  # answers, no data
    svc2 = EnrichmentService([prov2])
    obs = extract("check 185.220.101.5 and 10.0.0.5 please").observables
    rec2 = []
    async def record2(o):
        rec2.append(o); return sum(1 for i in o.enriched if synthesize(i.observable, i.signals))
    reg2 = build_capability_registry(enrichment=svc2, kb=FakeKnowledgeService(), observables=obs, record=record2)
    r = await reg2.get("enrich_observable").handler({"observables": [o.obs_id for o in obs] + ["8.8.4.4"]})
    print("2.", json.dumps(r, indent=None)[:900])
    print("   verdict rows the real persist would write:", sum(1 for i in rec2[0].enriched if synthesize(i.observable, i.signals)))

    # --- 3. context-only (InternetDB-shaped) signal synthesizes an UNKNOWN verdict that IS persisted ---
    ip = extract("185.220.101.6").observables[0]
    v = synthesize(ip, (ProviderSignal("InternetDB", VerdictLabel.UNKNOWN, 0.0, "open ports 80"),))
    print("3. context-only synthesize ->", v)

    # --- 4. same indicator twice in one turn -> record called twice ---
    prov4 = FakeProv(sig=ProviderSignal("FakeSrc", VerdictLabel.MALICIOUS, 0.9, "listed"))
    svc4 = EnrichmentService([prov4])
    obs4 = extract("check 185.220.101.7").observables
    calls = []
    async def record4(o): calls.append(len(o.enriched)); return 1
    reg4 = build_capability_registry(enrichment=svc4, kb=FakeKnowledgeService(), observables=obs4, record=record4)
    for _ in range(3):
        await reg4.get("enrich_observable").handler({"observables": [obs4[0].obs_id]})
    print("4. record calls for one indicator in one turn:", calls)
    await svc.aclose(); await svc2.aclose(); await svc4.aclose()

asyncio.run(main())
