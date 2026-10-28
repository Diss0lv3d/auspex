"""Integration routes (S33): an admin configures, edits and disables; any role reads.
Always the caller's active workspace (D-061); the workspace is never read from input."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auspex.auth import Admin, AnyRole
from auspex.edge_api.agents import health
from auspex.integrations import store
from auspex.integrations.store import Integration, IntegrationRefused
from auspex.tenancy.audit import person

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class NewIntegration(BaseModel):
    name: str
    prefix: str
    content_hash: str
    config: dict[str, Any]
    agent_id: UUID


class Change(BaseModel):
    name: str | None = None
    content_hash: str | None = None
    config: dict[str, Any] | None = None
    agent_id: UUID | None = None


async def _agent_health(pool, integration: Integration, now: datetime) -> str:
    row = await pool.fetchrow(
        "SELECT revoked_at, last_heartbeat_at FROM edge_agents WHERE id = $1"
        " AND workspace_id = $2", integration.agent_id, integration.workspace_id)
    if row is None or row["revoked_at"] is not None:
        return "revoked"
    return health(row["last_heartbeat_at"], now)


async def present(pool, integration: Integration) -> dict:
    return {
        "id": str(integration.id),
        "name": integration.name,
        "prefix": integration.prefix,
        "connector_id": integration.connector_id,
        "content_hash": integration.content_hash,
        "config": integration.config,  # secret fields hold names only (checked at write)
        "agent_id": str(integration.agent_id),
        "enabled": integration.enabled,
        "health": await _agent_health(pool, integration, datetime.now(UTC)),
        "created_at": integration.created_at.isoformat(),
    }


def _refused(err: IntegrationRefused) -> HTTPException:
    return HTTPException(status_code=422, detail=err.reason)


@router.post("", status_code=201)
async def create(body: NewIntegration, request: Request, auth: Admin) -> dict:
    pool = request.app.state.pool
    try:
        made = await store.create(
            pool, workspace_id=auth.workspace_id, actor=person(auth.user_id, auth.home_org_id),
            name=body.name, prefix=body.prefix, content_hash=body.content_hash,
            config=body.config, agent_id=body.agent_id)
    except IntegrationRefused as err:
        raise _refused(err) from err
    return await present(pool, made)


@router.get("")
async def listing(request: Request, auth: AnyRole) -> dict:
    pool = request.app.state.pool
    found = await store.list_for(pool, workspace_id=auth.workspace_id)
    return {"integrations": [await present(pool, i) for i in found]}


@router.patch("/{integration_id}")
async def change(integration_id: UUID, body: Change, request: Request, auth: Admin) -> dict:
    pool = request.app.state.pool
    try:
        changed = await store.update(
            pool, workspace_id=auth.workspace_id, actor=person(auth.user_id, auth.home_org_id),
            integration_id=integration_id, name=body.name, content_hash=body.content_hash,
            config=body.config, agent_id=body.agent_id)
    except LookupError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except IntegrationRefused as err:
        raise _refused(err) from err
    return await present(pool, changed)


@router.post("/{integration_id}/disable", status_code=204)
async def disable(integration_id: UUID, request: Request, auth: Admin) -> None:
    try:
        await store.disable(request.app.state.pool, workspace_id=auth.workspace_id,
                            actor=person(auth.user_id, auth.home_org_id),
                            integration_id=integration_id)
    except LookupError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
