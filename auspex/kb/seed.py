"""Seed corpus loaders — S6. Proves the pipeline; real feeds land S7/S8.

`nvd_to_doc` parses the NVD CVE API 2.0 shape (probe:
docs/probes/2026-07-17-nvd-api.md) and is written to be reused verbatim by the
S7 live feed. Fixture values are verbatim from live NVD responses. The ATT&CK
entries are hand-curated seed summaries (honestly labeled — not verbatim MITRE
text); STIX ingestion replaces them in S7/S8.
"""

import json
from importlib import resources

from auspex.kb.types import KBDoc

# Terse MSRC-style records exist (probe: CVE-2023-23397's description is 54
# chars) — parsing must not assume a paragraph.
_CVSS_KEYS = ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2")


MAX_DESCRIPTION_CHARS = 20_000  # untrusted feed text: bound the chunk fan-out
# (chunking caps chunk SIZE, never count — a poisoned multi-MB description
# would embed and index thousands of chunks; real NVD descriptions are <4k).


def nvd_to_doc(cve: dict) -> KBDoc:
    """One NVD `vulnerabilities[i].cve` object → KBDoc."""
    cve_id = cve["id"].upper()
    description = next(
        (d["value"] for d in cve.get("descriptions", ()) if d.get("lang") == "en"), ""
    )
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS] + " […]"
    severity = ""
    score: float | None = None
    metrics = cve.get("metrics", {})
    for key in _CVSS_KEYS:
        if metrics.get(key):
            entry = metrics[key][0]
            cvss = entry.get("cvssData", {})
            score = cvss.get("baseScore")
            # V2 keeps baseSeverity beside cvssData, V3x inside it (probed)
            severity = (cvss.get("baseSeverity") or entry.get("baseSeverity") or "").upper()
            break
    return KBDoc(
        doc_id=cve_id,
        title=cve_id,
        content=description,
        doc_type="cve",
        source="nvd",
        source_ref=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
        ids=(cve_id,),
        severity=severity,
        cvss_score=score,
    )


def _technique_to_doc(entry: dict, *, doc_type: str, source: str) -> KBDoc:
    doc_id = entry["id"].upper()
    return KBDoc(
        doc_id=doc_id,
        title=entry["name"],
        content=entry["summary"],
        doc_type=doc_type,
        source=source,
        source_ref=entry.get("url", ""),
        ids=(doc_id,) if not doc_id.startswith("CONCEPT-") else (),
    )


def load_seed_docs() -> list[KBDoc]:
    data_dir = resources.files("auspex.kb") / "seed_data"
    nvd = json.loads((data_dir / "nvd_cves.json").read_text(encoding="utf-8"))
    attack = json.loads((data_dir / "attack_techniques.json").read_text(encoding="utf-8"))
    docs = [nvd_to_doc(v["cve"]) for v in nvd["vulnerabilities"]]
    docs += [
        _technique_to_doc(t, doc_type="technique", source="attack-seed-summary")
        for t in attack["techniques"]
    ]
    docs += [
        _technique_to_doc(c, doc_type="concept", source="auspex-seed") for c in attack["concepts"]
    ]
    return docs
