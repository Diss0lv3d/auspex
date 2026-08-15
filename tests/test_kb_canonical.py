"""Which page answers a "what is X" question — TD-026's ranking signal (S21).

The numbers in this file are not invented: every case is a query from the
labeled battery (docs/probes/s21-td026/) with the titles the live corpus
actually returned for it. The battery runs against a real index and cannot run
in CI; these pin its *decisions* so a change that would move the battery fails
here first, on a laptop, in milliseconds.
"""

import pytest

from auspex.kb.canonical import (
    MIN_TITLE_SCORE,
    promote_canonical,
    query_coverage,
    title_coverage,
    title_score,
)
from auspex.kb.types import KBHit


def hit(doc_id: str, title: str, score: float) -> KBHit:
    return KBHit(
        chunk_id=f"{doc_id}#0",
        doc_id=doc_id,
        title=title,
        text="body",
        doc_type="technique",
        source="mitre",
        source_ref="",
        ids=(doc_id,),
        severity="",
        cvss_score=None,
        score=score,
    )


def test_the_id_prefix_is_our_formatting_not_the_pages_name():
    """Titles render as "T1566: Phishing". Counting "t1566" as a title word no
    analyst asked for would penalise every ATT&CK page equally and for nothing."""
    assert title_coverage("T1566: Phishing", "what is phishing") == 1.0
    assert title_coverage("TA0008: Lateral Movement", "what is lateral movement") == 1.0
    assert title_coverage("CVE-2021-44228: Log4Shell", "what is log4shell") == 1.0
    # A colon that is not an id prefix is left alone.
    assert title_coverage("Phishing: a primer", "what is phishing") == pytest.approx(1 / 3)


def test_plurals_are_the_same_word_without_a_stemmer():
    assert title_coverage("Command and Scripting Interpreter", "command line interpreters") > 0
    # Short words must match exactly — a 4-char prefix rule on "the" would
    # match "them", "then", "there".
    assert title_coverage("The Hive", "them") == 0.0


@pytest.mark.parametrize(
    "query,right,wrong",
    [
        # The bug that named TD-026: a sibling page whose title says more than
        # the question asked.
        ("what is phishing", "T1566: Phishing", "T1598: Phishing for Information"),
        # The parent tactic out-scoring the technique that was actually asked for.
        (
            "what is credential dumping",
            "T1003: OS Credential Dumping",
            "TA0006: Credential Access",
        ),
        # ...and the same pair the other way round, which is the real test: the
        # signal must not simply always prefer the technique.
        (
            "what is credential access",
            "TA0006: Credential Access",
            "T1003: OS Credential Dumping",
        ),
        (
            "how do adversaries abuse command line interpreters",
            "T1059: Command and Scripting Interpreter",
            "T1202: Indirect Command Execution",
        ),
        (
            "living off the land binaries",
            "Living off the land (LOLBins)",
            "T1554: Compromise Host Software Binary",
        ),
    ],
)
def test_the_page_the_question_is_about_scores_higher(query, right, wrong):
    assert title_score(right, query) > title_score(wrong, query)


def test_a_short_title_alone_does_not_win():
    """The trap that made the one-sided measure wrong. Asked about credential
    dumping, ATT&CK offers a page titled simply "Credentials" — every word of it
    asked for, and a reconnaissance page about harvesting identity information.
    Title coverage alone ranks it first; accounting for the question does not."""
    query = "what is credential dumping"
    assert title_coverage("T1589.001: Credentials", query) == 1.0
    assert title_coverage("T1003: OS Credential Dumping", query) < 1.0
    assert query_coverage("T1589.001: Credentials", query) < query_coverage(
        "T1003: OS Credential Dumping", query
    )
    assert title_score("T1003: OS Credential Dumping", query) > title_score(
        "T1589.001: Credentials", query
    )


def test_promotion_reorders_but_never_adds():
    """The property the honest-miss guarantee rests on: this is a re-ranking of
    a post-floor list, so it cannot resurrect a page the floor excluded and
    cannot invent one."""
    hits = [
        hit("T1598", "T1598: Phishing for Information", 0.016),
        hit("T1566", "T1566: Phishing", 0.009),
    ]
    promoted = promote_canonical("what is phishing", hits)
    assert promoted[0].doc_id == "T1566"
    assert {h.doc_id for h in promoted} == {h.doc_id for h in hits}
    assert len(promoted) == len(hits)


def test_an_empty_or_single_candidate_list_is_returned_unchanged():
    assert promote_canonical("what is phishing", []) == []
    one = [hit("T1566", "T1566: Phishing", 0.01)]
    assert promote_canonical("what is phishing", one) == one


def test_a_coincidental_word_does_not_reorder_anything():
    """Below MIN_TITLE_SCORE the retriever keeps its answer. "Windows" appearing
    in one title is not a reason to overrule two legs of retrieval."""
    hits = [
        hit("T1055", "T1055: Process Injection", 0.016),
        hit("T1218", "T1218: Windows Command Shell Bypass Techniques Overview", 0.009),
    ]
    assert title_score(hits[1].title, "what is windows") < MIN_TITLE_SCORE
    assert promote_canonical("what is windows", hits)[0].doc_id == "T1055"


def test_ties_leave_retrieval_in_charge():
    """Two pages whose titles are equally on-topic — the concept doc and the
    ATT&CK tactic page for "lateral movement" — must be separated by the fused
    score, not by list order or title length."""
    query = "what is lateral movement"
    hits = [
        hit("TA0008", "TA0008: Lateral Movement", 0.016),
        hit("CONCEPT-LATERAL-MOVEMENT", "Lateral movement", 0.009),
    ]
    assert title_score(hits[0].title, query) == title_score(hits[1].title, query)
    assert promote_canonical(query, hits)[0].doc_id == "TA0008"
