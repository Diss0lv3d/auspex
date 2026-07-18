"""RRF fusion + regime-aware floors — pure math, constants pinned (S6).
Pattern + constants: docs/probes/2026-07-17-sara-rrf-retriever-pattern.md §1,§4."""

import pytest

from auspex.kb.fuse import RRF_K, apply_floor, neural_leg_floor, regime_cutoff, rrf_fuse
from auspex.kb.types import KBHit


def hit(chunk_id: str, score: float = 1.0, doc_type: str = "cve") -> KBHit:
    return KBHit(
        chunk_id=chunk_id,
        doc_id=chunk_id.split("#")[0],
        title=chunk_id,
        text="body",
        doc_type=doc_type,
        source="nvd",
        source_ref="",
        ids=(),
        severity="",
        cvss_score=None,
        score=score,
    )


def test_rrf_scores_are_rank_based_not_score_based():
    # Leg scores differ wildly (BM25 12.3 vs kNN 0.87) — fusion must ignore them
    a = [hit("A#0", 12.3), hit("B#0", 4.1)]
    b = [hit("B#0", 0.87), hit("C#0", 0.61)]
    fused = rrf_fuse(a, b, weight_a=0.4, weight_b=0.6, top_k=3)
    scores = {h.chunk_id: h.score for h in fused}
    assert scores["A#0"] == pytest.approx(0.4 / (RRF_K + 1), abs=1e-6)
    # B is rank 2 in leg A and rank 1 in leg B — both contributions accumulate
    assert scores["B#0"] == pytest.approx(0.4 / (RRF_K + 2) + 0.6 / (RRF_K + 1), abs=1e-6)
    assert scores["C#0"] == pytest.approx(0.6 / (RRF_K + 2), abs=1e-6)


def test_rrf_orders_by_fused_score_and_truncates():
    a = [hit("A#0"), hit("B#0")]
    b = [hit("B#0"), hit("C#0")]
    # Default weights are asymmetric (bm25 0.4 / neural 0.6): the both-legs hit
    # wins, and neural's rank-2 (0.6/62) beats bm25's rank-1 (0.4/61).
    fused = rrf_fuse(a, b, top_k=2)
    assert [h.chunk_id for h in fused] == ["B#0", "C#0"]
    # With equal weights rank decides: A (rank-1 in its leg) beats C (rank-2).
    balanced = rrf_fuse(a, b, weight_a=0.5, weight_b=0.5, top_k=3)
    assert [h.chunk_id for h in balanced] == ["B#0", "A#0", "C#0"]


def test_rrf_empty_legs():
    assert rrf_fuse([], [], top_k=5) == []
    only_a = rrf_fuse([hit("A#0")], [], top_k=5)
    assert [h.chunk_id for h in only_a] == ["A#0"]


def test_regime_cutoff_rrf_regime_is_lenient():
    # RRF top scores are structurally tiny (≈0.016); 0.4× would kill the tail
    assert regime_cutoff(0.016) == pytest.approx(0.004)  # top * 0.25
    assert regime_cutoff(0.008) == pytest.approx(0.003)  # floor kicks in


def test_regime_cutoff_lexical_regime_is_strict():
    assert regime_cutoff(20.0) == pytest.approx(8.0)  # top * 0.4
    assert regime_cutoff(0.5) == pytest.approx(0.2)


def test_apply_floor_drops_longtail_per_regime():
    hits = [hit("A#0", 10.0), hit("B#0", 5.0), hit("C#0", 3.9)]
    kept = apply_floor(hits)
    assert [h.chunk_id for h in kept] == ["A#0", "B#0"]  # floor = 4.0


def test_apply_floor_keeps_rrf_longtail():
    hits = [hit("A#0", 0.016), hit("B#0", 0.007), hit("C#0", 0.003)]
    kept = apply_floor(hits)  # floor = max(0.003, 0.004) = 0.004
    assert [h.chunk_id for h in kept] == ["A#0", "B#0"]


def test_apply_floor_empty():
    assert apply_floor([]) == []


# TD-005 operating point — every (doc_type, score, keep) row below is a
# MEASURED value from the live 3,417-chunk corpus battery
# (docs/probes/2026-07-18-td005-calibration.md). If a floor constant moves,
# these labeled boundary cases flip and this test names the query that broke.
TD005_OPERATING_POINT = [
    # (query the score came from, doc_type, measured score, must_keep)
    ("living off the land binaries → CONCEPT-LOLBIN", "concept", 0.691, True),
    ("what is credential dumping → T1003", "technique", 0.788, True),
    ("what is credential access → TA0006", "tactic", 0.864, True),
    ("what is quantum entanglement → T1090.002 NOISE", "technique", 0.617, False),
    ("employee vacation policy → T1556.009 NOISE", "technique", 0.618, False),
    ("best hiking trails → T1518.001 NOISE (curated)", "technique", 0.594, False),
    ("SharePoint deserialization RCE → CVE-2026-58644", "cve", 0.766, True),
    ("Log4j JNDI RCE → CVE-2021-44228", "cve", 0.841, True),
    ("k8s ingress config → CVE-2026-55723 (RELEVANT)", "cve", 0.793, True),
    ("employee vacation policy → CVE-2026-52840 NOISE", "cve", 0.624, False),
    ("hiking trails → CVE-2026-54468 NOISE", "cve", 0.609, False),
]


@pytest.mark.parametrize("label,doc_type,score,keep", TD005_OPERATING_POINT)
def test_neural_floor_operating_point_matches_the_live_battery(label, doc_type, score, keep):
    kept = neural_leg_floor([hit("X#0", score, doc_type=doc_type)])
    assert bool(kept) is keep, label


def test_neural_leg_floor_cuts_off_corpus_noise():
    # The original S6 probed pair (relevant 0.695 concept vs unrelated 0.498)
    # still separates under the S8 per-doc_type floors; unlabeled doc_types
    # keep the legacy 0.6 default.
    hits = [
        hit("A#0", 0.695, doc_type="concept"),
        hit("B#0", 0.598, doc_type="concept"),
        hit("C#0", 0.498, doc_type="concept"),
    ]
    assert [h.chunk_id for h in neural_leg_floor(hits)] == ["A#0"]
    assert neural_leg_floor([]) == []
    assert neural_leg_floor([hit("D#0", 0.61, doc_type="future-type")])  # default 0.6


def test_neural_floors_are_pinned_to_the_calibrated_constants():
    # S9 review (test-hygiene lens): the parametrized rows above pin only
    # INTERVALS, so a silent regression that stays inside a gap passes —
    # concept/tactic/cve 0.65/0.65/0.70 could drop toward the 0.6 default (the
    # exact value the calibration exists to keep off). Pin the dict verbatim so
    # any constant move fails loudly, naming this test.
    from auspex.kb.fuse import NEURAL_FLOORS, NEURAL_MIN_SCORE

    assert NEURAL_FLOORS == {
        "concept": 0.65,
        "technique": 0.65,
        "tactic": 0.65,
        "cve": 0.70,
    }
    assert NEURAL_MIN_SCORE == 0.6


def test_every_produced_doc_type_has_a_calibrated_floor():
    # S9 review (test-hygiene lens): a NEW doc_type with no calibrated floor
    # silently rides the 0.6 default — the same default that fabricated twice.
    # Any doc_type the KB actually produces (seeds, ATT&CK bundle, live NVD)
    # must have an explicit floor; a new feed (Sigma etc.) trips this test.
    import json
    from pathlib import Path

    from auspex.ingest.attack import bundle_to_docs
    from auspex.kb.fuse import NEURAL_FLOORS
    from auspex.kb.seed import load_seed_docs

    bundle = json.loads((Path(__file__).parent / "fixtures" / "attack_bundle.json").read_text())
    produced = {d.doc_type for d in load_seed_docs()}
    produced |= {d.doc_type for d in bundle_to_docs(bundle["objects"])}
    produced |= {"cve"}  # the live NVD delta feed's doc_type
    missing = produced - set(NEURAL_FLOORS)
    assert not missing, f"doc_types without a calibrated neural floor: {missing}"
