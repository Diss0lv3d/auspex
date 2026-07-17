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


def test_cve_answer_omitted_count_is_stated_never_a_false_miss():
    # S6 review: when the caller caps the per-turn id list, the capped CVEs
    # must be named as deferred-to-follow-up — not silently dropped and not
    # rendered with the miss line (which would claim KB absence).
    answer = render_cve_answer(["CVE-2021-44228"], [], omitted=2)
    assert "2 more were requested — I read up to 1 per turn" in answer
    single = render_cve_answer(["CVE-2021-44228"], [], omitted=1)
    assert "1 more was requested" in single
    unomitted = render_cve_answer(["CVE-2021-44228"], [])
    assert "more w" not in unomitted  # no trailer when nothing was capped


def test_cve_chunks_render_in_numeric_order_past_ten():
    # S6 review: lexicographic chunk_id sort put "#10" before "#2"; long docs
    # (S7 feeds) cross ten chunks. Order must be numeric.
    hits = [hit(f"CVE-2024-0001#{i}", text=f"part-{i}.") for i in (10, 2, 0, 11, 1)]
    answer = render_cve_answer(["CVE-2024-0001"], hits)
    positions = [answer.index(f"part-{i}.") for i in (0, 1, 2, 10, 11)]
    assert positions == sorted(positions), "chunks must render in document order"


def test_related_entries_never_leak_internal_concept_ids():
    # S6 review: "Command and Control (CONCEPT-C2)" leaked our internal id
    # scheme; recognizable ids (T1059, CVE-…) still render in parentheses.
    top = hit("CONCEPT-LM#0", title="Lateral movement", doc_type="concept", source="auspex-seed")
    related_concept = hit(
        "CONCEPT-C2#0", title="Command and Control", doc_type="concept", source="auspex-seed"
    )
    related_technique = hit(
        "T1021#0", title="Remote Services", doc_type="technique", source="attack-seed-summary"
    )
    answer = render_definition_answer([top, related_concept, related_technique])
    assert "CONCEPT-" not in answer
    assert "Command and Control" in answer
    assert "Remote Services (T1021)" in answer


def _enriched_log4shell(**overrides):
    base = dict(
        chunk_id="CVE-2021-44228#0",
        text="Apache Log4j2 JNDI features allow remote code execution.",
        severity="CRITICAL",
        cvss=10.0,
        source_ref="https://nvd.nist.gov/vuln/detail/CVE-2021-44228",
    )
    h = hit(base.pop("chunk_id"), **base)
    from dataclasses import replace

    return replace(h, **overrides)


def test_cve_answer_renders_kev_and_epss_evidence():
    # S7: KEV/EPSS presence upgrades the echo — code renders, zero LLM.
    enriched = _enriched_log4shell(
        kev_date_added="2021-12-10",
        kev_ransomware=True,
        epss_score=0.99999,
        epss_percentile=1.0,
        epss_date="2026-07-16",
    )
    answer = render_cve_answer(["CVE-2021-44228"], [enriched])
    assert "Known exploited — in CISA KEV since 2021-12-10; used in ransomware campaigns." in answer
    # 0.99999 is NOT 1.00 — rounding must not manufacture certainty (S8);
    # percentile exactly 1.0 IS 100.0th and renders as held.
    assert "EPSS >0.99 — 100.0th percentile (as of 2026-07-16)." in answer
    # ordering: evidence lines sit between description and the Source trailer
    assert answer.index("remote code execution") < answer.index("Known exploited")
    assert answer.index("EPSS") < answer.index("Source: NVD")


def test_epss_rendering_never_crosses_boundaries_it_does_not_hold():
    # S8 review: the majority of real EPSS scores are <0.005 and rendered
    # "EPSS 0.00" — a zero the system does not hold; ≥0.9995 percentiles
    # rendered "100.0th" — a maximal rank the data contradicts.
    tiny = _enriched_log4shell(epss_score=0.0004, epss_percentile=0.153, epss_date="2026-07-17")
    answer = render_cve_answer(["CVE-2021-44228"], [tiny])
    assert "EPSS <0.01 — 15.3th percentile (as of 2026-07-17)." in answer
    near_top = _enriched_log4shell(epss_score=0.996, epss_percentile=0.9996)
    answer2 = render_cve_answer(["CVE-2021-44228"], [near_top])
    assert "EPSS >0.99 — >99.9th percentile." in answer2
    near_zero_pct = _enriched_log4shell(epss_score=0.5, epss_percentile=0.0004)
    answer3 = render_cve_answer(["CVE-2021-44228"], [near_zero_pct])
    assert "EPSS 0.50 — <0.1th percentile." in answer3
    exact = _enriched_log4shell(epss_score=1.0, epss_percentile=1.0)
    answer4 = render_cve_answer(["CVE-2021-44228"], [exact])
    assert "EPSS 1.00 — 100.0th percentile." in answer4  # actually held ⇒ renders


def test_kev_presence_renders_even_without_a_date():
    # S8 review: presence was keyed on dateAdded, so a KEV entry with held
    # ransomware evidence but no date rendered as TOTAL silence.
    dateless = _enriched_log4shell(kev_listed=True, kev_ransomware=True)
    answer = render_cve_answer(["CVE-2021-44228"], [dateless])
    assert "Known exploited — in CISA KEV; used in ransomware campaigns." in answer
    assert "since" not in answer  # no date claim without a held date
    # docs enriched before kev_listed existed keep rendering via the date
    legacy = _enriched_log4shell(kev_listed=False, kev_date_added="2021-12-10")
    answer2 = render_cve_answer(["CVE-2021-44228"], [legacy])
    assert "Known exploited — in CISA KEV since 2021-12-10." in answer2


def test_cve_answer_absent_enrichment_makes_no_exploitation_claims():
    # Honesty: no KEV row ⇒ no exploitation claim either way; no EPSS row ⇒ no
    # likelihood number; KEV ransomware "Unknown" ⇒ silence, never "no".
    plain = _enriched_log4shell()
    answer = render_cve_answer(["CVE-2021-44228"], [plain])
    assert "KEV" not in answer and "exploited" not in answer
    assert "EPSS" not in answer and "ransomware" not in answer
    kev_only_unknown_ransomware = _enriched_log4shell(kev_date_added="2021-12-10")
    answer2 = render_cve_answer(["CVE-2021-44228"], [kev_only_unknown_ransomware])
    assert "Known exploited — in CISA KEV since 2021-12-10." in answer2
    assert "ransomware" not in answer2  # Unknown renders as absence of evidence
    assert "EPSS" not in answer2
