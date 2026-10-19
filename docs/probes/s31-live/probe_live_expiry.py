"""S31 live check (Task 9): a proposal nobody decided expires through the REAL
job in the rebuilt app container, and approve answers 409 in the server's words.

Run from the repo root with the .venv active, after `./ci.sh` rebuilt the app
container (its worker is on: JOBS_WORKER_ENABLED defaults true there):

    python docs/probes/s31-live/probe_live_expiry.py setup     # seed + age
    python docs/probes/s31-live/probe_live_expiry.py watch     # wait for the job, read it, approve via HTTP
    python docs/probes/s31-live/probe_live_expiry.py cleanup   # delete everything it made

Everything lives under the `t-s31-live` prefix (an organization, its workspace,
one analyst, one observable, two proposals); cleanup drops the organization,
which cascades to the workspace, its proposals, its jobs and its job turn.
The token it writes for the browser check goes to the session scratchpad,
never into the repo. Synthetic data only.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()  # host DSN (port 55432), as the suite does

from _tenancy import drop_orgs, make_membership_world  # noqa: E402

from auspex.actions import PROPOSAL_TTL_SECONDS, ProposalSettlement  # noqa: E402
from auspex.actions.builtin import build_builtin_actions  # noqa: E402
from auspex.auth import issue_jwt  # noqa: E402
from auspex.classify.observables import ObservableType, observable_id  # noqa: E402
from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

PREFIX = "t-s31-live"
APP = "http://localhost:8000"
STATE = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/s31-live-state.json")


async def setup(pool) -> dict:
    await drop_orgs(pool, PREFIX)
    ws, user = await make_membership_world(pool, PREFIX)
    value = "s31-live.example"
    obs = observable_id(ObservableType.DOMAIN, value)
    await pool.execute("INSERT INTO observables (workspace_id, obs_id, type, value)"
                       " VALUES ($1, $2, 'domain', $3)", ws, obs, value)
    spec = build_builtin_actions(pool)[0]
    settlement = ProposalSettlement(pool)
    ids = []
    for note in ("the one nobody decided", "the one still waiting"):
        args = {"observable_id": obs, "note": note}
        dry = await spec.dry_run(workspace_id=ws, **args)
        ids.append((await settlement.file(workspace_id=ws, spec=spec, arguments=args,
                                          dry_run=dry))["id"])
    late, fresh = ids
    await pool.execute("UPDATE proposals SET created_at = now() - make_interval(secs => $2)"
                       " WHERE id = $1", late, float(PROPOSAL_TTL_SECONDS + 60))
    token = issue_jwt(get_settings(), user, ws)
    state = {"workspace": str(ws), "user": str(user), "late": str(late), "fresh": str(fresh),
             "token": token, "seeded_at": time.time()}
    print(json.dumps({k: v for k, v in state.items() if k != "token"}, indent=2))
    return state


async def watch(pool, state: dict) -> None:
    late = state["late"]
    started = time.monotonic()
    status = None
    while time.monotonic() - started < 340:
        status = await pool.fetchval("SELECT status FROM proposals WHERE id = $1::uuid", late)
        if status == "expired":
            break
        await asyncio.sleep(5)
    waited = round(time.monotonic() - started)
    print(f"late proposal: {status} after {waited} s of watching")
    rows = await pool.fetch(
        "SELECT kind, idempotency_key, status, attempts, claimed_by, result, last_error,"
        "       finished_at - created_at AS took"
        "  FROM jobs WHERE workspace_id = $1::uuid ORDER BY created_at", state["workspace"])
    for r in rows:
        print("job:", dict(r))
    fresh = await pool.fetchval("SELECT status FROM proposals WHERE id = $1::uuid",
                                state["fresh"])
    print(f"fresh proposal: {fresh}")
    resolved = await pool.fetchrow("SELECT resolved_at, resolved_by, decided_at FROM proposals"
                                   " WHERE id = $1::uuid", late)
    print("late row:", dict(resolved))
    headers = {"Authorization": f"Bearer {state['token']}"}
    with httpx.Client(base_url=APP, timeout=10) as http:
        for door in ("approve", "reject"):
            r = http.post(f"/api/proposals/{late}/{door}", headers=headers)
            print(f"POST {door}: {r.status_code} {r.json()}")
        listed = http.get("/api/proposals", headers=headers).json()
        print("listed:", [(p["id"][:8], p["status"]) for p in listed["proposals"]])


async def main() -> None:
    step = sys.argv[1]
    pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
    try:
        if step == "setup":
            STATE.write_text(json.dumps(await setup(pool)))
        elif step == "watch":
            await watch(pool, json.loads(STATE.read_text()))
        elif step == "cleanup":
            await drop_orgs(pool, PREFIX)
            left = await pool.fetchval(
                "SELECT count(*) FROM organizations WHERE starts_with(name, $1)", PREFIX)
            print(f"cleanup: organizations left {left}")
        else:
            raise SystemExit(f"unknown step {step!r}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
