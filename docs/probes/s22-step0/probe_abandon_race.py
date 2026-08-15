"""S22 Step 0 — the settlement half of the review (9f023f0), against live Postgres.

Scope from NEXT-SESSION.md: `abandon` is a state transition a human can trigger,
so it gets raced the way S18 raced settlement 8-way — two concurrent abandons, an
abandon that races the handler *finishing*, abandon on a never-claimed row, and
abandon across a tenant boundary. Plus the `pending()` stale arm's tenancy.

The lead this probe exists to settle: `abandon` guards on claim age in the same
UPDATE that moves the row, which the docstring says means it "cannot kill a
handler that is still working". But the age guard only proves the claim is OLD,
not that the process holding it is DEAD — and a handler that legitimately runs
longer than STALE_CLAIM_SECONDS is exactly a row that is abandonable while alive.
So what happens when it finishes afterwards?

Residue discipline (S21's rule, and STATE.md's): this probe creates its own two
workspaces, deletes them at the end, and asserts 0 rows left behind.

Run: python docs/probes/s22-step0/probe_abandon_race.py
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# `.env` carries compose-internal hostnames; pin the host-mapped ports BEFORE
# Settings is first constructed, exactly as pytest and scripts/ do.
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

from auspex.actions import (  # noqa: E402
    ActionExecutor,
    ActionRegistry,
    ProposalSettlement,
    Settlement,
)
from auspex.actions import settlement as settlement_mod  # noqa: E402
from auspex.actions.builtin import build_builtin_actions  # noqa: E402
from auspex.classify.observables import ObservableType, observable_id  # noqa: E402
from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

FAILURES: list[str] = []
WS_NAMES = ("t-s22-probe", "t-s22-probe-other")


def check(name: str, got: object, want: object) -> None:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: got={got!r} want={want!r}")
    if not ok:
        FAILURES.append(name)


def report(name: str, got: object) -> None:
    print(f"  ..   {name}: {got!r}")


async def _workspace(pool, name: str):
    return await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        name,
    )


async def _observable(pool, workspace_id):
    value = "evil-s22-probe.test"
    obs_id = observable_id(ObservableType.DOMAIN, value)
    await pool.execute(
        """
        INSERT INTO observables (workspace_id, obs_id, type, value)
        VALUES ($1, $2, 'domain', $3)
        ON CONFLICT (workspace_id, type, value) DO NOTHING
        """,
        workspace_id,
        obs_id,
        value,
    )
    return obs_id


async def _file(pool, spec, workspace_id, obs_id, note="s22 step0 probe"):
    settlement = ProposalSettlement(pool)
    args = {"observable_id": obs_id, "note": note}
    dry = await spec.dry_run(workspace_id=workspace_id, **args)
    return settlement, await settlement.file(
        workspace_id=workspace_id, spec=spec, arguments=args, dry_run=dry
    )


async def _backdate(pool, pid, seconds: float):
    """Age the outstanding claim. This is what a handler that has been running
    longer than the threshold looks like — the SAME row shape a dead process
    leaves, which is the whole difficulty."""
    await pool.execute(
        "UPDATE proposals SET claimed_at = now() - make_interval(secs => $2::double precision)"
        " WHERE id = $1::uuid",
        str(pid),
        float(seconds),
    )


# --------------------------------------------------------------------------
# 1. THE RACE: a human abandons a claim whose handler is slow, not dead.
# --------------------------------------------------------------------------
async def probe_late_handler(pool, spec, ws, obs):
    print("\n[1] abandon races a handler that is slow, not dead")
    release = asyncio.Event()
    ran = asyncio.Event()

    async def slow_execute(**kwargs):
        ran.set()
        await release.wait()
        return await spec.execute(**kwargs)

    slow = dataclasses.replace(spec, execute=slow_execute)
    registry = ActionRegistry()
    registry.register(slow)

    settlement, proposal = await _file(pool, spec, ws, obs)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=ws, proposal_id=pid, decision="approved", decided_by=None
    )

    task = asyncio.create_task(
        ActionExecutor(pool, registry).execute(workspace_id=ws, proposal_id=pid)
    )
    await asyncio.wait_for(ran.wait(), timeout=10)  # claim is taken, handler is inside

    claimed = await settlement.get(workspace_id=ws, proposal_id=pid)
    check("handler holds the claim", claimed["status"], "executing")

    # It has now been running longer than the threshold. Indistinguishable, from
    # the row alone, from a process that died holding the claim.
    await _backdate(pool, pid, settlement_mod.STALE_CLAIM_SECONDS + 60)
    stale = [p for p in await settlement.pending(workspace_id=ws) if p["id"] == pid]
    check("a long-running handler surfaces in the human's queue", bool(stale), True)

    result = await settlement.abandon(workspace_id=ws, proposal_id=pid, decided_by=None)
    check("the human's abandon is accepted", result.outcome, Settlement.CLAIMED)
    after_abandon = await settlement.get(workspace_id=ws, proposal_id=pid)
    report("status right after abandon", after_abandon["status"])
    decided_at = after_abandon["decided_at"]

    # ...and now the handler finishes, as it was always going to.
    release.set()
    await asyncio.wait_for(task, timeout=10)

    final = await settlement.get(workspace_id=ws, proposal_id=pid)
    report("status after the handler returns", final["status"])
    report("decided_at unchanged by the handler", final["decided_at"] == decided_at)
    check("the handler does not overwrite the human's terminal decision",
          final["status"], "abandoned")

    # The note the action writes is the real-world effect. Whatever the row says,
    # this is what actually happened in the world.
    notes = await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid", str(pid)
    ) if await _has_table(pool, "observable_notes") else None
    report("side effect rows written by the late handler", notes)
    return pid


async def _has_table(pool, name: str) -> bool:
    return bool(await pool.fetchval("SELECT to_regclass($1)", f"public.{name}"))


# --------------------------------------------------------------------------
# 2. Two concurrent abandons on one row.
# --------------------------------------------------------------------------
async def probe_concurrent_abandon(pool, spec, ws, obs):
    print("\n[2] eight concurrent abandons on one dead claim")
    settlement, proposal = await _file(pool, spec, ws, obs)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=ws, proposal_id=pid, decision="approved", decided_by=None
    )
    await pool.execute(
        "UPDATE proposals SET status = 'executing',"
        " claimed_at = now() - make_interval(secs => $2::double precision)"
        " WHERE id = $1::uuid",
        str(pid),
        float(settlement_mod.STALE_CLAIM_SECONDS + 60),
    )
    results = await asyncio.gather(
        *[
            settlement.abandon(workspace_id=ws, proposal_id=pid, decided_by=None)
            for _ in range(8)
        ]
    )
    won = [r for r in results if r.outcome is Settlement.CLAIMED]
    check("exactly one abandon wins", len(won), 1)
    check("the other seven are told it was already decided",
          {r.outcome for r in results if r.outcome is not Settlement.CLAIMED},
          {Settlement.ALREADY_DECIDED})
    return pid


# --------------------------------------------------------------------------
# 3. Never-claimed, cross-tenant, and the pending() stale arm's tenancy.
# --------------------------------------------------------------------------
async def probe_edges(pool, spec, ws, other_ws, obs):
    print("\n[3] never-claimed, cross-tenant, and the stale arm's tenancy")
    settlement, proposal = await _file(pool, spec, ws, obs)
    pid = proposal["id"]

    never = await settlement.abandon(workspace_id=ws, proposal_id=pid, decided_by=None)
    check("abandon on a never-claimed row is refused",
          never.outcome, Settlement.ALREADY_DECIDED)
    check("...and leaves it pending_approval",
          (await settlement.get(workspace_id=ws, proposal_id=pid))["status"],
          "pending_approval")

    await pool.execute(
        "UPDATE proposals SET status = 'executing',"
        " claimed_at = now() - make_interval(secs => $2::double precision)"
        " WHERE id = $1::uuid",
        str(pid),
        float(settlement_mod.STALE_CLAIM_SECONDS + 60),
    )
    # The stale arm is a NEW way for a row to enter this query. Tenancy has to
    # hold on it specifically, not just on the pending_approval arm.
    theirs = [p for p in await settlement.pending(workspace_id=other_ws) if p["id"] == pid]
    check("the stale arm never leaks across a workspace boundary", theirs, [])
    mine = [p for p in await settlement.pending(workspace_id=ws) if p["id"] == pid]
    check("...and does surface in its own workspace", len(mine), 1)

    cross = await settlement.abandon(workspace_id=other_ws, proposal_id=pid, decided_by=None)
    check("cross-tenant abandon is NOT_FOUND, not 409", cross.outcome, Settlement.NOT_FOUND)

    # A stale claim must not be settleable through the ordinary approve/reject
    # buttons — that is precisely what `abandon` exists to be instead of.
    approve = await settlement.settle(
        workspace_id=ws, proposal_id=pid, decision="approved", decided_by=None
    )
    check("a stale claim cannot be approved through the ordinary button",
          approve.outcome, Settlement.ALREADY_DECIDED)
    reject = await settlement.settle(
        workspace_id=ws, proposal_id=pid, decision="rejected", decided_by=None
    )
    check("a stale claim cannot be rejected through the ordinary button",
          reject.outcome, Settlement.ALREADY_DECIDED)
    return pid


async def main() -> None:
    settings = get_settings()
    pool = await create_pool(settings.database_url, retries=3, delay=0.5)
    ws = await _workspace(pool, WS_NAMES[0])
    other_ws = await _workspace(pool, WS_NAMES[1])
    obs = await _observable(pool, ws)
    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    spec = registry.get("annotate_observable")

    try:
        await probe_late_handler(pool, spec, ws, obs)
        await probe_concurrent_abandon(pool, spec, ws, obs)
        await probe_edges(pool, spec, ws, other_ws, obs)
    finally:
        print("\n[cleanup]")
        for name in WS_NAMES:
            await pool.execute("DELETE FROM workspaces WHERE name = $1", name)
        left = await pool.fetchval(
            "SELECT count(*) FROM proposals p JOIN workspaces w ON w.id = p.workspace_id"
            " WHERE w.name = ANY($1::text[])",
            list(WS_NAMES),
        )
        check("probe residue", left, 0)
        await pool.close()

    print("\n" + "=" * 70)
    if FAILURES:
        print(f"FINDINGS: {len(FAILURES)}")
        for f in FAILURES:
            print(f"  - {f}")
    else:
        print("no findings")


if __name__ == "__main__":
    asyncio.run(main())
