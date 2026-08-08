"""Next-lookup selection by expected information gain — S12 goal 3 (D-019).

"Which lookup next" is not a checklist (the SARA negative: its enrichment
selection is a static doctrine table, its step selection is LLM judgment —
docs/probes/2026-08-08-sara-ach-analogues.md). Here it is a computation: for
each candidate lookup, how much would its outcome be EXPECTED to shrink the
entropy of the surviving-hypothesis weights?

    IG(L) = H(w) − Σ_o P(o) · H(posterior after o)
    P(o)  = Σ_h w(h) · P(o | h)

The per-hypothesis outcome likelihoods P(o|h) are curated code constants
(`_LIKELIHOODS`), one row per (lookup kind, observable group, hypothesis),
each row summing to 1 and pinned by tests — analyst priors made inspectable,
not model output and not env vars. The posterior update is Bayes on those
rows over PLAUSIBILITY weights; the result is documented as expected
discrimination, not a probability forecast.

v1 ships ONE lookup kind: ENRICH_OBSERVABLE (the S5 fan-out — the only lookup
Auspex can execute today with zero LLM). The catalog is an enum precisely so
S13+ can add KB/context lookups by adding a row, a table, and a test.

Candidate hygiene reuses the hardened layers instead of re-deciding:
- enrichment's own skip filters (private IPs, ubiquitous domains) — a lookup
  that would be skipped can never be a candidate;
- the S11/S12 victim filter for email subjects — the engine must never
  recommend enriching the victim's own domain (the S12 review-B lesson);
- observables already covered by enrichment evidence are excluded (asking the
  same question twice gains nothing).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from auspex.ach.matrix import AchAssessment
from auspex.ach.types import EvidenceKind, HypothesisKey
from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.filters import skip_reason


class LookupKind(StrEnum):
    """Closed catalog of lookups the engine may recommend. v1: enrichment only
    (the one lookup executable today); extend by PR with a likelihood table."""

    ENRICH_OBSERVABLE = "enrich_observable"


# Outcome vocabulary for ENRICH_OBSERVABLE: the three claim labels the S5
# synthesis can produce, plus "unknown" (a completed lookup with no signal —
# still informative, because hypotheses differ in HOW OFTEN their infra is
# feed-listed at all).
_OUTCOMES = ("malicious", "suspicious", "benign", "unknown")

_HASH_TYPES = frozenset({ObservableType.SHA256, ObservableType.SHA1, ObservableType.MD5})
# CVE is knowledge, not attacker infrastructure — and the KB-context lookup for
# it is the 5×-parked idea (NEXT-SESSION.md: do NOT pick up). EMAIL is excluded
# because NO connected provider accepts ObservableType.EMAIL today: the S12
# verification proved the engine otherwise recommends an email lookup with
# claimed positive gain that the executor coverage-skips — a zero-progress
# recommendation loop. The candidate set must never promise a lookup the
# executor cannot perform; when a provider adds email coverage, remove it here
# (the likelihood row already exists — email addresses price as "net").
_UNENRICHABLE = frozenset({ObservableType.CVE, ObservableType.EMAIL})

# Response/plan bound: the FULL candidate set is priced and sorted; only the
# top slice is surfaced (a 32 KB paste dense with routable IPs yielded 2,984
# candidates → a 1.9 MB response recomputed on every GET — S12 verification,
# finding 8). `total_candidates` names what the slice hides.
_MAX_RANKED = 20

# P(outcome | hypothesis) per observable group. Rows sum to 1.0 (pinned by
# test). Hashes read sharper than network observables: a real malware hash is
# well covered by feeds, while red-team droppers and FP artifacts mostly miss.
_HASH_ROW: Mapping[HypothesisKey, tuple[float, float, float, float]] = MappingProxyType(
    {
        HypothesisKey.TRUE_POSITIVE: (0.55, 0.15, 0.02, 0.28),
        HypothesisKey.FALSE_POSITIVE: (0.02, 0.05, 0.30, 0.63),
        HypothesisKey.BENIGN_ACTIVITY: (0.01, 0.04, 0.45, 0.50),
        HypothesisKey.TEST_ACTIVITY: (0.10, 0.15, 0.05, 0.70),
    }
)
_NET_ROW: Mapping[HypothesisKey, tuple[float, float, float, float]] = MappingProxyType(
    {
        HypothesisKey.TRUE_POSITIVE: (0.45, 0.20, 0.05, 0.30),
        HypothesisKey.FALSE_POSITIVE: (0.02, 0.08, 0.40, 0.50),
        HypothesisKey.BENIGN_ACTIVITY: (0.02, 0.05, 0.55, 0.38),
        HypothesisKey.TEST_ACTIVITY: (0.08, 0.12, 0.20, 0.60),
    }
)

_LIKELIHOODS: Mapping[LookupKind, Mapping[str, Mapping[HypothesisKey, tuple[float, ...]]]] = (
    MappingProxyType(
        {
            LookupKind.ENRICH_OBSERVABLE: MappingProxyType(
                {"hash": _HASH_ROW, "net": _NET_ROW}
            )
        }
    )
)


def _group(obs_type: ObservableType) -> str:
    return "hash" if obs_type in _HASH_TYPES else "net"


@dataclass(frozen=True)
class CandidateLookup:
    kind: LookupKind
    observable: Observable
    reason: str  # why it qualifies (provenance for the analyst)


@dataclass(frozen=True)
class OutcomeTerm:
    """One itemized term of the expectation — named numbers, never an opaque
    score (the Auspex voice, applied to math)."""

    outcome: str
    probability: float
    posterior_entropy_bits: float


@dataclass(frozen=True)
class RankedLookup:
    candidate: CandidateLookup
    expected_gain_bits: float
    outcome_terms: tuple[OutcomeTerm, ...]


@dataclass(frozen=True)
class LookupPlan:
    """The engine's recommendation. `ranked` is empty when there is nothing
    worth looking up — `reason` says why (honesty rail, never a filler pick).
    `ranked` is capped at `_MAX_RANKED`; `total_candidates` names the full
    priced set so truncation is visible, never silent."""

    prior_entropy_bits: float
    ranked: tuple[RankedLookup, ...]
    reason: str | None
    total_candidates: int = 0


def _entropy(weights: Mapping[HypothesisKey, float]) -> float:
    return round(
        -sum(w * math.log2(w) for w in weights.values() if w > 0.0), 6
    )


def candidate_lookups(
    observables: tuple[Observable, ...],
    *,
    covered_obs_ids: frozenset[str] = frozenset(),
    victim_filtered: tuple[Observable, ...] | None = None,
) -> tuple[CandidateLookup, ...]:
    """Enrichment candidates from a subject's observables. `victim_filtered`
    (when the caller is an email investigation) is the ALREADY-filtered kept
    set from filter_victim_iocs — this function never re-derives victim logic,
    it reuses the S11/S12-hardened result."""
    pool = victim_filtered if victim_filtered is not None else observables
    out: list[CandidateLookup] = []
    seen: set[str] = set()
    for o in pool:
        if o.obs_id in seen:
            continue
        seen.add(o.obs_id)
        if o.type in _UNENRICHABLE:
            continue
        if o.obs_id in covered_obs_ids:
            continue  # already answered — zero expected gain by construction
        if skip_reason(o) is not None:
            continue  # enrichment itself would refuse (private IP, ubiquitous domain)
        out.append(
            CandidateLookup(
                kind=LookupKind.ENRICH_OBSERVABLE,
                observable=o,
                reason=f"unenriched {o.type.value} observed in the subject",
            )
        )
    return tuple(out)


def rank_lookups(assessment: AchAssessment, candidates: tuple[CandidateLookup, ...]) -> LookupPlan:
    """Rank candidates by expected information gain over the surviving-
    hypothesis plausibility weights. Deterministic: ties break by observable
    type then value, so the same state always yields the same plan."""
    weights = assessment.weights
    prior_h = _entropy(weights)

    if len(weights) <= 1:
        return LookupPlan(
            prior_entropy_bits=prior_h,
            ranked=(),
            # 0 and 1 survivors end the search for the same reason, but the
            # message must not claim "one survives" over an empty set
            # (S13 review, finding 7).
            reason=(
                "only one hypothesis survives — there is nothing left to discriminate"
                if len(weights) == 1
                else "the investigation has no hypotheses — there is nothing to discriminate"
            ),
            total_candidates=len(candidates),
        )
    if not candidates:
        return LookupPlan(
            prior_entropy_bits=prior_h,
            ranked=(),
            reason=(
                "no lookup candidates remain — every enrichable observable is "
                "covered, skipped, or victim-filtered"
            ),
            total_candidates=0,
        )

    ranked = sorted(
        (_rank_one(c, weights, prior_h) for c in candidates),
        key=lambda r: (
            -r.expected_gain_bits,
            r.candidate.observable.type.value,
            r.candidate.observable.value,
        ),
    )
    return LookupPlan(
        prior_entropy_bits=prior_h,
        ranked=tuple(ranked[:_MAX_RANKED]),
        reason=None,
        total_candidates=len(candidates),
    )


def _rank_one(
    c: CandidateLookup, weights: Mapping[HypothesisKey, float], prior_h: float
) -> RankedLookup:
    rows = _LIKELIHOODS[c.kind][_group(c.observable.type)]
    terms: list[OutcomeTerm] = []
    expected_posterior = 0.0
    for i, outcome in enumerate(_OUTCOMES):
        p_o = sum(w * rows[h][i] for h, w in weights.items())
        if p_o <= 0.0:
            continue
        posterior = {h: (w * rows[h][i]) / p_o for h, w in weights.items()}
        h_post = _entropy(posterior)
        expected_posterior += p_o * h_post
        terms.append(
            OutcomeTerm(
                outcome=outcome,
                probability=round(p_o, 6),
                posterior_entropy_bits=h_post,
            )
        )
    gain = round(max(prior_h - expected_posterior, 0.0), 6)
    return RankedLookup(candidate=c, expected_gain_bits=gain, outcome_terms=tuple(terms))


def enrichment_coverage(evidence_obs_ids: tuple[str | None, ...]) -> frozenset[str]:
    """The obs_ids already covered by enrichment evidence rows."""
    return frozenset(i for i in evidence_obs_ids if i)


__all__ = [
    "CandidateLookup",
    "EvidenceKind",
    "LookupKind",
    "LookupPlan",
    "OutcomeTerm",
    "RankedLookup",
    "candidate_lookups",
    "enrichment_coverage",
    "rank_lookups",
]
