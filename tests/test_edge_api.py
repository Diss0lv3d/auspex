"""S33 Task 4: the edge API (D-062). An Edge Agent, with its own credential only,
claims its integrations' jobs (long-poll), posts validated results, heartbeats (which
hold its leases) and fetches the packages its integrations pin, and nothing else."""

import shutil
import uuid
from pathlib import Path

import pytest
from _tenancy import build_mssp, drop_orgs
from auspex_sdk.build import build

from auspex.connectors.catalogue import register
from auspex.connectors.kinds import CONNECTOR_TEST
from auspex.db import create_pool
from auspex.edge_api import routes as edge_routes
from auspex.edge_api.agents import create_agent, enroll, revoke
from auspex.integrations.store import create, disable
from auspex.jobs.queue import enqueue
from auspex.tenancy.audit import person

PREFIX = "t-s33-edgeapi"
REFERENCE = Path(__file__).resolve().parents[1] / "examples/connectors/mock_siem/yaml"
CONFIG = {"base_url": "https://siem.example:9443", "api_token": "secret:siem_token"}


@pytest.fixture(scope="module")
def reference_zip(tmp_path_factory) -> bytes:
    copy = tmp_path_factory.mktemp("ref") / "c"
    shutil.copytree(REFERENCE, copy, ignore=shutil.ignore_patterns("dist", "__pycache__"))
    zip_path, _ = build(copy)
    return zip_path.read_bytes()


async def _site(pool, ws, admin, data, name):
    """A workspace's package, enrolled agent and integration naming it."""
    entry = await register(pool, workspace_id=ws, data=data, registered_by=admin.user_id,
                           offered_to_clients=False)
    agent, enrollment = await create_agent(pool, workspace_id=ws, actor=admin, name=name)
    _, credential = await enroll(pool, enrollment)
    integ = await create(pool, workspace_id=ws, actor=admin, name=name, prefix=name,
                         content_hash=entry.content_hash, config=CONFIG, agent_id=agent.id)
    return {"agent": agent, "credential": credential, "integration": integ,
            "hash": entry.content_hash, "ws": ws,
            "auth": {"Authorization": f"Bearer {credential}"}}


@pytest.fixture
async def world(client, settings, reference_zip, monkeypatch):
    monkeypatch.setattr(edge_routes, "LONG_POLL_SECONDS", 0.2)
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        m = await build_mssp(pool, PREFIX)
        a = await _site(pool, m.direct_ws, person(m.d_user, m.direct), reference_zip, "sitea")
        b = await _site(pool, m.client1_ws, person(m.c1_user, m.client1), reference_zip,
                        "siteb")
        yield pool, m, a, b
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


async def _job(pool, site, key=None):
    job, _ = await enqueue(
        pool, workspace_id=site["ws"], kind=CONNECTOR_TEST,
        idempotency_key=key or f"test:{uuid.uuid4()}",
        integration_id=site["integration"].id,
        payload={"integration_id": str(site["integration"].id), "content_hash": site["hash"],
                 "command": "test", "config": CONFIG, "arguments": {}})
    return job


async def _status(pool, job_id):
    return await pool.fetchrow("SELECT status, result, last_error FROM jobs WHERE id = $1",
                               job_id)


async def test_an_agent_claims_only_its_own_integrations_jobs(world, client):
    pool, _, a, b = world
    mine, theirs = await _job(pool, a), await _job(pool, b)
    got = client.post("/api/edge/claim", headers=a["auth"])
    assert got.status_code == 200, got.text
    assert got.json()["job"]["id"] == str(mine.id)
    assert got.json()["job"]["payload"]["config"] == CONFIG
    assert client.post("/api/edge/claim", headers=a["auth"]).status_code == 204
    assert (await _status(pool, theirs.id))["status"] == "queued"


async def test_a_disabled_integration_s_job_is_not_claimed(world, client):
    pool, m, a, _ = world
    await _job(pool, a)
    await disable(pool, workspace_id=a["ws"], actor=person(m.d_user, m.direct),
                  integration_id=a["integration"].id)
    assert client.post("/api/edge/claim", headers=a["auth"]).status_code == 204


async def test_a_valid_result_completes_the_job(world, client):
    pool, _, a, _ = world
    job = await _job(pool, a)
    claimed = client.post("/api/edge/claim", headers=a["auth"]).json()["job"]
    res = client.post(f"/api/edge/jobs/{job.id}/result", headers=a["auth"],
                      json={"token": claimed["token"], "result": {"ok": False,
                                                                  "detail": "401 from SIEM"}})
    assert res.status_code == 204, res.text
    row = await _status(pool, job.id)
    assert row["status"] == "done"


@pytest.mark.parametrize("body,reason", [
    ({"result": {"ok": "yes"}}, "test must return"),
    ({"error": "secret 'siem_token' (for config.api_token) is not on this agent"},
     "siem_token"),
])
async def test_an_invalid_result_or_an_error_fails_the_job_in_words(world, client, body,
                                                                     reason):
    pool, _, a, _ = world
    job = await _job(pool, a)
    claimed = client.post("/api/edge/claim", headers=a["auth"]).json()["job"]
    res = client.post(f"/api/edge/jobs/{job.id}/result", headers=a["auth"],
                      json={"token": claimed["token"], **body})
    assert res.status_code == 204, res.text
    row = await _status(pool, job.id)
    assert row["status"] == "failed" and reason in row["last_error"]


async def test_a_result_the_agent_may_not_post_is_refused_and_changes_nothing(world, client):
    """Review Focus 1: a wrong token, another workspace's job, a lost lease, a revoked
    agent: refused, and the job is exactly as it was."""
    pool, m, a, b = world
    job = await _job(pool, a)
    claimed = client.post("/api/edge/claim", headers=a["auth"]).json()["job"]
    ok = {"result": {"ok": True, "detail": "reachable"}}
    wrong = client.post(f"/api/edge/jobs/{job.id}/result", headers=a["auth"],
                        json={"token": str(uuid.uuid4()), **ok})
    assert wrong.status_code == 409
    foreign = client.post(f"/api/edge/jobs/{job.id}/result", headers=b["auth"],
                          json={"token": claimed["token"], **ok})
    assert foreign.status_code == 404
    assert (await _status(pool, job.id))["status"] == "claimed"
    await pool.execute("UPDATE jobs SET status = 'queued', claim_token = NULL WHERE id = $1",
                       job.id)  # the lease went, and the job with it
    lost = client.post(f"/api/edge/jobs/{job.id}/result", headers=a["auth"],
                       json={"token": claimed["token"], **ok})
    assert lost.status_code == 409
    assert (await _status(pool, job.id))["status"] == "queued"
    await revoke(pool, workspace_id=a["ws"], actor=person(m.d_user, m.direct),
                 agent_id=a["agent"].id)
    assert client.post(f"/api/edge/jobs/{job.id}/result", headers=a["auth"],
                       json={"token": claimed["token"], **ok}).status_code == 401


async def test_a_heartbeat_marks_the_agent_and_holds_only_its_own_leases(world, client):
    pool, _, a, b = world
    mine, theirs = await _job(pool, a), await _job(pool, b)
    client.post("/api/edge/claim", headers=a["auth"])
    client.post("/api/edge/claim", headers=b["auth"])
    await pool.execute("UPDATE jobs SET lease_expires_at = now() + interval '5 seconds'"
                       " WHERE id = ANY($1::uuid[])", [mine.id, theirs.id])
    assert client.post("/api/edge/heartbeat", headers=a["auth"]).status_code == 204
    leases = {r["id"]: r["left"] for r in await pool.fetch(
        "SELECT id, extract(epoch FROM lease_expires_at - now()) AS left FROM jobs"
        " WHERE id = ANY($1::uuid[])", [mine.id, theirs.id])}
    assert leases[mine.id] > 60 and leases[theirs.id] < 10
    assert await pool.fetchval("SELECT last_heartbeat_at IS NOT NULL FROM edge_agents"
                               " WHERE id = $1", a["agent"].id)


async def test_a_package_is_served_only_for_a_hash_the_agent_s_integration_pins(world, client,
                                                                                 reference_zip):
    pool, _, a, b = world
    got = client.get(f"/api/edge/packages/{a['hash']}", headers=a["auth"])
    assert got.status_code == 200 and got.content == reference_zip
    assert client.get(f"/api/edge/packages/sha256:{'0' * 64}",
                      headers=a["auth"]).status_code == 404


async def test_a_person_cannot_call_the_agent_endpoints(world, client, settings):
    from _tenancy import token

    _, m, a, _ = world
    person_auth = token(settings, m.d_user, m.direct_ws)
    for method, path in (("post", "/api/edge/claim"), ("post", "/api/edge/heartbeat"),
                         ("get", f"/api/edge/packages/{a['hash']}")):
        assert getattr(client, method)(path, headers=person_auth).status_code == 401
