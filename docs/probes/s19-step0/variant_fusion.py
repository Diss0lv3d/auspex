"""Candidate fixes for the wrong-definition finding, measured on all 7 positives.

Baseline  : current rrf_fuse (accumulates per chunk_id).
Variant A : dedupe each leg to best-chunk-per-doc BEFORE fusion, so one doc
            casts exactly one vote per leg (standard RRF-over-documents).
Variant B : A + a title-exactness tiebreak — a doc whose TITLE is the query's
            subject is the canonical page for it.

Prints, per query, what each variant would render as THE definition.
Reads only. Run: .venv/bin/python docs/probes/s19-step0/variant_fusion.py
"""

import asyncio
import re
import sys

sys.path.insert(0, ".")
from auspex.kb.fuse import apply_floor, rrf_fuse  # noqa: E402
from auspex.kb.service import KnowledgeService  # noqa: E402
from auspex.kb.types import KBHit  # noqa: E402

CURATED = ("concept", "technique", "tactic")
TOP_K = 5

POSITIVES = [
    ("what is lateral movement", "CONCEPT-LATERAL-MOVEMENT"),
    ("how do adversaries abuse command line interpreters", "T1059"),
    ("what is credential access", "TA0006"),
    ("what is process injection", "T1055"),
    ("what is phishing", "T1566"),
    ("what is credential dumping", "T1003"),
    ("living off the land binaries", "CONCEPT-LOLBIN"),
]
NEGATIVES = [
    "employee vacation policy template",
    "what is quantum entanglement",
    "best hiking trails in the alps",
    "how do I bake sourdough bread",
]

_STOP = {"what", "is", "are", "the", "a", "an", "how", "do", "does", "i", "adversaries", "abuse"}


def dedupe_by_doc(hits: list[KBHit]) -> list[KBHit]:
    """Keep each doc's best-ranked chunk, preserving leg order."""
    seen: dict[str, KBHit] = {}
    for h in hits:
        seen.setdefault(h.doc_id, h)
    return list(seen.values())


def _subject(query: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _STOP]
    return " ".join(words)


def _title_core(title: str) -> str:
    # STIX titles are "T1566: Phishing"; our concepts are "Lateral Movement".
    core = title.split(":", 1)[1] if ":" in title else title
    return " ".join(re.findall(r"[a-z0-9]+", core.lower()))


def title_exact_first(hits: list[KBHit], query: str) -> list[KBHit]:
    """Promote a doc whose title IS the query's subject ahead of neighbours."""
    subject = _subject(query)
    if not subject:
        return hits
    exact = [h for h in hits if _title_core(h.title) == subject]
    rest = [h for h in hits if h not in exact]
    return exact + rest


async def main():
    kb = KnowledgeService("http://localhost:9200", enabled=True)
    try:
        print(f"{'query':52s} {'baseline':16s} {'variantA':16s} {'variantB':16s} wanted")
        print("=" * 118)
        score = {"baseline": 0, "A": 0, "B": 0}
        for query, expected in POSITIVES:
            bm25 = await kb._bm25(query, TOP_K * 2, CURATED)
            neural = await kb._neural(query, TOP_K * 2, CURATED)

            base = apply_floor(rrf_fuse(bm25, neural, top_k=TOP_K))
            va = apply_floor(
                rrf_fuse(dedupe_by_doc(bm25), dedupe_by_doc(neural), top_k=TOP_K)
            )
            vb = title_exact_first(va, query)

            tops = {
                "baseline": base[0].doc_id if base else None,
                "A": va[0].doc_id if va else None,
                "B": vb[0].doc_id if vb else None,
            }
            for k, v in tops.items():
                if v == expected:
                    score[k] += 1
            print(
                f"{query[:52]:52s} {str(tops['baseline'])[:16]:16s} "
                f"{str(tops['A'])[:16]:16s} {str(tops['B'])[:16]:16s} {expected}"
            )

        print(f"\ncorrect definitions: baseline {score['baseline']}/7, "
              f"A {score['A']}/7, B {score['B']}/7")

        # The safety property must survive any variant: off-corpus stays a miss.
        print("\nhonest-miss check (must be None for every variant):")
        for query in NEGATIVES:
            bm25 = await kb._bm25(query, TOP_K * 2, CURATED)
            neural = await kb._neural(query, TOP_K * 2, CURATED)
            base = apply_floor(rrf_fuse(bm25, neural, top_k=TOP_K))
            va = apply_floor(rrf_fuse(dedupe_by_doc(bm25), dedupe_by_doc(neural), top_k=TOP_K))
            vb = title_exact_first(va, query)
            print(
                f"  {query[:44]:44s} base={bool(base)} A={bool(va)} B={bool(vb)}"
                f"{'   !! LEAK' if (base or va or vb) else ''}"
            )
    finally:
        await kb.aclose()


asyncio.run(main())
