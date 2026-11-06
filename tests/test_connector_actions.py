"""S34 Task 6: an approved connector action runs only while what it was approved for
still holds (design decision 7, Review Focus 4). Each refusal has its own reason and
comes before the claim, so the row stays `approved` and nothing is dispatched:

- `agent_offline`: the integration's agent is offline, revoked or never connected;
- `integration_disabled`;
- `not_granted`: an admin took the grant back;
- `spec_changed`: the integration now pins another package (the fingerprint, D-064).

And `EXECUTABLE_SYSTEMS` admits a connector's own system only through the resolver: a
granted action of an enabled integration with a live agent runs."""

import json
import shutil
from pathlib import Path

import pytest
from _tenancy import build_mssp, drop_orgs
from auspex_sdk.build import build
from auspex_sdk.package import build_zip

from auspex.actions import ActionRegistry
from auspex.actions.proposal import fingerprint, undo_identity
from auspex.actions.settlement import ActionExecutor, ExecutionRefused
from auspex.connectors.catalogue import register
from auspex.connectors.resolve import ActionResolver
from auspex.db import create_pool
from auspex.edge_api.agents import create_agent, enroll, revoke
from auspex.integrations.store import create, disable, set_grants
from auspex.tenancy.audit import person

PREFIX = "t-s34-actions"
REFERENCE = Path(__file__).resolve().parents[1] / "examples/connectors/mock_siem/yaml"
CONFIG = {"base_url": "https://siem.example:9443", "api_token": "secret:siem_token"}
ENVELOPE = {"would": "closed alert A-1", "affects": ["A-1"], "reversible": True,
            "detail": {"status": "closed"}}


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
        await enroll(pool, enrollment)
        await pool.execute("UPDATE edge_agents SET last_heartbeat_at = now() WHERE id = $1",
                           agent.id)
        integ = await create(pool, workspace_id=m.direct_ws, actor=admin, name="SIEM",
                             prefix="siem1", content_hash=entry.content_hash, config=CONFIG,
                             agent_id=agent.id)
        await set_grants(pool, workspace_id=m.direct_ws, actor=admin, integration_id=integ.id,
                         actions=["close_alert"])
        sent: list[str] = []

        def dispatch(integration):
            async def run(kind, payload):
                sent.append(kind)
                return 1 if kind.endswith("observe") else ENVELOPE
            return run

        resolver = ActionResolver(ActionRegistry(), pool, dispatch=dispatch)
        yield {"pool": pool, "m": m, "admin": admin, "integ": integ, "agent": agent,
               "resolver": resolver, "sent": sent, "zip": reference_zip}
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


async def _approved(w) -> str:
    spec = await w["resolver"].resolve("siem1__close_alert", w["m"].direct_ws)
    return str(await w["pool"].fetchval(
        "INSERT INTO proposals (workspace_id, tool_name, tool_level, tool_input,"
        " spec_fingerprint, undo_identity, card, status, decided_at)"
        " VALUES ($1, $2, $3, $4::jsonb, $5, $6, '{}', 'approved', now()) RETURNING id",
        w["m"].direct_ws, spec.name, spec.risk.value, json.dumps({"alert_id": "A-1"}),
        fingerprint(spec), undo_identity(spec)))


async def test_a_granted_action_with_a_live_agent_runs(world):
    pid = await _approved(world)
    executor = ActionExecutor(world["pool"], world["resolver"])
    outcome = await executor.execute(workspace_id=world["m"].direct_ws, proposal_id=pid)
    assert outcome.would == "closed alert A-1"
    assert world["sent"] == ["connector.action.execute"]
    assert "executed" == await world["pool"].fetchval(
        "SELECT status FROM proposals WHERE id = $1::uuid", pid)


@pytest.mark.parametrize("change,reason", [
    ("offline", "agent_offline"),
    ("never", "agent_offline"),
    ("revoked", "agent_offline"),
    ("disabled", "integration_disabled"),
    ("ungranted", "not_granted"),
    ("repackaged", "spec_changed"),
])
@pytest.mark.parametrize("door", ["execute", "stale"])
async def test_an_approved_action_is_refused_before_its_claim(world, change, reason, door):
    """Review Focus 4."""
    pool, m, integ = world["pool"], world["m"], world["integ"]
    pid = await _approved(world)
    if change == "offline":
        await pool.execute("UPDATE edge_agents SET last_heartbeat_at = now() - interval"
                           " '10 minutes' WHERE id = $1", world["agent"].id)
    elif change == "never":
        await pool.execute("UPDATE edge_agents SET last_heartbeat_at = NULL WHERE id = $1",
                           world["agent"].id)
    elif change == "revoked":
        await revoke(pool, workspace_id=m.direct_ws, actor=world["admin"],
                     agent_id=world["agent"].id)
    elif change == "disabled":
        await disable(pool, workspace_id=m.direct_ws, actor=world["admin"],
                      integration_id=integ.id)
    elif change == "ungranted":
        await set_grants(pool, workspace_id=m.direct_ws, actor=world["admin"],
                         integration_id=integ.id, actions=[])
    else:
        files = _files(world["zip"])
        files["mock_siem.py"] += b"\n# a new build\n"
        manifest = json.loads(files["manifest.json"])
        files["manifest.json"] = json.dumps({**manifest, "version": "1.0.1"}).encode()
        other = await register(pool, workspace_id=m.direct_ws, data=build_zip(files),
                               registered_by=m.d_user, offered_to_clients=False)
        await pool.execute("UPDATE integrations SET content_hash = $2 WHERE id = $1",
                           integ.id, other.content_hash)
    executor = ActionExecutor(pool, world["resolver"])
    with pytest.raises(ExecutionRefused) as refused:
        if door == "execute":
            await executor.execute(workspace_id=m.direct_ws, proposal_id=pid)
        else:
            await pool.execute("UPDATE proposals SET decided_at = now() - interval '1 hour'"
                               " WHERE id = $1::uuid", pid)
            await executor.run_stale_approval(workspace_id=m.direct_ws, proposal_id=pid,
                                              run_by=m.d_user)
    assert refused.value.reason == reason
    row = await pool.fetchrow("SELECT status, claimed_at FROM proposals WHERE id = $1::uuid", pid)
    assert row["status"] == "approved" and row["claimed_at"] is None
    assert world["sent"] == []


@pytest.mark.parametrize("change,reason", [("offline", "agent_offline"),
                                           ("disabled", "integration_disabled")])
async def test_an_undo_is_refused_with_its_reason_too(world, change, reason):
    pool, m = world["pool"], world["m"]
    pid = await _approved(world)
    executor = ActionExecutor(pool, world["resolver"])
    await executor.execute(workspace_id=m.direct_ws, proposal_id=pid)
    if change == "offline":
        await pool.execute("UPDATE edge_agents SET last_heartbeat_at = now() - interval"
                           " '10 minutes' WHERE id = $1", world["agent"].id)
    else:
        await disable(pool, workspace_id=m.direct_ws, actor=world["admin"],
                      integration_id=world["integ"].id)
    with pytest.raises(ExecutionRefused) as refused:
        await executor.undo(workspace_id=m.direct_ws, proposal_id=pid)
    assert refused.value.reason == reason
    assert "executed" == await pool.fetchval("SELECT status FROM proposals WHERE id = $1::uuid",
                                             pid)


async def test_a_connector_action_naming_another_system_is_still_refused(world):
    """The widening is the action's OWN connector, not any system."""
    from dataclasses import replace

    from auspex.actions.settlement import check_executable
    from auspex.actions.types import ActionScope

    spec = await world["resolver"].resolve("siem1__close_alert", world["m"].direct_ws)
    wider = replace(spec, scope=(*spec.scope, ActionScope(system="firewall", writes=True)))
    proposal = {"status": "approved", "spec_fingerprint": fingerprint(wider),
                "tool_input": {"alert_id": "A-1"}}
    with pytest.raises(ExecutionRefused) as refused:
        check_executable(wider, proposal)
    assert refused.value.reason == "system_not_executable"


def _files(zip_bytes: bytes) -> dict[str, bytes]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return {n: z.read(n) for n in z.namelist()}


async def test_moving_an_integration_to_another_package_clears_its_grants(world):
    """Fresh review of S34, #1: a grant approves an action AS DECLARED; a new package
    may declare the same name differently, so it is granted again or not at all."""
    from auspex.integrations.store import update

    pool, m, integ = world["pool"], world["m"], world["integ"]
    files = _files(world["zip"])
    manifest = json.loads(files["manifest.json"])
    files["manifest.json"] = json.dumps({**manifest, "version": "1.0.2"}).encode()
    other = await register(pool, workspace_id=m.direct_ws, data=build_zip(files),
                           registered_by=m.d_user, offered_to_clients=False)
    moved = await update(pool, workspace_id=m.direct_ws, actor=world["admin"],
                         integration_id=integ.id, content_hash=other.content_hash)
    assert moved.grants == ()
    assert await world["resolver"].resolve("siem1__close_alert", m.direct_ws) is None
    audit = await pool.fetchval(
        "SELECT details FROM audit_events WHERE action = 'integration.updated'"
        " AND workspace_id = $1 ORDER BY created_at DESC LIMIT 1", m.direct_ws)
    details = json.loads(audit) if isinstance(audit, str) else audit
    assert details["grants_cleared"] == ["close_alert"]


async def test_a_rename_or_config_edit_keeps_the_grants(world):
    from auspex.integrations.store import update

    moved = await update(world["pool"], workspace_id=world["m"].direct_ws,
                         actor=world["admin"], integration_id=world["integ"].id,
                         name="Main SIEM", config={**CONFIG, "base_url": "https://new.example"})
    assert moved.grants == ("close_alert",)


async def test_an_edit_cancels_a_queued_action_job(world):
    """Fresh review of S34, #3: a queued action job carries the old agent's config."""
    from auspex.connectors.kinds import ACTION_KINDS
    from auspex.integrations.store import update
    from auspex.jobs.queue import enqueue

    pool, m, integ = world["pool"], world["m"], world["integ"]
    job, _ = await enqueue(pool, workspace_id=m.direct_ws, kind=ACTION_KINDS["execute"],
                           idempotency_key="connector.execute:t", integration_id=integ.id,
                           payload={"config": CONFIG})
    await update(pool, workspace_id=m.direct_ws, actor=world["admin"],
                 integration_id=integ.id, config={**CONFIG, "base_url": "https://new.example"})
    row = await pool.fetchrow("SELECT status, last_error FROM jobs WHERE id = $1", job.id)
    assert row["status"] == "failed" and "cancelled" in row["last_error"]
