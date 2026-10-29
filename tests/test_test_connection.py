"""S33 Task 8: "Test connection" (D-062). An admin presses it; one `connector.test` job
waits for the integration's agent; the poll says queued, running, ok, failed (the SIEM
said no) or error (we could not ask). It refuses in words when it cannot run."""

import json
import shutil
import uuid
from pathlib import Path

import pytest
from _tenancy import build_mssp, drop_orgs, token
from auspex_sdk.build import build

from auspex.connectors.catalogue import register
from auspex.db import create_pool
from auspex.edge_api.agents import create_agent, enroll, revoke
from auspex.integrations.store import create
from auspex.tenancy.audit import person

PREFIX = "t-s33-testconn"
REFERENCE = Path(__file__).resolve().parents[1] / "examples/connectors/mock_siem/yaml"
SECRET_VALUE = "placeholder-secret-value-s33"  # noqa: S105 -- scanned for, never sent
CONFIG = {"base_url": "https://siem.example:9443", "api_token": "secret:siem_token"}


@pytest.fixture(scope="module")
def reference_zip(tmp_path_factory) -> bytes:
    copy = tmp_path_factory.mktemp("ref") / "c"
    shutil.copytree(REFERENCE, copy, ignore=shutil.ignore_patterns("dist", "__pycache__"))
    zip_path, _ = build(copy)
    return zip_path.read_bytes()


@pytest.fixture
async def world(client, settings, reference_zip):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        m = await build_mssp(pool, PREFIX)
        admin = person(m.d_user, m.direct)
        entry = await register(pool, workspace_id=m.direct_ws, data=reference_zip,
                               registered_by=m.d_user, offered_to_clients=False)
        agent, enrollment = await create_agent(pool, workspace_id=m.direct_ws, actor=admin,
                                               name="site")
        _, credential = await enroll(pool, enrollment)
        integ = await create(pool, workspace_id=m.direct_ws, actor=admin, name="SIEM",
                             prefix="siem1", content_hash=entry.content_hash, config=CONFIG,
                             agent_id=agent.id)
        await pool.execute("UPDATE edge_agents SET last_heartbeat_at = now() WHERE id = $1",
                           agent.id)
        yield {"pool": pool, "m": m, "integ": integ, "agent": agent,
               "agent_auth": {"Authorization": f"Bearer {credential}"},
               "admin": token(settings, m.d_user, m.direct_ws),
               "other": token(settings, m.c1_user, m.client1_ws), "hash": entry.content_hash}
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


def _press(client, w):
    return client.post(f"/api/integrations/{w['integ'].id}/test", headers=w["admin"])


def _poll(client, w, job_id, who="admin"):
    return client.get(f"/api/integrations/{w['integ'].id}/test/{job_id}", headers=w[who])


async def test_a_press_queues_one_test_for_the_integration_s_agent(world, client):
    pressed = _press(client, world)
    assert pressed.status_code == 202, pressed.text
    job_id = pressed.json()["job_id"]
    assert _poll(client, world, job_id).json()["state"] == "queued"
    row = await world["pool"].fetchrow("SELECT kind, integration_id, payload FROM jobs"
                                       " WHERE id = $1", uuid.UUID(job_id))
    assert row["kind"] == "connector.test" and row["integration_id"] == world["integ"].id
    payload = json.loads(row["payload"])
    assert payload["config"] == CONFIG and payload["content_hash"] == world["hash"]
    again = _press(client, world)
    assert again.status_code == 409 and again.json()["detail"]["job_id"] == job_id


@pytest.mark.parametrize("answer,state,detail", [
    ({"result": {"ok": True, "detail": "reachable"}}, "ok", "reachable"),
    ({"result": {"ok": False, "detail": "the SIEM answered 401"}}, "failed", "401"),
    ({"error": "secret 'siem_token' (for config.api_token) is not on this agent"}, "error",
     "siem_token"),
])
async def test_the_poll_tells_the_siem_saying_no_from_not_being_able_to_ask(
        world, client, answer, state, detail):
    job_id = _press(client, world).json()["job_id"]
    claimed = client.post("/api/edge/claim", params={"wait": 0},
                          headers=world["agent_auth"]).json()["job"]
    assert _poll(client, world, job_id).json()["state"] == "running"
    client.post(f"/api/edge/jobs/{job_id}/result", headers=world["agent_auth"],
                json={"token": claimed["token"], **answer})
    polled = _poll(client, world, job_id).json()
    assert polled["state"] == state and detail in polled["detail"]


@pytest.mark.parametrize("make_unable,words", [
    ("disable", "disabled"),
    ("revoke", "revoked"),
    ("offline", "offline"),
    ("never", "never connected"),
])
async def test_a_test_that_cannot_run_is_refused_in_words_and_queues_nothing(
        world, client, make_unable, words):
    """Review Focus 5."""
    pool, m = world["pool"], world["m"]
    admin = person(m.d_user, m.direct)
    if make_unable == "disable":
        client.post(f"/api/integrations/{world['integ'].id}/disable", headers=world["admin"])
    elif make_unable == "revoke":
        await revoke(pool, workspace_id=m.direct_ws, actor=admin,
                     agent_id=world["agent"].id)
    elif make_unable == "offline":
        await pool.execute("UPDATE edge_agents SET last_heartbeat_at = now() - interval"
                           " '10 minutes' WHERE id = $1", world["agent"].id)
    else:
        await pool.execute("UPDATE edge_agents SET last_heartbeat_at = NULL WHERE id = $1",
                           world["agent"].id)
    pressed = _press(client, world)
    assert pressed.status_code == 409 and words in pressed.json()["detail"]["reason"]
    assert 0 == await pool.fetchval("SELECT count(*) FROM jobs WHERE integration_id = $1",
                                    world["integ"].id)


async def test_disabling_cancels_a_queued_test(world, client):
    job_id = _press(client, world).json()["job_id"]
    client.post(f"/api/integrations/{world['integ'].id}/disable", headers=world["admin"])
    polled = _poll(client, world, job_id).json()
    assert polled["state"] == "error" and "cancelled" in polled["detail"]
    assert client.post("/api/edge/claim", params={"wait": 0},
                       headers=world["agent_auth"]).status_code == 204


async def test_another_workspace_cannot_press_or_poll(world, client):
    job_id = _press(client, world).json()["job_id"]
    assert client.post(f"/api/integrations/{world['integ'].id}/test",
                       headers=world["other"]).status_code in (403, 404)
    assert _poll(client, world, job_id, who="other").status_code == 404
    assert client.get(f"/api/integrations/{world['integ'].id}/test/{uuid.uuid4()}",
                      headers=world["admin"]).status_code == 404


async def test_no_response_carries_a_secret_value(world, client):
    """Review Focus 4 (D-063): the only secret anywhere here is a name; scan everything
    this file's routes answer for the value the agent's host would hold."""
    texts = [client.get("/api/integrations", headers=world["admin"]).text,
             client.get("/api/edge/agents", headers=world["admin"]).text]
    job_id = _press(client, world).json()["job_id"]
    texts.append(_poll(client, world, job_id).text)
    assert all(SECRET_VALUE not in t for t in texts)
    assert all("secret:siem_token" in texts[0] for _ in [0])


async def test_presses_at_once_never_hang_a_small_pool(world, client, settings):
    """PR #51 review s1: `press` held a connection and its transaction while `enqueue`
    took a second, so N presses on a pool of N could wait on each other for good. It
    now queues on the connection that holds the lock."""
    import asyncio

    import asyncpg

    from auspex.integrations import testing

    small = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=1)
    try:
        results = await asyncio.wait_for(asyncio.gather(
            *(testing.press(small, world["integ"]) for _ in range(3)),
            return_exceptions=True), timeout=10)
    finally:
        await small.close()
    assert sum(1 for r in results if isinstance(r, uuid.UUID)) == 1
    assert all(isinstance(r, (uuid.UUID, testing.CannotTest)) for r in results)


async def test_a_config_edit_cancels_a_queued_test(world, client):
    """PR #51 review s4: a test queued before a config edit ran with the old config.
    Any edit to what the test runs with cancels the queued one."""
    job_id = _press(client, world).json()["job_id"]
    changed = client.patch(f"/api/integrations/{world['integ'].id}", headers=world["admin"],
                           json={"config": {**CONFIG, "base_url": "https://new.example"}})
    assert changed.status_code == 200, changed.text
    polled = _poll(client, world, job_id).json()
    assert polled["state"] == "error" and "cancelled" in polled["detail"]


async def test_a_rename_alone_leaves_a_queued_test_alone(world, client):
    job_id = _press(client, world).json()["job_id"]
    client.patch(f"/api/integrations/{world['integ'].id}", headers=world["admin"],
                 json={"name": "Main SIEM"})
    assert _poll(client, world, job_id).json()["state"] == "queued"
