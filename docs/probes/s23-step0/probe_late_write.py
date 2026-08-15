"""S23 Step 0 — angle 3: `_finish_claim`'s NEW late-write path (4957b5e).

S22 made `abandon` a second writer to a claim, then made each completion guard on
the status it claimed. That fixed the overwrite. It also introduced a *third*
writer: the late handler now writes its answer onto the terminal `abandoned` row
via a second, unguarded-by-claim statement.

Two sharp questions NEXT-SESSION.md asked about that new path, neither of which
S22 raced:

  1. TWO late handlers. The late-write is guarded on `<column> IS NULL`, so the
     first should win and the second should be a silent no-op. Measured, not
     assumed — and the row must NOT move in either case.

  2. CROSS-COLUMN. The late-write matches on `status = 'abandoned'`, which does
     not record WHICH operation was abandoned. `execute` abandons to 'abandoned'
     and so does `undo`. So can an `undo` late-write land on a row that was
     abandoned during `execute`, stamping an `undo_result` for an undo that
     never legitimately began?

Discipline: assert the REASON. Every claim below reads the row back and checks
the fields that would differ, not just a boolean return.

Residue: creates its own workspace, deletes it, asserts 0 rows left.

Run: python docs/probes/s23-step0/probe_late_write.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_REPO = Path(os.environ.get("AUSPEX_REPO", Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(_REPO))

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

from auspex.actions import ActionExecutor, ActionRegistry, ProposalSettlement  # noqa: E402
from auspex.actions.builtin import build_builtin_actions  # noqa: E402
from auspex.classify.observables import ObservableType, observable_id  # noqa: E402
from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

FINDINGS: list[str] = []
PASSED: list[str] = []
WS_NAME = "t-s23-latewrite"


def record(ok: bool, label: str, detail: str = "") -> None:
    (PASSED if ok else FINDINGS).append(label + (f" — {detail}" if detail else ""))
    print(("  ok   " if ok else "  FIND ") + label + (f" — {detail}" if detail else ""))


async def _workspace(pool):
    return await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        WS_NAME,
    )


async def _observable(pool, ws):
    value = "evil-s23-latewrite.test"
    obs = observable_id(ObservableType.DOMAIN, value)
    await pool.execute(
        "INSERT INTO observables (workspace_id, obs_id, type, value)"
        " VALUES ($1, $2, 'domain', $3)"
        " ON CONFLICT (workspace_id, type, value) DO NOTHING",
        ws,
        obs,
        value,
    )
    return obs


async def _abandoned_row(pool, spec, ws, obs, *, from_status: str):
    """A row sitting in 'abandoned', abandoned out of `from_status`."""
    settlement = ProposalSettlement(pool)
    args = {"observable_id": obs, "note": "s23 late-write probe"}
    dry = await spec.dry_run(workspace_id=ws, **args)
    proposal = await settlement.file(workspace_id=ws, spec=spec, arguments=args, dry_run=dry)
    pid = proposal["id"]
    await settlement.settle(workspace_id=ws, proposal_id=pid, decision="approved", decided_by=None)
    # Put the row in the claimed state the handler would hold, backdated so the
    # human's abandon is legal, then abandon it — through the real transition.
    await pool.execute(
        "UPDATE proposals SET status = $2, claimed_at = now() - interval '1 hour'"
        " WHERE id = $1::uuid",
        str(pid),
        from_status,
    )
    res = await settlement.abandon(workspace_id=ws, proposal_id=pid, decided_by=None)
    assert res.won, f"abandon did not take: {res.outcome}"
    return settlement, pid


async def main():
    pool = await create_pool(get_settings().database_url)
    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    spec = registry.get("annotate_observable")
    ws = await _workspace(pool)
    obs = await _observable(pool, ws)
    executor = ActionExecutor(pool, registry)

    # -- 1. two late handlers race -----------------------------------------
    print("\n[1] two late handlers write onto the same abandoned row")
    settlement, pid = await _abandoned_row(pool, spec, ws, obs, from_status="executing")
    before = await settlement.get(workspace_id=ws, proposal_id=pid)

    a, b = await asyncio.gather(
        executor._finish_claim(
            pid,
            from_status="executing",
            to_status="executed",
            column="result",
            payload={"who": "first"},
        ),
        executor._finish_claim(
            pid,
            from_status="executing",
            to_status="failed",
            column="result",
            payload={"who": "second"},
        ),
    )
    after = await settlement.get(workspace_id=ws, proposal_id=pid)
    result = after["result"]
    if isinstance(result, str):
        result = json.loads(result)

    record(
        a is False and b is False,
        "neither late handler believes it held the claim",
        f"returns={a},{b}",
    )
    record(
        after["status"] == "abandoned",
        "the row did not move off 'abandoned'",
        f"status={after['status']}",
    )
    record(
        after["decided_by"] == before["decided_by"] and after["decided_at"] == before["decided_at"],
        "the human's decision fields are untouched",
        f"decided_at={after['decided_at']}",
    )
    record(
        result is not None and result.get("who") in ("first", "second"),
        "exactly one late answer landed, and it is one of the two real ones",
        f"result={result!r}",
    )

    # -- 2. cross-column: an undo late-write on an EXECUTE-abandoned row ----
    print("\n[2] an undo late-write aimed at a row abandoned during execute")
    settlement2, pid2 = await _abandoned_row(pool, spec, ws, obs, from_status="executing")
    landed = await executor._finish_claim(
        pid2,
        from_status="undoing",
        to_status="executed",
        column="undo_result",
        payload={"who": "undo-that-never-ran"},
    )
    row2 = await settlement2.get(workspace_id=ws, proposal_id=pid2)
    undo_result = row2["undo_result"]
    if isinstance(undo_result, str):
        undo_result = json.loads(undo_result)

    record(landed is False, "the undo late-write did not hold a claim", f"returned={landed}")
    record(row2["status"] == "abandoned", "the row stayed 'abandoned'", f"status={row2['status']}")
    record(
        undo_result is None,
        "CROSS-COLUMN: an undo_result was NOT stamped on a row abandoned during execute",
        f"undo_result={undo_result!r} — status alone does not record WHICH op was abandoned",
    )

    # -- 3. is [2] REACHABLE? ----------------------------------------------
    # [2] called the private helper directly. That proves the STATEMENT is one
    # column short of its own intent; it does not prove anything can reach it.
    # `undo` claims `WHERE status = 'executed'`, so an undo handler can only be
    # in flight on a row that was 'executed' — and abandon then moves it out of
    # 'undoing', never out of 'executing'. Measured, not read:
    print("\n[3] can a real undo even start on a row abandoned during execute?")
    settlement3, pid3 = await _abandoned_row(pool, spec, ws, obs, from_status="executing")
    try:
        await executor.undo(workspace_id=ws, proposal_id=pid3)
        reachable, why = True, "undo() was accepted on an abandoned row"
    except Exception as exc:
        reachable = False
        why = f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
    record(
        not reachable,
        "REACHABILITY: a real undo cannot start on a row abandoned during execute",
        why,
    )

    # -- cleanup -----------------------------------------------------------
    await pool.execute("DELETE FROM proposals WHERE workspace_id = $1::uuid", ws)
    await pool.execute("DELETE FROM observables WHERE workspace_id = $1::uuid", ws)
    await pool.execute("DELETE FROM workspaces WHERE id = $1::uuid", ws)
    left = await pool.fetchval("SELECT count(*) FROM proposals WHERE workspace_id = $1::uuid", ws)
    print(f"\nresidue: {left} rows (must be 0)")
    await pool.close()
    assert left == 0

    print("\n================ SUMMARY ================")
    print(f"pinned sound: {len(PASSED)}")
    print(f"FINDINGS:     {len(FINDINGS)}")
    for f in FINDINGS:
        print(f"  - {f}")


if __name__ == "__main__":
    asyncio.run(main())
