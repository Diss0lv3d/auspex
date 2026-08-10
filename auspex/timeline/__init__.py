"""Verdict timeline — S16 (Living Verdicts, Phase 3).

A verdict's life, readable end to end, plus the vocabulary that makes its decay
mean something. Reads only: four tables already hold the history, and if
rendering it had required storing anything new, the history was not being kept.
"""

from auspex.timeline.staleness import (
    NEEDS_ATTENTION,
    Staleness,
    Standing,
    band_for,
    confidence_now,
    half_lives_elapsed,
    standing_for,
)
from auspex.timeline.store import MAX_TRAIL, decayed_since, digest, timeline_for
from auspex.timeline.types import (
    Decayed,
    DecayedVerdict,
    Digest,
    StandingClaim,
    VerdictTimeline,
)

__all__ = [
    "MAX_TRAIL",
    "NEEDS_ATTENTION",
    "Decayed",
    "DecayedVerdict",
    "Digest",
    "Staleness",
    "Standing",
    "StandingClaim",
    "VerdictTimeline",
    "band_for",
    "confidence_now",
    "decayed_since",
    "digest",
    "half_lives_elapsed",
    "standing_for",
    "timeline_for",
]
