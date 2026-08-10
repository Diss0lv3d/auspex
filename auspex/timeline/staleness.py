"""What "stale" means, in code — S16 (Living Verdicts, Phase 3).

`effective_confidence` has been executable since S5 and pinned by a test since
S5, and in eleven sessions nothing has ever rendered it. A decay curve nobody
reads is a number, not a behaviour: the platform has been quietly holding
month-old beliefs at full strength on every surface an analyst actually looks
at. This module is the vocabulary that makes the curve mean something, and the
whole of it is arithmetic over columns we already write (D-017).

Two decisions this module MAKES rather than inherits:

1. **Bands are measured in half-lives elapsed, not days.** A 14-day IP verdict
   and a 365-day hash verdict are the same amount of stale after one half-life,
   and that is the only comparison worth putting in front of an analyst. Days
   would make every band a per-type table that drifts out of sync with
   `HALF_LIFE_DAYS`; half-lives make the band a property of the curve itself.

2. **Staleness never touches a label.** A decayed `malicious` verdict is still
   malicious — decay is a statement about how much the platform still stands
   behind its own confidence, not about the observable. Same rail as D-017 and
   D-020: nothing here rewrites a verdict, and no band is stored. Every value
   is derived at read time from (confidence_at_write, floor, half_life_days,
   created_at), so a verdict's staleness cannot fall out of date with itself.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from auspex.enrich.verdict import effective_confidence

# Band edges in HALF-LIVES elapsed. The retained fraction beside each is exactly
# 2^(-n), so the vocabulary and the curve cannot disagree: these are names for
# points on the D-017 formula, not a second opinion about aging.
#
#   0.00 half-lives  100%  ─┐ fresh    the claim stands roughly as written
#   0.50              71%  ─┘
#   0.50              71%  ─┐ aging    visibly weaker, still worth acting on
#   1.50              35%  ─┘
#   1.50              35%  ─┐ stale    more of the claim has evaporated than
#   3.00            12.5%  ─┘          remains — re-enrich before relying on it
#   3.00            12.5%  ─┐ lapsed   what is left is not evidence any more
#                            ┘
AGING_AT_HALF_LIVES = 0.5
STALE_AT_HALF_LIVES = 1.5
LAPSED_AT_HALF_LIVES = 3.0


class Staleness(StrEnum):
    """How much of what a verdict asserted still stands."""

    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    LAPSED = "lapsed"
    # `floor >= confidence_at_write` means the writer said this verdict does not
    # decay — there is no decayable part to lose. S5 sets ENRICHMENT_FLOOR = 0.0
    # so nothing produces this today, but the S7 floors (defanged input ⇒ at
    # least suspicious) are exactly that statement, and a band vocabulary that
    # reported them as `lapsed` after a year would be reporting the opposite of
    # what the floor was written to mean.
    HELD = "held"


# Which bands the UI renders in the warning colour, and which in Slate. Kept
# here rather than in the template so "stale" means one thing in the payload and
# on the screen (CLAUDE.md brand: Slate is the muted/DEFERRED/stale colour).
NEEDS_ATTENTION: frozenset[Staleness] = frozenset({Staleness.STALE, Staleness.LAPSED})


def half_lives_elapsed(*, created_at: datetime, now: datetime, half_life_days: float) -> float:
    """Age in half-lives. Negative ages (clock skew between a writer and a
    reader) clamp to 0 rather than reporting a verdict as fresher than new."""
    age_days = (now - created_at).total_seconds() / 86_400.0
    return max(age_days, 0.0) / half_life_days


def band_for(
    *,
    confidence_at_write: float,
    floor: float,
    half_life_days: float,
    created_at: datetime,
    now: datetime,
) -> Staleness:
    """The band this verdict is in right now."""
    if floor >= confidence_at_write:
        return Staleness.HELD
    n = half_lives_elapsed(
        created_at=created_at, now=now, half_life_days=half_life_days
    )
    if n < AGING_AT_HALF_LIVES:
        return Staleness.FRESH
    if n < STALE_AT_HALF_LIVES:
        return Staleness.AGING
    if n < LAPSED_AT_HALF_LIVES:
        return Staleness.STALE
    return Staleness.LAPSED


def confidence_now(
    *,
    confidence_at_write: float,
    floor: float,
    half_life_days: float,
    created_at: datetime,
    now: datetime,
) -> float:
    """`effective_confidence` with the age worked out from the row. The S5
    function takes `age_days` and every caller would otherwise compute it —
    which is how two callers end up disagreeing about what "now" means."""
    age_days = max((now - created_at).total_seconds() / 86_400.0, 0.0)
    return effective_confidence(
        confidence_at_write=confidence_at_write,
        floor=floor,
        half_life_days=half_life_days,
        age_days=age_days,
    )


class Standing(StrEnum):
    """What an OPEN falsification claim is still worth — the S16 answer to
    TD-020's open question.

    TD-020 recorded that an open watcher on a fully-decayed verdict reads
    exactly like one written yesterday. It does, and the fix is NOT to expire
    it: `status` answers "was this claim contradicted?", and letting decay write
    to that column would destroy the audit trail (a claim nobody ever
    contradicted would become indistinguishable from one that was, or from one
    a newer verdict superseded).

    So standing is a SECOND, derived question — "does this claim still carry
    weight?" — answered from the staleness of the verdict that made it, stored
    nowhere, and never conflated with the first. A lapsed claim is still watched
    and will still fire: the platform committed to it, and quietly ceasing to
    check would be the failure this whole feature exists to prevent."""

    LOAD_BEARING = "load_bearing"  # the verdict it guards still stands
    LAPSED = "lapsed"  # still watched, but the belief behind it has decayed


def standing_for(band: Staleness) -> Standing:
    """An open claim inherits the standing of the verdict that made it."""
    return Standing.LAPSED if band in NEEDS_ATTENTION else Standing.LOAD_BEARING
