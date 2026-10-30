"""The Edge Agent's credential: the only identity the edge API admits (S33, D-062).

An agent sends `Authorization: Bearer apa_…`. It resolves to the agent and its one
workspace, or 401: unknown, never enrolled, or revoked. A person's token is not an
agent credential (it is not one of these hashes), and an agent credential is not a
person's login (`resolve_user` refuses it as a bad JWT).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import Depends, HTTPException, Request

from auspex.auth import hash_api_key
from auspex.edge_api.agents import AGENT_KEY_PREFIX


@dataclass(frozen=True)
class AgentContext:
    agent_id: UUID
    workspace_id: UUID


async def resolve_agent_credential(pool: asyncpg.Pool, credential: str) -> AgentContext:
    if not credential.startswith(AGENT_KEY_PREFIX):
        raise HTTPException(status_code=401, detail="Not an Edge Agent credential")
    row = await pool.fetchrow(
        "SELECT id, workspace_id FROM edge_agents WHERE credential_hash = $1"
        " AND revoked_at IS NULL", hash_api_key(credential))
    if row is None:
        raise HTTPException(status_code=401, detail="Unknown or revoked Edge Agent")
    return AgentContext(row["id"], row["workspace_id"])


async def resolve_agent(request: Request) -> AgentContext:
    """The one place an edge request becomes an agent."""
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await resolve_agent_credential(
        request.app.state.pool, authorization.removeprefix("Bearer ").strip())


AgentAuth = Annotated[AgentContext, Depends(resolve_agent)]

__all__ = ["AGENT_KEY_PREFIX", "AgentAuth", "AgentContext", "resolve_agent",
           "resolve_agent_credential"]
