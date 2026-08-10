"""Watcher persistence — S15.

Two checkers, split by where the falsifying evidence actually appears:

* `check_documents` runs on ingest, against a batch of changed docs. Same
  constraint as the S14 sweep (ROADMAP: "indexed join, never a scan per
  change") and the same chunk bound, for the same measured reason —
  docs/probes/2026-08-09-s15-watchers-explain.md holds the EXPLAIN.
* `check_escalation` runs inside the enrichment transaction, where labels are
  written, because that is the only place a provider disagreement exists.

Registration is deliberately not a checker's job: watchers are written by
`register` from the caller that wrote the verdict, in the SAME transaction. A
verdict that committed without its falsification conditions would be a claim
with no way to be wrong, which is the thing this feature exists to prevent.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from uuid import UUID

import asyncpg

from auspex.enrich.types import SEVERITY, VerdictLabel
from auspex.retrohunt.store import SWEEP_CHUNK, normalize_doc_ids
from auspex.retrohunt.types import SWEEPABLE_TYPE
from auspex.watchers.types import (
    FalsificationCondition,
    Watcher,
    WatcherHit,
    WatcherKind,
)

logger = logging.getLogger("auspex.watchers")

# Doc ids → observables → open watchers of one kind. The changed docs are the
# driving set (unnest), each probing idx_observables_type_value exactly as the
# S14 sweep does, and each matched observable then probes
# idx_watchers_open_obs_kind — a partial index, so the second leg is
# proportional to the watchers still WATCHING, not to every watcher ever
# registered.
#
# Chunked at SWEEP_CHUNK for the S14 reason, which was measured rather than
# assumed: an unchunked `= ANY($1)` over a large batch loses the index to a
# whole-table scan, and the crossover rises with the table, so a chunk that
# holds at the smallest interesting size holds forever.
_CHECK_SQL = """
SELECT w.id, w.workspace_id, w.observable_id, w.kind, w.claim, d.doc_id
FROM unnest($1::text[]) AS d(doc_id)
JOIN observables o ON o.type = $2 AND o.value = d.doc_id
JOIN watchers w ON w.observable_id = o.id
               AND w.workspace_id = o.workspace_id
               AND w.kind = $3
               AND w.status = 'open'
"""


async def register(
    conn: asyncpg.Connection,
    *,
    workspace_id: UUID,
    observable_id: UUID,
    verdict_id: UUID,
    conditions: Sequence[FalsificationCondition],
) -> int:
    """Attach this verdict's falsification conditions, and retire the previous
    verdict's. Runs on the CALLER's connection, inside the enrichment
    transaction — watchers that outlived a rolled-back verdict would be watching
    on behalf of a claim nobody made.

    Superseding is scoped to OPEN watchers: a satisfied one is a historical
    fact ("this claim was contradicted on the 9th") and rewriting it would
    erase the event the analyst still owes a look."""
    await conn.execute(
        """
        UPDATE watchers SET status = 'superseded'
        WHERE workspace_id = $1 AND observable_id = $2 AND status = 'open'
              AND verdict_id <> $3
        """,
        workspace_id,
        observable_id,
        verdict_id,
    )
    written = 0
    for c in conditions:
        # ON CONFLICT on (verdict_id, kind): re-persisting the same verdict must
        # not duplicate its claims.
        row = await conn.fetchrow(
            """
            INSERT INTO watchers
                (workspace_id, observable_id, verdict_id, kind, claim, params)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (verdict_id, kind) DO NOTHING
            RETURNING id
            """,
            workspace_id,
            observable_id,
            verdict_id,
            c.kind.value,
            c.claim,
            json.dumps(c.params),
        )
        if row is not None:
            written += 1
    return written


async def check_documents(
    pool: asyncpg.Pool,
    *,
    doc_ids: Sequence[str],
    kind: WatcherKind,
    observable_type: str = SWEEPABLE_TYPE,
) -> list[WatcherHit]:
    """Open watchers of `kind` whose condition these changed docs satisfy.
    Read-only: finds, decides nothing, writes nothing."""
    ids = normalize_doc_ids(doc_ids)
    hits: list[WatcherHit] = []
    for start in range(0, len(ids), SWEEP_CHUNK):
        chunk = ids[start : start + SWEEP_CHUNK]
        async with pool.acquire() as conn:
            rows = await conn.fetch(_CHECK_SQL, chunk, observable_type, kind.value)
        hits.extend(
            WatcherHit(
                watcher_id=r["id"],
                workspace_id=r["workspace_id"],
                observable_id=r["observable_id"],
                kind=r["kind"],
                claim=r["claim"],
                doc_id=r["doc_id"],
            )
            for r in rows
        )
    return hits


async def satisfy_documents(
    pool: asyncpg.Pool, hits: Sequence[WatcherHit], *, change_kind: str
) -> int:
    """Mark watchers satisfied, recording WHICH change contradicted the claim.
    Returns watchers actually moved — re-emission of the same DocChange is not
    news twice, so the UPDATE is guarded on status.

    It does NOT reach into `retrohunt_matches` to link the S14 re-open event,
    which is what S15 did. That write could only land if the retro-hunt sink had
    already recorded the match, so the analyst-facing `falsifies` existed by
    virtue of the order `FanoutSink` happened to be constructed in. Executed at
    S16 Step 0: reverse the sinks — or let the retro-hunt sink fail that one
    batch, which it is designed to survive — and the link vanished with no error
    anywhere, permanently, because the next cycle finds the watcher already
    satisfied and never retries. Storing `satisfied_change_kind` instead makes
    the pairing a property of this row that `list_matches` derives from either
    side, in any order, including when the two rows are written cycles apart.

    Writes NO verdict, exactly as `record_matches` writes none: a watcher firing
    is the platform's own prediction coming true, which is the moment it would
    feel safest to skip the analyst, so the rail is held in code here too."""
    if not hits:
        return 0
    moved = 0
    async with pool.acquire() as conn, conn.transaction():
        for h in hits:
            row = await conn.fetchrow(
                """
                UPDATE watchers
                SET status = 'satisfied',
                    satisfied_at = clock_timestamp(),
                    satisfied_by = $2,
                    satisfied_change_kind = $3
                WHERE id = $1 AND status = 'open'
                RETURNING id
                """,
                h.watcher_id,
                h.doc_id,
                change_kind,
            )
            if row is not None:
                moved += 1
    return moved


async def check_escalation(
    conn: asyncpg.Connection,
    *,
    workspace_id: UUID,
    observable_id: UUID,
    new_label: str,
    satisfied_by: str,
) -> list[UUID]:
    """Satisfy the PROVIDER_ESCALATION watchers this new label contradicts.

    Runs on the caller's connection inside the enrichment transaction, and MUST
    run before `register` retires the previous verdict's watchers — the claim
    being falsified belongs to the verdict this enrichment is replacing, and
    once it is superseded there is nothing left to contradict. `enrich/store.py`
    holds that order.

    The comparison is SEVERITY, not inequality. A watcher claimed "no connected
    source rates this worse than X"; `suspicious → benign` is a de-escalation
    and falsifies nothing it said. Judging in Python rather than SQL because
    SEVERITY is the enrichment module's ordering — duplicating it as a CASE
    expression is how the two drift apart."""
    rows = await conn.fetch(
        """
        SELECT id, params FROM watchers
        WHERE workspace_id = $1 AND observable_id = $2 AND kind = $3
              AND status = 'open'
        """,
        workspace_id,
        observable_id,
        WatcherKind.PROVIDER_ESCALATION.value,
    )
    new_severity = SEVERITY[VerdictLabel(new_label)]
    contradicted = [
        r["id"]
        for r in rows
        if new_severity > SEVERITY[VerdictLabel(json.loads(r["params"])["label"])]
    ]
    if not contradicted:
        return []
    await conn.execute(
        """
        UPDATE watchers
        SET status = 'satisfied',
            satisfied_at = clock_timestamp(),
            satisfied_by = $2
        WHERE id = ANY($1::uuid[]) AND status = 'open'
        """,
        contradicted,
        satisfied_by,
    )
    # Structural only — never the observable value (org data-handling rule).
    logger.info(
        "falsification watcher satisfied: kind=%s label=%s n=%d",
        WatcherKind.PROVIDER_ESCALATION.value,
        new_label,
        len(contradicted),
    )
    return contradicted


async def list_watchers(
    pool: asyncpg.Pool,
    *,
    workspace_id: UUID,
    status: str | None = None,
    limit: int = 50,
) -> list[Watcher]:
    """This workspace's registered falsification conditions, newest first.
    Workspace-scoped in the WHERE clause (D-008)."""
    rows = await pool.fetch(
        """
        SELECT w.id, w.workspace_id, w.observable_id, o.obs_id, o.value,
               w.verdict_id, v.label AS verdict_label, w.kind, w.claim, w.params,
               w.status, w.created_at, w.satisfied_at, w.satisfied_by
        FROM watchers w
        JOIN observables o ON o.id = w.observable_id AND o.workspace_id = w.workspace_id
        JOIN verdicts v ON v.id = w.verdict_id AND v.workspace_id = w.workspace_id
        WHERE w.workspace_id = $1 AND ($2::text IS NULL OR w.status = $2)
        ORDER BY w.created_at DESC, w.id
        LIMIT $3
        """,
        workspace_id,
        status,
        limit,
    )
    return [
        Watcher(
            id=r["id"],
            workspace_id=r["workspace_id"],
            observable_id=r["observable_id"],
            obs_id=r["obs_id"],
            value=r["value"],
            verdict_id=r["verdict_id"],
            verdict_label=r["verdict_label"],
            kind=r["kind"],
            claim=r["claim"],
            params=json.loads(r["params"]),
            status=r["status"],
            created_at=r["created_at"],
            satisfied_at=r["satisfied_at"],
            satisfied_by=r["satisfied_by"],
        )
        for r in rows
    ]
