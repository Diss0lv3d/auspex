"""Schema v0 invariants, asserted against the live database (reality over memory)."""

import asyncpg

from auspex.db import create_pool
from auspex.migrations import run_migrations

EXPECTED_TABLES = {
    "workspaces",
    "users",
    "api_keys",
    "chat_sessions",
    "messages",
    "llm_endpoint_scorecards",
    "proposals",
    "observables",
    "verdicts",
    "ingest_state",
    "investigations",
    "hypotheses",
    "ach_evidence",
    "retrohunt_matches",
    "verdict_flips",
}

# D-008: workspace_id on EVERY table. `workspaces` is the sole exception —
# its primary key IS the workspace id.
WORKSPACE_ID_EXEMPT = {"workspaces"}


async def _connect(settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url)


async def test_schema_v0_tables_exist(client, settings):
    conn = await _connect(settings)
    try:
        rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = {row["tablename"] for row in rows}
        assert EXPECTED_TABLES <= tables, f"missing: {EXPECTED_TABLES - tables}"
    finally:
        await conn.close()


async def test_workspace_id_on_every_table(client, settings):
    """D-008 enforced: every public table carries workspace_id (except workspaces itself)."""
    conn = await _connect(settings)
    try:
        rows = await conn.fetch(
            """
            SELECT t.tablename
            FROM pg_tables t
            WHERE t.schemaname = 'public'
              AND NOT EXISTS (
                  SELECT 1 FROM information_schema.columns c
                  WHERE c.table_schema = 'public'
                    AND c.table_name = t.tablename
                    AND c.column_name = 'workspace_id'
              )
            """
        )
        violators = {row["tablename"] for row in rows} - WORKSPACE_ID_EXEMPT
        assert not violators, f"tables missing workspace_id: {violators}"
    finally:
        await conn.close()


async def test_migration_is_idempotent(client, settings):
    """Running the startup migration again (twice) must be a no-op, not an error."""
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    try:
        await run_migrations(pool)
        await run_migrations(pool)
    finally:
        await pool.close()


async def test_llm_scorecard_agent_mode_is_constrained(client, settings):
    """S2: agent_mode must be one of the three runtime modes; scorecard is jsonb."""
    conn = await _connect(settings)
    try:
        workspace_id = await conn.fetchval(
            "INSERT INTO workspaces (name) VALUES ('t-scorecard') RETURNING id"
        )
        # valid row round-trips
        await conn.execute(
            "INSERT INTO llm_endpoint_scorecards"
            " (workspace_id, endpoint_fingerprint, base_url, model, agent_mode, scorecard)"
            " VALUES ($1, 'fp-test', 'http://example.test', 'test-model',"
            " 'native_tools', '{\"ok\": true}')",
            workspace_id,
        )
        try:
            await conn.execute(
                "INSERT INTO llm_endpoint_scorecards"
                " (workspace_id, endpoint_fingerprint, base_url, model, agent_mode, scorecard)"
                " VALUES ($1, 'fp-test', 'http://example.test', 'test-model', 'vibes_only', '{}')",
                workspace_id,
            )
            raise AssertionError("CHECK constraint on agent_mode did not fire")
        except asyncpg.CheckViolationError:
            pass
    finally:
        await conn.execute("DELETE FROM workspaces WHERE name = 't-scorecard'")
        await conn.close()


async def test_proposals_check_constraints(client, settings):
    """S3/D-014: proposals.tool_level ∈ {write,destructive} and status is a
    closed set. A read-level action must never reach this table — the gate
    auto-executes reads, so 'read' is intentionally not a legal tool_level."""
    conn = await _connect(settings)
    try:
        workspace_id = await conn.fetchval(
            "INSERT INTO workspaces (name) VALUES ('t-proposals') RETURNING id"
        )
        # a valid write proposal round-trips at the default status
        pid = await conn.fetchval(
            "INSERT INTO proposals (workspace_id, tool_name, tool_level, tool_input)"
            " VALUES ($1, 'create_ticket', 'write', '{\"title\": \"x\"}') RETURNING id",
            workspace_id,
        )
        status = await conn.fetchval("SELECT status FROM proposals WHERE id = $1", pid)
        assert status == "pending_approval"

        # 'read' is not a legal proposal level (reads auto-execute, never propose)
        try:
            await conn.execute(
                "INSERT INTO proposals (workspace_id, tool_name, tool_level, tool_input)"
                " VALUES ($1, 'lookup_ip', 'read', '{}')",
                workspace_id,
            )
            raise AssertionError("CHECK on proposals.tool_level did not fire for 'read'")
        except asyncpg.CheckViolationError:
            pass

        # bogus status rejected
        try:
            await conn.execute(
                "INSERT INTO proposals (workspace_id, tool_name, tool_level, tool_input, status)"
                " VALUES ($1, 'create_ticket', 'write', '{}', 'totally_done')",
                workspace_id,
            )
            raise AssertionError("CHECK on proposals.status did not fire")
        except asyncpg.CheckViolationError:
            pass
    finally:
        await conn.execute("DELETE FROM workspaces WHERE name = 't-proposals'")
        await conn.close()


async def test_verdict_decay_fields_are_constrained(client, settings):
    """S5/D-017: label is a closed set; confidence/floor live in [0,1] with
    floor <= confidence_at_write; half_life_days must be positive."""
    conn = await _connect(settings)
    try:
        workspace_id = await conn.fetchval(
            "INSERT INTO workspaces (name) VALUES ('t-verdicts') RETURNING id"
        )
        observable_id = await conn.fetchval(
            "INSERT INTO observables (workspace_id, obs_id, type, value)"
            " VALUES ($1, 'ipv4-deadbeef', 'ipv4', '203.0.113.7') RETURNING id",
            workspace_id,
        )

        async def insert_verdict(**overrides):
            row = {
                "label": "malicious",
                "confidence": 0.9,
                "half_life": 14.0,
                "floor": 0.0,
            } | overrides
            await conn.execute(
                "INSERT INTO verdicts (workspace_id, observable_id, label,"
                " confidence_at_write, half_life_days, floor, source)"
                " VALUES ($1, $2, $3, $4, $5, $6, 'enrichment:test')",
                workspace_id,
                observable_id,
                row["label"],
                row["confidence"],
                row["half_life"],
                row["floor"],
            )

        await insert_verdict()  # valid row round-trips
        for bad in (
            {"label": "vibes"},
            {"confidence": 1.5},
            {"half_life": 0.0},
            {"floor": 0.5, "confidence": 0.4},  # floor above confidence
        ):
            try:
                await insert_verdict(**bad)
                raise AssertionError(f"verdicts CHECK did not fire for {bad}")
            except asyncpg.CheckViolationError:
                pass
    finally:
        await conn.execute("DELETE FROM workspaces WHERE name = 't-verdicts'")
        await conn.close()


async def test_messages_role_is_constrained(client, settings):
    conn = await _connect(settings)
    try:
        workspace_id = await conn.fetchval(
            "INSERT INTO workspaces (name) VALUES ('t-schema') RETURNING id"
        )
        user_id = await conn.fetchval(
            "INSERT INTO users (workspace_id, email) VALUES ($1, 't@auspex.dev') RETURNING id",
            workspace_id,
        )
        session_id = await conn.fetchval(
            "INSERT INTO chat_sessions (workspace_id, user_id) VALUES ($1, $2) RETURNING id",
            workspace_id,
            user_id,
        )
        try:
            await conn.execute(
                "INSERT INTO messages (workspace_id, session_id, role, content)"
                " VALUES ($1, $2, 'wizard', 'nope')",
                workspace_id,
                session_id,
            )
            raise AssertionError("CHECK constraint on messages.role did not fire")
        except asyncpg.CheckViolationError:
            pass
    finally:
        await conn.execute("DELETE FROM workspaces WHERE name = 't-schema'")
        await conn.close()
