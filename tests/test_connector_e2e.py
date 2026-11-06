"""S34 Task 7: a connector action through the whole path and every door, against the
running app (the TestClient), a real `Agent` in a thread and the real `auspex_sdk.run`
subprocess answering from the mock SIEM's recorded exchanges.

propose (the card from a dry-run job) -> approve under the policy -> the execute job ->
undo; observe after a failed execute; abandon, keep, withdraw and D-048's stale run;
and proposing while the agent is offline, or while it does not answer, is refused in
words with nothing filed."""

import asyncio
import json
import shutil
import threading
import time
from pathlib import Path

import pytest
from _tenancy import build_mssp, drop_orgs, token
from auspex_sdk.build import build

from auspex.actions import ActionRegistry
from auspex.actions.settlement import NothingToPropose, action_proposer
from auspex.connectors.catalogue import register
from auspex.connectors.dispatch import dispatcher
from auspex.connectors.resolve import ActionResolver
from auspex.db import create_pool
from auspex.edge.agent import Agent
from auspex.edge_api.agents import create_agent, enroll
from auspex.integrations.store import create, set_grants
from auspex.tenancy.audit import person

PREFIX = "t-s34-e2e"
EXAMPLE = Path(__file__).resolve().parents[1] / "examples/connectors/mock_siem"
TOKEN = "example-token-placeholder"  # noqa: S105 -- a placeholder, not a credential
CONFIG = {"base_url": "https://siem.example.test", "api_token": "secret:siem_token"}


def _exchanges(*names: str) -> dict:
    loaded = (json.loads((EXAMPLE / "fixtures" / f"{n}.json").read_text()) for n in names)
    return {"exchanges": [x for f in loaded for x in f["exchanges"]]}


@pytest.fixture(scope="module")
def reference_zip(tmp_path_factory) -> bytes:
    copy = tmp_path_factory.mktemp("ref") / "c"
    shutil.copytree(EXAMPLE / "yaml", copy, ignore=shutil.ignore_patterns("dist", "__pycache__"))
    zip_path, _ = build(copy)
    return zip_path.read_bytes()


class Site:
    """The agent's host, serving jobs in a thread while the test drives the app."""

    def __init__(self, agent: Agent) -> None:
        self.agent, self._stop = agent, threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.agent.run_once():
                    time.sleep(0.05)
            except Exception:  # noqa: BLE001 -- a test's agent keeps serving
                time.sleep(0.05)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=30)


@pytest.fixture
async def world(client, settings, reference_zip, tmp_path, monkeypatch):
    fixture = tmp_path / "siem.json"
    monkeypatch.setenv("AUSPEX_SDK_RUN_FIXTURE", str(fixture))
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        m = await build_mssp(pool, PREFIX)
        admin = person(m.d_user, m.direct)
        entry = await register(pool, workspace_id=m.direct_ws, data=reference_zip,
                               registered_by=m.d_user, offered_to_clients=False)
        agent_row, enrollment = await create_agent(pool, workspace_id=m.direct_ws,
                                                   actor=admin, name="site")
        _, credential = await enroll(pool, enrollment)
        await pool.execute("UPDATE edge_agents SET last_heartbeat_at = now() WHERE id = $1",
                           agent_row.id)
        integ = await create(pool, workspace_id=m.direct_ws, actor=admin, name="SIEM",
                             prefix="siem1", content_hash=entry.content_hash, config=CONFIG,
                             agent_id=agent_row.id)
        await set_grants(pool, workspace_id=m.direct_ws, actor=admin, integration_id=integ.id,
                         actions=["close_alert"])
        secrets = tmp_path / "secrets.json"
        secrets.write_text(json.dumps({"siem_token": TOKEN}))
        secrets.chmod(0o600)
        agent = Agent(http=client, credential=credential, secrets_path=secrets,
                      cache_dir=tmp_path / "cache", wait=0)

        # The app's own wiring, on this test's pool (the app's lives on its own loop).
        registry = ActionResolver(ActionRegistry(), pool,
                                  dispatch=lambda i: dispatcher(pool, i, poll=0.05))

        async def propose(*exchanges: str):
            """File a proposal the way the agent loop does, the agent serving its dry run."""
            fixture.write_text(json.dumps(_exchanges(*exchanges)))
            spec = await registry.resolve("siem1__close_alert", m.direct_ws)
            proposer = action_proposer(pool, registry)
            with Site(agent):
                return await proposer(spec=spec, arguments={"alert_id": "A-1001"},
                                      workspace_id=m.direct_ws)

        yield {"pool": pool, "m": m, "agent": agent, "agent_id": agent_row.id,
               "propose": propose, "fixture": fixture, "registry": registry,
               "admin": token(settings, m.d_user, m.direct_ws)}
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


def _post(client, w, pid, door: str, *exchanges: str):
    w["fixture"].write_text(json.dumps(_exchanges(*exchanges)))
    with Site(w["agent"]):
        return client.post(f"/api/proposals/{pid}/{door}", headers=w["admin"])


async def _status(w, pid) -> str:
    return await w["pool"].fetchval("SELECT status FROM proposals WHERE id = $1", pid)


async def test_propose_approve_execute_undo(world, client):
    proposal = await world["propose"]("alert_open")
    assert proposal["card"]["summary"] == "close alert A-1001"
    pid = proposal["id"]
    approved = await asyncio.to_thread(_post, client, world, pid, "approve", "close")
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["executed"] is True and body["outcome"]["did"] == "closed alert A-1001"
    assert await _status(world, pid) == "executed"
    undone = await asyncio.to_thread(_post, client, world, pid, "undo", "reopen")
    assert undone.status_code == 200, undone.text
    assert await _status(world, pid) == "undone"
    kinds = [r["kind"] for r in await world["pool"].fetch(
        "SELECT kind FROM jobs WHERE workspace_id = $1 ORDER BY created_at", world["m"].direct_ws)]
    assert kinds == ["connector.action.dry_run", "connector.action.execute",
                     "connector.action.undo"]


async def test_a_failed_execute_asks_observe_what_landed(world, client):
    """The SIEM's close fails (no recorded exchange); observe finds the alert closed
    anyway, so the row is `incomplete`, not `failed`; a human keeps it."""
    pid = (await world["propose"]("alert_open"))["id"]
    failed = await asyncio.to_thread(_post, client, world, pid, "approve", "alert_closed")
    assert failed.status_code == 500
    row = await world["pool"].fetchrow("SELECT status, result FROM proposals WHERE id = $1", pid)
    assert row["status"] == "incomplete"
    assert json.loads(row["result"])["effects"] == "present"
    kept = client.post(f"/api/proposals/{pid}/keep", headers=world["admin"])
    assert kept.status_code == 200 and await _status(world, pid) == "kept"


async def test_withdraw_and_abandon(world, client):
    pool = world["pool"]
    withdrawn = (await world["propose"]("alert_open"))["id"]
    await pool.execute("UPDATE proposals SET status = 'approved', decided_at = now() -"
                       " interval '1 hour', decided_by = $2 WHERE id = $1", withdrawn,
                       world["m"].d_user)  # D-048: an approval no run ever started
    assert client.post(f"/api/proposals/{withdrawn}/withdraw",
                       headers=world["admin"]).status_code == 200
    assert await _status(world, withdrawn) == "withdrawn"

    stuck = (await world["propose"]("alert_open"))["id"]
    await pool.execute("UPDATE proposals SET status = 'executing', claimed_at = now() -"
                       " interval '1 hour', claim_token = gen_random_uuid(), decided_at ="
                       " now() WHERE id = $1", stuck)
    assert client.post(f"/api/proposals/{stuck}/abandon",
                       headers=world["admin"]).status_code == 200
    assert await _status(world, stuck) == "abandoned"


async def test_a_stale_approval_runs_on_the_agent(world, client):
    """D-048: an approval no run ever started is run by a human pressing execute."""
    pid = (await world["propose"]("alert_open"))["id"]
    await world["pool"].execute("UPDATE proposals SET status = 'approved', decided_at ="
                                " now() - interval '1 hour', decided_by = $2 WHERE id = $1",
                                pid, world["m"].d_user)
    ran = await asyncio.to_thread(_post, client, world, pid, "execute", "close")
    assert ran.status_code == 200, ran.text
    assert await _status(world, pid) == "executed"


async def test_proposing_with_the_agent_offline_is_refused_with_its_reason(world):
    await world["pool"].execute("UPDATE edge_agents SET last_heartbeat_at = now() - interval"
                                " '10 minutes' WHERE id = $1", world["agent_id"])
    with pytest.raises(Exception) as refused:
        await world["propose"]("alert_open")
    assert "offline" in refused.value.model_feedback
    assert 0 == await world["pool"].fetchval("SELECT count(*) FROM proposals"
                                             " WHERE workspace_id = $1", world["m"].direct_ws)
    assert 0 == await world["pool"].fetchval("SELECT count(*) FROM jobs"
                                             " WHERE workspace_id = $1", world["m"].direct_ws)


async def test_a_preview_nobody_answers_is_refused_in_words_and_nothing_is_filed(
        world, client, monkeypatch):
    from auspex.connectors import dispatch

    monkeypatch.setitem(dispatch.WAITS, "dry_run", 0.5)
    registry = world["registry"]
    spec = await registry.resolve("siem1__close_alert", world["m"].direct_ws)
    with pytest.raises(Exception) as refused:  # no agent serving
        await action_proposer(world["pool"], registry)(
            spec=spec, arguments={"alert_id": "A-1001"}, workspace_id=world["m"].direct_ws)
    assert not isinstance(refused.value, NothingToPropose)
    assert "did not answer the preview" in refused.value.model_feedback
    assert 0 == await world["pool"].fetchval("SELECT count(*) FROM proposals"
                                             " WHERE workspace_id = $1", world["m"].direct_ws)
