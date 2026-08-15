"""TD-005 re-battery, part 2 — the REAL production definition path.

battery_td005.py measures the neural leg in isolation. The user-visible answer
comes from KnowledgeService.search() (BM25 + neural, RRF-fused, regime floor)
and render_definition_answer() renders hits[0] as THE definition. So the thing
that must still be right at 31,819 docs is the FUSED top hit, not the leg.

Drives the real service against the live index. Reads only.
Run: .venv/bin/python docs/probes/s19-step0/battery_definition_path.py
"""

import asyncio
import json
import sys

sys.path.insert(0, ".")
from auspex.kb.echo import render_definition_answer  # noqa: E402
from auspex.kb.service import KnowledgeService  # noqa: E402

CURATED = ("concept", "technique", "tactic")

# Same labeled battery; `expected` is the doc the analyst asking this question
# should get as the DEFINITION (hits[0]), not merely somewhere in the list.
BATTERY = [
    ("what is lateral movement", "CONCEPT-LATERAL-MOVEMENT"),
    ("how do adversaries abuse command line interpreters", "T1059"),
    ("what is credential access", "TA0006"),
    ("what is process injection", "T1055"),
    ("what is phishing", "T1566"),
    ("what is credential dumping", "T1003"),
    ("living off the land binaries", "CONCEPT-LOLBIN"),
    ("employee vacation policy template", None),
    ("what is quantum entanglement", None),
    ("best hiking trails in the alps", None),
    ("how do I bake sourdough bread", None),
]


async def main():
    kb = KnowledgeService("http://localhost:9200", enabled=True)
    rows = []
    try:
        print(f"{'query':52s} {'fused top':22s} {'verdict'}")
        print("=" * 100)
        for query, expected in BATTERY:
            hits = await kb.search(query, doc_types=CURATED)
            rendered = render_definition_answer(hits)
            top = hits[0].doc_id if hits else None
            if expected is None:
                ok = rendered is None
                verdict = "honest MISS (correct)" if ok else f"!! FABRICATED -> {top}"
            else:
                ok = top == expected
                verdict = "correct definition" if ok else f"!! WRONG TOP (wanted {expected})"
            rank = next((i for i, h in enumerate(hits) if h.doc_id == expected), None)
            rows.append(
                {
                    "query": query,
                    "expected": expected,
                    "fused_top": top,
                    "fused_top_title": hits[0].title if hits else None,
                    "n_hits": len(hits),
                    "expected_rank": rank,
                    "ok": ok,
                    "first_line": rendered.splitlines()[0] if rendered else None,
                }
            )
            print(f"{query[:52]:52s} {str(top)[:22]:22s} {verdict}")

        bad = [r for r in rows if not r["ok"]]
        print(f"\n{len(rows) - len(bad)}/{len(rows)} correct; {len(bad)} wrong")
        for r in bad:
            print(f"\n  QUERY : {r['query']}")
            print(f"  WANTED: {r['expected']}")
            print(f"  GOT   : {r['fused_top']} — {r['fused_top_title']}")
            print(f"  rank of wanted: {r['expected_rank']} (of {r['n_hits']} hits)")
            print(f"  renders as: {r['first_line']}")
        with open("docs/probes/s19-step0/battery_definition_result.json", "w") as fh:
            json.dump(rows, fh, indent=2)
        print("\nwrote docs/probes/s19-step0/battery_definition_result.json")
    finally:
        await kb.aclose()


asyncio.run(main())
