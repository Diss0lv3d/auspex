"""S28 — D-048 live, through the running container: an approval no run ever
started rejoins the queue and both doors open.

Setup writes the state a process death leaves behind (the S27 reproduction,
`docs/probes/s27-review/probe_approved_wedge.py`): two proposals filed and
settled `approved` with no run, their approvals aged past STALE_CLAIM_SECONDS.
Everything after that goes through HTTP as the dev-login analyst:
- GET /api/proposals lists both;
- POST /execute runs one (and a second press is refused);
- POST /withdraw withdraws the other;
- the run is put back with POST /undo.

The probe's rows are deleted at the end. It spends no inference. Do NOT run
pytest at the same time: the suite purges the shared dev user.

Run:  .venv/bin/python docs/probes/s28-td042/probe_app_stale_approval.py
"""

import asyncio
import sys

import httpx

sys.path.insert(0, ".")
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
from auspex.actions import ActionRegistry, ProposalSettlement  # noqa: E402
from auspex.actions.builtin import build_builtin_actions  # noqa: E402
from auspex.actions.settlement import STALE_CLAIM_SECONDS  # noqa: E402
from auspex.classify.observables import ObservableType, observable_id  # noqa: E402
from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

API = "http://localhost:8000/api"
VALUE = "s28-stale-approval.test"


async def main() -> None:
    pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
    pids: list = []
    async with httpx.AsyncClient(timeout=30) as http:
        token = (await http.post(f"{API}/auth/dev-login",
                                 json={"email": "analyst@auspex.dev"})).json()["access_token"]
        hdr = {"Authorization": f"Bearer {token}"}
        ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = 'default'")
        obs = observable_id(ObservableType.DOMAIN, VALUE)
        await pool.execute(
            "INSERT INTO observables (workspace_id, obs_id, type, value) VALUES ($1,$2,'domain',$3)"
            " ON CONFLICT (workspace_id, type, value) DO NOTHING", ws, obs, VALUE)
        try:
            reg = ActionRegistry()
            reg.register_all(build_builtin_actions(pool))
            spec = reg.get("annotate_observable")
            s = ProposalSettlement(pool)
            for note in ("run me now", "withdraw me"):
                args = {"observable_id": obs, "note": f"s28 probe: {note}"}
                p = await s.file(workspace_id=ws, spec=spec, arguments=args,
                                 dry_run=await spec.dry_run(workspace_id=ws, **args))
                await s.settle(workspace_id=ws, proposal_id=p["id"], decision="approved",
                               decided_by=None)
                pids.append(p["id"])
            run_id, wd_id = (str(p) for p in pids)

            early = await http.post(f"{API}/proposals/{run_id}/execute", headers=hdr)
            print(f"fresh approval, execute: {early.status_code} {early.json()['detail']!r}")

            # the process "died" a while ago
            await pool.execute(
                "UPDATE proposals SET decided_at = now() - make_interval(secs => $2::double precision)"
                " WHERE id = ANY($1::uuid[])", pids, float(STALE_CLAIM_SECONDS + 60))
            listed = {p["id"]: p for p in
                      (await http.get(f"{API}/proposals", headers=hdr)).json()["proposals"]}
            print(f"in queue once stale: run={run_id in listed} withdraw={wd_id in listed} "
                  f"(status {listed.get(run_id, {}).get('status')})")

            ran = await http.post(f"{API}/proposals/{run_id}/execute", headers=hdr)
            body = ran.json()
            print(f"execute: {ran.status_code} executed={body.get('executed')} "
                  f"status={body['proposal']['status']} resolved_at set="
                  f"{body['proposal']['resolved_at'] is not None} did={body['outcome']['did']!r}")
            again = await http.post(f"{API}/proposals/{run_id}/execute", headers=hdr)
            print(f"execute again: {again.status_code} {again.json()['detail']!r}")

            wd = await http.post(f"{API}/proposals/{wd_id}/withdraw", headers=hdr)
            print(f"withdraw: {wd.status_code} status={wd.json()['proposal']['status']}")
            undo_wd = await http.post(f"{API}/proposals/{wd_id}/undo", headers=hdr)
            print(f"undo a withdrawn row: {undo_wd.status_code}")

            notes = await pool.fetchval(
                "SELECT count(*) FROM observable_notes WHERE proposal_id = ANY($1::uuid[])", pids)
            print(f"notes written: {notes} (expected 1: the run, not the withdrawal)")
            put_back = await http.post(f"{API}/proposals/{run_id}/undo", headers=hdr)
            print(f"undo the run: {put_back.status_code} "
                  f"status={put_back.json().get('proposal', {}).get('status')}")
            still = {p["id"] for p in
                     (await http.get(f"{API}/proposals", headers=hdr)).json()["proposals"]}
            print(f"left in queue: {[p for p in (run_id, wd_id) if p in still]}")
        finally:
            await pool.execute("DELETE FROM observable_notes WHERE proposal_id = ANY($1::uuid[])",
                               pids)
            await pool.execute("DELETE FROM proposals WHERE id = ANY($1::uuid[])", pids)
            await pool.execute("DELETE FROM observables WHERE workspace_id = $1 AND obs_id = $2",
                               ws, obs)
            await pool.close()


asyncio.run(main())
