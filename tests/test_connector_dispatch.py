"""S34 Task 5: a compiled connector action dispatches each role as a job on its
integration's Edge Agent and waits for the answer (design decisions 3, 6 and 9).

Driven against the real app (the TestClient is the agent's HTTP client), a real `Agent`
in a thread and the real `auspex_sdk.run` subprocess, answering from recorded
exchanges. Review Focus 2 (a lost result never runs the action twice) and 5 (an answer
that breaks the manifest, or from another workspace, is refused or failed in words)."""

import asyncio
import json
import shutil
import uuid
from pathlib import Path

import pytest
from _tenancy import build_mssp, drop_orgs
from auspex_sdk.build import build
from auspex_sdk.package import build_zip

from auspex.actions import ActionRegistry, operation_key
from auspex.connectors import dispatch as dispatch_mod
from auspex.connectors.catalogue import register
from auspex.connectors.resolve import ActionResolver
from auspex.db import create_pool
from auspex.edge.agent import Agent
from auspex.edge_api.agents import create_agent, enroll
from auspex.integrations.store import create, set_grants
from auspex.tenancy.audit import person

PREFIX = "t-s34-dispatch"
EXAMPLE = Path(__file__).resolve().parents[1] / "examples/connectors/mock_siem"
TOKEN = "example-token-placeholder"  # noqa: S105 -- a placeholder, not a credential
CONFIG = {"base_url": "https://siem.example.test", "api_token": "secret:siem_token"}
WAITS = {"dry_run": 20, "execute": 20, "undo": 20, "observe": 20}


def _exchanges(*names: str) -> dict:
    loaded = (json.loads((EXAMPLE / "fixtures" / f"{n}.json").read_text()) for n in names)
    return {"exchanges": [x for f in loaded for x in f["exchanges"]]}


@pytest.fixture(scope="module")
def reference_zip(tmp_path_factory) -> bytes:
    copy = tmp_path_factory.mktemp("ref") / "c"
    shutil.copytree(EXAMPLE / "yaml", copy, ignore=shutil.ignore_patterns("dist", "__pycache__"))
    zip_path, _ = build(copy)
    return zip_path.read_bytes()


@pytest.fixture
async def site(client, settings, reference_zip, tmp_path, monkeypatch):
    fixture = tmp_path / "siem.json"
    fixture.write_text(json.dumps(_exchanges("alert_open", "close", "alert_closed", "reopen")))
    monkeypatch.setenv("AUSPEX_SDK_RUN_FIXTURE", str(fixture))
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        m = await build_mssp(pool, PREFIX)
        admin = person(m.d_user, m.direct)
        agent_row, enrollment = await create_agent(pool, workspace_id=m.direct_ws,
                                                   actor=admin, name="site")
        _, credential = await enroll(pool, enrollment)
        secrets = tmp_path / "secrets.json"
        secrets.write_text(json.dumps({"siem_token": TOKEN}))
        secrets.chmod(0o600)

        async def integration(data: bytes, prefix: str):
            entry = await register(pool, workspace_id=m.direct_ws, data=data,
                                   registered_by=m.d_user, offered_to_clients=False)
            integ = await create(pool, workspace_id=m.direct_ws, actor=admin, name=prefix,
                                 prefix=prefix, content_hash=entry.content_hash,
                                 config=CONFIG, agent_id=agent_row.id)
            await set_grants(pool, workspace_id=m.direct_ws, actor=admin,
                             integration_id=integ.id, actions=["close_alert"])
            return integ

        resolver = ActionResolver(
            ActionRegistry(), pool,
            dispatch=lambda i: dispatch_mod.dispatcher(pool, i, waits=WAITS, poll=0.05))
        agent = Agent(http=client, credential=credential, secrets_path=secrets,
                      cache_dir=tmp_path / "cache", wait=0)
        yield {"pool": pool, "m": m, "agent": agent, "integration": integration,
               "resolver": resolver, "zip": reference_zip, "credential": credential,
               "fixture": fixture}
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


async def _with_agent(agent: Agent, call):
    """Run the core's call while the agent, in a thread, claims and answers one job."""

    def serve():
        for _ in range(200):
            if agent.run_once():
                return
            import time
            time.sleep(0.05)

    served = asyncio.create_task(asyncio.to_thread(serve))
    try:
        return await call
    finally:
        await served


async def test_a_dry_run_round_trips_through_the_agent(site):
    integ = await site["integration"](site["zip"], "siem1")
    spec = await site["resolver"].resolve("siem1__close_alert", site["m"].direct_ws)
    outcome = await _with_agent(site["agent"],
                                spec.dry_run(workspace_id=site["m"].direct_ws, alert_id="A-1001"))
    assert outcome.would == "close alert A-1001" and outcome.affects == ("A-1001",)
    assert outcome.detail == {"status": "open"}
    row = await site["pool"].fetchrow("SELECT kind, status, integration_id, payload FROM jobs"
                                      " WHERE integration_id = $1", integ.id)
    assert row["kind"] == "connector.action.dry_run" and row["status"] == "done"
    payload = json.loads(row["payload"])
    assert payload["config"] == CONFIG and payload["action"] == "close_alert"


async def test_a_wait_that_runs_out_raises_in_words_and_cancels_the_queued_job(site):
    integ = await site["integration"](site["zip"], "siem2")
    short = dispatch_mod.dispatcher(site["pool"], integ, waits={**WAITS, "dry_run": 0.3},
                                    poll=0.05)
    resolver = ActionResolver(ActionRegistry(), site["pool"], dispatch=lambda i: short)
    spec = await resolver.resolve("siem2__close_alert", site["m"].direct_ws)
    with pytest.raises(dispatch_mod.DispatchFailed, match="did not answer"):
        await spec.dry_run(workspace_id=site["m"].direct_ws, alert_id="A-1001")
    status = await site["pool"].fetchval("SELECT status FROM jobs WHERE integration_id = $1",
                                         integ.id)
    assert status == "failed"  # never claimed later, so it never runs after the wait
    assert site["agent"].run_once() is False


async def test_an_envelope_that_breaks_the_manifest_s_output_is_failed(site, client):
    """Review Focus 5: `detail.priority` is not declared in close_alert's output."""
    integ = await site["integration"](site["zip"], "siem3")
    spec = await site["resolver"].resolve("siem3__close_alert", site["m"].direct_ws)
    auth = {"Authorization": f"Bearer {site['credential']}"}

    def answer_badly():
        import time
        for _ in range(200):
            res = client.post("/api/edge/claim", params={"wait": 0}, headers=auth)
            if res.status_code == 200:
                job = res.json()["job"]
                client.post(f"/api/edge/jobs/{job['id']}/result", headers=auth, json={
                    "token": job["token"],
                    "result": {"would": "close", "affects": ["A-1001"], "reversible": True,
                               "detail": {"status": "open", "priority": "p1"}}})
                return
            time.sleep(0.05)

    served = asyncio.create_task(asyncio.to_thread(answer_badly))
    with pytest.raises(dispatch_mod.DispatchFailed, match="priority"):
        await spec.dry_run(workspace_id=site["m"].direct_ws, alert_id="A-1001")
    await served
    row = await site["pool"].fetchrow("SELECT status, last_error FROM jobs"
                                      " WHERE integration_id = $1", integ.id)
    assert row["status"] == "failed" and "not declared" in row["last_error"]


async def test_a_lost_execute_result_never_runs_the_action_twice(site, tmp_path):
    """Review Focus 2: the agent's first answer is lost and the lease runs out. Asking
    again under the same idempotency key finds the same job, never a second one, and
    the SIEM was asked to close the alert once."""
    calls = tmp_path / "calls.log"
    counting = build_zip({**_files(site["zip"]), "mock_siem.py": _files(site["zip"])[
        "mock_siem.py"] + (
        "\n\n_real_close = close_alert\n\n"
        "def close_alert(ctx, alert_id, note=None):\n"
        f"    with open({str(calls)!r}, 'a') as f:\n"
        "        f.write('close\\n')\n"
        "    return _real_close(ctx, alert_id, note)\n").encode()})
    integ = await site["integration"](counting, "siem4")
    spec = await site["resolver"].resolve("siem4__close_alert", site["m"].direct_ws)
    pool, ws = site["pool"], site["m"].direct_ws
    key = operation_key(uuid.uuid4(), "execute")
    agent = site["agent"]
    agent._post = lambda job, answer: None  # the answer never reaches the core

    async def execute():
        return await spec.execute(workspace_id=ws, proposal_id=None, idempotency_key=key,
                                  alert_id="A-1001")

    with pytest.raises(dispatch_mod.DispatchFailed):
        short = dispatch_mod.dispatcher(pool, integ, waits={**WAITS, "execute": 3}, poll=0.05)
        spec = await ActionResolver(ActionRegistry(), pool, dispatch=lambda i: short).resolve(
            "siem4__close_alert", ws)
        await _with_agent(agent, execute())
    await pool.execute("UPDATE jobs SET lease_expires_at = now() - interval '1 second'"
                       " WHERE integration_id = $1", integ.id)
    assert agent.run_once() is False  # one attempt: the expired job is not re-run
    with pytest.raises(dispatch_mod.DispatchFailed):
        await execute()
    jobs = await pool.fetch("SELECT kind, status, idempotency_key FROM jobs"
                            " WHERE integration_id = $1", integ.id)
    assert len(jobs) == 1 and jobs[0]["kind"] == "connector.action.execute"
    assert jobs[0]["status"] == "dead"
    assert calls.read_text().splitlines() == ["close"]


async def test_an_answered_execute_asked_again_returns_its_answer_without_running(site):
    integ = await site["integration"](site["zip"], "siem5")
    spec = await site["resolver"].resolve("siem5__close_alert", site["m"].direct_ws)
    ws, key = site["m"].direct_ws, operation_key(uuid.uuid4(), "execute")
    first = await _with_agent(site["agent"], spec.execute(
        workspace_id=ws, proposal_id=None, idempotency_key=key, alert_id="A-1001"))
    again = await spec.execute(workspace_id=ws, proposal_id=None, idempotency_key=key,
                               alert_id="A-1001")
    assert first == again and first.would == "closed alert A-1001"
    assert 1 == await site["pool"].fetchval(
        "SELECT count(*) FROM jobs WHERE integration_id = $1", integ.id)


async def test_another_workspace_s_agent_cannot_claim_or_answer_an_action_job(site, client):
    """Review Focus 5 (tenancy): an enrolled agent of client1 sees nothing of it."""
    m, pool = site["m"], site["pool"]
    await site["integration"](site["zip"], "siem6")
    other, enrollment = await create_agent(pool, workspace_id=m.client1_ws,
                                           actor=person(m.c1_user, m.client1), name="x")
    _, other_cred = await enroll(pool, enrollment)
    spec = await site["resolver"].resolve("siem6__close_alert", m.direct_ws)
    short = asyncio.create_task(spec.dry_run(workspace_id=m.direct_ws, alert_id="A-1001"))
    await asyncio.sleep(0.2)
    auth = {"Authorization": f"Bearer {other_cred}"}
    assert client.post("/api/edge/claim", params={"wait": 0}, headers=auth).status_code == 204
    job_id = await pool.fetchval("SELECT id FROM jobs WHERE kind = 'connector.action.dry_run'"
                                 " AND workspace_id = $1 ORDER BY created_at DESC LIMIT 1",
                                 m.direct_ws)
    refused = client.post(f"/api/edge/jobs/{job_id}/result", headers=auth,
                          json={"token": str(uuid.uuid4()), "result": {}})
    assert refused.status_code == 404
    short.cancel()


def _files(zip_bytes: bytes) -> dict[str, bytes]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return {n: z.read(n) for n in z.namelist()}


async def test_a_claimed_job_that_is_not_answered_may_have_run(site, client):
    """Fresh review of S34, #2: past the wait, a claimed job is not "nothing happened"."""
    integ = await site["integration"](site["zip"], "siem7")
    short = dispatch_mod.dispatcher(site["pool"], integ, waits={**WAITS, "execute": 1},
                                    poll=0.05)
    spec = await ActionResolver(ActionRegistry(), site["pool"],
                                dispatch=lambda i: short).resolve("siem7__close_alert",
                                                                  site["m"].direct_ws)
    auth = {"Authorization": f"Bearer {site['credential']}"}

    def claim_and_say_nothing():
        import time
        for _ in range(100):
            if client.post("/api/edge/claim", params={"wait": 0},
                           headers=auth).status_code == 200:
                return
            time.sleep(0.05)

    served = asyncio.create_task(asyncio.to_thread(claim_and_say_nothing))
    with pytest.raises(dispatch_mod.DispatchFailed) as failed:
        await spec.execute(workspace_id=site["m"].direct_ws, proposal_id=None,
                           idempotency_key=operation_key(uuid.uuid4(), "execute"),
                           alert_id="A-1001")
    await served
    assert failed.value.may_have_run is True


async def test_a_wait_that_ran_out_before_any_claim_did_not_run(site):
    integ = await site["integration"](site["zip"], "siem8")
    short = dispatch_mod.dispatcher(site["pool"], integ, waits={**WAITS, "execute": 0.3},
                                    poll=0.05)
    spec = await ActionResolver(ActionRegistry(), site["pool"],
                                dispatch=lambda i: short).resolve("siem8__close_alert",
                                                                  site["m"].direct_ws)
    with pytest.raises(dispatch_mod.DispatchFailed) as failed:
        await spec.execute(workspace_id=site["m"].direct_ws, proposal_id=None,
                           idempotency_key=operation_key(uuid.uuid4(), "execute"),
                           alert_id="A-1001")
    assert failed.value.may_have_run is False


@pytest.mark.parametrize("ended", ["agent_error", "never_claimed"])
async def test_a_failed_undo_can_be_tried_again(site, ended):
    """PR #53 review #1: a failed undo returns its row for another try, but the job key
    was the same each time, so the retry got the old failure back in 70 ms and the
    change could never be put back. A job that failed (the agent said so, or nobody
    claimed it) lets a retry enqueue a fresh job; the handler keeps the operation key."""
    pool, ws = site["pool"], site["m"].direct_ws
    integ = await site["integration"](site["zip"], f"siemu{ended[:3]}")
    key = operation_key(uuid.uuid4(), "undo")
    from auspex.connectors.kinds import ACTION_KINDS
    from auspex.jobs.queue import enqueue

    first, _ = await enqueue(pool, workspace_id=ws, kind=ACTION_KINDS["undo"],
                             idempotency_key=f"connector.undo:{key}", integration_id=integ.id,
                             payload={})
    reason = ("the core stopped waiting before an Edge Agent claimed it"
              if ended == "never_claimed" else "RuntimeError: no reopen recorded")
    await pool.execute("UPDATE jobs SET status = 'failed', last_error = $2, finished_at ="
                       " now() WHERE id = $1", first.id, reason)
    spec = await site["resolver"].resolve(f"siemu{ended[:3]}__close_alert", ws)
    outcome = await _with_agent(site["agent"], spec.undo.handler(
        workspace_id=ws, proposal_id=None, idempotency_key=key, alert_id="A-1001"))
    assert outcome.would == "reopen alert A-1001"
    rows = await pool.fetch("SELECT status, payload FROM jobs WHERE integration_id = $1"
                            " ORDER BY created_at", integ.id)
    assert [r["status"] for r in rows] == ["failed", "done"]
    assert json.loads(rows[1]["payload"])["idempotency_key"] == key  # the handler's key


async def test_an_undo_that_may_have_run_is_not_run_again(site):
    """The other half of #1: a dead job (claimed, unanswered) may have run; no retry."""
    pool, ws = site["pool"], site["m"].direct_ws
    integ = await site["integration"](site["zip"], "siemudead")
    key = operation_key(uuid.uuid4(), "undo")
    from auspex.connectors.kinds import ACTION_KINDS
    from auspex.jobs.queue import enqueue

    first, _ = await enqueue(pool, workspace_id=ws, kind=ACTION_KINDS["undo"],
                             idempotency_key=f"connector.undo:{key}", integration_id=integ.id,
                             payload={})
    await pool.execute("UPDATE jobs SET status = 'dead', last_error = 'lease expired' WHERE"
                       " id = $1", first.id)
    spec = await site["resolver"].resolve("siemudead__close_alert", ws)
    with pytest.raises(dispatch_mod.DispatchFailed) as failed:
        await spec.undo.handler(workspace_id=ws, proposal_id=None, idempotency_key=key,
                                alert_id="A-1001")
    assert failed.value.may_have_run is True
    assert 1 == await pool.fetchval("SELECT count(*) FROM jobs WHERE integration_id = $1",
                                    integ.id)


def test_each_agent_timeout_is_under_the_core_s_wait_and_the_lease():
    """PR #53 review s1: an execute timed out at the agent at 60 s while the core waited
    60 s from enqueue, so a slow success read as unknown effects."""
    from auspex.connectors.kinds import ACTION_KINDS
    from auspex.edge.agent import COMMAND_TIMEOUTS

    for step, kind in ACTION_KINDS.items():
        assert COMMAND_TIMEOUTS[step] + 5 <= dispatch_mod.WAITS[step] < kind.lease_seconds
