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
}

# D-008: workspace_id on EVERY table. `workspaces` is the sole exception —
# its primary key IS the workspace id.
WORKSPACE_ID_EXEMPT = {"workspaces"}


async def _connect(settings) -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url)


async def test_schema_v0_tables_exist(client, settings):
    conn = await _connect(settings)
    try:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
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
