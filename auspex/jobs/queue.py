"""The jobs queue (D-065; docs/superpowers/specs/2026-10-16-s31-jobs-design.md).

Our own Postgres table, claimed with `FOR UPDATE SKIP LOCKED`, in settlement's
style: every transition is one conditional UPDATE, and a claim is a token. A job
belongs to one workspace (D-008). What a job does is code: a `JobKind` declares
its handler, lease and attempts beside the handler.

A handler must be idempotent on the job's `idempotency_key`. A lease that
expires means the job can run again (that is what a lease is for), and the key
is how the second run knows it is the second.

Every query here is literal text, never assembled from Python strings.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from auspex.migrations import MIGRATION_LOCK

JobHandler = Callable[[asyncpg.Pool, "Job"], Awaitable[dict]]


@dataclass(frozen=True)
class JobKind:
    """One kind of job, declared in code beside its handler."""

    name: str
    handler: JobHandler
    lease_seconds: int = 60
    max_attempts: int = 5

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a job kind needs a name")
        if self.lease_seconds < 1 or self.max_attempts < 1:
            raise ValueError(f"{self.name}: lease_seconds and max_attempts must be at least 1")


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


@dataclass(frozen=True)
class Job:
    id: UUID
    workspace_id: UUID
    kind: str
    integration_id: UUID | None
    payload: dict
    idempotency_key: str
    status: str
    attempts: int
    max_attempts: int
    lease_seconds: int
    claim_token: UUID | None
    claimed_by: str | None
    result: dict | None
    last_error: str | None

    @classmethod
    def from_row(cls, row: asyncpg.Record) -> Job:
        return cls(
            id=row["id"],
            workspace_id=row["workspace_id"],
            kind=row["kind"],
            integration_id=row["integration_id"],
            payload=_json(row["payload"]) or {},
            idempotency_key=row["idempotency_key"],
            status=row["status"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            lease_seconds=row["lease_seconds"],
            claim_token=row["claim_token"],
            claimed_by=row["claimed_by"],
            result=_json(row["result"]),
            last_error=row["last_error"],
        )


async def enqueue(
    pool: asyncpg.Pool,
    *,
    workspace_id: UUID,
    kind: JobKind,
    idempotency_key: str,
    payload: dict | None = None,
    integration_id: UUID | None = None,
    run_after: datetime | None = None,
) -> tuple[Job, bool]:
    """A job, once per (workspace, key). When the key is already taken, by a job
    in any status, `done` and `dead` included, nothing is written and the
    existing job comes back with `created=False`. It takes the migration's
    advisory lock shared first, so a booting replica's schema DDL (which locks
    `workspaces`, then `jobs`) is never caught in a lock cycle with this insert."""
    async with pool.acquire() as conn, conn.transaction():
        return await enqueue_on(conn, workspace_id=workspace_id, kind=kind,
                                idempotency_key=idempotency_key, payload=payload,
                                integration_id=integration_id, run_after=run_after)


async def enqueue_on(
    conn: asyncpg.Connection,
    *,
    workspace_id: UUID,
    kind: JobKind,
    idempotency_key: str,
    payload: dict | None = None,
    integration_id: UUID | None = None,
    run_after: datetime | None = None,
) -> tuple[Job, bool]:
    """`enqueue`, on a connection whose transaction the caller holds: a caller that
    checks and enqueues under one lock needs no second connection (PR #51 review s1)."""
    if not idempotency_key.strip():
        raise ValueError("a job needs an idempotency key")
    await conn.execute("SELECT pg_advisory_xact_lock_shared($1)", MIGRATION_LOCK)
    row = await conn.fetchrow(
        """
        INSERT INTO jobs (workspace_id, kind, integration_id, payload, idempotency_key,
                          max_attempts, lease_seconds, run_after)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, COALESCE($8, now()))
        ON CONFLICT (workspace_id, idempotency_key) DO NOTHING
        RETURNING *
        """,
        workspace_id, kind.name, integration_id, json.dumps(payload or {}),
        idempotency_key, kind.max_attempts, kind.lease_seconds, run_after,
    )
    if row is not None:
        return Job.from_row(row), True
    existing = await conn.fetchrow(
        "SELECT * FROM jobs WHERE workspace_id = $1 AND idempotency_key = $2",
        workspace_id, idempotency_key,
    )
    return Job.from_row(existing), False


# Backoff after a failure (Burhan's call, S31): 30 s, doubling, capped at 15 min.
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 900
# A handler's error is stored for a human, not kept whole: a 1 MB message is a
# row nobody can read and a column nobody should have to page through.
MAX_ERROR_CHARS = 2000


def _clean_text(text: str) -> str:
    """Postgres text and jsonb refuse a NUL and a lone surrogate. The answer
    writes must never raise on what a handler said, so a NUL becomes U+FFFD and
    a lone surrogate becomes `?`."""
    return text.replace("\x00", "\ufffd").encode("utf-8", "replace").decode("utf-8")


def _clean_json(value):
    """`_clean_text` on every string in a JSON value, dict keys included."""
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, dict):
        return {_clean_text(k) if isinstance(k, str) else k: _clean_json(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_json(v) for v in value]
    return value


class JobLost(RuntimeError):
    """The claimer no longer holds the job: its lease was re-claimed, the job
    went dead, or it was already finished. Its answer is refused."""


@dataclass(frozen=True)
class ClaimScope:
    """What one claimer may take (§1). `kinds` is what it can run. A
    `workspace_ids` of None is every workspace (the in-app worker); S33's Edge
    Agent passes its one. An `integration_ids` of None means jobs bound to NO
    integration; a set means only those integrations' jobs, so nobody claims an
    integration's job without naming the integration."""

    kinds: frozenset[str]
    workspace_ids: frozenset[UUID] | None = None
    integration_ids: frozenset[UUID] | None = None

    def __post_init__(self) -> None:
        if not self.kinds:
            raise ValueError("a claim names the kinds it can run")


def _ids(values: frozenset[UUID] | None) -> list[UUID] | None:
    return None if values is None else list(values)


async def claim(pool: asyncpg.Pool, scope: ClaimScope, *, claimer: str) -> Job | None:
    """The next ready job in `scope`, claimed: a fresh token, one more attempt,
    a lease. Ready means queued and due, or claimed with a lease that expired
    and attempts left. One transaction: first the expired leases with no
    attempts left go `dead`, then one statement picks and claims, skipping rows
    another claimer holds locked. Candidates are ordered by whose turn it is: the
    workspace served longest ago first (never-served first), then by due time. A
    one-pass "oldest job first" would let a client that bulk-enqueued earlier
    starve every other until it drained (§1). The transaction takes the
    migration's advisory lock shared first, so it waits out a booting replica's
    schema DDL instead of deadlocking with it (jobs rows, then `workspaces`)."""
    kinds, workspaces, integrations = (
        list(scope.kinds), _ids(scope.workspace_ids), _ids(scope.integration_ids))
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock_shared($1)", MIGRATION_LOCK)
        await conn.execute(
            """
            UPDATE jobs
               SET status = 'dead', last_error = 'lease expired', claim_token = NULL,
                   claimed_by = NULL, lease_expires_at = NULL, finished_at = now()
             WHERE status = 'claimed' AND lease_expires_at < now()
               AND attempts >= max_attempts
               AND kind = ANY($1::text[])
               AND ($2::uuid[] IS NULL OR workspace_id = ANY($2::uuid[]))
               AND CASE WHEN $3::uuid[] IS NULL THEN integration_id IS NULL
                        ELSE integration_id = ANY($3::uuid[]) END
            """,
            kinds, workspaces, integrations,
        )
        row = await conn.fetchrow(
            """
            WITH pick AS (
                SELECT j.id FROM jobs j
                  LEFT JOIN job_turns t ON t.workspace_id = j.workspace_id
                 WHERE j.kind = ANY($1::text[])
                   AND ($2::uuid[] IS NULL OR j.workspace_id = ANY($2::uuid[]))
                   AND CASE WHEN $3::uuid[] IS NULL THEN j.integration_id IS NULL
                            ELSE j.integration_id = ANY($3::uuid[]) END
                   AND ((j.status = 'queued' AND j.run_after <= now())
                        OR (j.status = 'claimed' AND j.lease_expires_at < now()
                            AND j.attempts < j.max_attempts))
                 ORDER BY t.last_served_at ASC NULLS FIRST, j.run_after, j.id
                 LIMIT 1
                 FOR UPDATE OF j SKIP LOCKED
            )
            UPDATE jobs
               SET status = 'claimed', claim_token = gen_random_uuid(), claimed_by = $4,
                   attempts = jobs.attempts + 1,
                   lease_expires_at = now() + make_interval(secs => jobs.lease_seconds)
              FROM pick
             WHERE jobs.id = pick.id
            RETURNING jobs.*
            """,
            kinds, workspaces, integrations, claimer,
        )
        if row is not None:
            await conn.execute(
                """
                INSERT INTO job_turns (workspace_id, last_served_at)
                VALUES ($1, clock_timestamp())
                ON CONFLICT (workspace_id) DO UPDATE SET last_served_at = EXCLUDED.last_served_at
                """,
                row["workspace_id"],
            )
    return Job.from_row(row) if row is not None else None


async def extend_leases(pool: asyncpg.Pool, *, claimer: str, job_ids: list[UUID]) -> int:
    """Renew the leases of `job_ids` that `claimer` still holds (TD-064): an Edge Agent's
    heartbeat names the jobs it is running, so a long command's job is not reclaimed.
    Only the named jobs move: renewing everything the claimer held kept a job whose
    answer was lost "running" for ever (PR #51 review #1). Returns how many."""
    if not job_ids:
        return 0
    return await pool.fetchval(
        """
        WITH moved AS (
            UPDATE jobs SET lease_expires_at = now() + make_interval(secs => lease_seconds)
             WHERE status = 'claimed' AND claimed_by = $1 AND id = ANY($2::uuid[])
               AND lease_expires_at >= now()
            RETURNING 1
        ) SELECT count(*) FROM moved
        """,
        claimer, job_ids,
    )


async def complete(pool: asyncpg.Pool, job_id: UUID, token: UUID, result: dict) -> None:
    """Record a job's answer, only for the claim that still holds it."""
    done = await pool.fetchval(
        """
        UPDATE jobs
           SET status = 'done', result = $3::jsonb, claim_token = NULL, claimed_by = NULL,
               lease_expires_at = NULL, finished_at = now()
         WHERE id = $1 AND status = 'claimed' AND claim_token = $2
        RETURNING id
        """,
        job_id, token, json.dumps(_clean_json(result)),
    )
    if done is None:
        raise JobLost(f"job {job_id} is no longer held by this claim")


async def fail(pool: asyncpg.Pool, job_id: UUID, token: UUID, error: str, *,
               permanent: bool = False) -> str:
    """A failed attempt, only for the claim that still holds it. With attempts
    left the job is queued again after the backoff; with none it is `dead`; a
    permanent failure is `failed` and never retried. Returns the new status."""
    status = await pool.fetchval(
        """
        UPDATE jobs
           SET status = CASE WHEN $4 THEN 'failed'
                             WHEN attempts >= max_attempts THEN 'dead'
                             ELSE 'queued' END,
               run_after = CASE WHEN $4 OR attempts >= max_attempts THEN run_after
                                ELSE now() + make_interval(secs => LEAST(
                                    $5::double precision * power(2, attempts - 1),
                                    $6::double precision)) END,
               finished_at = CASE WHEN $4 OR attempts >= max_attempts THEN now() END,
               last_error = $3, claim_token = NULL, claimed_by = NULL,
               lease_expires_at = NULL
         WHERE id = $1 AND status = 'claimed' AND claim_token = $2
        RETURNING status
        """,
        job_id, token, _clean_text(error)[:MAX_ERROR_CHARS], permanent,
        float(BACKOFF_BASE_SECONDS), float(BACKOFF_CAP_SECONDS),
    )
    if status is None:
        raise JobLost(f"job {job_id} is no longer held by this claim")
    return status
