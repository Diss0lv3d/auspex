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

# What each kind actually claims, in the analyst's words. Both emitters of
# `deleted` mean one thing — NVD REJECTED a CVE we hold (scheduler.py, the delta
# stream and the KEV single-fetch path) — and that is the opposite motion from a
# KEV addition: nothing new was learned about the observable, the evidence a
# verdict may have rested on was RETRACTED. S14 gave both kinds the same
# sentence ("New intel touches an observable this workspace already saw"), which
# told the analyst the wrong story about half of them. Keyed by kind and kept
# next to TRIGGER_KINDS so a kind added without copy fails a test rather than
# silently inheriting a sentence that does not describe it.
MATCH_NOTES: dict[str, str] = {
    "kev-added": (
        "New intel touches an observable this workspace already saw: the CVE "
        "has entered CISA's Known Exploited Vulnerabilities catalogue, a "
        "statement that it is being exploited in the wild. This is a reason to "
        "re-examine, not a re-classification: no verdict has been changed."
    ),
    "deleted": (
        "A CVE this workspace already saw has been WITHDRAWN by NVD, and its "
        "record has been removed from the knowledge base. This is not new "
        "evidence about the observable — it is the removal of evidence a "
        "verdict may have rested on. A reason to re-examine, not a "
        "re-classification: no verdict has been changed."
    ),
}


def note_for(change_kind: str) -> str:
    """The analyst-facing sentence for a match. Unknown kinds cannot reach the
    surface today (TRIGGER_KINDS is closed and filtered in the sink), so the
    fallback states only what is true of every kind rather than guessing."""
    return MATCH_NOTES.get(
        change_kind,
        "New intel touches an observable this workspace already saw. This is a "
        "reason to re-examine, not a re-classification: no verdict has been "
        "changed.",
    )

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
    # S15: the claim a registered falsification watcher was guarding, when this
    # same doc change satisfied one. None means the intel touched the observable
    # without contradicting anything the verdict had committed to — a weaker
    # and honestly different event, which is why it is a distinct field rather
    # than stronger wording on every match.
    falsified_claim: str | None = None


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
