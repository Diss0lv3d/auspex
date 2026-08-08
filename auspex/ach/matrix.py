"""The ACH matrix scorer — S12 (D-019: deterministic, zero-LLM, fixture-pinned).

Heuer's rule, kept faithfully: hypotheses are ranked by LEAST weighted
inconsistency, not most support. Confirmation is cheap — most evidence in a
security investigation is consistent with several stories at once (an encoded
command fits both an attack and a red-team drill). Disconfirmation is what
discriminates, so inconsistency drives ranking and elimination; support is
computed for display and tiebreaks only.

Honest rails (the S10/S11 philosophy, applied to reasoning):
- zero evidence            → every hypothesis surviving, NO ranking claimed;
- zero DIAGNOSTIC evidence → no ranking claimed (everything gathered so far
  fits all surviving hypotheses equally — say so, don't invent an ordering);
- a hypothesis is REJECTED only on enough weighted inconsistency INCLUDING at
  least one hard contradiction (a −2 cell at high credibility), and the reason
  is recorded on the score;
- if the evidence would reject EVERY hypothesis, none are rejected and the
  assessment says the hypothesis space itself looks wrong — an empty space is
  a lie, not a conclusion.

Plausibility weights (for gain.py's entropy math) derive from inconsistency via
the D-017 half-life idiom: w ∝ 2^(−inconsistency / PLAUSIBILITY_HALF_LIFE),
normalized over surviving hypotheses. They are plausibility weights, NOT
probabilities — nothing here estimates base rates.
"""

from __future__ import annotations

from dataclasses import dataclass

from auspex.ach.types import Evidence, Hypothesis, HypothesisKey

# Every 2.0 points of weighted inconsistency halve a hypothesis's plausibility
# weight (one strongly-inconsistent cell at full credibility = one halving).
PLAUSIBILITY_HALF_LIFE = 2.0

# Rejection: at least this much weighted inconsistency AND ≥1 hard contradiction.
REJECT_AT = 3.0
HARD_CELL = -2
HARD_CREDIBILITY = 0.7


@dataclass(frozen=True)
class HypothesisScore:
    """One hypothesis's standing against the evidence. `inconsistency` is the
    ranking key (lower survives); `support` is display/tiebreak only."""

    hypothesis: Hypothesis
    inconsistency: float
    support: float
    hard_contradictions: int
    status: str  # "surviving" | "rejected"
    rejected_reason: str | None = None
    weight: float = 0.0  # plausibility weight; 0.0 for rejected


@dataclass(frozen=True)
class EvidenceReading:
    """One evidence item's diagnosticity against the CURRENT surviving set.
    Spread 0 means the item fits every surviving hypothesis equally — true,
    perhaps, but useless for discrimination; the assessment names those."""

    evidence: Evidence
    spread: int  # max(cell) − min(cell) over surviving hypotheses' non-None cells
    diagnostic: bool


@dataclass(frozen=True)
class AchAssessment:
    """The full code-decided matrix state. `ranking_claimed=False` means the
    order of `scores` must not be read as a conclusion — `reason` says why."""

    scores: tuple[HypothesisScore, ...]  # surviving by ascending inconsistency, rejected last
    readings: tuple[EvidenceReading, ...]
    ranking_claimed: bool
    reason: str | None
    notes: tuple[str, ...] = ()

    @property
    def surviving(self) -> tuple[HypothesisScore, ...]:
        return tuple(s for s in self.scores if s.status == "surviving")

    @property
    def weights(self) -> dict[HypothesisKey, float]:
        """Plausibility weights over surviving hypotheses (sum 1.0)."""
        return {s.hypothesis.key: s.weight for s in self.surviving}


def _raw_scores(
    hypotheses: tuple[Hypothesis, ...], evidence: tuple[Evidence, ...]
) -> list[tuple[Hypothesis, float, float, int]]:
    out = []
    for h in hypotheses:
        inconsistency = support = 0.0
        hard = 0
        for e in evidence:
            cell = e.cells.get(h.key)
            if cell is None:  # unavailable — excluded, never counted either way
                continue
            if cell < 0:
                inconsistency += -cell * e.credibility
                if cell <= HARD_CELL and e.credibility >= HARD_CREDIBILITY:
                    hard += 1
            elif cell > 0:
                support += cell * e.credibility
        out.append((h, round(inconsistency, 6), round(support, 6), hard))
    return out


def score_matrix(
    hypotheses: tuple[Hypothesis, ...], evidence: tuple[Evidence, ...]
) -> AchAssessment:
    """Score every hypothesis against every evidence cell and decide statuses.
    Pure function: same inputs, same assessment — the persistence layer stores
    hypotheses and evidence, never derived scores (single source of truth)."""
    raw = _raw_scores(hypotheses, evidence)

    rejected = {
        h.key: (
            f"weighted inconsistency {inc:.2f} ≥ {REJECT_AT} with "
            f"{hard} hard contradiction(s)"
        )
        for h, inc, _, hard in raw
        if inc >= REJECT_AT and hard >= 1
    }
    notes: list[str] = []
    if len(rejected) == len(hypotheses) and hypotheses:
        # Everything rejected = the candidate space is wrong, not the world.
        notes.append(
            "evidence contradicts every candidate hypothesis — the hypothesis "
            "space itself is suspect; all kept surviving pending a better candidate"
        )
        rejected = {}

    surviving_raw = [(h, inc, sup, hard) for h, inc, sup, hard in raw if h.key not in rejected]
    weights_raw = {
        h.key: 2 ** (-inc / PLAUSIBILITY_HALF_LIFE) for h, inc, _, _ in surviving_raw
    }
    total = sum(weights_raw.values())
    weights = {k: round(v / total, 6) for k, v in weights_raw.items()} if total else {}

    surviving_keys = {h.key for h, *_ in surviving_raw}
    readings = tuple(
        _reading(e, surviving_keys) for e in evidence
    )

    scores = [
        HypothesisScore(
            hypothesis=h,
            inconsistency=inc,
            support=sup,
            hard_contradictions=hard,
            status="rejected" if h.key in rejected else "surviving",
            rejected_reason=rejected.get(h.key),
            weight=weights.get(h.key, 0.0),
        )
        for h, inc, sup, hard in raw
    ]
    # Surviving first by ascending inconsistency (Heuer), support as tiebreak,
    # ENUM declaration order as the final stable key. The enum — not the input
    # tuple — because the input order is not stable across persistence (the
    # store loads hypotheses alphabetically; the S12 verification caught the
    # API ranking TEST above TP on exact ties while the in-memory fixtures
    # ranked TP first). The closed enum IS the catalog order, everywhere.
    enum_order = list(HypothesisKey)
    scores.sort(
        key=lambda s: (
            s.status != "surviving",
            s.inconsistency,
            -s.support,
            enum_order.index(s.hypothesis.key),
        )
    )

    ranking_claimed, reason = _ranking_claim(evidence, readings)
    return AchAssessment(
        scores=tuple(scores),
        readings=readings,
        ranking_claimed=ranking_claimed,
        reason=reason,
        notes=tuple(notes),
    )


def _reading(e: Evidence, surviving: set[HypothesisKey]) -> EvidenceReading:
    # Diagnosticity must match SCORING semantics: a None cell contributes
    # nothing, exactly like 0 — so the spread is over effective (None→0)
    # cells across ALL survivors. A lone −2 cell on one hypothesis IS
    # diagnostic (it halves that hypothesis's weight relative to the rest);
    # the earlier len>=2 gate called that state "fits every surviving
    # hypothesis equally" while the weights were skewed 2× (S12 verification).
    cells = [(e.cells.get(k) if e.cells.get(k) is not None else 0) for k in surviving]
    spread = (max(cells) - min(cells)) if cells else 0
    return EvidenceReading(evidence=e, spread=spread, diagnostic=spread > 0)


def _ranking_claim(
    evidence: tuple[Evidence, ...], readings: tuple[EvidenceReading, ...]
) -> tuple[bool, str | None]:
    if not evidence:
        return False, "no evidence yet — every hypothesis is equally live"
    if not any(r.diagnostic for r in readings):
        return False, (
            "the evidence gathered so far fits every surviving hypothesis "
            "equally — it does not discriminate; no ranking is claimed"
        )
    return True, None
