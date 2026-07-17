"""Seed corpus + NVD parser (S6). Fixture values are verbatim from live NVD
responses (docs/probes/2026-07-17-nvd-api.md); nvd_to_doc is the same function
the S7 live feed will use."""

from auspex.kb.seed import load_seed_docs, nvd_to_doc


def test_load_seed_docs_shape():
    docs = load_seed_docs()
    by_type: dict[str, int] = {}
    for d in docs:
        by_type[d.doc_type] = by_type.get(d.doc_type, 0) + 1
    assert by_type == {"cve": 5, "technique": 6, "concept": 3}
    assert len({d.doc_id for d in docs}) == len(docs)  # unique doc ids


def test_log4shell_parses_with_cvss_and_ids():
    docs = {d.doc_id: d for d in load_seed_docs()}
    log4shell = docs["CVE-2021-44228"]
    assert log4shell.severity == "CRITICAL"
    assert log4shell.cvss_score == 10.0
    assert log4shell.ids == ("CVE-2021-44228",)
    assert "Log4j2" in log4shell.content
    assert log4shell.source == "nvd"
    assert log4shell.source_ref.endswith("CVE-2021-44228")


def test_terse_msrc_description_still_parses():
    # Probe reality: CVE-2023-23397's en description is 54 chars — no paragraph
    docs = {d.doc_id: d for d in load_seed_docs()}
    outlook = docs["CVE-2023-23397"]
    assert outlook.content  # present, however short
    assert len(outlook.content) < 100
    assert outlook.severity == "CRITICAL"


def test_nvd_to_doc_survives_missing_metrics_and_descriptions():
    bare = nvd_to_doc({"id": "cve-2099-1", "descriptions": [], "metrics": {}})
    assert bare.doc_id == "CVE-2099-1"  # normalized upper
    assert bare.content == ""
    assert bare.severity == "" and bare.cvss_score is None


def test_nvd_to_doc_v2_fallback_reads_severity_beside_cvss_data():
    # Probed: V2 keeps baseSeverity on the metric entry, not inside cvssData
    doc = nvd_to_doc(
        {
            "id": "CVE-2010-0001",
            "descriptions": [{"lang": "en", "value": "old bug"}],
            "metrics": {
                "cvssMetricV2": [{"cvssData": {"baseScore": 5.0}, "baseSeverity": "MEDIUM"}]
            },
        }
    )
    assert doc.cvss_score == 5.0
    assert doc.severity == "MEDIUM"


def test_techniques_carry_ids_and_concepts_do_not():
    docs = load_seed_docs()
    techniques = [d for d in docs if d.doc_type == "technique"]
    concepts = [d for d in docs if d.doc_type == "concept"]
    assert all(d.ids == (d.doc_id,) for d in techniques)
    assert all(d.ids == () for d in concepts)  # no fake exact-match rail
    # Sub-technique presence — the prefix-rail test data depends on these
    ids = {d.doc_id for d in techniques}
    assert {"T1059", "T1059.001", "T1566", "T1566.001"} <= ids


def test_seed_provenance_is_honestly_labeled():
    docs = load_seed_docs()
    for d in docs:
        if d.doc_type == "technique":
            assert d.source == "attack-seed-summary"  # never claims verbatim MITRE
        elif d.doc_type == "concept":
            assert d.source == "auspex-seed"
