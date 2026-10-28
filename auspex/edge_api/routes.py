"""The edge routes (S33, D-062). Two audiences, never mixed:

- people manage agents (`/api/edge/agents`): an admin creates and revokes, any role
  reads, always in the caller's active workspace;
- agents call the edge API (Task 4) with their own credential, and enroll once with
  the token an admin was shown.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auspex.auth import Admin, AnyRole
from auspex.edge_api.agents import (
    Agent,
    EnrollmentRefused,
    create_agent,
    enroll,
    health,
    list_agents,
    revoke,
)
from auspex.tenancy.audit import person

router = APIRouter(prefix="/api/edge", tags=["edge"])


class NewAgent(BaseModel):
    name: str


class Enrollment(BaseModel):
    token: str


def present(agent: Agent, now: datetime) -> dict:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "enrolled": agent.enrolled_at is not None,
        "revoked": agent.revoked_at is not None,
        "health": "revoked" if agent.revoked_at else health(agent.last_heartbeat_at, now),
        "last_heartbeat_at": agent.last_heartbeat_at.isoformat()
        if agent.last_heartbeat_at else None,
    }


@router.post("/agents", status_code=201)
async def create(body: NewAgent, request: Request, auth: Admin) -> dict:
    """A new agent, and its enrollment token: shown here once, never again."""
    try:
        agent, token = await create_agent(
            request.app.state.pool, workspace_id=auth.workspace_id,
            actor=person(auth.user_id, auth.home_org_id), name=body.name)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"agent": present(agent, datetime.now(UTC)), "enrollment_token": token}


@router.get("/agents")
async def listing(request: Request, auth: AnyRole) -> dict:
    now = datetime.now(UTC)
    agents = await list_agents(request.app.state.pool, workspace_id=auth.workspace_id)
    return {"agents": [present(a, now) for a in agents]}


@router.post("/agents/{agent_id}/revoke", status_code=204)
async def revoke_agent(agent_id: UUID, request: Request, auth: Admin) -> None:
    try:
        await revoke(request.app.state.pool, workspace_id=auth.workspace_id,
                     actor=person(auth.user_id, auth.home_org_id), agent_id=agent_id)
    except LookupError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


@router.post("/enroll")
async def enroll_agent(body: Enrollment, request: Request) -> dict:
    """The agent's first call: spend the one-time token for its credential."""
    try:
        agent, credential = await enroll(request.app.state.pool, body.token)
    except EnrollmentRefused as err:
        raise HTTPException(status_code=401, detail=str(err)) from err
    return {"agent_id": str(agent.id), "credential": credential}
