"""TD-005 re-battery — the labeled retrieval battery, re-run on the grown corpus.

Trigger fired at S18 end: corpus crossed 30k chunks (27,475 -> 31,819).
This re-runs the EXACT S8 battery (docs/probes/2026-07-18-td005-calibration.md)
against the live index so the numbers are comparable row-for-row, and reports
where each pool's noise ceiling and weakest true positive now sit relative to
the shipped floors in auspex/kb/fuse.py.

Reads only. Run: .venv/bin/python docs/probes/s19-step0/battery_td005.py
"""

import asyncio
import json
import sys

import httpx

sys.path.insert(0, ".")
from auspex.kb.fuse import NEURAL_FLOORS, NEURAL_MIN_SCORE  # noqa: E402
from auspex.kb.mapping import KNOWLEDGE_INDEX, SOURCE_EXCLUDES  # noqa: E402

OS_URL = "http://localhost:9200"
CURATED = ("concept", "technique", "tactic")

# The S8 battery, verbatim. `expected=None` means "off-corpus" — a labeled
# NEGATIVE whose top score is a noise datum, not a hit.
CURATED_BATTERY = [
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

CVE_BATTERY = [
    ("Log4j JNDI lookup remote code execution", "CVE-2021-44228"),
    ("kubernetes ingress controller configuration", "CVE-2026-55723"),
    ("SharePoint deserialization remote code execution", "CVE-2026-58644"),
    ("employee vacation policy template", None),
    ("best hiking trails in the alps", None),
    ("how do I bake sourdough bread", None),
]


async def find_model(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/_plugins/_ml/models/_search",
        json={
            "size": 1,
            "query": {"bool": {"must_not": [{"exists": {"field": "chunk_number"}}]}},
            "_source": ["name", "model_state"],
        },
    )
    resp.raise_for_status()
    hit = resp.json()["hits"]["hits"][0]
    return hit["_id"]


async def neural(
    client: httpx.AsyncClient, model_id: str, query: str, k: int, doc_types=None
) -> list[dict]:
    embedding: dict = {"query_text": query, "model_id": model_id, "k": k}
    if doc_types:
        embedding["filter"] = {"terms": {"doc_type": list(doc_types)}}
    resp = await client.post(
        f"/{KNOWLEDGE_INDEX}/_search",
        json={
            "size": k,
            "_source": {"excludes": SOURCE_EXCLUDES},
            "query": {"neural": {"embedding": embedding}},
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    return [
        {
            "doc_id": h["_source"].get("doc_id", ""),
            "title": h["_source"].get("title", ""),
            "doc_type": h["_source"].get("doc_type", ""),
            "score": float(h.get("_score") or 0.0),
        }
        for h in resp.json()["hits"]["hits"]
    ]


def rank_of(hits: list[dict], expected: str) -> int | None:
    for i, h in enumerate(hits):
        if h["doc_id"] == expected or expected in h["doc_id"]:
            return i
    return None


async def run_pool(client, model_id, name, battery, doc_types, k):
    print(f"\n{'=' * 78}\n{name}  (k={k}, filter={doc_types or 'NONE (unfiltered)'})\n{'=' * 78}")
    rows = []
    for query, expected in battery:
        hits = await neural(client, model_id, query, k, doc_types)
        top = hits[0] if hits else None
        r = rank_of(hits, expected) if expected else None
        rows.append(
            {
                "query": query,
                "expected": expected,
                "top_doc": top["doc_id"] if top else "",
                "top_title": (top["title"] if top else "")[:44],
                "top_type": top["doc_type"] if top else "",
                "top_score": round(top["score"], 4) if top else 0.0,
                "expected_rank": r,
                "expected_score": round(hits[r]["score"], 4) if r is not None else None,
            }
        )
        label = "NEGATIVE" if expected is None else (f"HIT@{r}" if r is not None else "MISS")
        print(
            f"  {query[:52]:52s} -> {rows[-1]['top_doc'][:22]:22s} "
            f"{rows[-1]['top_score']:.4f}  [{label}]"
        )
    return rows


def summarize(name, rows, floor):
    positives = [r for r in rows if r["expected"] is not None]
    negatives = [r for r in rows if r["expected"] is None]
    # The score that MATTERS for a positive is the expected doc's own score —
    # that is what the floor must not cut. Fall back to top when it missed.
    pos_scores = [
        (r["expected_score"] if r["expected_score"] is not None else r["top_score"], r["query"])
        for r in positives
    ]
    weakest = min(pos_scores) if pos_scores else (None, "")
    ceiling = max(((r["top_score"], r["query"]) for r in negatives), default=(None, ""))
    print(f"\n--- {name} ---")
    print(f"  shipped floor          : {floor}")
    print(f"  weakest true positive  : {weakest[0]}  ({weakest[1]})")
    print(f"  noise ceiling (max neg): {ceiling[0]}  ({ceiling[1]})")
    misses = [r["query"] for r in positives if r["expected_rank"] is None]
    if misses:
        print(f"  !! recall misses       : {misses}")
    if ceiling[0] is not None and ceiling[0] >= floor:
        print(f"  !! BREACH: noise {ceiling[0]} >= floor {floor} — noise now clears the floor")
    if weakest[0] is not None and weakest[0] < floor:
        print(f"  !! FALSE-MISS: weakest positive {weakest[0]} < floor {floor}")
    if ceiling[0] is not None and weakest[0] is not None:
        print(f"  gap [{ceiling[0]} .. {weakest[0]}] width {round(weakest[0] - ceiling[0], 4)}")
    return {"weakest_positive": weakest, "noise_ceiling": ceiling, "floor": floor}


async def main():
    async with httpx.AsyncClient(base_url=OS_URL, timeout=60.0) as client:
        model_id = await find_model(client)
        counts = await client.post(
            f"/{KNOWLEDGE_INDEX}/_search",
            json={"size": 0, "aggs": {"t": {"terms": {"field": "doc_type", "size": 20}}}},
        )
        mix = {b["key"]: b["doc_count"] for b in counts.json()["aggregations"]["t"]["buckets"]}
        total = sum(mix.values())
        print(f"model_id={model_id}  corpus={total} chunks  mix={mix}")
        print(f"NEURAL_FLOORS={NEURAL_FLOORS}  NEURAL_MIN_SCORE={NEURAL_MIN_SCORE}")

        curated_rows = await run_pool(
            client, model_id, "CURATED POOL", CURATED_BATTERY, CURATED, 10
        )
        cve_rows = await run_pool(client, model_id, "CVE POOL (unfiltered)", CVE_BATTERY, None, 10)

        out = {
            "corpus": {"total": total, "mix": mix},
            "model_id": model_id,
            "curated": curated_rows,
            "cve_unfiltered_k10": cve_rows,
            "summary": {},
        }
        out["summary"]["curated"] = summarize("CURATED", curated_rows, NEURAL_FLOORS["concept"])
        out["summary"]["cve"] = summarize("CVE (unfiltered)", cve_rows, NEURAL_FLOORS["cve"])

        # k-sensitivity for the unfiltered pool — the S8 note said the k=10
        # result is "a datum, not a license". The pool is 15x bigger now.
        print(f"\n{'=' * 78}\nUNFILTERED k-SENSITIVITY (labeled positives)\n{'=' * 78}")
        ksens = {}
        for k in (10, 50, 100):
            hits_at_k = {}
            for query, expected in CVE_BATTERY:
                if expected is None:
                    continue
                hits = await neural(client, model_id, query, k, None)
                hits_at_k[query] = rank_of(hits, expected)
            ksens[k] = hits_at_k
            print(f"  k={k:3d}: " + ", ".join(f"{q[:28]}={r}" for q, r in hits_at_k.items()))
        out["k_sensitivity"] = ksens

        # CVE pool filtered to doc_type=cve — does filtering change the picture
        # the way it did for the curated pool at S7/S8?
        print(f"\n{'=' * 78}\nCVE POOL, FILTERED to doc_type=cve (k=10)\n{'=' * 78}")
        cve_filtered = await run_pool(
            client, model_id, "CVE POOL (filtered)", CVE_BATTERY, ("cve",), 10
        )
        out["cve_filtered_k10"] = cve_filtered
        out["summary"]["cve_filtered"] = summarize(
            "CVE (filtered)", cve_filtered, NEURAL_FLOORS["cve"]
        )

        return out


RESULT_PATH = "docs/probes/s19-step0/battery_td005_result.json"

with open(RESULT_PATH, "w") as fh:
    json.dump(asyncio.run(main()), fh, indent=2)
print(f"\nwrote {RESULT_PATH}")
