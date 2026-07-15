"""Permission gate + proposal store tests (S3 step 3, D-014).

Gate logic is pure/offline; the PgProposalStore round-trip runs against the live
dev DB (reality over memory) and cleans up its own workspace.
"""

import json

from auspex.agent.permissions import (
    PermissionOutcome,
    PgProposalStore,
    gate,
)
from auspex.agent.registry import ToolLevel
from auspex.db import create_pool


def test_read_is_allowed():
    decision = gate(ToolLevel.READ)
    assert decision.outcome is PermissionOutcome.ALLOW


def test_write_is_proposed():
    assert gate(ToolLevel.WRITE).outcome is PermissionOutcome.PROPOSE


def test_destructive_is_proposed():
    assert gate(ToolLevel.DESTRUCTIVE).outcome is PermissionOutcome.PROPOSE


def test_unknown_level_fails_safe_to_propose():
    """Anything not unambiguously READ must never auto-execute (D-014)."""
    assert gate(None).outcome is PermissionOutcome.PROPOSE


async def test_pg_proposal_store_round_trips(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    try:
        workspace_id = await pool.fetchval(
            "INSERT INTO workspaces (name) VALUES ('t-propstore') RETURNING id"
        )
        store = PgProposalStore(pool)
        proposal_id = await store.create(
            workspace_id=workspace_id,
            tool_name="create_ticket",
            tool_level="write",
            tool_input={"title": "Malicious IP investigation", "severity": "high"},
        )
        row = await pool.fetchrow("SELECT * FROM proposals WHERE id = $1::uuid", proposal_id)
        assert row["tool_name"] == "create_ticket"
        assert row["tool_level"] == "write"
        assert row["status"] == "pending_approval"  # nothing executed — just filed
        assert json.loads(row["tool_input"])["severity"] == "high"
        assert row["result"] is None  # no execution result exists for a pending proposal
    finally:
        await pool.execute("DELETE FROM workspaces WHERE name = 't-propstore'")
        await pool.close()
