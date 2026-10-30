"""S33 Task 3: Edge Agents (D-062). An admin creates an agent and gets a one-time
enrollment token; the agent spends it once for its credential, which is stored hashed
and reaches only the edge API; a revoked credential is refused at once."""

from datetime import UTC, datetime, timedelta

import pytest
from _tenancy import build_mssp, drop_orgs, token
from fastapi import HTTPException

from auspex.auth import hash_api_key
from auspex.db import create_pool
from auspex.edge_api.agents import (
    ENROLLMENT_TTL,
    EnrollmentRefused,
    create_agent,
    enroll,
    health,
    revoke,
)
from auspex.edge_api.auth import AGENT_KEY_PREFIX, resolve_agent_credential
from auspex.tenancy.audit import list_events, person

PREFIX = "t-s33-agents"


@pytest.fixture
async def world(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        yield pool, await build_mssp(pool, PREFIX)
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


def _admin(m):
    return person(m.d_user, m.direct)


async def test_an_enrollment_token_is_spent_once_for_a_hashed_credential(world):
    pool, m = world
    agent, enrollment = await create_agent(pool, workspace_id=m.direct_ws, actor=_admin(m),
                                           name="site-a")
    enrolled, credential = await enroll(pool, enrollment)
    assert enrolled.id == agent.id and credential.startswith(AGENT_KEY_PREFIX)
    stored = await pool.fetchrow("SELECT credential_hash FROM edge_agents WHERE id = $1",
                                 agent.id)
    assert stored["credential_hash"] == hash_api_key(credential)
    assert credential not in str(dict(stored))
    with pytest.raises(EnrollmentRefused):
        await enroll(pool, enrollment)  # spent
    actions = [e["action"] for e in await list_events(pool, m.direct_ws)]
    assert "edge_agent.created" in actions and "edge_agent.enrolled" in actions


async def test_an_expired_or_unknown_token_is_refused(world):
    pool, m = world
    _, enrollment = await create_agent(pool, workspace_id=m.direct_ws, actor=_admin(m),
                                       name="late")
    await pool.execute("UPDATE edge_enrollments SET expires_at = now() - interval '1 second'"
                       " WHERE token_hash = $1", hash_api_key(enrollment))
    with pytest.raises(EnrollmentRefused):
        await enroll(pool, enrollment)
    with pytest.raises(EnrollmentRefused):
        await enroll(pool, "ape_not-a-token")
    assert ENROLLMENT_TTL == timedelta(hours=24)


async def test_a_credential_resolves_to_its_agent_and_a_revoked_one_is_refused(world):
    pool, m = world
    agent, enrollment = await create_agent(pool, workspace_id=m.direct_ws, actor=_admin(m),
                                           name="site-b")
    _, credential = await enroll(pool, enrollment)
    ctx = await resolve_agent_credential(pool, credential)
    assert (ctx.agent_id, ctx.workspace_id) == (agent.id, m.direct_ws)
    await revoke(pool, workspace_id=m.direct_ws, actor=_admin(m), agent_id=agent.id)
    with pytest.raises(HTTPException) as err:
        await resolve_agent_credential(pool, credential)
    assert err.value.status_code == 401


async def test_another_workspace_cannot_revoke_an_agent(world):
    pool, m = world
    agent, _ = await create_agent(pool, workspace_id=m.direct_ws, actor=_admin(m), name="x")
    with pytest.raises(LookupError):
        await revoke(pool, workspace_id=m.client1_ws, actor=person(m.c1_user, m.client1),
                     agent_id=agent.id)


async def test_a_person_token_is_not_an_agent_credential_and_the_reverse(world, client,
                                                                          settings):
    pool, m = world
    agent, enrollment = await create_agent(pool, workspace_id=m.direct_ws, actor=_admin(m),
                                           name="site-c")
    _, credential = await enroll(pool, enrollment)
    person_jwt = token(settings, m.d_user, m.direct_ws)["Authorization"].removeprefix(
        "Bearer ")
    with pytest.raises(HTTPException):
        await resolve_agent_credential(pool, person_jwt)
    res = client.get("/api/edge/agents", headers={"Authorization": f"Bearer {credential}"})
    assert res.status_code == 401  # an agent credential is no person's login


async def test_the_agent_routes_are_admin_written_and_workspace_scoped(world, client,
                                                                        settings):
    pool, m = world
    admin = token(settings, m.d_user, m.direct_ws)
    made = client.post("/api/edge/agents", json={"name": "site-d"}, headers=admin)
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["enrollment_token"] and body["agent"]["health"] == "never"
    analyst = token(settings, m.c1_user, m.client1_ws)
    assert client.post("/api/edge/agents", json={"name": "n"},
                       headers=analyst).status_code == 403
    assert client.get("/api/edge/agents", headers=analyst).json() == {"agents": []}
    listed = client.get("/api/edge/agents", headers=admin).json()["agents"]
    assert [a["name"] for a in listed] == ["site-d"]
    assert "enrollment_token" not in listed[0] and "credential_hash" not in listed[0]
    enrolled = client.post("/api/edge/enroll", json={"token": body["enrollment_token"]})
    assert enrolled.status_code == 200 and enrolled.json()["credential"].startswith(
        AGENT_KEY_PREFIX)
    assert client.post("/api/edge/enroll",
                       json={"token": body["enrollment_token"]}).status_code == 401


@pytest.mark.parametrize("seconds,state", [(0, "online"), (59, "online"), (60, "stale"),
                                           (299, "stale"), (300, "offline"),
                                           (None, "never")])
def test_health_from_the_last_heartbeat(seconds, state):
    now = datetime(2026, 10, 28, tzinfo=UTC)
    last = None if seconds is None else now - timedelta(seconds=seconds)
    assert health(last, now) == state
