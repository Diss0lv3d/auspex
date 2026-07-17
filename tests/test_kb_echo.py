"""KB-backed shortcut copy (S6) — honesty rules + brand rule, like enrich echo."""

from _fakes import FORBIDDEN_ENGINE_NAMES

from auspex.kb.echo import (
    CVE_MISS_LINE,
    DEFINITION_MISS_COPY,
    KB_UNAVAILABLE_COPY,
    render_cve_answer,
    render_definition_answer,
)
from auspex.kb.types import KBHit


def hit(
    chunk_id: str,
    *,
    title: str = "",
    text: str = "chunk body",
    ids: tuple = (),
    source: str = "nvd",
    source_ref: str = "",
    severity: str = "",
    cvss: float | None = None,
    doc_type: str = "cve",
    score: float = 1.0,
) -> KBHit:
    doc_id = chunk_id.split("#")[0]
    return KBHit(
        chunk_id=chunk_id,
        doc_id=doc_id,
        title=title or doc_id,
        text=text,
        doc_type=doc_type,
        source=source,
        source_ref=source_ref,
        ids=ids or (doc_id,),
        severity=severity,
        cvss_score=cvss,
        score=score,
    )


def test_cve_answer_renders_hit_and_explicit_miss():
    hits = [
        hit(
            "CVE-2021-44228#0",
            text="Apache Log4j2 JNDI features allow remote code execution.",
            severity="CRITICAL",
            cvss=10.0,
            source_ref="https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
        )
    ]
    answer = render_cve_answer(["CVE-2021-44228", "CVE-2099-9999"], hits)
    assert "CVE-2021-44228 — CRITICAL (CVSS 10.0)" in answer
    assert "Log4j2" in answer
    assert "Source: NVD · https://nvd.nist.gov/vuln/detail/CVE-2021-44228" in answer
    assert f"- CVE-2099-9999 — {CVE_MISS_LINE}" in answer  # miss is explicit, never silent
    assert "2 vulnerabilities" in answer


def test_cve_answer_multi_chunk_orders_by_chunk_id():
    hits = [
        hit("CVE-2024-3400#1", text="second part"),
        hit("CVE-2024-3400#0", text="first part"),
    ]
    answer = render_cve_answer(["CVE-2024-3400"], hits)
    assert answer.index("first part") < answer.index("second part")
    assert "1 vulnerability" in answer


def test_cve_answer_groups_only_by_exact_id_match():
    # A chunk whose ids don't contain the requested CVE never attaches to it
    stray = hit("T1059#0", ids=("T1059",), doc_type="technique")
    answer = render_cve_answer(["CVE-2021-44228"], [stray])
    assert CVE_MISS_LINE in answer
    assert "T1059" not in answer


def test_definition_answer_cites_source_and_related():
    hits = [
        hit(
            "CONCEPT-C2#0",
            title="Command and control (C2)",
            text="C2 is the channel an adversary maintains…",
            ids=(),
            source="auspex-seed",
            doc_type="concept",
            score=0.016,
        ),
        hit("T1059#0", title="Command and Scripting Interpreter", doc_type="technique"),
    ]
    answer = render_definition_answer(hits)
    assert answer is not None
    assert answer.startswith("Command and control (C2) — from the knowledge base:")
    assert "C2 is the channel" in answer
    assert "Related entries: Command and Scripting Interpreter (T1059)" in answer
    assert "Source: Auspex seed corpus" in answer


def test_definition_answer_none_when_kb_has_nothing():
    assert render_definition_answer([]) is None


def test_definition_related_skips_same_doc_chunks():
    hits = [
        hit("CONCEPT-C2#0", title="C2", ids=(), doc_type="concept"),
        hit("CONCEPT-C2#1", title="C2", ids=(), doc_type="concept"),
    ]
    answer = render_definition_answer(hits)
    assert "Related entries" not in answer


def test_kb_copy_never_names_the_engine_or_fabricates():
    for copy in (KB_UNAVAILABLE_COPY, DEFINITION_MISS_COPY, CVE_MISS_LINE):
        lowered = copy.lower()
        for name in FORBIDDEN_ENGINE_NAMES:
            assert name not in lowered
    # the three truths stay distinct strings
    assert len({KB_UNAVAILABLE_COPY, DEFINITION_MISS_COPY, CVE_MISS_LINE}) == 3
