"""S26 — D-041 live: twins, a crashed run's clean-up, and the ordinary path,
through the running container's API.

No HTTP route files a proposal (chat's agent path offers no actions yet), so
proposals are filed with the real `ProposalSettlement` from the host — the same
code the agent loop's proposer calls — and every DECISION goes through
/api/proposals on the rebuilt container. A crashed run is reproduced the way
S21 did: by writing the row a dead process leaves (claimed, old claim) plus the
note its handler had landed. Everything created here is deleted at the end.

Run:  .venv/bin/python docs/probes/s26-step0/probe_terminal_states_live.py
"""

import asyncio
import sys

import httpx

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

from auspex.actions import ActionRegistry, ProposalSettlement  # noqa: E402
from auspex.actions.builtin import build_builtin_actions  # noqa: E402
from auspex.classify.observables import ObservableType, observable_id  # noqa: E402
from auspex.config import Settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

API = "http://localhost:8000/api"
VALUE = "s26-d041-live.test"


async def main() -> None:
    http = httpx.Client(timeout=30.0)
    token = http.post(f"{API}/auth/dev-login",
                      json={"email": "analyst@auspex.dev"}).json()["access_token"]
    hdr = {"Authorization": f"Bearer {token}"}
    pool = await create_pool(Settings().database_url)
    ws = await pool.fetchval("SELECT workspace_id FROM users WHERE email = 'analyst@auspex.dev'")
    obs = observable_id(ObservableType.DOMAIN, VALUE)
    await pool.execute(
        "INSERT INTO observables (workspace_id, obs_id, type, value) VALUES ($1, $2, 'domain', $3)"
        " ON CONFLICT (workspace_id, type, value) DO NOTHING", ws, obs, VALUE)
    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    spec = registry.get("annotate_observable")
    settlement = ProposalSettlement(pool)
    made = []

    async def file(note):
        args = {"observable_id": obs, "note": note}
        row = await settlement.file(workspace_id=ws, spec=spec, arguments=args,
                                    dry_run=await spec.dry_run(workspace_id=ws, **args))
        made.append(str(row["id"]))
        return str(row["id"])

    def card(pid):
        listed = http.get(f"{API}/proposals", headers=hdr).json()["proposals"]
        return next((p for p in listed if p["id"] == pid), None)

    try:
        print("[1] two identical requests and one different, filed by the real settlement")
        a, b, c = await file("same words"), await file("same words"), await file("other words")
        print(f"    twin A names: {card(a)['identical_pending'] == [b]}   "
              f"twin B names: {card(b)['identical_pending'] == [a]}   "
              f"the different one names nothing: {card(c)['identical_pending'] == []}")

        print("[2] reject twin A through the API")
        r = http.post(f"{API}/proposals/{a}/reject", headers=hdr)
        print(f"    {r.status_code} {r.json()['settled']}   "
              f"twin B now names nothing: {card(b)['identical_pending'] == []}")

        print("[3] a crashed run: approved, claimed an hour ago, its note already landed")
        await pool.execute("UPDATE proposals SET status = 'executing', decided_at = now(),"
                           " claimed_at = now() - interval '1 hour' WHERE id = $1::uuid", c)
        await spec.execute(workspace_id=ws, proposal_id=c, observable_id=obs,
                           note="landed before the crash")
        shown = card(c)
        print(f"    in the queue: {shown is not None}   status={shown and shown['status']}")
        r = http.post(f"{API}/proposals/{c}/abandon", headers=hdr)
        body = r.json()["proposal"]
        print(f"    abandon -> {r.status_code} status={body['status']} "
              f"abandoned_from={body['abandoned_from']}")
        r = http.post(f"{API}/proposals/{c}/undo", headers=hdr)
        notes = await pool.fetchval(
            "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid", c)
        print(f"    undo    -> {r.status_code} status={r.json()['proposal']['status']} "
              f"removed={r.json()['outcome']['detail']}   notes left: {notes}")

        print("[4] the ordinary path still works: approve twin B, then undo it")
        r = http.post(f"{API}/proposals/{b}/approve", headers=hdr)
        print(f"    approve -> {r.status_code} executed={r.json()['executed']} "
              f"status={r.json()['proposal']['status']}")
        r = http.post(f"{API}/proposals/{b}/undo", headers=hdr)
        print(f"    undo    -> {r.status_code} status={r.json()['proposal']['status']}")

        print("[5] a checked failure has nothing to put back")
        f = await file("never runs")
        await pool.execute("UPDATE proposals SET status = 'failed',"
                           " result = '{\"error\": \"RuntimeError\", \"effects\": \"none\"}'"
                           " WHERE id = $1::uuid", f)
        r = http.post(f"{API}/proposals/{f}/undo", headers=hdr)
        print(f"    undo of failed -> {r.status_code}: {r.json()['detail'][:70]}")
    finally:
        await pool.execute("DELETE FROM observable_notes WHERE proposal_id = ANY($1::uuid[])", made)
        await pool.execute("DELETE FROM proposals WHERE id = ANY($1::uuid[])", made)
        await pool.execute("DELETE FROM observables WHERE workspace_id = $1 AND value = $2",
                           ws, VALUE)
        await pool.close()
        http.close()


if __name__ == "__main__":
    asyncio.run(main())
