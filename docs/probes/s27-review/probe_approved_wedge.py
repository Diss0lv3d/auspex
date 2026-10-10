"""S27 review: an approved row whose run never claimed has no door and no queue slot."""
import asyncio, sys
sys.path.insert(0, ".")  # run from the repo root with .venv/bin/python
from auspex.devhost import pin_host_defaults; pin_host_defaults()
from auspex.config import get_settings
from auspex.db import create_pool
from auspex.actions import ActionRegistry, ProposalSettlement
from auspex.actions.builtin import build_builtin_actions
from auspex.classify.observables import ObservableType, observable_id

async def main():
    pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
    ws = await pool.fetchval("INSERT INTO workspaces (name) VALUES ('s27-wedge-probe') RETURNING id")
    try:
        obs = observable_id(ObservableType.DOMAIN, "wedge.test")
        await pool.execute("INSERT INTO observables (workspace_id, obs_id, type, value) VALUES ($1,$2,'domain','wedge.test')", ws, obs)
        reg = ActionRegistry(); reg.register_all(build_builtin_actions(pool))
        spec = reg.get("annotate_observable"); s = ProposalSettlement(pool)
        args = {"observable_id": obs, "note": "n"}
        p = await s.file(workspace_id=ws, spec=spec, arguments=args, dry_run=await spec.dry_run(workspace_id=ws, **args))
        await s.settle(workspace_id=ws, proposal_id=p["id"], decision="approved", decided_by=None)
        # the process dies here: approved, never claimed
        print("in queue:", any(r["id"] == p["id"] for r in await s.pending(workspace_id=ws)))
        print("reject:", (await s.settle(workspace_id=ws, proposal_id=p["id"], decision="rejected", decided_by=None)).outcome)
        print("abandon:", (await s.abandon(workspace_id=ws, proposal_id=p["id"], decided_by=None)).outcome)
        print("keep:", (await s.keep(workspace_id=ws, proposal_id=p["id"], decided_by=None)).outcome)
        print("status:", (await s.get(workspace_id=ws, proposal_id=p["id"]))["status"])
    finally:
        await pool.execute("DELETE FROM workspaces WHERE id = $1", ws); await pool.close()

asyncio.run(main())
