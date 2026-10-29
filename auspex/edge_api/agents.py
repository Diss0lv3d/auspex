"""Edge Agents: create, enroll, revoke, and health (S33, D-062).

An admin creates an agent and is shown a one-time enrollment token once. The agent
spends it once for its credential: a random secret stored hashed only (the `api_keys`
pattern, `auspex/auth.py`), reaching only the edge API (`auth.py` beside this). Revoke
refuses the credential at once. Every change is audited in the agent's workspace, in
the same transaction (D-073).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import asyncpg

from auspex.auth import hash_api_key
from auspex.tenancy import audit
from auspex.untrusted import unstorable

ENROLLMENT_PREFIX = "ape_"
AGENT_KEY_PREFIX = "apa_"
ENROLLMENT_TTL = timedelta(hours=24)
ONLINE_SECONDS = 60
STALE_SECONDS = 300


class EnrollmentRefused(ValueError):
    """The token is unknown, spent, expired, or its agent was revoked."""


@dataclass(frozen=True)
class Agent:
    id: UUID
    workspace_id: UUID
    name: str
    enrolled_at: datetime | None
    revoked_at: datetime | None
    last_heartbeat_at: datetime | None


def _agent(row: asyncpg.Record) -> Agent:
    return Agent(row["id"], row["workspace_id"], row["name"], row["enrolled_at"],
                 row["revoked_at"], row["last_heartbeat_at"])


def health(last_heartbeat_at: datetime | None, now: datetime) -> str:
    """online under a minute since the last heartbeat, stale under five, then offline;
    `never` before the first one (spec decision 7)."""
    if last_heartbeat_at is None:
        return "never"
    age = (now - last_heartbeat_at).total_seconds()
    if age < ONLINE_SECONDS:
        return "online"
    return "stale" if age < STALE_SECONDS else "offline"


async def create_agent(pool: asyncpg.Pool, *, workspace_id: UUID, actor: audit.Actor,
                       name: str) -> tuple[Agent, str]:
    """A new agent and its one-time enrollment token, which exists only in this return."""
    if unstorable(name):
        raise ValueError("an agent's name holds a NUL or a lone surrogate, which cannot be"
                         " stored")
    name = " ".join(name.split())
    if not name or len(name) > 80:
        raise ValueError("an agent needs a name of at most 80 characters")
    raw = ENROLLMENT_PREFIX + secrets.token_urlsafe(32)
    async with pool.acquire() as conn, conn.transaction():
        try:
            row = await conn.fetchrow(
                "INSERT INTO edge_agents (workspace_id, name, created_by) VALUES ($1, $2, $3)"
                " RETURNING id, workspace_id, name, enrolled_at, revoked_at,"
                " last_heartbeat_at", workspace_id, name, actor.user_id)
        except asyncpg.UniqueViolationError as err:
            raise ValueError(f"an agent named {name!r} already exists here") from err
        await conn.execute(
            "INSERT INTO edge_enrollments (workspace_id, agent_id, token_hash, created_by,"
            " expires_at) VALUES ($1, $2, $3, $4, now() + $5::interval)",
            workspace_id, row["id"], hash_api_key(raw), actor.user_id, ENROLLMENT_TTL)
        await audit.record(conn, workspace_id=workspace_id, action="edge_agent.created",
                           actor=actor, details={"agent_id": str(row["id"]), "name": name})
    return _agent(row), raw


async def enroll(pool: asyncpg.Pool, token: str) -> tuple[Agent, str]:
    """Spend an enrollment token once: the agent's credential, which exists only in this
    return. Refused when the token is unknown, spent or expired, or the agent revoked."""
    credential = AGENT_KEY_PREFIX + secrets.token_urlsafe(32)
    async with pool.acquire() as conn, conn.transaction():
        # The spend is the claim: one UPDATE, so two agents racing one token get one.
        spent = await conn.fetchrow(
            "UPDATE edge_enrollments SET used_at = now() WHERE token_hash = $1"
            " AND used_at IS NULL AND expires_at > now() RETURNING agent_id, workspace_id",
            hash_api_key(token))
        if spent is None:
            raise EnrollmentRefused("this enrollment token is unknown, used or expired")
        row = await conn.fetchrow(
            "UPDATE edge_agents SET credential_hash = $2, key_prefix = $3,"
            " enrolled_at = now() WHERE id = $1 AND revoked_at IS NULL"
            " RETURNING id, workspace_id, name, enrolled_at, revoked_at, last_heartbeat_at",
            spent["agent_id"], hash_api_key(credential), credential[:12])
        if row is None:
            raise EnrollmentRefused("this agent was revoked")
        await audit.record(conn, workspace_id=spent["workspace_id"],
                           action="edge_agent.enrolled", actor=audit.SYSTEM,
                           details={"agent_id": str(row["id"])})
    return _agent(row), credential


async def revoke(pool: asyncpg.Pool, *, workspace_id: UUID, actor: audit.Actor,
                 agent_id: UUID) -> None:
    """Refuse the agent's credential from now on. LookupError outside its workspace."""
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "UPDATE edge_agents SET revoked_at = coalesce(revoked_at, now())"
            " WHERE id = $1 AND workspace_id = $2 RETURNING id", agent_id, workspace_id)
        if row is None:
            raise LookupError("no such agent in this workspace")
        await audit.record(conn, workspace_id=workspace_id, action="edge_agent.revoked",
                           actor=actor, details={"agent_id": str(agent_id)})


async def list_agents(pool: asyncpg.Pool, *, workspace_id: UUID) -> list[Agent]:
    rows = await pool.fetch(
        "SELECT id, workspace_id, name, enrolled_at, revoked_at, last_heartbeat_at"
        " FROM edge_agents WHERE workspace_id = $1 ORDER BY name",
        workspace_id)
    return [_agent(r) for r in rows]
