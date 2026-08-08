"""S12 ACH engine — hermetic fixture tests (D-019: the matrix is code, zero
LLM). Covers the closed vocabularies, the three evidence adapters, the
Heuer-faithful matrix (least-inconsistency ranking, rejection rails, honesty
rails), and the information-gain lookup picker (likelihood rows pinned,
hand-computed gain fixtures, candidate hygiene, deterministic ties)."""

from pathlib import Path

import pytest

from auspex.ach import (
    Evidence,
    EvidenceKind,
    HypothesisKey,
    SubjectKind,
    candidate_lookups,
    cells_for,
    enrichment_coverage,
    evidence_from_alert,
    evidence_from_email,
    evidence_from_enrichment,
    rank_lookups,
    score_matrix,
    seed_hypotheses,
)
from auspex.ach.gain import _LIKELIHOODS, LookupKind
from auspex.ach.matrix import PLAUSIBILITY_HALF_LIFE, REJECT_AT
from auspex.alerts import normalize
from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.types import ObservableEnrichment, ProviderSignal, VerdictLabel
from auspex.phishing import decide_verdict, parse_email
from auspex.phishing.victims import filter_victim_iocs

FIXTURES = Path(__file__).parent / "fixtures" / "emails"

ALL_KEYS = (
    HypothesisKey.TRUE_POSITIVE,
    HypothesisKey.FALSE_POSITIVE,
    HypothesisKey.BENIGN_ACTIVITY,
    HypothesisKey.TEST_ACTIVITY,
)

RICH_CEF = (
    "CEF:0|Trellix|ENS|10.7|1201|Malware detected|9|src=10.1.2.3 "
    "cs1=powershell -enc SQBFAFgA externalId=T1059.001 confidence=90"
)


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def _ev(kind: EvidenceKind, credibility: float = 1.0, **cells) -> Evidence:
    """Synthetic evidence with explicit cells (bypasses the curated tables)."""
    return Evidence(
        kind=kind,
        statement="synthetic",
        credibility=credibility,
        cells={k: cells.get(k.value) for k in ALL_KEYS},
        source="test",
    )


def _obs(t: ObservableType, value: str) -> Observable:
    from auspex.classify.observables import observable_id

    return Observable(type=t, value=value, obs_id=observable_id(t, value), defanged=False)


# -- closed vocabularies -------------------------------------------------------


def test_catalog_seeds_all_four_hypotheses_per_subject_kind():
    for kind in SubjectKind:
        seeded = seed_hypotheses(kind)
        assert tuple(h.key for h in seeded) == ALL_KEYS
        assert all(h.label for h in seeded)


def test_cell_tables_cover_every_evidence_kind_and_hypothesis():
    for kind in EvidenceKind:
        vec = cells_for(kind)
        assert set(vec.keys()) == set(ALL_KEYS), kind
        for cell in vec.values():
            assert cell is None or -2 <= cell <= 2, kind


def test_likelihood_rows_sum_to_one_for_every_hypothesis():
    for kind, groups in _LIKELIHOODS.items():
        for group, rows in groups.items():
            assert set(rows.keys()) == set(ALL_KEYS), (kind, group)
            for h, row in rows.items():
                assert len(row) == 4, (kind, group, h)
                assert sum(row) == pytest.approx(1.0, abs=1e-9), (kind, group, h)


# -- evidence adapters ---------------------------------------------------------


def test_alert_evidence_from_rich_envelope():
    env = normalize(RICH_CEF)
    evidence = evidence_from_alert(env)
    kinds = {e.kind for e in evidence}
    assert EvidenceKind.ALERT_ENCODED_COMMAND in kinds
    assert EvidenceKind.ALERT_HIGH_SEVERITY in kinds
    assert EvidenceKind.ALERT_MITRE_MAPPED in kinds
    by_kind = {e.kind: e for e in evidence}
    # a vendor claim is weaker than a content-anchored detection
    assert (
        by_kind[EvidenceKind.ALERT_HIGH_SEVERITY].credibility
        < by_kind[EvidenceKind.ALERT_ENCODED_COMMAND].credibility
    )


def test_unparsed_alert_yields_no_evidence():
    env = normalize("complete gibberish, nothing structured here")
    if env.parsed:  # normalizer may classify as unknown-but-parsed; force the rail
        from dataclasses import replace

        env = replace(env, parsed=False)
    assert evidence_from_alert(env) == ()


def test_email_evidence_reuses_the_s11_findings():
    env = parse_email(_load("failing_typosquat.eml"))
    verdict = decide_verdict(env)
    evidence = evidence_from_email(env, verdict)
    kinds = [e.kind for e in evidence]
    # ONE collapsed auth row — SPF/DKIM/DMARC are one gateway assertion, not
    # three independent contradictions (S12 verification finding 7)
    assert kinds.count(EvidenceKind.EMAIL_AUTH_FAIL) == 1
    assert EvidenceKind.EMAIL_LOOKALIKE_DOMAIN in kinds
    # no positive-auth evidence on a failing email
    assert EvidenceKind.EMAIL_AUTH_PASS not in kinds
    # non-auth statements are the S11 finding details verbatim; the auth
    # statement carries every collapsed detail
    detail_set = {f.detail for f in verdict.findings}
    auth_row = next(e for e in evidence if e.kind is EvidenceKind.EMAIL_AUTH_FAIL)
    assert auth_row.credibility == 0.9
    assert all(
        e.statement in detail_set
        for e in evidence
        if e.kind is not EvidenceKind.EMAIL_AUTH_FAIL
    )
    for f in verdict.findings:
        if f.type.value.startswith(("spf_", "dkim_", "dmarc_")):
            assert f.detail in auth_row.statement


def test_forwarded_legit_email_does_not_reject_benign():
    """S12 verification finding 7: the canonical forwarding signature
    (spf=softfail; dkim=fail; dmarc=fail) previously produced 3 hard
    contradictions from one header line and PERMANENTLY rejected the exact
    hypothesis whose label covers ESP mediation/forwarding. Collapsed, it is
    one contradiction — BENIGN stays alive for enrichment to adjudicate."""
    raw = (
        "From: newsletter@vendor-updates.test\nTo: user@acme.com\n"
        "Subject: your weekly digest\n"
        "Authentication-Results: mx.acme.com; spf=softfail; dkim=fail; dmarc=fail\n"
        "Received: from forwarder by mx.acme.com\n\nthe digest"
    )
    env = parse_email(raw)
    verdict = decide_verdict(env)
    evidence = evidence_from_email(env, verdict)
    assert [e.kind for e in evidence].count(EvidenceKind.EMAIL_AUTH_FAIL) == 1
    a = score_matrix(seed_hypotheses(SubjectKind.EMAIL), evidence)
    benign = next(
        s for s in a.scores if s.hypothesis.key is HypothesisKey.BENIGN_ACTIVITY
    )
    assert benign.status == "surviving"


def test_softfail_alone_stays_below_the_hard_contradiction_bar():
    raw = (
        "From: b@vendor.test\nTo: u@acme.com\nSubject: hi\n"
        "Authentication-Results: mx; spf=softfail; dkim=none; dmarc=none\n"
        "Received: a\n\nbody"
    )
    env = parse_email(raw)
    evidence = evidence_from_email(env, decide_verdict(env))
    auth = next(e for e in evidence if e.kind is EvidenceKind.EMAIL_AUTH_FAIL)
    assert auth.credibility == 0.5  # a forwarding artifact until corroborated
    a = score_matrix(seed_hypotheses(SubjectKind.EMAIL), evidence)
    assert all(s.hard_contradictions == 0 for s in a.scores)


def test_auth_passing_email_yields_positive_evidence_only():
    env = parse_email(_load("passing.eml"))
    verdict = decide_verdict(env)
    evidence = evidence_from_email(env, verdict)
    assert [e.kind for e in evidence] == [EvidenceKind.EMAIL_AUTH_PASS]
    assert evidence[0].credibility == 0.9


def test_enrichment_skip_and_unanswered_yield_nothing():
    obs = _obs(ObservableType.DOMAIN, "evil.test")
    skipped = ObservableEnrichment(
        observable=obs, signals=(), skip_reason="private/reserved", sources_answered=0
    )
    assert evidence_from_enrichment(skipped) == ()
    # nothing completed a lookup: NOT coverage — stays a candidate, no row
    unanswered = ObservableEnrichment(
        observable=obs, signals=(), skip_reason=None, sources_answered=0
    )
    assert evidence_from_enrichment(unanswered) == ()


def test_enrichment_completed_but_unknown_yields_weak_no_signal_coverage():
    # A COMPLETED lookup with no claim retires the candidate and applies the
    # small update the gain math priced into the "unknown" outcome — it must
    # never read as benign.
    obs = _obs(ObservableType.DOMAIN, "fresh-sim-infra.test")
    unknown_only = ObservableEnrichment(
        observable=obs,
        signals=(
            ProviderSignal(
                provider="OTX",
                label=VerdictLabel.UNKNOWN,
                confidence=0.2,
                summary="no pulses",
                evidence={},
            ),
        ),
        skip_reason=None,
        sources_answered=1,
    )
    (e,) = evidence_from_enrichment(unknown_only)
    assert e.kind is EvidenceKind.ENRICHMENT_NO_SIGNAL
    assert e.credibility == 0.3  # weak by construction
    assert e.obs_id == obs.obs_id
    assert "not benign" in e.statement
    # direction mirrors the likelihood rows: unknown weakly favors FP/TEST
    assert e.cells[HypothesisKey.TRUE_POSITIVE] < 0
    assert e.cells[HypothesisKey.FALSE_POSITIVE] > 0
    assert e.cells[HypothesisKey.TEST_ACTIVITY] > 0


def test_enrichment_signal_becomes_directional_evidence_with_obs_id():
    obs = _obs(ObservableType.DOMAIN, "paypa1.com")
    item = ObservableEnrichment(
        observable=obs,
        signals=(
            ProviderSignal(
                provider="ThreatFox",
                label=VerdictLabel.MALICIOUS,
                confidence=0.85,
                summary="listed as phishing C2",
                evidence={},
            ),
        ),
        skip_reason=None,
        sources_answered=1,
    )
    (e,) = evidence_from_enrichment(item)
    assert e.kind is EvidenceKind.ENRICHMENT_MALICIOUS
    assert e.credibility == 0.85
    assert e.obs_id == obs.obs_id
    assert e.source == "enrichment:ThreatFox"


# -- matrix: rails and ranking -------------------------------------------------


def test_no_evidence_means_uniform_weights_and_no_ranking():
    hyps = seed_hypotheses(SubjectKind.ALERT)
    a = score_matrix(hyps, ())
    assert a.ranking_claimed is False
    assert "no evidence" in (a.reason or "")
    assert all(s.status == "surviving" for s in a.scores)
    for w in a.weights.values():
        assert w == pytest.approx(0.25, abs=1e-6)


def test_nondiagnostic_evidence_claims_no_ranking():
    hyps = seed_hypotheses(SubjectKind.ALERT)
    flat = _ev(
        EvidenceKind.ALERT_LOLBIN,
        true_positive=1,
        false_positive=1,
        benign_activity=1,
        test_activity=1,
    )
    a = score_matrix(hyps, (flat,))
    assert a.ranking_claimed is False
    assert "does not discriminate" in (a.reason or "")
    assert a.readings[0].diagnostic is False


def test_least_inconsistency_ranks_first_support_is_tiebreak_only():
    hyps = seed_hypotheses(SubjectKind.EMAIL)
    # FP racks up support but also a big inconsistency; TP stays clean.
    e1 = _ev(
        EvidenceKind.EMAIL_SPOOF_INDICATOR,
        true_positive=2,
        false_positive=-2,
        benign_activity=-1,
        test_activity=1,
    )
    e2 = _ev(
        EvidenceKind.EMAIL_HEADER_ANOMALY,
        credibility=0.5,
        true_positive=0,
        false_positive=2,
        benign_activity=0,
        test_activity=0,
    )
    a = score_matrix(hyps, (e1, e2))
    assert a.ranking_claimed is True
    assert a.scores[0].hypothesis.key is HypothesisKey.TRUE_POSITIVE
    fp = next(s for s in a.scores if s.hypothesis.key is HypothesisKey.FALSE_POSITIVE)
    assert fp.support > 0  # the support did not rescue the ranking
    assert fp.inconsistency == pytest.approx(2.0)


def test_rejection_requires_both_threshold_and_hard_contradiction():
    hyps = seed_hypotheses(SubjectKind.ALERT)
    # 4 × (−1 at cred 0.8) = 3.2 ≥ REJECT_AT but NO hard (−2 high-cred) cell.
    soft = tuple(
        _ev(
            EvidenceKind.ALERT_SUSPICIOUS_PROCESS,
            credibility=0.8,
            true_positive=1,
            false_positive=-1,
            benign_activity=0,
            test_activity=0,
        )
        for _ in range(4)
    )
    a = score_matrix(hyps, soft)
    fp = next(s for s in a.scores if s.hypothesis.key is HypothesisKey.FALSE_POSITIVE)
    assert fp.inconsistency >= REJECT_AT
    assert fp.status == "surviving"  # no hard contradiction → never rejected

    hard = (
        *soft,
        _ev(
            EvidenceKind.ENRICHMENT_MALICIOUS,
            credibility=0.9,
            true_positive=2,
            false_positive=-2,
            benign_activity=-2,
            test_activity=-1,
        ),
    )
    a2 = score_matrix(hyps, hard)
    fp2 = next(s for s in a2.scores if s.hypothesis.key is HypothesisKey.FALSE_POSITIVE)
    assert fp2.status == "rejected"
    assert "hard contradiction" in (fp2.rejected_reason or "")
    assert fp2.weight == 0.0
    assert fp2.hypothesis.key not in a2.weights


def test_all_rejected_keeps_all_surviving_with_note():
    hyps = seed_hypotheses(SubjectKind.ALERT)
    against_all = tuple(
        _ev(
            EvidenceKind.ENRICHMENT_MALICIOUS,
            credibility=1.0,
            true_positive=-2,
            false_positive=-2,
            benign_activity=-2,
            test_activity=-2,
        )
        for _ in range(2)
    )
    a = score_matrix(hyps, against_all)
    assert all(s.status == "surviving" for s in a.scores)
    assert any("hypothesis space itself is suspect" in n for n in a.notes)


def test_weights_halve_per_half_life_of_inconsistency():
    hyps = seed_hypotheses(SubjectKind.ALERT)
    # TP gains exactly PLAUSIBILITY_HALF_LIFE of inconsistency; FP none.
    e = _ev(
        EvidenceKind.ENRICHMENT_BENIGN,
        credibility=1.0,
        true_positive=-2,
        false_positive=0,
        benign_activity=0,
        test_activity=0,
    )
    assert PLAUSIBILITY_HALF_LIFE == 2.0  # the fixture below assumes it
    a = score_matrix(hyps, (e,))
    w = a.weights
    assert w[HypothesisKey.TRUE_POSITIVE] == pytest.approx(
        w[HypothesisKey.FALSE_POSITIVE] / 2, abs=1e-6
    )


def test_none_cells_are_excluded_from_scoring_but_lone_cells_diagnose():
    hyps = seed_hypotheses(SubjectKind.ALERT)
    e = _ev(
        EvidenceKind.ALERT_LOLBIN,
        true_positive=2,
        false_positive=None,
        benign_activity=None,
        test_activity=None,
    )
    a = score_matrix(hyps, (e,))
    fp = next(s for s in a.scores if s.hypothesis.key is HypothesisKey.FALSE_POSITIVE)
    assert fp.inconsistency == 0.0 and fp.support == 0.0
    # a lone non-None nonzero cell DOES discriminate (it moves one hypothesis
    # relative to the rest) — S12 verification: the earlier <2-cells gate
    # claimed "fits every surviving hypothesis equally" while weights skewed.
    assert a.readings[0].diagnostic is True
    assert a.ranking_claimed is True
    # and an all-None row is honestly non-diagnostic
    blank = _ev(EvidenceKind.ALERT_LOLBIN)
    b = score_matrix(hyps, (blank,))
    assert b.readings[0].diagnostic is False
    assert b.ranking_claimed is False


def test_heuer_least_inconsistency_beats_most_support():
    """The flagship property, pinned so a most-support-first mutation FAILS:
    FP carries the most support overall but also real inconsistency; TP is
    clean with less support. Heuer ranks TP first."""
    hyps = seed_hypotheses(SubjectKind.ALERT)
    support_heavy = _ev(
        EvidenceKind.ALERT_HIGH_SEVERITY,
        false_positive=2,
        true_positive=0,
        benign_activity=0,
        test_activity=0,
    )
    mixed = _ev(
        EvidenceKind.ALERT_SUSPICIOUS_PROCESS,
        false_positive=-1,
        true_positive=1,
        benign_activity=0,
        test_activity=0,
    )
    a = score_matrix(hyps, (support_heavy, mixed))
    fp = next(s for s in a.scores if s.hypothesis.key is HypothesisKey.FALSE_POSITIVE)
    tp = next(s for s in a.scores if s.hypothesis.key is HypothesisKey.TRUE_POSITIVE)
    assert fp.support > tp.support  # FP would win a most-support ranking
    assert a.scores[0].hypothesis.key is HypothesisKey.TRUE_POSITIVE


def test_ranking_is_invariant_to_hypothesis_input_order():
    """S12 verification: the store loads hypotheses alphabetically, and the
    old input-tuple tiebreak then ranked TEST above TP on exact ties. The
    final tiebreak is the enum declaration order, whatever order arrives."""
    seeded = seed_hypotheses(SubjectKind.ALERT)
    shuffled = tuple(sorted(seeded, key=lambda h: h.key.value))  # alphabetical
    e = _ev(
        EvidenceKind.ALERT_ENCODED_COMMAND,
        true_positive=2,
        false_positive=-1,
        benign_activity=-2,
        test_activity=2,
    )
    for arrangement in (seeded, shuffled, tuple(reversed(seeded))):
        a = score_matrix(arrangement, (e,))
        assert a.scores[0].hypothesis.key is HypothesisKey.TRUE_POSITIVE, arrangement


# -- information gain ----------------------------------------------------------


def test_gain_fixture_uniform_net_and_hash():
    """Hand-computed independently (scratch script, pure math): uniform 0.25
    over 4 hypotheses → prior entropy 2.0 bits; a NET candidate gains
    0.28305 bits, a HASH candidate 0.37457 — hashes read sharper."""
    hyps = seed_hypotheses(SubjectKind.ALERT)
    a = score_matrix(hyps, ())
    net = candidate_lookups((_obs(ObservableType.DOMAIN, "evil-payments.ru"),))
    hsh = candidate_lookups((_obs(ObservableType.SHA256, "a" * 64),))
    plan_net = rank_lookups(a, net)
    plan_hash = rank_lookups(a, hsh)
    assert plan_net.prior_entropy_bits == pytest.approx(2.0, abs=1e-6)
    assert plan_net.ranked[0].expected_gain_bits == pytest.approx(0.28305, abs=1e-5)
    assert plan_hash.ranked[0].expected_gain_bits == pytest.approx(0.37457, abs=1e-5)
    assert (
        plan_hash.ranked[0].expected_gain_bits > plan_net.ranked[0].expected_gain_bits
    )
    # itemized outcome terms: probabilities over the outcome space sum to 1
    assert sum(t.probability for t in plan_net.ranked[0].outcome_terms) == pytest.approx(
        1.0, abs=1e-6
    )


def test_candidates_exclude_covered_skipped_cve_email_and_victims():
    covered = _obs(ObservableType.DOMAIN, "already-done.test")
    private = _obs(ObservableType.IPV4, "10.0.0.5")  # enrichment skip filter
    cve = _obs(ObservableType.CVE, "CVE-2026-1234")
    # S12 verification finding 5: no provider covers EMAIL — recommending it
    # produced a zero-progress lookup loop (claimed gain, executor skip,
    # nothing retired, same recommendation forever)
    email = _obs(ObservableType.EMAIL, "helpdesk-refund@gmail.com")
    fresh = _obs(ObservableType.URL, "http://evil.test/x")
    cands = candidate_lookups(
        (covered, private, cve, email, fresh),
        covered_obs_ids=enrichment_coverage((covered.obs_id,)),
    )
    assert [c.observable.value for c in cands] == ["http://evil.test/x"]
    assert cands[0].kind is LookupKind.ENRICH_OBSERVABLE


def test_candidate_hygiene_matches_the_executor():
    """The invariant behind finding 5, pinned structurally: every candidate
    the engine can recommend must be an observable type SOME provider
    accepts — the plan must never promise a lookup the executor coverage-
    skips."""
    from auspex.ach.gain import _UNENRICHABLE
    from auspex.config import get_settings
    from auspex.enrich.providers import build_providers

    covered_types = set()
    for p in build_providers(get_settings()):
        covered_types |= set(p.accepts)
    for t in ObservableType:
        if t in _UNENRICHABLE:
            continue
        cand = candidate_lookups((_obs(t, {
            ObservableType.IPV4: "198.18.0.9",
            ObservableType.IPV6: "2001:db8::9",
            ObservableType.DOMAIN: "candidate-check.test",
            ObservableType.URL: "http://candidate-check.test/x",
            ObservableType.SHA256: "b" * 64,
            ObservableType.SHA1: "b" * 40,
            ObservableType.MD5: "b" * 32,
        }[t]),))
        if cand:  # the engine would recommend this type…
            assert t in covered_types, f"{t} is recommendable but no provider accepts it"


def test_ranked_plan_is_capped_with_named_total():
    """Finding 8: 2,984 candidates serialized a 1.9 MB response. The plan
    surfaces at most _MAX_RANKED, and total_candidates names the rest."""
    from auspex.ach.gain import _MAX_RANKED

    hyps = seed_hypotheses(SubjectKind.ALERT)
    a = score_matrix(hyps, ())
    many = tuple(_obs(ObservableType.DOMAIN, f"host-{i}.evil.test") for i in range(50))
    plan = rank_lookups(a, candidate_lookups(many))
    assert len(plan.ranked) == _MAX_RANKED
    assert plan.total_candidates == 50


def test_email_candidates_ride_the_victim_filter():
    env = parse_email(_load("victim_named.eml"))
    kept, _ = filter_victim_iocs(env)
    cands = candidate_lookups(env.iocs, victim_filtered=kept)
    values = [c.observable.value for c in cands]
    assert values  # attacker infra is there
    assert not any("acme.com" in v and "evilsender" not in v for v in values)
    assert "10.0.0.5" not in values


def test_single_surviving_hypothesis_ends_the_search():
    hyps = seed_hypotheses(SubjectKind.ALERT)[:1]
    a = score_matrix(hyps, ())
    plan = rank_lookups(a, candidate_lookups((_obs(ObservableType.DOMAIN, "x.test"),)))
    assert plan.ranked == ()
    assert "one hypothesis" in (plan.reason or "")


def test_no_candidates_is_named_not_silent():
    hyps = seed_hypotheses(SubjectKind.ALERT)
    a = score_matrix(hyps, ())
    plan = rank_lookups(a, ())
    assert plan.ranked == ()
    assert "no lookup candidates" in (plan.reason or "")


def test_ties_break_deterministically_by_type_then_value():
    hyps = seed_hypotheses(SubjectKind.ALERT)
    a = score_matrix(hyps, ())
    cands = candidate_lookups(
        (
            _obs(ObservableType.DOMAIN, "zzz.test"),
            _obs(ObservableType.DOMAIN, "aaa.test"),
        )
    )
    plan = rank_lookups(a, cands)
    assert [r.candidate.observable.value for r in plan.ranked] == ["aaa.test", "zzz.test"]


# -- the demo story, end to end (zero LLM) --------------------------------------


def test_typosquat_email_scenario_discriminates_then_converges():
    """The S12 story: a typosquat email leaves TP and TEST both live (a
    lookalike domain is the hallmark of real phish AND simulations); the
    engine recommends enriching the lookalike domain; a malicious TI answer
    then collapses the space toward TRUE_POSITIVE."""
    env = parse_email(_load("failing_typosquat.eml"))
    verdict = decide_verdict(env)
    evidence = evidence_from_email(env, verdict)
    hyps = seed_hypotheses(SubjectKind.EMAIL)

    a1 = score_matrix(hyps, evidence)
    assert a1.ranking_claimed is True
    order1 = [s.hypothesis.key for s in a1.scores if s.status == "surviving"]
    assert order1[0] is HypothesisKey.TRUE_POSITIVE
    # the test-activity hypothesis is still live — auth fails and lookalikes
    # do not separate a phish from a sanctioned simulation
    assert HypothesisKey.TEST_ACTIVITY in order1

    kept, _ = filter_victim_iocs(env)
    cands = candidate_lookups(env.iocs, victim_filtered=kept)
    plan = rank_lookups(a1, cands)
    assert plan.ranked, plan.reason
    top = plan.ranked[0].candidate.observable
    assert top.type in (ObservableType.DOMAIN, ObservableType.URL, ObservableType.EMAIL)

    # simulate the recommended lookup answering MALICIOUS
    item = ObservableEnrichment(
        observable=top,
        signals=(
            ProviderSignal(
                provider="ThreatFox",
                label=VerdictLabel.MALICIOUS,
                confidence=0.9,
                summary="active phishing infrastructure",
                evidence={},
            ),
        ),
        skip_reason=None,
        sources_answered=1,
    )
    a2 = score_matrix(hyps, (*evidence, *evidence_from_enrichment(item)))
    assert a2.scores[0].hypothesis.key is HypothesisKey.TRUE_POSITIVE
    w1 = a1.weights[HypothesisKey.TRUE_POSITIVE]
    w2 = a2.weights[HypothesisKey.TRUE_POSITIVE]
    assert w2 > w1  # the lookup moved belief toward the true explanation
    # and the answered observable is no longer a candidate
    cands2 = candidate_lookups(
        env.iocs,
        covered_obs_ids=enrichment_coverage(
            tuple(e.obs_id for e in evidence_from_enrichment(item))
        ),
        victim_filtered=kept,
    )
    assert top.obs_id not in {c.observable.obs_id for c in cands2}
