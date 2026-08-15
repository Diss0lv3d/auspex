"""TD-026 acceptance battery — the REAL definition path, re-labeled at S21.

The S19 version of this battery (docs/probes/s19-step0/) measured
`kb.search(...)`; the app now calls `kb.search_definition(...)`, so this one
drives that. Same queries, same live index, reads only.

**Labels re-examined first** (docs/probes/s21-td026/relabel_battery.py printed
every candidate page's title and opening line, and the judgement is recorded in
docs/probes/2026-08-15-s21-td026.md):

- `what is lateral movement` accepts EITHER `TA0008` or
  `CONCEPT-LATERAL-MOVEMENT`. Both pages define the term and TA0008 is titled
  exactly "Lateral Movement" — S19 called this label stale and it is.
- The other six labels were checked against the corpus and stand.
- S19's claim that **two** of the seven are stale does not survive: the second
  stale label is in the CVE battery (the SharePoint query), not this one.

Run: .venv/bin/python docs/probes/s21-td026/battery_definition_path.py
"""

import asyncio
import json
import sys

sys.path.insert(0, ".")
from auspex.kb.echo import render_definition_answer  # noqa: E402
from auspex.kb.service import KnowledgeService  # noqa: E402

# `expected` is the doc that must be rendered AS the definition (hits[0]).
# A tuple means either page is a correct answer to this question.
BATTERY: list[tuple[str, object]] = [
    ("what is lateral movement", ("TA0008", "CONCEPT-LATERAL-MOVEMENT")),
    ("how do adversaries abuse command line interpreters", "T1059"),
    ("what is credential access", "TA0006"),
    ("what is process injection", "T1055"),
    ("what is phishing", "T1566"),
    ("what is credential dumping", "T1003"),
    ("living off the land binaries", "CONCEPT-LOLBIN"),
    # The honest-miss half. Nothing here may EVER render an answer: promotion
    # and doc-level fusion re-order a post-floor list and must not resurrect.
    ("employee vacation policy template", None),
    ("what is quantum entanglement", None),
    ("best hiking trails in the alps", None),
    ("how do I bake sourdough bread", None),
]


async def main() -> list[dict]:
    kb = KnowledgeService("http://localhost:9200", enabled=True)
    rows = []
    try:
        print(f"{'query':52s} {'rendered top':24s} {'verdict'}")
        print("=" * 104)
        for query, expected in BATTERY:
            hits = await kb.search_definition(query)
            rendered = render_definition_answer(hits)
            top = hits[0].doc_id if hits else None
            if expected is None:
                ok = rendered is None
                verdict = "honest MISS (correct)" if ok else f"!! FABRICATED -> {top}"
            else:
                accepted = expected if isinstance(expected, tuple) else (expected,)
                ok = top in accepted
                verdict = "correct definition" if ok else f"!! WRONG TOP (wanted {expected})"
            rows.append(
                {
                    "query": query,
                    "expected": expected,
                    "rendered_top": top,
                    "rendered_top_title": hits[0].title if hits else None,
                    "n_hits": len(hits),
                    "ok": ok,
                }
            )
            print(f"{query[:52]:52s} {str(top)[:24]:24s} {verdict}")

        positives = [r for r in rows if r["expected"] is not None]
        misses = [r for r in rows if r["expected"] is None]
        print(
            f"\npositives {sum(r['ok'] for r in positives)}/{len(positives)}"
            f"   honest misses {sum(r['ok'] for r in misses)}/{len(misses)}"
        )
        for r in rows:
            if not r["ok"]:
                print(f"  WRONG  {r['query']}: wanted {r['expected']}, got "
                      f"{r['rendered_top']} — {r['rendered_top_title']}")
        return rows
    finally:
        await kb.aclose()


RESULT_PATH = "docs/probes/s21-td026/battery_definition_result.json"
with open(RESULT_PATH, "w") as fh:
    json.dump(asyncio.run(main()), fh, indent=2)
print(f"\nwrote {RESULT_PATH}")
