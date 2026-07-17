"""ID-query detection — the neural-bypass gate (S6). Pattern source:
docs/probes/2026-07-17-sara-rrf-retriever-pattern.md §2."""

import pytest

from auspex.kb.idquery import extract_kb_ids, is_id_query


def test_extract_normalizes_and_dedupes_in_order():
    assert extract_kb_ids("cve-2021-44228 and T1059.001, then CVE-2021-44228 again") == (
        "CVE-2021-44228",
        "T1059.001",
    )


def test_extract_all_mitre_shapes():
    text = "T1059 TA0002 M1038 G0016 S0154 DS0017"
    assert extract_kb_ids(text) == ("T1059", "TA0002", "M1038", "G0016", "S0154", "DS0017")


def test_extract_nothing_from_prose():
    assert extract_kb_ids("how do adversaries move laterally?") == ()


@pytest.mark.parametrize(
    "query",
    [
        "CVE-2021-44228",
        "cve-2021-44228?",
        "what is CVE-2024-3400",
        "tell me about T1059.001",
        "T1059 overview",
        "describe mitre technique T1055",
        "CVE-2019-19781 details please",  # 2 leftover words ⇒ still ID-dominant
        "how do I mitigate T1548.002 in my environment",  # all trivial qualifiers
    ],
)
def test_id_dominant_queries(query):
    assert is_id_query(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "how do I detect powershell abuse",  # no ID at all
        "was CVE-2021-44228 exploited against our citrix boxes last night",
        "write a detection rule for T1059.001 targeting encoded commands",
        "compare T1059 and T1047 for stealth",  # "compare"/"stealth" non-trivial
    ],
)
def test_contextual_queries_are_not_id_dominant(query):
    assert is_id_query(query) is False


def test_two_leftover_words_still_id_dominant():
    # SARA rule: ≤ 2 residual words pass even if unusual words
    assert is_id_query("T1566 quarterly report") is True
