"""Falsification watchers — S15, zero-LLM (Living Verdicts, Phase 3 flagship).

GET /api/watchers — what this workspace's verdicts have committed to being
wrong about, and which of those commitments have since been contradicted.

There is no endpoint to CREATE a watcher, for the same reason S14 has no "run a
hunt" endpoint: a falsification condition is something a verdict incurs when it
is written, not something an analyst remembers to attach. Hand-registered
watchers would make coverage a function of who was paying attention.

There is no endpoint to acknowledge one either. A satisfied watcher is
acknowledged through the re-open event it upgraded (`POST
/api/retrohunt/matches/{id}/ack`) — one event, one acknowledgement. A second
ack surface for the same fact is how two half-read inboxes get created.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from auspex.auth import AuthContext, resolve_user
from auspex.watchers import list_watchers
from auspex.watchers.types import (
    CHECKED_ON_ENRICHMENT,
    CHECKED_ON_INGEST,
    WatcherKind,
)

logger = logging.getLogger("auspex.watchers")

router = APIRouter(prefix="/api/watchers", tags=["watchers"])

Auth = Annotated[AuthContext, Depends(resolve_user)]

MAX_PAGE = 200
DEFAULT_PAGE = 50

# What actually evaluates each kind, stated in the payload rather than in docs
# no client reads. "Registered" is a promise; naming the checker is the evidence
# that something keeps it.
_CHECKED_BY = {
    **{k.value: "ingest" for k in CHECKED_ON_INGEST},
    **{k.value: "enrichment" for k in CHECKED_ON_ENRICHMENT},
}


@router.get("")
async def get_watchers(
    request: Request,
    auth: Auth,
    status: Annotated[
        str | None, Query(pattern="^(open|satisfied|superseded|all)$")
    ] = "open",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = DEFAULT_PAGE,
) -> dict:
    """Registered falsification conditions, newest first. Defaults to `open` —
    the claims still standing."""
    watchers = await list_watchers(
        request.app.state.pool,
        workspace_id=auth.workspace_id,
        status=None if status == "all" else status,
        limit=limit,
    )
    return {
        "status_filter": status,
        "count": len(watchers),
        "limit": limit,
        "watchers": [
            {
                "watcher_id": str(w.id),
                "observable": {"obs_id": w.obs_id, "value": w.value},
                "verdict": {"id": str(w.verdict_id), "label": w.verdict_label},
                "kind": w.kind,
                # The sentence the VERDICT asserts — what would become false.
                "claim": w.claim,
                "checked_by": _CHECKED_BY.get(w.kind),
                "status": w.status,
                "created_at": w.created_at.isoformat(),
                "satisfied_at": w.satisfied_at.isoformat() if w.satisfied_at else None,
                "satisfied_by": w.satisfied_by,
            }
            for w in watchers
        ],
        # Naming the vocabulary is the difference between "this verdict has no
        # open falsifiers" and "we do not check anything of that kind".
        "kinds": sorted(k.value for k in WatcherKind),
        # Repeated in the payload because it is the rail most likely to be
        # assumed away by a client author: a fired watcher is still only a
        # reason to look (D-017, D-020).
        "note": (
            "A satisfied watcher is a reason to re-examine the verdict, never a "
            "re-classification: no verdict is changed by a watcher firing. The "
            "re-open event it upgraded is acknowledged at "
            "POST /api/retrohunt/matches/{id}/ack."
        ),
    }
