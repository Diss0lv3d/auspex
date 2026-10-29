"""Test connection (S33): one `connector.test` job for an integration's agent, and what
the admin reads back. Two failures, told apart (spec, builder check 2):

- `failed`: the job ran and the connector said no (`{"ok": false, "detail": …}`);
- `error`: the job could not run (no secret on the agent, a hash mismatch, a timeout, an
  invalid result, cancelled), with the reason in words.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from uuid import UUID

from auspex.connectors.kinds import CONNECTOR_TEST
from auspex.edge_api.agents import health
from auspex.integrations.store import Integration, _integration
from auspex.jobs.queue import enqueue_on
from auspex.migrations import MIGRATION_LOCK


class CannotTest(Exception):
    def __init__(self, reason: str, job_id: UUID | None = None) -> None:
        super().__init__(reason)
        self.reason, self.job_id = reason, job_id


async def _refusal(pool, integration: Integration) -> str | None:
    if not integration.enabled:
        return "this integration is disabled"
    agent = await pool.fetchrow(
        "SELECT name, revoked_at, last_heartbeat_at FROM edge_agents WHERE id = $1"
        " AND workspace_id = $2", integration.agent_id, integration.workspace_id)
    if agent is None or agent["revoked_at"] is not None:
        return "its Edge Agent was revoked; choose another agent"
    state = health(agent["last_heartbeat_at"], datetime.now(UTC))
    if state == "never":
        return f"its Edge Agent {agent['name']!r} has never connected"
    if state == "offline":
        return f"its Edge Agent {agent['name']!r} is offline"
    return None


async def press(pool, integration: Integration) -> UUID:
    """Queue one test, or CannotTest (with the in-flight job's id when one is running).

    One transaction, its locks in this order:
    1. the migration's lock, shared, before anything touches `jobs`, as `enqueue`
       takes it, so a booting replica's DDL never meets it in a lock cycle (fresh
       review of PR #51, I1);
    2. a lock per integration, so two presses at once queue one test;
    3. the integration's row, re-read `FOR SHARE`: the job is built from the row as it
       is now, and an edit (`store.update` writes the row) waits for this press, then
       cancels what it queued (fresh review of PR #51, I2).
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock_shared($1)", MIGRATION_LOCK)
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))",
                           f"connector-test:{integration.id}")
        row = await conn.fetchrow(
            "SELECT id, workspace_id, name, prefix, connector_id, content_hash, config,"
            " agent_id, created_at, disabled_at FROM integrations"
            " WHERE id = $1 AND workspace_id = $2 FOR SHARE",
            integration.id, integration.workspace_id)
        if row is None:
            raise CannotTest("this integration no longer exists")
        current = _integration(row)
        if (reason := await _refusal(conn, current)) is not None:
            raise CannotTest(reason)
        running = await conn.fetchval(
            "SELECT id FROM jobs WHERE integration_id = $1 AND kind = 'connector.test'"
            " AND status IN ('queued', 'claimed') ORDER BY created_at LIMIT 1",
            current.id)
        if running is not None:
            raise CannotTest("a test of this integration is already running", running)
        job, _ = await enqueue_on(
            conn, workspace_id=current.workspace_id, kind=CONNECTOR_TEST,
            idempotency_key=f"test:{current.id}:{uuid.uuid4()}",
            integration_id=current.id,
            payload={"integration_id": str(current.id),
                     "content_hash": current.content_hash, "command": "test",
                     "config": current.config, "arguments": {}})
    return job.id


async def state(pool, integration: Integration, job_id: UUID) -> dict | None:
    row = await pool.fetchrow(
        "SELECT status, result, last_error FROM jobs WHERE id = $1 AND workspace_id = $2"
        " AND integration_id = $3 AND kind = 'connector.test'",
        job_id, integration.workspace_id, integration.id)
    if row is None:
        return None
    if row["status"] == "queued":
        return {"state": "queued", "detail": "waiting for the Edge Agent"}
    if row["status"] == "claimed":
        return {"state": "running", "detail": "the Edge Agent is running the test"}
    if row["status"] == "done":
        result = row["result"]
        result = json.loads(result) if isinstance(result, str) else result
        return {"state": "ok" if result.get("ok") else "failed",
                "detail": str(result.get("detail", ""))}
    return {"state": "error", "detail": row["last_error"] or "the test could not run"}
