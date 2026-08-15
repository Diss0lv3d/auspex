"""TD-026, step 1 — RE-EXAMINE THE LABELS before attempting a third fix.

The S19 record says two of the seven positives are corpus-stale and must be
re-examined first, and names only one of them. A fix tuned against a wrong
label is worse than no fix: it optimises the retriever toward the wrong page and
the battery reports success.

So this prints, for every positive, the candidate docs the corpus ACTUALLY
contains — title and opening line, which is what an analyst reads — and leaves
the judgement to a human rather than asserting one. Reads only.

Run: .venv/bin/python docs/probes/s21-td026/relabel_battery.py
"""

import asyncio
import sys

sys.path.insert(0, ".")
from auspex.kb.service import KnowledgeService  # noqa: E402

CURATED = ("concept", "technique", "tactic")

POSITIVES = [
    ("what is lateral movement", "CONCEPT-LATERAL-MOVEMENT"),
    ("how do adversaries abuse command line interpreters", "T1059"),
    ("what is credential access", "TA0006"),
    ("what is process injection", "T1055"),
    ("what is phishing", "T1566"),
    ("what is credential dumping", "T1003"),
    ("living off the land binaries", "CONCEPT-LOLBIN"),
]


async def main() -> None:
    kb = KnowledgeService("http://localhost:9200", enabled=True)
    try:
        for query, labeled in POSITIVES:
            hits = await kb.search(query, doc_types=CURATED)
            print("=" * 78)
            print(f"QUERY   {query}")
            print(f"LABEL   {labeled}")
            for rank, hit in enumerate(hits):
                opening = " ".join((hit.text or "").split())[:110]
                flag = "  <-- LABELED" if hit.doc_id == labeled else ""
                print(f"  [{rank}] {hit.doc_id:28s} {hit.title[:44]:44s}{flag}")
                print(f"      {opening}")
            if labeled not in [h.doc_id for h in hits]:
                print(f"  (!) {labeled} is NOT in the returned {len(hits)} hits")
            print()
    finally:
        await kb.aclose()


asyncio.run(main())
