"""Analysis of Competing Hypotheses engine — S12 (D-019: the matrix is code).

Pipeline: seed_hypotheses → evidence adapters (S5/S10/S11 typed shapes in) →
score_matrix (Heuer inconsistency-first, honest rails) → candidate_lookups +
rank_lookups (expected information gain over plausibility weights). Zero LLM
end to end; the model may later PROPOSE through a contract, never decide."""

from auspex.ach.evidence import (
    cells_for,
    evidence_from_alert,
    evidence_from_email,
    evidence_from_enrichment,
)
from auspex.ach.gain import (
    CandidateLookup,
    LookupKind,
    LookupPlan,
    RankedLookup,
    candidate_lookups,
    enrichment_coverage,
    rank_lookups,
)
from auspex.ach.matrix import (
    AchAssessment,
    EvidenceReading,
    HypothesisScore,
    score_matrix,
)
from auspex.ach.types import (
    Cell,
    Evidence,
    EvidenceKind,
    Hypothesis,
    HypothesisKey,
    SubjectKind,
    seed_hypotheses,
)

__all__ = [
    "AchAssessment",
    "CandidateLookup",
    "Cell",
    "Evidence",
    "EvidenceKind",
    "EvidenceReading",
    "Hypothesis",
    "HypothesisKey",
    "HypothesisScore",
    "LookupKind",
    "LookupPlan",
    "RankedLookup",
    "SubjectKind",
    "candidate_lookups",
    "cells_for",
    "enrichment_coverage",
    "evidence_from_alert",
    "evidence_from_email",
    "evidence_from_enrichment",
    "rank_lookups",
    "score_matrix",
    "seed_hypotheses",
]
