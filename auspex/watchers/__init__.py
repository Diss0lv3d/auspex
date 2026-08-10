"""Falsification watchers — S15 (Living Verdicts, Phase 3 flagship).

Every verdict registers, at write time, the typed conditions that would prove it
wrong. Feeds and re-enrichment are checked against those conditions, and a
satisfied watcher upgrades the S14 re-open event from "new intel touches an
observable you saw" to "new intel contradicts the specific claim this verdict
made" — a reason to re-examine, never an auto-flip (D-017, D-020).
"""

from auspex.watchers.derive import conditions_for
from auspex.watchers.sink import FanoutSink, WatcherSink
from auspex.watchers.store import (
    check_documents,
    check_escalation,
    list_watchers,
    register,
    satisfy_documents,
)
from auspex.watchers.types import (
    CHECKED_ON_ENRICHMENT,
    CHECKED_ON_INGEST,
    SATISFIED_BY_CHANGE,
    FalsificationCondition,
    Watcher,
    WatcherHit,
    WatcherKind,
    WatcherStatus,
)

__all__ = [
    "CHECKED_ON_ENRICHMENT",
    "CHECKED_ON_INGEST",
    "SATISFIED_BY_CHANGE",
    "FalsificationCondition",
    "FanoutSink",
    "Watcher",
    "WatcherHit",
    "WatcherKind",
    "WatcherSink",
    "WatcherStatus",
    "check_documents",
    "check_escalation",
    "conditions_for",
    "list_watchers",
    "register",
    "satisfy_documents",
]
