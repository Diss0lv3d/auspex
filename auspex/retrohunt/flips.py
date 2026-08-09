"""Verdict flip events — S14, the D-017 trail's first AUTOMATED writer.

`verdicts` is append-only and records what was believed at each point. What it
does not record is that belief CHANGED — you can only infer a flip by diffing
adjacent rows, and nothing was reading the table at all before S14 (it was
write-only from S5 through S13). An analyst who needs to know "the platform
changed its mind about this one, and here is why" should not have to diff a
trail, and neither should a falsification watcher.

So a label change becomes its own typed row, with provenance: which verdict rows
it moved between, what prompted the re-look, and the retro-hunt match that
triggered it when there is one.

Direction of causation matters and is preserved: a retro-hunt match NEVER
changes a label (see store.record_matches — it has no verdict write at all).
Only real provider signals do. The match merely explains why anyone looked
again, which is exactly the claim this row makes.
"""

from __future__ import annotations

import logging
from uuid import UUID

import asyncpg

from auspex.retrohunt.store import open_match_for

logger = logging.getLogger("auspex.retrohunt")

# Trigger vocabulary. Small and closed on purpose: a free-text trigger would rot
# into unqueryable prose, and "why did this change" is the question the row
# exists to answer.
TRIGGER_ENRICHMENT = "enrichment"
TRIGGER_RETROHUNT_PREFIX = "retrohunt:"


async def latest_verdict(
    conn: asyncpg.Connection, *, workspace_id: UUID, observable_id: UUID
) -> asyncpg.Record | None:
    """The current verdict for an observable — the latest row of the append-only
    trail. Must be read BEFORE the new verdict is inserted, or "previous" and
    "new" are the same row."""
    return await conn.fetchrow(
        """
        SELECT id, label FROM verdicts
        WHERE workspace_id = $1 AND observable_id = $2
        ORDER BY created_at DESC
        LIMIT 1
        """,
        workspace_id,
        observable_id,
    )


async def record_flip_if_changed(
    conn: asyncpg.Connection,
    *,
    workspace_id: UUID,
    observable_id: UUID,
    previous: asyncpg.Record | None,
    new_verdict_id: UUID,
    new_label: str,
) -> UUID | None:
    """Write a flip row if this enrichment changed the label. Returns the flip
    id, or None when there was nothing to record.

    Runs on the CALLER's connection, inside the enrichment transaction: a flip
    that survived while its verdict rolled back would be a lie about the trail.

    A first-ever verdict is not a flip — there was no previous belief to change.
    That is a distinction analysts care about (a new malicious observable is
    triage; a benign one turning malicious is news), so it is a real branch
    rather than a `from_label` of "unknown"."""
    if previous is None or previous["label"] == new_label:
        return None

    match = await open_match_for(
        conn, workspace_id=workspace_id, observable_id=observable_id
    )
    trigger = (
        f"{TRIGGER_RETROHUNT_PREFIX}{match['doc_id']}"
        if match is not None
        else TRIGGER_ENRICHMENT
    )
    # The open match is deliberately NOT auto-marked reviewed. A match asks the
    # analyst to re-examine; a flip is the strongest possible sign the ask was
    # worth making, so closing it silently would hide the event exactly when it
    # mattered most. Acknowledgement stays explicit (store.mark_reviewed), the
    # approvals-table precedent.
    flip_id = await conn.fetchval(
        """
        INSERT INTO verdict_flips
            (workspace_id, observable_id, from_label, to_label,
             from_verdict_id, to_verdict_id, trigger, match_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        workspace_id,
        observable_id,
        previous["label"],
        new_label,
        previous["id"],
        new_verdict_id,
        trigger,
        match["id"] if match is not None else None,
    )
    # Structural only — never the observable value (org data-handling rule).
    logger.info(
        "verdict flip: %s -> %s trigger=%s", previous["label"], new_label, trigger
    )
    return flip_id
