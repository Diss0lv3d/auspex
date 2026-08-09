"""Retro-hunt surface — S14, zero-LLM (Living Verdicts, Phase 3 flagship).

The analyst-facing half of the retro-hunt: the sweep itself is driven by ingest
(auspex/retrohunt/sink.py), so there is no "run a hunt" endpoint — a hunt is
something new intel does to you, not something you ask for. These routes are how
you find out it happened.

GET  /api/retrohunt/matches            — re-open events (default: still open)
POST /api/retrohunt/matches/{id}/ack   — acknowledge one (analyst, explicit)
GET  /api/retrohunt/flips              — recorded verdict label changes

The honesty rail is repeated in the payload, not just the docs: every match
carries `action: "re-examine"` and the label as it stood AT MATCH TIME. Nothing
on this surface has changed a verdict, and `verdict_label` is deliberately not
re-read live — the analyst is being told what the platform believed when the
intel landed, which is the fact that makes the event meaningful.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auspex.auth import AuthContext, resolve_user
from auspex.retrohunt import list_flips, list_matches, mark_reviewed
from auspex.retrohunt.types import TRIGGER_KINDS, note_for

logger = logging.getLogger("auspex.retrohunt")

router = APIRouter(prefix="/api/retrohunt", tags=["retrohunt"])

Auth = Annotated[AuthContext, Depends(resolve_user)]

# Bounded like every other collection on this codebase's surfaces (the S12
# top-20 discipline): a workspace that has been running for a year has a long
# trail, and an unbounded list is a slow query waiting to happen.
MAX_PAGE = 200
DEFAULT_PAGE = 50


def _match_payload(m) -> dict:
    return {
        "match_id": str(m.id),
        "observable": {"obs_id": m.obs_id, "type": m.type, "value": m.value},
        "trigger_doc": m.doc_id,
        "feed": m.feed,
        "change_kind": m.change_kind,
        # What the verdict said WHEN the intel landed — the reason this is news.
        "verdict_label_at_match": m.verdict_label,
        "settled": m.verdict_label is not None,
        "status": m.status,
        "created_at": m.created_at.isoformat(),
        # Stated in the payload so no UI has to remember it (D-017). The note is
        # per-kind: a withdrawn CVE and a KEV listing are opposite events, and
        # S14 described both with the sentence for the second (S15 Step 0).
        "action": "re-examine",
        "note": note_for(m.change_kind),
    }


@router.get("/matches")
async def get_matches(
    request: Request,
    auth: Auth,
    status: Annotated[str | None, Query(pattern="^(open|reviewed|all)$")] = "open",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = DEFAULT_PAGE,
) -> dict:
    """Re-open events for this workspace, newest first. Defaults to `open`
    because the unacknowledged ones are the actionable ones."""
    matches = await list_matches(
        request.app.state.pool,
        workspace_id=auth.workspace_id,
        status=None if status == "all" else status,
        limit=limit,
    )
    return {
        "status_filter": status,
        "count": len(matches),
        "limit": limit,
        "matches": [_match_payload(m) for m in matches],
        # Naming the filter is the difference between "you have no re-open
        # events" and "nothing you have seen has appeared in new intel of the
        # kinds we sweep on".
        "sweeps_on": sorted(TRIGGER_KINDS),
    }


@router.post("/matches/{match_id}/ack")
async def ack_match(request: Request, match_id: UUID, auth: Auth) -> dict:
    """Acknowledge a re-open event. Explicit by design: a match is closed by an
    analyst deciding it is handled, never by the platform deciding for them —
    not even when a re-enrichment already produced a verdict flip (see
    retrohunt/flips.py)."""
    acked = await mark_reviewed(
        request.app.state.pool, workspace_id=auth.workspace_id, match_id=match_id
    )
    if not acked:
        # Same 404 whether the id belongs to another workspace or is already
        # reviewed — cross-tenant existence is not something to leak (D-008).
        raise HTTPException(status_code=404, detail="Unknown or already-reviewed match")
    return {"match_id": str(match_id), "status": "reviewed"}


@router.get("/flips")
async def get_flips(
    request: Request,
    auth: Auth,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = DEFAULT_PAGE,
) -> dict:
    """Recorded verdict label changes, newest first — the D-017 trail's
    automated writer, read back. `trigger` names why the re-look happened;
    `match_id` links the retro-hunt event that prompted it, when there was one."""
    flips = await list_flips(
        request.app.state.pool, workspace_id=auth.workspace_id, limit=limit
    )
    return {
        "count": len(flips),
        "limit": limit,
        "flips": [
            {
                "flip_id": str(f.id),
                "observable": {"obs_id": f.obs_id, "value": f.value},
                "from_label": f.from_label,
                "to_label": f.to_label,
                "trigger": f.trigger,
                "match_id": str(f.match_id) if f.match_id else None,
                "created_at": f.created_at.isoformat(),
            }
            for f in flips
        ],
    }
