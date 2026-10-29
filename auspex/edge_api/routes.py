"""The edge routes (S33, D-062). Two audiences, never mixed:

- people manage agents (`/api/edge/agents`): an admin creates and revokes, any role
  reads, always in the caller's active workspace;
- agents call the edge API (Task 4) with their own credential, and enroll once with
  the token an admin was shown.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from auspex_sdk import validate
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auspex.auth import Admin, AnyRole
from auspex.connectors.kinds import EDGE_KINDS
from auspex.edge_api.agents import (
    Agent,
    EnrollmentRefused,
    create_agent,
    enroll,
    health,
    list_agents,
    revoke,
)
from auspex.edge_api.auth import AgentAuth, AgentContext
from auspex.jobs.queue import ClaimScope, JobLost, claim, complete, extend_leases, fail
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


# --- the edge API: an Edge Agent's own credential, and nothing else reaches it -------------

LONG_POLL_SECONDS = 25.0  # under common proxy idle timeouts; the agent simply asks again
POLL_INTERVAL = 1.0


class Answer(BaseModel):
    token: UUID
    result: Any = None
    error: str | None = None


async def _integrations_of(pool, agent: AgentContext) -> list[UUID]:
    """The enabled integrations of the agent's workspace that name this agent."""
    rows = await pool.fetch(
        "SELECT id FROM integrations WHERE workspace_id = $1 AND agent_id = $2"
        " AND disabled_at IS NULL", agent.workspace_id, agent.agent_id)
    return [r["id"] for r in rows]


def _claimer(agent: AgentContext) -> str:
    return f"agent:{agent.agent_id}"


@router.post("/claim")
async def claim_job(request: Request, agent: AgentAuth, wait: float | None = None) -> Response:
    """A long-poll: the next job of this agent's integrations, or 204 after at most
    `wait` seconds (capped at LONG_POLL_SECONDS). Scoped to the agent's one workspace and
    its own integrations, so no other job is ever in reach (S31's `ClaimScope`)."""
    pool = request.app.state.pool
    bound = LONG_POLL_SECONDS if wait is None else max(0.0, min(wait, LONG_POLL_SECONDS))
    deadline = asyncio.get_running_loop().time() + bound
    while True:
        integrations = await _integrations_of(pool, agent)
        if integrations:
            job = await claim(pool, ClaimScope(kinds=EDGE_KINDS,
                                               workspace_ids=frozenset({agent.workspace_id}),
                                               integration_ids=frozenset(integrations)),
                              claimer=_claimer(agent))
            if job is not None:
                return JSONResponse({"job": {"id": str(job.id), "kind": job.kind,
                                             "token": str(job.claim_token),
                                             "payload": job.payload}})
        left = deadline - asyncio.get_running_loop().time()
        if left <= 0:
            return Response(status_code=204)
        await asyncio.sleep(min(POLL_INTERVAL, left))


@router.post("/jobs/{job_id}/result", status_code=204)
async def post_result(job_id: UUID, body: Answer, request: Request, agent: AgentAuth) -> None:
    """The agent's answer for a job it holds. The job must be in its workspace and one
    of its integrations' (404 otherwise, whatever the token); the claim token must
    still hold it (409). A result is checked with the SDK's validators before it is
    stored; an invalid one, or the agent's error, fails the job in words."""
    pool = request.app.state.pool
    row = await pool.fetchrow(
        "SELECT kind FROM jobs WHERE id = $1 AND workspace_id = $2"
        " AND integration_id = ANY($3::uuid[])",
        job_id, agent.workspace_id, await _integrations_of(pool, agent))
    if row is None or row["kind"] not in EDGE_KINDS:
        raise HTTPException(status_code=404, detail="no such job for this agent")
    try:
        if body.error is not None:
            await fail(pool, job_id, body.token, body.error, permanent=True)
            return
        try:
            validate.check_test(body.result)
        except validate.ResultInvalid as err:
            await fail(pool, job_id, body.token, f"invalid result: {err}", permanent=True)
            return
        await complete(pool, job_id, body.token, body.result)
    except JobLost as err:
        raise HTTPException(status_code=409, detail="this job is no longer held") from err


class Beat(BaseModel):
    jobs: list[UUID] = []


@router.post("/heartbeat", status_code=204)
async def heartbeat(request: Request, agent: AgentAuth, body: Beat | None = None) -> None:
    """Liveness (health is read from it), and the leases of the jobs the agent says it
    is running now, renewed; no others (PR #51 review #1)."""
    pool = request.app.state.pool
    await pool.execute("UPDATE edge_agents SET last_heartbeat_at = now() WHERE id = $1",
                       agent.agent_id)
    await extend_leases(pool, claimer=_claimer(agent), job_ids=(body.jobs if body else []))


@router.get("/packages/{content_hash}")
async def package(content_hash: str, request: Request, agent: AgentAuth) -> Response:
    """A package's bytes, only for a hash an enabled integration of this agent pins.
    The agent re-hashes what it gets before running any of it (D-062)."""
    pool = request.app.state.pool
    data = await pool.fetchval(
        "SELECT p.package FROM connector_packages p WHERE p.content_hash = $1"
        " AND EXISTS (SELECT 1 FROM integrations i WHERE i.content_hash = $1"
        " AND i.workspace_id = $2 AND i.agent_id = $3 AND i.disabled_at IS NULL) LIMIT 1",
        content_hash, agent.workspace_id, agent.agent_id)
    if data is None:
        raise HTTPException(status_code=404, detail="no such package for this agent")
    return Response(content=bytes(data), media_type="application/zip")
