"""Retro-hunt types — S14 (Living Verdicts, Phase 3 flagship).

The premise: a verdict written last month was true about the evidence available
last month. When new intel lands, the observables we have already settled are
exactly the ones nobody is looking at any more — so the platform looks for us.

The honesty rail is the whole design (D-017): **a retro-hunt match is a reason
to re-examine, never an auto-flip.** A match records what the verdict said at
match time and stops. Only a real re-enrichment — new provider signals — may
change a label, and when it does, the change becomes its own typed row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

# Which DocChange kinds are worth waking an analyst for. `upserted` is NOT one:
# the NVD delta feed upserts ~770 docs/day (STATE.md) and a re-scored CVSS
# vector or a reworded description is not new information about an observable.
# `kev-added` is — a CVE moving into CISA's Known Exploited catalogue is a
# statement that it is being exploited in the wild, which is precisely the kind
# of intel that should reopen a settled question. `deleted` (NVD rejected a
# held CVE) is also material: the ground under an old verdict moved.
# events.py named "kev-added" as the intended trigger back in S7.
TRIGGER_KINDS: frozenset[str] = frozenset({"kev-added", "deleted"})

# CVE observables are the only class a CVE-keyed feed can match. ATT&CK
# technique ids (the attack feed) are not observables anyone pastes as an IOC,
# so they sweep nothing today — named here rather than left implicit.
SWEEPABLE_TYPE = "cve"


@dataclass(frozen=True)
class RetroHuntHit:
    """One historical observable that a newly-changed doc touches, with the
    verdict as it stood when the sweep found it."""

    workspace_id: UUID
    observable_id: UUID
    obs_id: str  # the short id analysts use in chat ("cve-1a2b3c4d")
    type: str
    value: str
    doc_id: str
    feed: str
    change_kind: str
    verdict_id: UUID | None  # None = seen but never enriched to a verdict
    verdict_label: str | None
    verdict_created_at: datetime | None

    @property
    def settled(self) -> bool:
        """A verdict exists, so there is something for new intel to unsettle.
        Unsettled observables are still recorded — an analyst who pasted an IOC
        and never enriched it still wants to know it is now known-exploited."""
        return self.verdict_id is not None


@dataclass(frozen=True)
class RetroHuntMatch:
    """A persisted re-open event."""

    id: UUID
    workspace_id: UUID
    observable_id: UUID
    obs_id: str
    type: str
    value: str
    doc_id: str
    feed: str
    change_kind: str
    verdict_label: str | None
    status: str  # "open" | "reviewed"
    created_at: datetime


@dataclass(frozen=True)
class VerdictFlip:
    """A recorded label change. `trigger` names WHY the re-enrichment happened
    ("retrohunt:CVE-2026-58644" when an open match explains it, otherwise
    "enrichment"), and `match_id` links the retro-hunt event that prompted it."""

    id: UUID
    workspace_id: UUID
    observable_id: UUID
    obs_id: str
    value: str
    from_label: str
    to_label: str
    trigger: str
    match_id: UUID | None
    created_at: datetime
