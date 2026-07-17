"""Rank fusion + regime-aware score floors — SARA pattern, constants preserved
(docs/probes/2026-07-17-sara-rrf-retriever-pattern.md §1, §4).

RRF is rank-based on purpose: our kNN leg scores are bounded [0,1]
(lucene cosinesimil, measured) while BM25 is unbounded and corpus-dependent —
mixing raw scores would be meaningless. Pure functions, no I/O.
"""

from auspex.kb.types import KBHit

RRF_K = 60
BM25_WEIGHT = 0.4
NEURAL_WEIGHT = 0.6

# Two score regimes (SARA audit 2026-05-06, verified against our own scales):
# RRF-fused scores live around weight/(k+rank) ≈ 0.006–0.016; BM25 scores start
# near 1 and grow. A top score < 0.1 can only be the RRF regime.
_REGIME_BOUNDARY = 0.1
_RRF_FLOOR = 0.003
_RRF_TOP_FRACTION = 0.25
_LEXICAL_TOP_FRACTION = 0.4
DEFAULT_SCORE_THRESHOLD = 0.005

# Absolute floors for the kNN leg BEFORE fusion. kNN always returns k nearest
# neighbors — for an off-corpus query those are pure noise, and RRF would
# promote them into a fabricated "KB answer". lucene cosinesimil scores are
# bounded [0,1], so absolute cuts are meaningful — but max-of-N noise GROWS
# with pool size, so the floor is per doc_type, calibrated against the live
# grown corpus (probe 2026-07-18-td005-calibration.md, 3,417 chunks):
# - curated pool (concept/technique/tactic, ~1.4k chunks, structurally
#   bounded — ATT&CK is the full universe): noise ceiling 0.618 vs weakest
#   true positive 0.691 → 0.65. At 0.6 the definition path FABRICATED
#   (live: "quantum entanglement" → T1090.002 at 0.617).
# - cve pool (grows ~770 docs/day, erosion-prone): noise ceiling 0.624 vs
#   weakest true positive 0.766 → 0.70 with headroom for growth.
# Re-run the calibration battery when the corpus passes ~30k chunks or a
# new doc_type lands (TD-005).
NEURAL_MIN_SCORE = 0.6  # unlabeled doc_types only — calibrated types override
NEURAL_FLOORS = {
    "concept": 0.65,
    "technique": 0.65,
    "tactic": 0.65,
    "cve": 0.70,
}


def neural_leg_floor(hits: list[KBHit]) -> list[KBHit]:
    return [h for h in hits if h.score >= NEURAL_FLOORS.get(h.doc_type, NEURAL_MIN_SCORE)]


def rrf_fuse(
    leg_a: list[KBHit],
    leg_b: list[KBHit],
    *,
    weight_a: float = BM25_WEIGHT,
    weight_b: float = NEURAL_WEIGHT,
    top_k: int,
) -> list[KBHit]:
    """Reciprocal-rank fusion; a chunk in both legs accumulates both scores."""
    fused: dict[str, KBHit] = {}
    scores: dict[str, float] = {}
    for weight, leg in ((weight_a, leg_a), (weight_b, leg_b)):
        for rank, hit in enumerate(leg):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + weight / (RRF_K + rank + 1)
            fused.setdefault(hit.chunk_id, hit)
    merged = sorted(fused.values(), key=lambda h: scores[h.chunk_id], reverse=True)
    return [KBHit(**{**h.__dict__, "score": round(scores[h.chunk_id], 6)}) for h in merged[:top_k]]


def regime_cutoff(top_score: float, *, threshold: float = DEFAULT_SCORE_THRESHOLD) -> float:
    """Relevance floor adapted to which score regime the top hit is in."""
    if top_score < _REGIME_BOUNDARY:
        return max(_RRF_FLOOR, top_score * _RRF_TOP_FRACTION)
    return max(threshold, top_score * _LEXICAL_TOP_FRACTION)


def apply_floor(hits: list[KBHit], *, threshold: float = DEFAULT_SCORE_THRESHOLD) -> list[KBHit]:
    if not hits:
        return []
    floor = regime_cutoff(hits[0].score, threshold=threshold)
    return [h for h in hits if h.score >= floor]
