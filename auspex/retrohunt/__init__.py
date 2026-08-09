"""Retro-hunt — S14 (Living Verdicts, Phase 3 flagship).

New intel re-hunts historical observables: when a CVE moves into CISA's
Known-Exploited catalogue (or NVD rejects one), the observables a workspace has
already settled are swept for matches through ONE indexed join, and every match
becomes a typed re-open event. A match is a reason to re-examine — never an
auto-flip (D-017). When a real re-enrichment then changes a label, the change
gets its own provenanced row naming the doc that prompted the second look.
"""

from auspex.retrohunt.flips import record_flip_if_changed
from auspex.retrohunt.sink import RetroHuntSink
from auspex.retrohunt.store import (
    list_flips,
    list_matches,
    mark_reviewed,
    record_matches,
    sweep,
)
from auspex.retrohunt.types import (
    TRIGGER_KINDS,
    RetroHuntHit,
    RetroHuntMatch,
    VerdictFlip,
)

__all__ = [
    "TRIGGER_KINDS",
    "RetroHuntHit",
    "RetroHuntMatch",
    "RetroHuntSink",
    "VerdictFlip",
    "list_flips",
    "list_matches",
    "mark_reviewed",
    "record_flip_if_changed",
    "record_matches",
    "sweep",
]
