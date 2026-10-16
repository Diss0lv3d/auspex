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
    existing job comes back with `created=False`."""
    if not idempotency_key.strip():
        raise ValueError("a job needs an idempotency key")
    row = await pool.fetchrow(
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
    existing = await pool.fetchrow(
        "SELECT * FROM jobs WHERE workspace_id = $1 AND idempotency_key = $2",
        workspace_id, idempotency_key,
    )
    return Job.from_row(existing), False
