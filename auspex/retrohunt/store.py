"""Retro-hunt persistence — S14.

The sweep is ONE indexed join for a whole batch of doc changes, not a query per
change (ROADMAP S14 constraint: "indexed join, never scan"). Ingest is
platform-global, so the join deliberately does not filter by workspace — it
finds every workspace's matches at once via `idx_observables_type_value` and
carries each hit's `workspace_id` into the row it writes. Tenancy is preserved
by the write and by every read path, never by the sweep.

The query plan is probed, not assumed: docs/probes/2026-08-09-s14-retrohunt-
explain.md holds the EXPLAIN against a seeded corpus.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

import asyncpg

from auspex.retrohunt.types import (
    SWEEPABLE_TYPE,
    RetroHuntHit,
    RetroHuntMatch,
    VerdictFlip,
)

logger = logging.getLogger("auspex.retrohunt")

# One sweep's worth of doc ids. A KEV first-run refresh can carry ~1,600 ids
# (S8 review), so this is a real bound, not a formality.
#
# 50 is not arbitrary — it is chosen from the measured plan crossover. The
# planner abandons the per-id index descent for a whole-table hash join once the
# batch looks expensive relative to one heap scan, and that threshold RISES with
# the table (docs/probes/2026-08-09-s14-retrohunt-explain.md, re-measured at
# S15 Step 0 in docs/probes/2026-08-09-s15-step0-review.md):
#
#   observables(cve)     index path holds up to
#        1,600           never — seq scan at every batch size
#       20,000           batch 50
#       25,000           batch 50
#      200,000           batch 1000+ (every size measured)
#
# The small-table row is not a gap in the bound, and S14's comment was wrong to
# claim the sweep is "index-driven at every scale" — measured, 1,600 observables
# is 22 pages, so the planner reads the whole table in 0.37 ms and is right to.
# What matters is that the scan never becomes the plan at a size where scanning
# hurts, and the crossover moving UP with the table is what guarantees that: a
# chunk that holds the index at 20k holds it at every size above, because the
# table only ever grows and growth makes the index relatively cheaper, never
# dearer. At 50, 1,600 ids cost 32 queries of ~0.3 ms rather than one query that
# reads every observable the platform has ever recorded.
SWEEP_CHUNK = 50

# The sweep join. The changed doc ids are the DRIVING set (unnest) and each one
# probes idx_observables_type_value — a nested loop of index descents whose cost
# scales with the batch, not with the table. The LATERAL then takes each matched
# observable's LATEST verdict through idx_verdicts_ws_obs (workspace_id,
# observable_id, created_at DESC): a descent to one row, not a sort of the trail.
#
# What keeps this plan off a table scan is SWEEP_CHUNK, not this spelling. Worth
# being exact, because the first reading of the EXPLAIN got it wrong
# (docs/probes/2026-08-09-s14-retrohunt-explain.md): the original
# `WHERE o.value = ANY($1)` with a 500-id batch planned as
# `Seq Scan on observables ... Rows Removed by Filter: 19760`, and rewriting it
# as this join did NOT fix that — measured on 25k VACUUMed rows, the join scans
# from batch 100 up while the array spelling holds the index to ~500. Both plan
# identically (indexed nested loop) at the shipped chunk of 50.
#
# The join is kept because it is the shape the work actually has — the changed
# docs are the driving relation, and it returns `d.doc_id`, the doc that caused
# each match, instead of inferring it from the matched value. The BOUND is the
# load-bearing decision; see SWEEP_CHUNK.
_SWEEP_SQL = """
SELECT o.id, o.workspace_id, o.obs_id, o.type, o.value, d.doc_id,
       v.id AS verdict_id, v.label AS verdict_label, v.created_at AS verdict_created_at
FROM unnest($1::text[]) AS d(doc_id)
JOIN observables o ON o.type = $2 AND o.value = d.doc_id
LEFT JOIN LATERAL (
    SELECT id, label, created_at
    FROM verdicts
    WHERE workspace_id = o.workspace_id AND observable_id = o.id
    ORDER BY created_at DESC
    LIMIT 1
) v ON TRUE
"""


# The re-open list, with the falsified claim derived rather than stored (S16
# Step 0 — see `list_matches`). A module constant for the same reason as
# `_SWEEP_SQL`: the plan is asserted by a test, and a query only a test can see
# is a query nobody probes.
#
# The LATERAL runs at most `limit` times — the outer LIMIT is applied to the
# match rows before it — and each run is a descent into the PARTIAL index on
# status='satisfied'. That index is what keeps this proportional to the events
# on screen instead of to every watcher the workspace has ever satisfied, which
# is the population that grows without bound.
_MATCHES_SQL = """
SELECT m.id, m.workspace_id, m.observable_id, o.obs_id, o.type, o.value,
       m.doc_id, m.feed, m.change_kind, m.verdict_label, m.status,
       m.created_at, w.claim AS falsified_claim
FROM retrohunt_matches m
JOIN observables o ON o.id = m.observable_id AND o.workspace_id = m.workspace_id
LEFT JOIN LATERAL (
    SELECT claim
    FROM watchers
    WHERE workspace_id = m.workspace_id
      AND observable_id = m.observable_id
      AND status = 'satisfied'
      AND satisfied_by = m.doc_id
      AND satisfied_change_kind = m.change_kind
    ORDER BY satisfied_at DESC, id
    LIMIT 1
) w ON TRUE
WHERE m.workspace_id = $1 AND ($2::text IS NULL OR m.status = $2)
ORDER BY m.created_at DESC, m.id
LIMIT $3
"""


def normalize_doc_ids(doc_ids: Sequence[str]) -> list[str]:
    """CVE ids are canonically upper-case and every writer already upper-cases
    (kb/seed.py, kev.py, the S4 classifier), so the join can compare exactly and
    keep using the index — `UPPER(o.value) = ANY(...)` would throw the index
    away. Normalizing here anyway makes that an invariant of this boundary
    instead of a coincidence of four call sites."""
    return sorted({d.strip().upper() for d in doc_ids if d and d.strip()})


async def sweep(
    pool: asyncpg.Pool,
    *,
    doc_ids: Sequence[str],
    feed: str,
    change_kind: str,
    observable_type: str = SWEEPABLE_TYPE,
) -> list[RetroHuntHit]:
    """Historical observables touched by these changed docs, with the verdict
    that stood when we looked. Read-only: writes nothing, decides nothing."""
    ids = normalize_doc_ids(doc_ids)
    hits: list[RetroHuntHit] = []
    for start in range(0, len(ids), SWEEP_CHUNK):
        chunk = ids[start : start + SWEEP_CHUNK]
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SWEEP_SQL, chunk, observable_type)
        hits.extend(
            RetroHuntHit(
                workspace_id=r["workspace_id"],
                observable_id=r["id"],
                obs_id=r["obs_id"],
                type=r["type"],
                value=r["value"],
                doc_id=r["doc_id"],  # the changed doc that drove this match
                feed=feed,
                change_kind=change_kind,
                verdict_id=r["verdict_id"],
                verdict_label=r["verdict_label"],
                verdict_created_at=r["verdict_created_at"],
            )
            for r in rows
        )
    return hits


async def record_matches(pool: asyncpg.Pool, hits: Sequence[RetroHuntHit]) -> int:
    """Persist re-open events. Returns rows actually written — re-emission is
    idempotent (ON CONFLICT DO NOTHING on the natural key), because the KEV
    first-run refresh re-emits every held id on a fresh volume and a re-read of
    the catalogue repeats ids. An already-known match is not news twice.

    Writes NO verdict. That is the D-017 rail, held in code: this function
    physically cannot flip a label."""
    if not hits:
        return 0
    written = 0
    async with pool.acquire() as conn, conn.transaction():
        for h in hits:
            row = await conn.fetchrow(
                """
                INSERT INTO retrohunt_matches
                    (workspace_id, observable_id, doc_id, feed, change_kind,
                     verdict_id, verdict_label)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (workspace_id, observable_id, doc_id, change_kind)
                DO NOTHING
                RETURNING id
                """,
                h.workspace_id,
                h.observable_id,
                h.doc_id,
                h.feed,
                h.change_kind,
                h.verdict_id,
                h.verdict_label,
            )
            if row is not None:
                written += 1
    return written


async def list_matches(
    pool: asyncpg.Pool,
    *,
    workspace_id: UUID,
    status: str | None = None,
    limit: int = 50,
) -> list[RetroHuntMatch]:
    """This workspace's re-open events, newest first. Workspace-scoped in the
    WHERE clause (D-008) — the sweep is global, every read is not.

    The falsified claim is DERIVED here rather than read from a column a writer
    had to remember to set (S16 Step 0 — see satisfy_documents). A watcher and
    the match it upgrades describe the same fact from two sides: same workspace,
    same observable, same doc, same change kind. Deriving that pairing at read
    time means neither writer has to run first, or at all, for the analyst to
    see which claim the intel contradicted.

    The LATERAL is ordered because the pairing is not unique over time: a later
    verdict registers its own watcher of the same kind, and a re-emitted change
    can satisfy that one too, leaving two satisfied rows with identical keys.
    Newest wins — which is what the old column did when the second satisfaction
    overwrote it, except now it is a decision instead of a write-order accident.
    """
    rows = await pool.fetch(_MATCHES_SQL, workspace_id, status, limit)
    return [
        RetroHuntMatch(
            id=r["id"],
            workspace_id=r["workspace_id"],
            observable_id=r["observable_id"],
            obs_id=r["obs_id"],
            type=r["type"],
            value=r["value"],
            doc_id=r["doc_id"],
            feed=r["feed"],
            change_kind=r["change_kind"],
            verdict_label=r["verdict_label"],
            status=r["status"],
            created_at=r["created_at"],
            # S15: set when a registered falsification condition was satisfied
            # by this same doc — the claim that just stopped being true.
            falsified_claim=r["falsified_claim"],
        )
        for r in rows
    ]


async def open_match_for(
    conn: asyncpg.Connection, *, workspace_id: UUID, observable_id: UUID
) -> asyncpg.Record | None:
    """The newest OPEN re-open event for this observable, if any — what lets a
    flip name the intel that prompted the re-look. Takes a connection, not a
    pool: the flip writer runs inside the enrichment transaction."""
    return await conn.fetchrow(
        """
        SELECT id, doc_id FROM retrohunt_matches
        WHERE workspace_id = $1 AND observable_id = $2 AND status = 'open'
        ORDER BY created_at DESC, id
        LIMIT 1
        """,
        workspace_id,
        observable_id,
    )


async def mark_reviewed(pool: asyncpg.Pool, *, workspace_id: UUID, match_id: UUID) -> bool:
    """Analyst acknowledgement. Workspace-scoped so one tenant can never close
    another's event; returns False when the id is not theirs (or already
    reviewed), which the route turns into an honest 404."""
    result = await pool.execute(
        """
        UPDATE retrohunt_matches SET status = 'reviewed'
        WHERE workspace_id = $1 AND id = $2 AND status = 'open'
        """,
        workspace_id,
        match_id,
    )
    return result.endswith(" 1")


async def list_flips(
    pool: asyncpg.Pool, *, workspace_id: UUID, limit: int = 50
) -> list[VerdictFlip]:
    """This workspace's recorded label changes, newest first."""
    rows = await pool.fetch(
        """
        SELECT f.id, f.workspace_id, f.observable_id, o.obs_id, o.value,
               f.from_label, f.to_label, f.trigger, f.match_id, f.created_at
        FROM verdict_flips f
        JOIN observables o ON o.id = f.observable_id AND o.workspace_id = f.workspace_id
        WHERE f.workspace_id = $1
        ORDER BY f.created_at DESC, f.id
        LIMIT $2
        """,
        workspace_id,
        limit,
    )
    return [
        VerdictFlip(
            id=r["id"],
            workspace_id=r["workspace_id"],
            observable_id=r["observable_id"],
            obs_id=r["obs_id"],
            value=r["value"],
            from_label=r["from_label"],
            to_label=r["to_label"],
            trigger=r["trigger"],
            match_id=r["match_id"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
