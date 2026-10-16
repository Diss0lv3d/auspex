"""S31 (TD-025, D-066; spec §3): every execution attempt carries an
idempotency key, one per operation and stable across attempts, handed to
execute, undo and observe. The built-in note action uses it."""

import dataclasses

import pytest
from _tenancy import ensure_workspace

from auspex.actions import (
    STALE_CLAIM_SECONDS,
    ActionExecutor,
    ActionOutcome,
    ActionParam,
    ActionRegistry,
    ActionRisk,
    ActionScope,
    ActionSpec,
    ActionSpecError,
    ParamType,
    ProposalSettlement,
    UndoSpec,
    operation_key,
)
from auspex.actions.builtin import build_builtin_actions
from auspex.classify.observables import ObservableType, observable_id
from auspex.db import create_pool

WS = "t-s31-idem"


@pytest.fixture
async def pool(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    yield pool
    await pool.close()


@pytest.fixture
async def workspace_id(pool):
    ws = await ensure_workspace(pool, WS)
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


def _spy_spec(calls: list, *, fail_execute: bool = False) -> ActionSpec:
    async def would(**kw):
        return ActionOutcome(would="Would mark the spy.", affects=("spy",), reversible=True)

    async def run(**kw):
        calls.append(("execute", kw["idempotency_key"]))
        if fail_execute:
            raise RuntimeError("spy died")
        return ActionOutcome(would="Marked the spy.", affects=("spy",), reversible=True)

    async def put_back(**kw):
        calls.append(("undo", kw["idempotency_key"]))
        return ActionOutcome(would="Unmarked the spy.", affects=("spy",), reversible=True)

    async def look(**kw):
        calls.append(("observe", kw["idempotency_key"]))
        return 0

    return ActionSpec(
        name="spy_action",
        description="Record what the platform hands an action",
        risk=ActionRisk.WRITE,
        scope=(ActionScope(system="auspex", writes=True, detail="nothing"),),
        params=(),
        dry_run=would,
        execute=run,
        undo=UndoSpec(description="Unmark the spy", handler=put_back,
                      restores="the spy, unmarked"),
        observe=look,
    )


async def _approved(pool, spec, ws):
    settlement = ProposalSettlement(pool)
    dry = await spec.dry_run(workspace_id=ws)
    pid = (await settlement.file(workspace_id=ws, spec=spec, arguments={}, dry_run=dry))["id"]
    await settlement.settle(workspace_id=ws, proposal_id=pid, decision="approved",
                            decided_by=None)
    return pid


def _registry(spec) -> ActionRegistry:
    r = ActionRegistry()
    r.register(spec)
    return r


def test_each_operation_has_one_key():
    assert operation_key("p1", "execute") == "proposal:p1:execute"
    assert operation_key("p1", "undo") == "proposal:p1:undo"
    with pytest.raises(ValueError):
        operation_key("p1", "dry_run")


async def test_the_run_and_its_undo_get_their_operations_keys(pool, workspace_id):
    calls = []
    spec = _spy_spec(calls)
    pid = await _approved(pool, spec, workspace_id)
    executor = ActionExecutor(pool, _registry(spec))
    await executor.execute(workspace_id=workspace_id, proposal_id=pid)
    await executor.undo(workspace_id=workspace_id, proposal_id=pid)
    assert calls == [("execute", f"proposal:{pid}:execute"), ("undo", f"proposal:{pid}:undo")]


async def test_a_stale_approvals_run_carries_the_same_key(pool, workspace_id):
    calls = []
    spec = _spy_spec(calls)
    pid = await _approved(pool, spec, workspace_id)
    await pool.execute("UPDATE proposals SET decided_at = now() - make_interval(secs => $2)"
                       " WHERE id = $1", pid, float(STALE_CLAIM_SECONDS + 60))
    await ActionExecutor(pool, _registry(spec)).run_stale_approval(
        workspace_id=workspace_id, proposal_id=pid, run_by=None)
    assert calls == [("execute", f"proposal:{pid}:execute")]


async def test_the_look_after_a_failed_run_gets_the_runs_key(pool, workspace_id):
    calls = []
    spec = _spy_spec(calls, fail_execute=True)
    pid = await _approved(pool, spec, workspace_id)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _registry(spec)).execute(workspace_id=workspace_id,
                                                           proposal_id=pid)
    key = f"proposal:{pid}:execute"
    assert calls == [("execute", key), ("observe", key)]


@pytest.mark.parametrize("slot", ["execute", "undo", "observe"])
def test_a_handler_that_cannot_take_the_key_is_refused_at_registration(slot):
    async def narrow(*, workspace_id, proposal_id):
        return 0

    base = _spy_spec([])
    changes = {
        "execute": {"execute": narrow},
        "undo": {"undo": dataclasses.replace(base.undo, handler=narrow)},
        "observe": {"observe": narrow},
    }[slot]
    with pytest.raises(ActionSpecError, match="idempotency_key"):
        dataclasses.replace(base, **changes)


@pytest.mark.parametrize("name", ["idempotency_key", "workspace_id", "proposal_id"])
def test_a_parameter_named_like_a_platform_keyword_is_refused(name):
    with pytest.raises(ActionSpecError, match="platform"):
        dataclasses.replace(_spy_spec([]),
                            params=(ActionParam(name, ParamType.STRING, "a value"),))


async def test_the_note_action_run_twice_with_one_key_leaves_one_note(pool, workspace_id):
    value = "idem.test"
    obs = observable_id(ObservableType.DOMAIN, value)
    await pool.execute("INSERT INTO observables (workspace_id, obs_id, type, value)"
                       " VALUES ($1, $2, 'domain', $3)", workspace_id, obs, value)
    spec = build_builtin_actions(pool)[0]
    args = {"observable_id": obs, "note": "seen twice"}
    dry = await spec.dry_run(workspace_id=workspace_id, **args)
    pid = (await ProposalSettlement(pool).file(workspace_id=workspace_id, spec=spec,
                                               arguments=args, dry_run=dry))["id"]
    kw = dict(workspace_id=workspace_id, proposal_id=str(pid),
              idempotency_key=operation_key(pid, "execute"), **args)
    first = await spec.execute(**kw)
    second = await spec.execute(**kw)
    assert await pool.fetchval("SELECT count(*) FROM observable_notes WHERE proposal_id = $1",
                               pid) == 1
    assert first.detail["repeat"] is False and second.detail["repeat"] is True
