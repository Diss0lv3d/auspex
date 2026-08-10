"""Verdict timeline surface — S16, zero-LLM (Living Verdicts, Phase 3).

GET /api/timeline/digest        — "your past got re-scored", since a cutoff
GET /api/timeline/{obs_id}      — one observable's whole history

Both are readings of rows S5–S15 already wrote. Nothing here creates a new
notification shape: a re-open event is still a `retrohunt_matches` row
acknowledged at `POST /api/retrohunt/matches/{id}/ack`, and a contradicted claim
is still shown through the event it upgraded (D-020, D-021 — the rail has held
three sessions running and this surface is where it would have been easiest to
break, because a digest is the natural place to invent an inbox).

The one genuinely new thing on this surface is decay, and it is arithmetic:
`effective_confidence` has been executable and pinned by a test since S5 and
rendered nowhere, which means every surface has been showing month-old beliefs
at the strength they had the day they were written.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auspex.auth import AuthContext, resolve_user
from auspex.retrohunt.types import note_for
from auspex.timeline import Digest, VerdictTimeline, digest, timeline_for
from auspex.timeline.staleness import (
    AGING_AT_HALF_LIVES,
    LAPSED_AT_HALF_LIVES,
    NEEDS_ATTENTION,
    STALE_AT_HALF_LIVES,
    Staleness,
)
from auspex.timeline.store import reader_now

logger = logging.getLogger("auspex.timeline")

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

Auth = Annotated[AuthContext, Depends(resolve_user)]

DEFAULT_SINCE_DAYS = 7  # "the view an analyst opens after a week away"
MAX_SINCE_DAYS = 365
MAX_PAGE = 200
DEFAULT_PAGE = 50

# Stated in the payload rather than in docs no client reads, exactly as
# /api/watchers names its checker for each kind. A band is a point on the D-017
# curve, and a client that invented its own thresholds would be a second opinion
# about aging living in JavaScript.
_BANDS = {
    Staleness.FRESH.value: f"under {AGING_AT_HALF_LIVES} half-lives",
    Staleness.AGING.value: f"{AGING_AT_HALF_LIVES}–{STALE_AT_HALF_LIVES} half-lives",
    Staleness.STALE.value: f"{STALE_AT_HALF_LIVES}–{LAPSED_AT_HALF_LIVES} half-lives",
    Staleness.LAPSED.value: f"over {LAPSED_AT_HALF_LIVES} half-lives",
    Staleness.HELD.value: "written with a floor — does not decay",
}


def _verdict_payload(v) -> dict:
    return {
        "verdict_id": str(v.id),
        "label": v.label,
        # Both numbers, always. Showing only the second would hide what the
        # platform originally claimed; showing only the first is what every
        # surface did before S16.
        "confidence_at_write": round(v.confidence_at_write, 4),
        "confidence_now": v.confidence_now,
        "floor": round(v.floor, 4),
        "half_life_days": v.half_life_days,
        "half_lives_elapsed": v.half_lives_elapsed,
        "staleness": v.staleness.value,
        "needs_attention": v.staleness in NEEDS_ATTENTION,
        "source": v.source,
        "created_at": v.created_at.isoformat(),
        "current": v.current,
    }


def _claim_payload(c) -> dict:
    w = c.watcher
    return {
        "watcher_id": str(w.id),
        "kind": w.kind,
        "claim": w.claim,
        "status": w.status,
        # S16's answer to TD-020. `status` says whether anything contradicted
        # the claim; `standing` says whether the belief behind it still stands.
        # A lapsed claim is STILL WATCHED — the platform committed to it.
        "standing": c.standing.value if c.standing else None,
        "created_at": w.created_at.isoformat(),
        "satisfied_at": w.satisfied_at.isoformat() if w.satisfied_at else None,
        "satisfied_by": w.satisfied_by,
    }


def _timeline_payload(t: VerdictTimeline) -> dict:
    current = t.current
    return {
        "observable": {"obs_id": t.obs_id, "type": t.type, "value": t.value},
        "current": _verdict_payload(current) if current else None,
        "trail": [_verdict_payload(v) for v in t.trail],
        "flips": [
            {
                "flip_id": str(f.id),
                "from_label": f.from_label,
                "to_label": f.to_label,
                "trigger": f.trigger,
                "match_id": str(f.match_id) if f.match_id else None,
                "created_at": f.created_at.isoformat(),
            }
            for f in t.flips
        ],
        "reopened_by": [
            {
                "match_id": str(m.id),
                "trigger_doc": m.doc_id,
                "feed": m.feed,
                "change_kind": m.change_kind,
                "verdict_label_at_match": m.verdict_label,
                "status": m.status,
                "created_at": m.created_at.isoformat(),
                "note": note_for(m.change_kind),
                "falsifies": m.falsified_claim,
            }
            for m in t.matches
        ],
        "claims": [_claim_payload(c) for c in t.claims],
        "bands": _BANDS,
        "note": (
            "Decay describes how much of its own confidence the platform still "
            "stands behind, never the observable. A stale malicious verdict is "
            "still malicious — it is the confidence that has aged, and the fix "
            "is to re-enrich, not to re-label."
        ),
    }


# Which payload list each Digest field is rendered as. Explicit because the
# payload renames three of the four, and a truncation flag naming a key the
# client cannot find in the response would be worse than no flag at all.
_LIST_NAMES = {
    "matches": "reopened",
    "flips": "flipped",
    "contradicted": "contradicted",
    "decayed": "decayed",
}


def _digest_payload(d: Digest) -> dict:
    return {
        "since": d.since.isoformat(),
        "now": d.now.isoformat(),
        "quiet": d.quiet,
        # A page size and what it hid (S17 Step 0). Without these, a digest
        # showing 50 of 32,930 decayed verdicts reads exactly like one showing
        # all 50 there were — the surface that refuses to present an unexplained
        # empty list must not present a truncated one either.
        "limit": d.limit,
        "complete": d.complete,
        "truncated": [_LIST_NAMES[f] for f in d.truncated],
        # The honest half of a quiet answer (S16 Step 0): "nothing contradicted
        # your verdicts" is an absence claim, and 50 consecutive failed checks
        # produce exactly the same empty lists as 50 quiet ones.
        "trustworthy": d.trustworthy,
        "checkers": [
            {
                "name": c.name,
                "degraded": c.degraded,
                "consecutive_failures": c.consecutive_failures,
                "ever_succeeded": c.ever_succeeded,
                "last_error": c.last_error,
            }
            for c in d.checkers
        ],
        "reopened": [
            {
                "match_id": str(m.id),
                "observable": {"obs_id": m.obs_id, "type": m.type, "value": m.value},
                "trigger_doc": m.doc_id,
                "change_kind": m.change_kind,
                "verdict_label_at_match": m.verdict_label,
                "created_at": m.created_at.isoformat(),
                "falsifies": m.falsified_claim,
                "action": "re-examine",
            }
            for m in d.matches
        ],
        "flipped": [
            {
                "flip_id": str(f.id),
                "observable": {"obs_id": f.obs_id, "value": f.value},
                "from_label": f.from_label,
                "to_label": f.to_label,
                "trigger": f.trigger,
                "created_at": f.created_at.isoformat(),
            }
            for f in d.flips
        ],
        "contradicted": [
            {
                "watcher_id": str(w.id),
                "observable": {"obs_id": w.obs_id, "value": w.value},
                "kind": w.kind,
                "claim": w.claim,
                "satisfied_at": w.satisfied_at.isoformat() if w.satisfied_at else None,
                "satisfied_by": w.satisfied_by,
            }
            for w in d.contradicted
        ],
        "decayed": [
            {
                "observable": {"obs_id": x.obs_id, "type": x.type, "value": x.value},
                "label": x.label,
                "was": x.was.value,
                "now": x.now.value,
                "confidence_at_write": round(x.confidence_at_write, 4),
                "confidence_now": x.confidence_now,
                "half_lives_elapsed": x.half_lives_elapsed,
                "created_at": x.created_at.isoformat(),
            }
            for x in d.decayed
        ],
        "bands": _BANDS,
        "note": (
            "Nothing on this surface has changed a verdict. Re-open events are "
            "acknowledged at POST /api/retrohunt/matches/{id}/ack — the same "
            "one event, not a second inbox."
        ),
    }


@router.get("/digest")
async def get_digest(
    request: Request,
    auth: Auth,
    days: Annotated[int, Query(ge=1, le=MAX_SINCE_DAYS)] = DEFAULT_SINCE_DAYS,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = DEFAULT_PAGE,
) -> dict:
    """What happened to this workspace's settled questions in the last `days`.

    Declared BEFORE `/{obs_id}` so the literal path wins the route match — an
    observable can never be called "digest", but relying on that would be a
    coincidence rather than a decision."""
    # Both ends of the window come from the DATABASE's clock, because the
    # `created_at` they are compared against does (S17 Step 0 — see
    # timeline.store.reader_now). Deriving `since` from the app clock and the
    # rows from Postgres let a skewed container slide the whole window.
    now = await reader_now(request.app.state.pool)
    # The scheduler owns the change consumers; when ingest is disabled (the
    # devhost pins, a fresh process) there is no roster, and `trustworthy` says
    # so rather than assuming the quiet is real.
    ingest = getattr(request.app.state, "ingest", None)
    checkers = getattr(ingest, "checker_health", ()) if ingest is not None else ()
    result = await digest(
        request.app.state.pool,
        workspace_id=auth.workspace_id,
        since=now - timedelta(days=days),
        now=now,
        limit=limit,
        checkers=checkers,
    )
    return _digest_payload(result)


@router.get("/{obs_id}")
async def get_timeline(request: Request, obs_id: str, auth: Auth) -> dict:
    """One observable's whole life: every verdict with its decay worked out,
    every flip, every re-open event, and every claim its verdicts committed to."""
    result = await timeline_for(
        request.app.state.pool, workspace_id=auth.workspace_id, obs_id=obs_id
    )
    if result is None:
        # Identical 404 whether it is another workspace's observable or nobody's
        # (D-008) — cross-tenant existence is not something to leak.
        raise HTTPException(status_code=404, detail="Unknown observable")
    return _timeline_payload(result)
