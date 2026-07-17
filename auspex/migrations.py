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
    # S2: one row per capability-probe run of a customer LLM endpoint (D-005).
    # endpoint_fingerprint = sha256(base_url|model) — identifies the endpoint
    # without ever storing its API key. agent_mode is what the runtime compiles
    # to (code picks the mode from the typed scorecard, not the prompt).
    """
    CREATE TABLE IF NOT EXISTS llm_endpoint_scorecards (
        id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id          uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        endpoint_fingerprint  text NOT NULL,
        base_url              text NOT NULL,
        model                 text NOT NULL,
        agent_mode            text NOT NULL
            CHECK (agent_mode IN ('native_tools', 'prompted_tools', 'plan_only')),
        scorecard             jsonb NOT NULL,
        probed_at             timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_llm_scorecards_ws_fp
        ON llm_endpoint_scorecards (workspace_id, endpoint_fingerprint, probed_at DESC)
    """,
    # S3 (D-014): a write/destructive tool call routed through the permission
    # gate becomes a PROPOSAL, never an execution. A proposal is only ever
    # created from a real tool call — model text claiming an action was done
    # mints nothing here. session_id is nullable + SET NULL so the audit trail
    # of proposed actions outlives the chat session that spawned it.
    """
    CREATE TABLE IF NOT EXISTS proposals (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        session_id    uuid REFERENCES chat_sessions(id) ON DELETE SET NULL,
        tool_name     text NOT NULL,
        tool_level    text NOT NULL CHECK (tool_level IN ('write', 'destructive')),
        tool_input    jsonb NOT NULL,
        status        text NOT NULL DEFAULT 'pending_approval'
            CHECK (status IN ('pending_approval', 'approved', 'rejected', 'executed')),
        created_at    timestamptz NOT NULL DEFAULT now(),
        decided_at    timestamptz,
        decided_by    uuid REFERENCES users(id) ON DELETE SET NULL,
        result        jsonb
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_proposals_ws_status
        ON proposals (workspace_id, status, created_at DESC)
    """,
    # S5: enrichment substrate. `observables` is keyed by the S4-normalized
    # (type, value) per workspace; obs_id is the short deterministic id users
    # reference in chat ("check ipv4-9c463859 again"). `verdicts` is APPEND-ONLY
    # with decay-curve fields from day one (D-017, first Living Verdicts brick):
    # effective confidence at t = floor + (confidence_at_write - floor)
    #                              * 2^(-(t - created_at)/half_life_days).
    """
    CREATE TABLE IF NOT EXISTS observables (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        obs_id        text NOT NULL,
        type          text NOT NULL CHECK (type IN
            ('ipv4', 'ipv6', 'domain', 'url', 'sha256', 'sha1', 'md5', 'email', 'cve')),
        value         text NOT NULL,
        first_seen    timestamptz NOT NULL DEFAULT now(),
        last_seen     timestamptz NOT NULL DEFAULT now(),
        UNIQUE (workspace_id, type, value)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_observables_ws_obsid ON observables (workspace_id, obs_id)",
    """
    CREATE TABLE IF NOT EXISTS verdicts (
        id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id         uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        observable_id        uuid NOT NULL REFERENCES observables(id) ON DELETE CASCADE,
        label                text NOT NULL CHECK (label IN
            ('malicious', 'suspicious', 'benign', 'unknown')),
        confidence_at_write  real NOT NULL
            CHECK (confidence_at_write >= 0 AND confidence_at_write <= 1),
        half_life_days       real NOT NULL CHECK (half_life_days > 0),
        floor                real NOT NULL DEFAULT 0
            CHECK (floor >= 0 AND floor <= confidence_at_write),
        source               text NOT NULL,
        details              jsonb NOT NULL DEFAULT '{}',
        created_at           timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_verdicts_ws_obs
        ON verdicts (workspace_id, observable_id, created_at DESC)
    """,
    # S7: per-feed ingestion watermarks (NVD delta / KEV / EPSS). KB content is
    # platform-global (workspace_id "" in the OpenSearch index), so feed state
    # is too: workspace_id is NULLABLE here — NULL = global feed — keeping the
    # D-008 column for the day workspace-private sources exist. `cursor` is
    # jsonb because watermark shapes differ per feed (NVD: lastMod window end;
    # KEV: HTTP Last-Modified + dateAdded horizon).
    """
    CREATE TABLE IF NOT EXISTS ingest_state (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id  uuid REFERENCES workspaces(id) ON DELETE CASCADE,
        feed          text NOT NULL,
        cursor        jsonb NOT NULL DEFAULT '{}',
        last_run_at   timestamptz,
        last_status   text NOT NULL DEFAULT '',
        docs_upserted bigint NOT NULL DEFAULT 0,
        updated_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ingest_state_global_feed
        ON ingest_state (feed) WHERE workspace_id IS NULL
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
