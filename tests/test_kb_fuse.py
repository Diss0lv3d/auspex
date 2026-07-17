"""RRF fusion + regime-aware floors — pure math, constants pinned (S6).
Pattern + constants: docs/probes/2026-07-17-sara-rrf-retriever-pattern.md §1,§4."""

import pytest

from auspex.kb.fuse import RRF_K, apply_floor, regime_cutoff, rrf_fuse
from auspex.kb.types import KBHit


def hit(chunk_id: str, score: float = 1.0) -> KBHit:
    return KBHit(
        chunk_id=chunk_id,
        doc_id=chunk_id.split("#")[0],
        title=chunk_id,
        text="body",
        doc_type="cve",
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
