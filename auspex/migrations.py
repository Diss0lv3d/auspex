"""Schema v0 — idempotent startup migration.

D-008: `workspace_id` on EVERY table from day one. The single exception is
`workspaces` itself, whose primary key IS the workspace id. The schema test
enforces this invariant against the live database.

Every statement is IF NOT EXISTS / idempotent: running this N times is safe,
which is the whole migration strategy for v0 (no version table yet).
"""

import logging

import asyncpg

logger = logging.getLogger("auspex.migrations")

SCHEMA_V0: list[str] = [
    'CREATE EXTENSION IF NOT EXISTS "pgcrypto"',
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name        text NOT NULL,
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    # UNIQUE on name makes get-or-create race-safe (ON CONFLICT) and prevents two
    # concurrent first logins from splitting one identity across duplicate workspaces.
    # Separate index statement so it also applies to pre-existing tables (idempotent).
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_workspaces_name ON workspaces (name)",
    """
    CREATE TABLE IF NOT EXISTS users (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        email         text NOT NULL,
        display_name  text NOT NULL DEFAULT '',
        google_sub    text,
        role          text NOT NULL DEFAULT 'analyst',
        created_at    timestamptz NOT NULL DEFAULT now(),
        UNIQUE (workspace_id, email)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name          text NOT NULL DEFAULT '',
        key_prefix    text NOT NULL,
        key_hash      text NOT NULL UNIQUE,
        created_at    timestamptz NOT NULL DEFAULT now(),
        last_used_at  timestamptz,
        revoked_at    timestamptz
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title         text NOT NULL DEFAULT '',
        created_at    timestamptz NOT NULL DEFAULT now(),
        updated_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        session_id    uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
        role          text NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
        content       text NOT NULL,
        created_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_workspace ON users (workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_workspace ON api_keys (workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_ws_user ON chat_sessions (workspace_id, user_id)",
    """
    CREATE INDEX IF NOT EXISTS idx_messages_ws_session
        ON messages (workspace_id, session_id, created_at)
    """,
]


async def run_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        # Serialize concurrent app replicas racing the same DDL.
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(715001)")
            for statement in SCHEMA_V0:
                await conn.execute(statement)
    logger.info("Schema v0 migration applied (idempotent, %d statements)", len(SCHEMA_V0))
