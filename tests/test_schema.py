"""Schema v0 invariants, asserted against the live database (reality over memory)."""

import re

import asyncpg
import pytest
from _tenancy import ensure_member, ensure_workspace

from auspex.db import create_pool
from auspex.migrations import run_migrations

EXPECTED_TABLES = {
    "workspaces",
    "organizations",
    "memberships",
    "audit_events",
    "users",
    "api_keys",
    "chat_sessions",
    "messages",
    "llm_endpoint_scorecards",
    "proposals",
    "jobs",
    "observables",
    "verdicts",
    "ingest_state",
    "investigations",
    "hypotheses",
    "ach_evidence",
    "retrohunt_matches",
    "verdict_flips",
}

# D-008: workspace_id on EVERY table. D-061 (S30) names the only exemptions:
# `workspaces` (its key IS the workspace id), `organizations` (they OWN
# workspaces) and `users` (a person, no longer a row per workspace).
WORKSPACE_ID_EXEMPT = {"workspaces", "organizations", "users"}


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
        workspace_id = await ensure_workspace(conn, "t-scorecard")
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
        workspace_id = await ensure_workspace(conn, "t-proposals")
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
        workspace_id = await ensure_workspace(conn, "t-verdicts")
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
        workspace_id = await ensure_workspace(conn, "t-schema")
        user_id = await ensure_member(conn, workspace_id, "t@auspex.dev")
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


async def test_startup_survives_every_status_a_proposal_can_be_in(client, settings):
    """S26 review, HIGH: every boot re-runs every migration, and an earlier block
    that re-adds the status CHECK with an older list validated every existing
    row against it. One `incomplete` row (TD-028b) — then a restart — and the
    whole migration rolled back: the app could not start. Idempotence was only
    ever tested on rows that had no new status in them.

    So: one row in EVERY status the constraint allows, then the startup
    migration, twice. The list is read from the live constraint itself, so a
    status added later is covered without editing this test."""
    conn = await _connect(settings)
    try:
        definition = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'proposals_status_check'"
        )
        statuses = re.findall(r"'([a-z_]+)'::text", definition)
        assert {"incomplete", "abandoned", "pending_approval"} <= set(statuses)
        ws = await ensure_workspace(conn, "t-every-status")
        for status in statuses:
            await conn.execute(
                "INSERT INTO proposals (workspace_id, tool_name, tool_level, tool_input, status)"
                " VALUES ($1, 'annotate_observable', 'write', '{}'::jsonb, $2)",
                ws, status,
            )
    finally:
        await conn.close()

    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    try:
        await run_migrations(pool)
        await run_migrations(pool)
    finally:
        await pool.execute("DELETE FROM workspaces WHERE name = 't-every-status'")
        await pool.close()


async def test_identity_left_the_workspace(client, settings):
    conn = await _connect(settings)
    try:
        columns = {
            r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
            )
        }
        assert "workspace_id" not in columns and "role" not in columns
        assert "home_org_id" in columns
    finally:
        await conn.close()


async def test_s30_constraints_hold(client, settings):
    conn = await _connect(settings)
    try:
        bad = [
            "INSERT INTO organizations (name, kind) VALUES ('t-s30-orphan', 'client')",
            "INSERT INTO organizations (name, kind, restricted) VALUES ('t-s30-r', 'direct', true)",
            "INSERT INTO workspaces (name) VALUES ('t-s30-no-org')",
            "INSERT INTO workspaces (name, org_id, region)"
            " SELECT 't-s30-mars', id, 'mars' FROM organizations LIMIT 1",
        ]
        for sql in bad:
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(sql)
    finally:
        await conn.close()


async def test_the_region_check_is_the_codes_vocabulary(client, settings):
    from auspex.tenancy.region import REGIONS

    conn = await _connect(settings)
    try:
        definition = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'workspaces_region_check'"
        )
        assert set(re.findall(r"'(\w+)'", definition)) == REGIONS
    finally:
        await conn.close()


async def test_a_job_status_outside_the_list_is_refused(client, settings):
    conn = await _connect(settings)
    try:
        ws = await ensure_workspace(conn, "t-s31-job-status")
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO jobs (workspace_id, kind, idempotency_key, max_attempts,"
                " lease_seconds, status) VALUES ($1, 't.s31.x', 'k', 1, 1, 'running')", ws)
    finally:
        await conn.execute("DELETE FROM workspaces WHERE name = 't-s31-job-status'")
        await conn.close()
