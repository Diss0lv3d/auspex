"""S30: the migration from "a user row per workspace" to "a person plus
memberships" (D-061), run on a scratch database built in the pre-S30 shape."""

from uuid import uuid4

import asyncpg
import pytest

from auspex.db import create_pool
from auspex.migrations import PRE_S30_STATEMENTS, run_migrations


@pytest.fixture
async def scratch(settings):
    name = f"auspex_s30_mig_{uuid4().hex[:10]}"
    admin = await asyncpg.connect(settings.database_url)
    await admin.execute(f'CREATE DATABASE "{name}"')
    dsn = settings.database_url.rsplit("/", 1)[0] + "/" + name
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            for statement in PRE_S30_STATEMENTS:
                await conn.execute(statement)
            # Removed from the list at S30 (it would fail a migrated boot), but
            # every pre-S30 database has it.
            await conn.execute("CREATE INDEX idx_users_workspace ON users (workspace_id)")
        yield dsn, conn
    finally:
        await conn.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


async def _seed_old_shape(conn) -> dict:
    ids = {}
    for ws in ("default", "dev", "__deployment__", "acme"):
        ids[ws] = await conn.fetchval("INSERT INTO workspaces (name) VALUES ($1) RETURNING id", ws)
    ids["a1"] = await conn.fetchval(
        "INSERT INTO users (workspace_id, email) VALUES ($1, 'a1@x.dev') RETURNING id",
        ids["default"])
    ids["a2"] = await conn.fetchval(
        "INSERT INTO users (workspace_id, email, role) VALUES ($1, 'a2@x.dev', 'admin')"
        " RETURNING id", ids["default"])
    ids["b1"] = await conn.fetchval(
        "INSERT INTO users (workspace_id, email, role) VALUES ($1, 'b1@x.dev', 'superuser')"
        " RETURNING id", ids["acme"])
    ids["chat"] = await conn.fetchval(
        "INSERT INTO chat_sessions (workspace_id, user_id) VALUES ($1, $2) RETURNING id",
        ids["default"], ids["a1"])
    ids["key"] = await conn.fetchval(
        "INSERT INTO api_keys (workspace_id, user_id, key_prefix, key_hash)"
        " VALUES ($1, $2, 'apx_x', 'h1') RETURNING id", ids["acme"], ids["b1"])
    ids["proposal"] = await conn.fetchval(
        "INSERT INTO proposals (workspace_id, tool_name, tool_level, tool_input, decided_by)"
        " VALUES ($1, 'annotate_observable', 'write', '{}', $2) RETURNING id",
        ids["default"], ids["a2"])
    return ids


async def test_the_old_shape_becomes_people_and_memberships_keeping_every_id(scratch):
    dsn, conn = scratch
    ids = await _seed_old_shape(conn)
    pool = await create_pool(dsn, retries=2, delay=0.5)
    try:
        await run_migrations(pool)
        await run_migrations(pool)  # a second boot is a no-op
    finally:
        await pool.close()

    orgs = {r["name"]: r["kind"] for r in await conn.fetch("SELECT name, kind FROM organizations")}
    assert orgs == {"default": "direct", "dev": "direct", "acme": "direct"}
    assert await conn.fetchval(
        "SELECT org_id FROM workspaces WHERE name = '__deployment__'") is None
    assert await conn.fetchval(
        "SELECT count(*) FROM workspaces w JOIN organizations o ON o.id = w.org_id"
        " WHERE o.name = w.name") == 3

    homes = {
        r["id"]: r["home"] for r in await conn.fetch(
            "SELECT u.id, o.name AS home FROM users u JOIN organizations o ON o.id = u.home_org_id")
    }
    assert homes == {ids["a1"]: "default", ids["a2"]: "default", ids["b1"]: "acme"}
    roles = {
        r["user_id"]: (r["ws"], r["role"]) for r in await conn.fetch(
            "SELECT m.user_id, w.name AS ws, m.role FROM memberships m"
            " JOIN workspaces w ON w.id = m.workspace_id")
    }
    assert roles == {
        ids["a1"]: ("default", "analyst"),
        ids["a2"]: ("default", "admin"),
        ids["b1"]: ("acme", "viewer"),  # an unknown role becomes the least one
    }

    columns = {r["column_name"] for r in await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")}
    assert "workspace_id" not in columns and "role" not in columns
    # Every reference to a user survived, because no id changed.
    assert await conn.fetchval("SELECT user_id FROM chat_sessions WHERE id = $1",
                               ids["chat"]) == ids["a1"]
    assert await conn.fetchval("SELECT user_id FROM api_keys WHERE id = $1",
                               ids["key"]) == ids["b1"]
    assert await conn.fetchval("SELECT decided_by FROM proposals WHERE id = $1",
                               ids["proposal"]) == ids["a2"]
    assert await conn.fetchval("SELECT count(*) FROM memberships") == 3


@pytest.mark.parametrize(
    "placement", ["two workspaces", "one workspace, two cases"]
)
async def test_one_email_on_two_rows_stops_the_migration_naming_no_one(scratch, placement):
    dsn, conn = scratch
    a = await conn.fetchval("INSERT INTO workspaces (name) VALUES ('a') RETURNING id")
    b = await conn.fetchval("INSERT INTO workspaces (name) VALUES ('b') RETURNING id")
    second = b if placement == "two workspaces" else a
    await conn.execute(
        "INSERT INTO users (workspace_id, email) VALUES ($1, 'Dup@x.dev'), ($2, 'dup@x.dev')",
        a, second)
    pool = await create_pool(dsn, retries=2, delay=0.5)
    try:
        with pytest.raises(asyncpg.RaiseError) as err:
            await run_migrations(pool)
    finally:
        await pool.close()
    message = str(err.value)
    assert "1 email address" in message
    assert "dup@" not in message.lower()
    # The whole migration is one transaction: nothing half-moved.
    assert await conn.fetchval(
        "SELECT count(*) FROM information_schema.columns"
        " WHERE table_name = 'users' AND column_name = 'workspace_id'") == 1


async def test_a_user_in_the_reserved_workspace_stops_the_migration(scratch):
    dsn, conn = scratch
    ws = await conn.fetchval(
        "INSERT INTO workspaces (name) VALUES ('__deployment__') RETURNING id")
    await conn.execute("INSERT INTO users (workspace_id, email) VALUES ($1, 'x@x.dev')", ws)
    pool = await create_pool(dsn, retries=2, delay=0.5)
    try:
        with pytest.raises(asyncpg.RaiseError, match="__deployment__"):
            await run_migrations(pool)
    finally:
        await pool.close()
