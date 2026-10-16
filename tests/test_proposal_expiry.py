"""S31 (TD-025, D-066; spec §3): a pending proposal nobody decided within
PROPOSAL_TTL_SECONDS expires. The refusal is in settlement's own UPDATE; the
sweep only makes the status visible. Against live Postgres."""

import pytest
from _tenancy import drop_orgs, ensure_workspace, make_membership_world, token

from auspex.actions import (
    PROPOSAL_TTL_SECONDS,
    STALE_CLAIM_SECONDS,
    ActionExecutor,
    ActionRegistry,
    ExecutionRefused,
    ProposalSettlement,
    Settlement,
)
from auspex.actions.builtin import build_builtin_actions
from auspex.classify.observables import ObservableType, observable_id
from auspex.db import create_pool
from auspex.routes.proposals import EXPIRED_DETAIL

PREFIX = "t-s31-ttl"


@pytest.fixture
async def pool(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    yield pool
    await pool.close()


async def _workspace_with_observable(pool, name):
    ws = await ensure_workspace(pool, name)
    value = f"{name}.test"
    obs = observable_id(ObservableType.DOMAIN, value)
    await pool.execute(
        "INSERT INTO observables (workspace_id, obs_id, type, value) VALUES ($1, $2, 'domain', $3)"
        " ON CONFLICT (workspace_id, type, value) DO NOTHING", ws, obs, value)
    return ws, obs


@pytest.fixture
async def world(pool):
    made = []

    async def make(name):
        ws, obs = await _workspace_with_observable(pool, f"{PREFIX}-{name}")
        made.append(ws)
        return ws, obs

    yield make
    for ws in made:
        await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


@pytest.fixture
def registry(pool):
    r = ActionRegistry()
    r.register_all(build_builtin_actions(pool))
    return r


async def _file(pool, registry, ws, obs):
    spec = registry.get("annotate_observable")
    args = {"observable_id": obs, "note": "seen at the edge"}
    dry = await spec.dry_run(workspace_id=ws, **args)
    return (await ProposalSettlement(pool).file(
        workspace_id=ws, spec=spec, arguments=args, dry_run=dry))["id"]


async def _age(pool, pid, seconds):
    await pool.execute("UPDATE proposals SET created_at = now() - make_interval(secs => $2)"
                       " WHERE id = $1", pid, float(seconds))


async def _status(pool, pid):
    return await pool.fetchval("SELECT status FROM proposals WHERE id = $1", pid)


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_a_decision_past_the_ttl_is_refused_and_the_row_reads_expired(
        pool, registry, world, decision):
    ws, obs = await world("late")
    pid = await _file(pool, registry, ws, obs)
    await _age(pool, pid, PROPOSAL_TTL_SECONDS + 1)
    out = await ProposalSettlement(pool).settle(workspace_id=ws, proposal_id=pid,
                                                decision=decision, decided_by=None)
    assert out.outcome is Settlement.EXPIRED and out.current_status == "expired"
    row = await pool.fetchrow("SELECT status, decided_at, resolved_at, resolved_by"
                              " FROM proposals WHERE id = $1", pid)
    assert row["status"] == "expired" and row["decided_at"] is None
    assert row["resolved_at"] is not None and row["resolved_by"] is None


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_a_decision_inside_the_ttl_still_settles(pool, registry, world, decision):
    ws, obs = await world("ontime")
    pid = await _file(pool, registry, ws, obs)
    await _age(pool, pid, PROPOSAL_TTL_SECONDS - 5)
    out = await ProposalSettlement(pool).settle(workspace_id=ws, proposal_id=pid,
                                                decision=decision, decided_by=None)
    assert out.won and await _status(pool, pid) == decision


async def test_an_expired_row_is_closed_to_every_door(pool, registry, world):
    ws, obs = await world("closed")
    pid = await _file(pool, registry, ws, obs)
    await _age(pool, pid, PROPOSAL_TTL_SECONDS + 1)
    settlement, executor = ProposalSettlement(pool), ActionExecutor(pool, registry)
    for decision in ("approved", "rejected"):
        out = await settlement.settle(workspace_id=ws, proposal_id=pid, decision=decision,
                                      decided_by=None)
        assert out.outcome is Settlement.EXPIRED
    await pool.execute("UPDATE proposals SET decided_at = now() - make_interval(secs => $2)"
                       " WHERE id = $1", pid, float(STALE_CLAIM_SECONDS + 60))
    for door in (settlement.withdraw, settlement.keep, settlement.abandon):
        assert not (await door(workspace_id=ws, proposal_id=pid, decided_by=None)).won
    with pytest.raises(ExecutionRefused) as ran:
        await executor.execute(workspace_id=ws, proposal_id=pid)
    assert ran.value.reason == "not_approved"
    with pytest.raises(ExecutionRefused) as stale:
        await executor.run_stale_approval(workspace_id=ws, proposal_id=pid, run_by=None)
    assert stale.value.reason == "not_approved"
    with pytest.raises(ExecutionRefused) as undo:
        await executor.undo(workspace_id=ws, proposal_id=pid)
    assert undo.value.reason == "not_executed"
    assert await _status(pool, pid) == "expired"
    assert await pool.fetchval("SELECT count(*) FROM observable_notes WHERE proposal_id = $1",
                               pid) == 0


async def test_the_sweep_expires_only_its_own_workspaces_overdue_rows(pool, registry, world):
    ws, obs = await world("mine")
    other_ws, other_obs = await world("theirs")
    overdue = await _file(pool, registry, ws, obs)
    fresh = await _file(pool, registry, ws, obs)
    theirs = await _file(pool, registry, other_ws, other_obs)
    await _age(pool, overdue, PROPOSAL_TTL_SECONDS + 1)
    await _age(pool, theirs, PROPOSAL_TTL_SECONDS + 1)
    await _age(pool, fresh, PROPOSAL_TTL_SECONDS - 5)
    assert await ProposalSettlement(pool).expire_overdue(workspace_id=ws) == 1
    assert await _status(pool, overdue) == "expired"
    assert await _status(pool, fresh) == "pending_approval"
    assert await _status(pool, theirs) == "pending_approval"
    assert await ProposalSettlement(pool).expire_overdue(workspace_id=ws) == 0  # a retry


async def test_an_expired_row_is_listed_for_a_day_then_not(pool, registry, world):
    ws, obs = await world("listed")
    pid = await _file(pool, registry, ws, obs)
    await _age(pool, pid, PROPOSAL_TTL_SECONDS + 1)
    settlement = ProposalSettlement(pool)
    await settlement.expire_overdue(workspace_id=ws)
    listed = {p["id"]: p["status"] for p in await settlement.pending(workspace_id=ws)}
    assert listed.get(pid) == "expired"
    await pool.execute("UPDATE proposals SET resolved_at = now() - make_interval(secs => $2)"
                       " WHERE id = $1", pid, float(PROPOSAL_TTL_SECONDS + 60))
    assert pid not in {p["id"] for p in await settlement.pending(workspace_id=ws)}


@pytest.mark.parametrize("door", ["approve", "reject"])
async def test_the_routes_answer_409_in_words_for_an_expired_proposal(
        pool, registry, client, settings, door):
    prefix = f"{PREFIX}-route-{door}"
    await drop_orgs(pool, prefix)
    try:
        ws, user = await make_membership_world(pool, prefix)
        value = f"{prefix}.test"
        obs = observable_id(ObservableType.DOMAIN, value)
        await pool.execute("INSERT INTO observables (workspace_id, obs_id, type, value)"
                           " VALUES ($1, $2, 'domain', $3)", ws, obs, value)
        pid = await _file(pool, registry, ws, obs)
        await _age(pool, pid, PROPOSAL_TTL_SECONDS + 1)
        resp = client.post(f"/api/proposals/{pid}/{door}", headers=token(settings, user, ws))
        assert resp.status_code == 409 and resp.json()["detail"] == EXPIRED_DETAIL
        assert EXPIRED_DETAIL == "expired: nobody decided within 24 h; propose it again"
    finally:
        await drop_orgs(pool, prefix)
