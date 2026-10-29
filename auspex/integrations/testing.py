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
from auspex.integrations.store import Integration
from auspex.jobs.queue import enqueue_on


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
    A transaction-scoped lock per integration makes "at most one in flight" hold for two
    presses at once."""
    if (reason := await _refusal(pool, integration)) is not None:
        raise CannotTest(reason)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))",
                           f"connector-test:{integration.id}")
        running = await conn.fetchval(
            "SELECT id FROM jobs WHERE integration_id = $1 AND kind = 'connector.test'"
            " AND status IN ('queued', 'claimed') ORDER BY created_at LIMIT 1",
            integration.id)
        if running is not None:
            raise CannotTest("a test of this integration is already running", running)
        job, _ = await enqueue_on(
            conn, workspace_id=integration.workspace_id, kind=CONNECTOR_TEST,
            idempotency_key=f"test:{integration.id}:{uuid.uuid4()}",
            integration_id=integration.id,
            payload={"integration_id": str(integration.id),
                     "content_hash": integration.content_hash, "command": "test",
                     "config": integration.config, "arguments": {}})
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
