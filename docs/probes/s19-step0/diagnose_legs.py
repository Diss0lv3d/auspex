"""Why does the definition path render the wrong page? Dump both legs + fusion.

For each failing battery query: the BM25 leg, the neural leg (post-floor), the
RRF-fused order, and where apply_floor cuts. Establishes whether the wrong top
hit comes from the embedding, from BM25, or from fusion/floor interaction.

Reads only. Run: .venv/bin/python docs/probes/s19-step0/diagnose_legs.py
"""

import asyncio
import sys

sys.path.insert(0, ".")
from auspex.kb.fuse import apply_floor, regime_cutoff, rrf_fuse  # noqa: E402
from auspex.kb.service import KnowledgeService  # noqa: E402

CURATED = ("concept", "technique", "tactic")
FAILING = [
    ("what is lateral movement", "CONCEPT-LATERAL-MOVEMENT"),
    ("how do adversaries abuse command line interpreters", "T1059"),
    ("what is phishing", "T1566"),
    ("what is credential dumping", "T1003"),
]
TOP_K = 5


async def main():
    kb = KnowledgeService("http://localhost:9200", enabled=True)
    try:
        for query, expected in FAILING:
            print(f"\n{'=' * 92}\nQUERY: {query}\nWANTED AS DEFINITION: {expected}\n{'=' * 92}")
            bm25 = await kb._bm25(query, TOP_K * 2, CURATED)
            neural = await kb._neural(query, TOP_K * 2, CURATED)

            print("  BM25 leg (size 10):")
            for i, h in enumerate(bm25):
                mark = " <<<" if h.doc_id == expected else ""
                print(f"    {i:2d} {h.score:8.4f} {h.doc_id[:26]:26s} {h.title[:40]}{mark}")
            if not any(h.doc_id == expected for h in bm25):
                print(f"    (expected {expected} ABSENT from BM25 leg)")

            print("  NEURAL leg (size 10, post neural_leg_floor):")
            for i, h in enumerate(neural):
                mark = " <<<" if h.doc_id == expected else ""
                print(f"    {i:2d} {h.score:8.4f} {h.doc_id[:26]:26s} {h.title[:40]}{mark}")
            if not any(h.doc_id == expected for h in neural):
                print(f"    (expected {expected} ABSENT from NEURAL leg)")

            fused = rrf_fuse(bm25, neural, top_k=TOP_K)
            print("  RRF-FUSED (top_k=5):")
            for i, h in enumerate(fused):
                mark = " <<<" if h.doc_id == expected else ""
                print(f"    {i:2d} {h.score:8.6f} {h.doc_id[:26]:26s} {h.title[:40]}{mark}")

            if fused:
                cut = regime_cutoff(fused[0].score)
                kept = apply_floor(fused)
                print(f"  regime_cutoff = {cut:.6f} (top {fused[0].score:.6f}) -> kept {len(kept)}")
                dropped = [h.doc_id for h in fused if h not in kept]
                if dropped:
                    print(f"  dropped by floor: {dropped}")
                print(f"  RENDERED DEFINITION = {kept[0].doc_id if kept else None}")
    finally:
        await kb.aclose()


asyncio.run(main())
