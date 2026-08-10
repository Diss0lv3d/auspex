"""Falsification watchers — S15 (Living Verdicts, Phase 3 flagship).

S14 gave verdicts a way to be re-examined when new intel lands, and a way to
record that they changed. What neither answers is the question a good analyst
asks BEFORE they are wrong: *what would change my mind?*

A verdict is a claim. Claims that cannot be wrong are not worth writing down, so
every verdict here registers the concrete, checkable conditions that would
falsify it — **at write time, before the evidence arrives**, which is the only
moment the answer is honest. Afterwards it is rationalisation.

Three rails, in order of how easily each could have been given away:

1. **Typed, not prose.** A watcher is a `kind` from a closed vocabulary plus
   params. "This domain's registrar changes" as free text is a wish; as
   `(kind=registrar_change, params={"registrar": "..."})` it is something code
   can evaluate against a feed. Prose falsifiers would have been faster to
   write and impossible to check — which is exactly the D-007 "specs over
   prompts" line, applied to our own reasoning instead of the model's.

2. **Registered by code, from the evidence.** The conditions are DERIVED from
   the observable, the label and the signals that produced it (see derive.py),
   never proposed by a model. A model-proposed falsifier is a live idea
   (D-019-later) but it would have to come through a contract, and S15 does not
   need it to be true.

3. **A satisfied watcher is a reason to re-examine, never an auto-flip.** Same
   rail as D-020, and it is load-bearing in the opposite direction here: a
   watcher that fired is the platform's own prediction coming true, which is
   precisely when it would feel safest to skip the analyst. It does not. The
   satisfaction upgrades the S14 re-open event from "new intel touches this" to
   "new intel contradicts the specific claim this verdict made", and stops.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class WatcherKind(StrEnum):
    """The closed falsification vocabulary. Each kind names a CHECKABLE event,
    not a worry: something a feed or an enrichment either produces or does not.

    Adding a kind means teaching a checker to evaluate it — `CHECKED_ON_INGEST`
    and `CHECKED_ON_ENRICHMENT` below partition this enum, and a test asserts
    the partition is total, so a kind that nothing evaluates cannot be added by
    accident. A registered watcher nobody checks is worse than no watcher: it
    reads as coverage."""

    # A CVE this verdict is about enters CISA's Known Exploited catalogue.
    # Falsifies any claim short of malicious: "not known-exploited" is exactly
    # what a KEV listing denies.
    KEV_LISTING = "kev_listing"
    # NVD withdraws the record this verdict was reasoned from. Falsifies the
    # verdict's BASIS rather than its label — the evidence is gone, so the
    # confidence attached to it is no longer earned.
    RECORD_WITHDRAWN = "record_withdrawn"
    # A later enrichment returns a more severe label than this verdict carries.
    # The claim being made by a benign/unknown/suspicious verdict is "no
    # connected source calls this worse than X"; a source doing so falsifies it.
    PROVIDER_ESCALATION = "provider_escalation"


# Which checker owns each kind. Doc-keyed kinds are evaluated against ingest's
# DocChange batches through an indexed join (store.check_documents); the
# enrichment-keyed kind is evaluated where labels are actually written, inside
# the enrichment transaction (store.check_escalation).
CHECKED_ON_INGEST: frozenset[WatcherKind] = frozenset(
    {WatcherKind.KEV_LISTING, WatcherKind.RECORD_WITHDRAWN}
)
CHECKED_ON_ENRICHMENT: frozenset[WatcherKind] = frozenset(
    {WatcherKind.PROVIDER_ESCALATION}
)

# The DocChange kind that satisfies each ingest-checked watcher. The mapping is
# explicit rather than a naming coincidence: ingest's vocabulary
# ("kev-added" / "deleted", auspex/ingest/events.py) and the falsification
# vocabulary are separate namespaces that happen to be adjacent today, and
# silently coupling them would break the first time a feed renames a kind.
SATISFIED_BY_CHANGE: dict[str, WatcherKind] = {
    "kev-added": WatcherKind.KEV_LISTING,
    "deleted": WatcherKind.RECORD_WITHDRAWN,
}


class WatcherStatus(StrEnum):
    OPEN = "open"  # registered, watching, not yet contradicted
    SATISFIED = "satisfied"  # the condition happened — an analyst owes it a look
    # A newer verdict for the same observable replaced the claim this watcher
    # was guarding. Not deleted: "we were watching for this and stopped" is part
    # of the audit trail, and a superseded watcher is how you find a claim that
    # was quietly dropped rather than answered.
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class FalsificationCondition:
    """One "what would flip me", derived in code from a verdict and its signals.

    `claim` is the sentence the verdict is asserting — the thing that would
    become false. It is written from the VERDICT's point of view, not the
    watcher's, because that is what an analyst needs to weigh: "no connected
    source calls this malicious" is a claim you can judge; "watch for provider
    escalation" is a chore."""

    kind: WatcherKind
    claim: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Watcher:
    """A persisted falsification condition, with what became of it."""

    id: UUID
    workspace_id: UUID
    observable_id: UUID
    obs_id: str
    value: str
    verdict_id: UUID
    verdict_label: str
    kind: str
    claim: str
    params: dict
    status: str
    created_at: datetime
    satisfied_at: datetime | None
    satisfied_by: str | None  # the doc id or flip that contradicted the claim


@dataclass(frozen=True)
class WatcherHit:
    """An open watcher whose condition just happened."""

    watcher_id: UUID
    workspace_id: UUID
    observable_id: UUID
    kind: str
    claim: str
    doc_id: str
