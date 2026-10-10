"""Approvals — S18 (Phase 4). The surface where a human decides.

GET  /api/proposals                  — what is waiting, each with its card
POST /api/proposals/{id}/approve     — claim it, then run it
POST /api/proposals/{id}/reject      — claim it, and do not
POST /api/proposals/{id}/undo        — put back an executed, incomplete or abandoned action
POST /api/proposals/{id}/abandon     — declare a dead claim dead (TD-028a)

Four things about this surface are deliberate:

**The card is served, not rebuilt.** Each row carries the card that was rendered
when the proposal was filed. Re-deriving it on read would show today's
declaration for yesterday's decision — an audit trail that quietly updates itself
is worse than none.

**Approve and execute are one request, and still two guarantees.** The claim
settles the row before anything runs, so a double-approve is impossible; the
execute path then re-checks the D-014 gate and the spec fingerprint, so an
approval granted an hour ago cannot run against a changed declaration. A caller
that wins the claim and then fails the re-check gets `approved` plus the refusal
— the decision stands, the execution does not happen, and the response says both.

**A 409 means someone else decided.** Not a 400: nothing about the request was
malformed, and the client's correct response is to re-read the proposal rather
than to fix and retry.

**The queue shows stale claims, and no timer resolves them.** A row wedged in
`executing` because the process holding it died is a decision waiting on a human
exactly like a pending one, so `GET /api/proposals` returns it (S21, TD-028a).
What it does NOT do is guess: only a human can say whether a lost handler ran,
and `abandon` records that the answer is unknown rather than asserting one.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from auspex.actions.settlement import (
    STALE_CLAIM_SECONDS,
    ActionExecutor,
    ExecutionRefused,
    ProposalSettlement,
    Settlement,
)
from auspex.auth import AuthContext, resolve_user

logger = logging.getLogger("auspex.proposals")

router = APIRouter(prefix="/api/proposals", tags=["proposals"])

Auth = Annotated[AuthContext, Depends(resolve_user)]

MAX_PAGE = 200
DEFAULT_PAGE = 50

# Poll cadence for the card stream. One indexed query per tick; a second is well
# inside what an approval queue needs and cheap enough not to need a budget.
STREAM_POLL_SECONDS = 1.0
# A heartbeat every N quiet ticks, so a client can distinguish "nothing waiting"
# from "this connection died" without waiting for a proposal to prove it.
HEARTBEAT_EVERY = 15
# And an explicit lifetime. `request.is_disconnected()` is the only other way out
# of this loop, and it does not reliably flip behind every proxy — an unbounded
# server-side generator whose exit condition might never fire is a leak with a
# polite name. SSE clients reconnect natively, so ending the stream costs a
# round trip and buys a bound.
STREAM_MAX_TICKS = 600


def _sse(event: dict) -> str:
    """Single-key JSON frame, same protocol as /api/chat."""
    return f"data: {json.dumps(event)}\n\n"


def _public(row: dict) -> dict:
    """What a client may see. `tool_input` is echoed because the card already
    names the arguments a human is consenting to; the internal fingerprint is
    surfaced too, since a client that caches a card needs to notice when the
    declaration behind it moved."""
    return {
        "id": str(row["id"]),
        "action": row["tool_name"],
        "risk": row["tool_level"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "decided_at": row["decided_at"].isoformat() if row["decided_at"] else None,
        "undone_at": row["undone_at"].isoformat() if row.get("undone_at") else None,
        # Present only while a claim is outstanding. A card showing `executing`
        # with a claim five minutes old is the one thing an approver must be
        # able to tell apart from a run that started a second ago (TD-028a).
        "claimed_at": row["claimed_at"].isoformat() if row.get("claimed_at") else None,
        # Which operation a human gave up on (TD-034): `executing` or `undoing`.
        "abandoned_from": row.get("abandoned_from"),
        # The other requests awaiting a decision that ask exactly this (TD-028d)
        # — present on queue reads; an approver asked twice can see it.
        "identical_pending": [str(i) for i in row.get("identical_pending") or []],
        "arguments": row["tool_input"],
        "card": row["card"],
        "spec_fingerprint": row["spec_fingerprint"],
        "result": row["result"],
        "undo_result": row["undo_result"],
    }


# What a failed run's 500 says, by what the action found (TD-028b). The status
# alone read as "nothing happened" when the write had landed.
_EFFECTS_COPY = {
    "none": "the action checked and nothing of it landed",
    "present": "part of it landed before it failed — undo will remove what landed",
    "unknown": "it cannot tell whether any of it landed — undo will remove whatever did",
}


def _failure_detail(row: dict | None) -> str:
    if row is None:
        return "the action was approved and failed while running"
    effects = (row.get("result") or {}).get("effects")
    found = _EFFECTS_COPY.get(effects, "its effects were not checked")
    return (
        f"the action was approved and failed while running: {found}; "
        f"its proposal is {row['status']}"
    )


def _settlement(request: Request) -> ProposalSettlement:
    return ProposalSettlement(request.app.state.pool)


def _executor(request: Request) -> ActionExecutor:
    return ActionExecutor(request.app.state.pool, request.app.state.action_registry)


@router.get("")
async def list_proposals(
    request: Request,
    auth: Auth,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = DEFAULT_PAGE,
) -> dict:
    """Everything waiting on a human in this workspace, newest first."""
    rows = await _settlement(request).pending(workspace_id=auth.workspace_id, limit=limit)
    return {
        "proposals": [_public(r) for r in rows],
        "limit": limit,
        "complete": len(rows) < limit,
    }


@router.get("/stream")
async def stream_proposals(request: Request, auth: Auth) -> StreamingResponse:
    """Approval cards, as they arrive, over SSE.

    Same single-key JSON frame protocol as `/api/chat` — `{"proposal": {...}}`
    per card, `{"heartbeat": ...}` while nothing is waiting, so a client can tell
    a quiet queue from a dead connection (the S16 lesson about absence claims,
    applied to a socket).

    It streams on the APPROVALS surface rather than inside a chat turn because
    the AgentLoop is not wired into `/api/chat` yet (STATE.md blocker 2). That
    ordering is right anyway: a proposal outlives the turn that produced it, and
    an analyst who was not in the conversation still has to be able to decide.

    Polled rather than LISTEN/NOTIFY: one indexed query per tick against
    `idx_proposals_ws_status`, and a poll that misses nothing beats a
    notification channel whose delivery guarantees would need their own probe.
    """
    settlement = _settlement(request)
    workspace_id = auth.workspace_id

    async def stream():
        seen: set[str] = set()
        # Everything already waiting, so a client that connects late is not told
        # the queue is empty.
        for row in reversed(await settlement.pending(workspace_id=workspace_id, limit=MAX_PAGE)):
            seen.add(str(row["id"]))
            yield _sse({"proposal": _public(row)})
        ticks = 0
        while ticks < STREAM_MAX_TICKS:
            if await request.is_disconnected():
                break
            await asyncio.sleep(STREAM_POLL_SECONDS)
            ticks += 1
            try:
                rows = await settlement.pending(workspace_id=workspace_id, limit=MAX_PAGE)
            except Exception:
                logger.exception("proposal stream poll failed")
                yield _sse({"error": "could not read the approval queue"})
                break
            fresh = [r for r in rows if str(r["id"]) not in seen]
            for row in reversed(fresh):
                seen.add(str(row["id"]))
                yield _sse({"proposal": _public(row)})
            if not fresh and ticks % HEARTBEAT_EVERY == 0:
                yield _sse({"heartbeat": {"waiting": len(rows)}})
        else:
            # Said out loud rather than just closing the socket: a client that
            # cannot tell "the stream ended normally" from "the stream died"
            # will either reconnect in a loop or stop watching the queue.
            yield _sse({"reconnect": {"reason": "stream lifetime reached"}})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{proposal_id}")
async def get_proposal(request: Request, auth: Auth, proposal_id: UUID) -> dict:
    row = await _settlement(request).get(
        workspace_id=auth.workspace_id, proposal_id=proposal_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="no such proposal")
    return _public(row)


@router.post("/{proposal_id}/reject")
async def reject(request: Request, auth: Auth, proposal_id: UUID) -> dict:
    result = await _settlement(request).settle(
        workspace_id=auth.workspace_id,
        proposal_id=proposal_id,
        decision="rejected",
        decided_by=auth.user_id,
    )
    if result.outcome is Settlement.NOT_FOUND:
        raise HTTPException(status_code=404, detail="no such proposal")
    if result.outcome is Settlement.ALREADY_DECIDED:
        raise HTTPException(
            status_code=409,
            detail=f"already {result.current_status} — someone else decided this one",
        )
    return {"settled": "rejected", "proposal": _public(result.proposal)}


@router.post("/{proposal_id}/abandon")
async def abandon(request: Request, auth: Auth, proposal_id: UUID) -> dict:
    """Declare a stale claim dead (TD-028a).

    The row said `executing` or `undoing` and nothing has moved it since, which
    means the process holding the claim is gone. This is the only door out, and
    it is deliberately a human's to open: nobody can know whether the handler
    ran before it died, so `abandoned` records that the answer was lost rather
    than asserting either half of it.

    A claim younger than the threshold is refused — a 409, not a 404, because
    the proposal is fine and the request was early.
    """
    result = await _settlement(request).abandon(
        workspace_id=auth.workspace_id,
        proposal_id=proposal_id,
        decided_by=auth.user_id,
    )
    if result.outcome is Settlement.NOT_FOUND:
        raise HTTPException(status_code=404, detail="no such proposal")
    if result.outcome is Settlement.ALREADY_DECIDED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"proposal is {result.current_status} with no claim outstanding for "
                f"longer than {STALE_CLAIM_SECONDS}s — nothing to abandon"
            ),
        )
    return {"settled": "abandoned", "proposal": _public(result.proposal)}


@router.post("/{proposal_id}/approve")
async def approve(request: Request, auth: Auth, proposal_id: UUID) -> dict:
    """Approve and run. The claim is what makes this exactly-once; the re-check
    is what makes it safe to have waited."""
    result = await _settlement(request).settle(
        workspace_id=auth.workspace_id,
        proposal_id=proposal_id,
        decision="approved",
        decided_by=auth.user_id,
    )
    if result.outcome is Settlement.NOT_FOUND:
        raise HTTPException(status_code=404, detail="no such proposal")
    if result.outcome is Settlement.ALREADY_DECIDED:
        raise HTTPException(
            status_code=409,
            detail=f"already {result.current_status} — someone else decided this one",
        )

    try:
        outcome = await _executor(request).execute(
            workspace_id=auth.workspace_id, proposal_id=proposal_id
        )
    except ExecutionRefused as refused:
        # The approval STANDS and the execution did not happen. Reported as 200
        # with both facts rather than an error status, because the request did
        # exactly what it should have and the analyst needs to see why nothing
        # ran — an error code here would read as "your approval failed".
        logger.info("execution refused for %s: %s", proposal_id, refused.reason)
        row = await _settlement(request).get(
            workspace_id=auth.workspace_id, proposal_id=proposal_id
        )
        return {
            "settled": "approved",
            "executed": False,
            "refused": {"reason": refused.reason, "detail": refused.detail},
            "proposal": _public(row),
        }
    except Exception:
        logger.exception("action %s failed during execution", proposal_id)
        row = await _settlement(request).get(
            workspace_id=auth.workspace_id, proposal_id=proposal_id
        )
        raise HTTPException(
            status_code=500,
            detail=_failure_detail(row),
        ) from None

    row = await _settlement(request).get(
        workspace_id=auth.workspace_id, proposal_id=proposal_id
    )
    return {
        "settled": "approved",
        "executed": True,
        "outcome": {
            "did": outcome.would,
            "affects": list(outcome.affects),
            "reversible": outcome.reversible,
        },
        "proposal": _public(row),
    }


@router.post("/{proposal_id}/undo")
async def undo(request: Request, auth: Auth, proposal_id: UUID) -> dict:
    """Put an action back: executed, incomplete or abandoned (TD-028c). Only
    what this approval added (TD-023)."""
    try:
        outcome = await _executor(request).undo(
            workspace_id=auth.workspace_id, proposal_id=proposal_id
        )
    except ExecutionRefused as refused:
        status = 404 if refused.reason == "not_found" else 409
        raise HTTPException(status_code=status, detail=refused.detail) from None
    except Exception:
        logger.exception("undo of %s failed", proposal_id)
        # A failed put-back returns the row to where it started (TD-028c) —
        # executed, incomplete or abandoned — so say which, from the row.
        row = await _settlement(request).get(
            workspace_id=auth.workspace_id, proposal_id=proposal_id
        )
        raise HTTPException(
            status_code=500,
            detail=f"the undo failed; the proposal is {row['status'] if row else 'unknown'}",
        ) from None
    row = await _settlement(request).get(
        workspace_id=auth.workspace_id, proposal_id=proposal_id
    )
    return {
        "undone": True,
        "outcome": {"did": outcome.would, "detail": outcome.detail},
        "proposal": _public(row),
    }
