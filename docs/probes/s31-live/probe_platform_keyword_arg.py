"""S31: an action argument named like a platform keyword, supplied at propose
time, is filed and approved, then wrecks the run (found by S31's review of the
idempotency key; reproduced here before it was logged).

`validate_spec` refuses a DECLARED parameter named `workspace_id`,
`proposal_id` or `idempotency_key`, but nothing drops an UNDECLARED argument a
caller (the model, through the agent loop) puts in a proposal's arguments: the
note action's dry run swallows it in `**_`, so the card files, and the approved
run then passes the keyword twice.

Run from the repo root with the .venv active (in-process, the dev Postgres):

    python docs/probes/s31-live/probe_platform_keyword_arg.py

Rows live under the `t-s31-kwarg` prefix and are dropped at the end.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()  # host DSN (port 55432), as the suite does

from _tenancy import drop_orgs, make_membership_world  # noqa: E402

from auspex.actions import ActionExecutor, ActionRegistry, ProposalSettlement  # noqa: E402
from auspex.actions.builtin import build_builtin_actions  # noqa: E402
from auspex.classify.observables import ObservableType, observable_id  # noqa: E402
from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

PREFIX = "t-s31-kwarg"


async def main() -> None:
    pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        ws, _ = await make_membership_world(pool, PREFIX)
        value = "s31-kwarg.example"
        obs = observable_id(ObservableType.DOMAIN, value)
        await pool.execute("INSERT INTO observables (workspace_id, obs_id, type, value)"
                           " VALUES ($1, $2, 'domain', $3)", ws, obs, value)
        registry = ActionRegistry()
        registry.register_all(build_builtin_actions(pool))
        spec = registry.get("annotate_observable")
        for extra in ("idempotency_key", "proposal_id"):
            args = {"observable_id": obs, "note": "a note", extra: "model-chosen"}
            dry = await spec.dry_run(workspace_id=ws, **args)
            print(f"[{extra}] dry run affects: {dry.affects}")
            settlement = ProposalSettlement(pool)
            pid = (await settlement.file(workspace_id=ws, spec=spec, arguments=args,
                                         dry_run=dry))["id"]
            settled = await settlement.settle(workspace_id=ws, proposal_id=pid,
                                              decision="approved", decided_by=None)
            print(f"[{extra}] filed and approved: {settled.outcome.value}")
            try:
                await ActionExecutor(pool, registry).execute(workspace_id=ws, proposal_id=pid)
                print(f"[{extra}] execute: ran")
            except Exception as exc:  # noqa: BLE001 — the point is what it raises
                print(f"[{extra}] execute raised: {type(exc).__name__}: {exc}")
            row = await pool.fetchrow("SELECT status, result FROM proposals WHERE id = $1", pid)
            notes = await pool.fetchval(
                "SELECT count(*) FROM observable_notes WHERE proposal_id = $1", pid)
            print(f"[{extra}] row: status={row['status']} result={row['result']} notes={notes}")
    finally:
        await drop_orgs(pool, PREFIX)
        left = await pool.fetchval(
            "SELECT count(*) FROM organizations WHERE starts_with(name, $1)", PREFIX)
        print(f"cleanup: organizations left {left}")
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
