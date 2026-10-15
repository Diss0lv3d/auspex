import asyncio, importlib.util, sys
sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
S = sys.argv[1]
from _fakes import FakeEnrichmentService, FakeKnowledgeService
import auspex.agent.capabilities as new
spec = importlib.util.spec_from_file_location("cap_old", S + "/capabilities_old.py")
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
from auspex.kb.types import KBHit
from auspex.enrich.types import EnrichmentOutcome, ObservableEnrichment
from auspex.classify.observables import extract
SN = new.SNIPPET_CHARS
class LUE(FakeEnrichmentService):
    def __init__(self): super().__init__(EnrichmentOutcome(items=()))
    async def enrich(self, observables):
        self.enrich_calls.append(observables)
        return EnrichmentOutcome(items=tuple(ObservableEnrichment(observable=o, sources_answered=1) for o in observables))
def hit(text, title="CVE-2021-44228", source_ref="https://nvd.nist.gov/vuln/detail/CVE-2021-44228"):
    return KBHit(chunk_id="c#0", doc_id="CVE-2021-44228", title=title, text=text, doc_type="cve", source="nvd",
                 source_ref=source_ref, ids=("CVE-2021-44228",), severity="CRITICAL", cvss_score=10.0, score=10.0)
async def run(mod, text, ask, **kw):
    svc = LUE(); rec = []
    async def record(o): rec.append(o); return 1
    reg = mod.build_capability_registry(enrichment=svc, kb=FakeKnowledgeService(hits=[hit(text, **kw)]), observables=(), record=record)
    shown = await reg.get("search_knowledge").handler({"query": "c2"})
    r = await reg.get("enrich_observable").handler({"observables": [ask]})
    looked = [o.value for c in svc.enrich_calls for o in c]
    return shown["results"][0]["text"][-30:], looked, r
async def main():
    print("extract a*40:", [(o.type, o.value) for o in extract("a"*40).observables])
    print("extract z.. a*40:", [(o.type, o.value) for o in extract("z"*5 + " " + "a"*40).observables])
    cases = [("185.220.101.45","185.220.101.4"),("badsite.com","badsite.co"),("a"*64,"a"*40)]
    for whole, cut in cases:
        text = "z" * (SN - len(cut) - 1) + f" {whole} was the C2 server."
        for name, mod in (("old", old), ("new", new)):
            tail, looked, r = await run(mod, text, cut)
            print(name, repr(cut[:16]), "looked:", looked, "res:", {k: (v if k!='results' else [x.get('not_checked','CHECKED') for x in v]) for k,v in r.items()})
asyncio.run(main())
