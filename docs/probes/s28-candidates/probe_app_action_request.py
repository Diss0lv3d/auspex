"""S28 — D-050 live: a note-only request, through the running container.

S27 saw "add a note to X" resolve to ioc_enrichment and read
contract_valid:false; S28 measured a third of such requests taking the IOC
shortcut, where no model runs and no note is ever proposed. After D-050 the
request is a deep turn in `action_request`, a mode with no sections. Through
`/api/chat`:
- path, mode and contract_valid of a note-only turn;
- whether the proposal is filed (the indicator is new to the workspace, so the
  agent has to look it up first, which records it — D-049).

Every proposal filed is REJECTED afterwards; the observable is deleted only if
the probe created it. About 3-6 inference calls on the shared `default`
workspace. Do NOT run pytest at the same time.

Run:  .venv/bin/python docs/probes/s28-candidates/probe_app_action_request.py
"""

import asyncio
import json
import sys

import httpx

sys.path.insert(0, ".")
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

API = "http://localhost:8000/api"
IOC = "185.220.101.33"
MESSAGE = f"add a note to {IOC}: seen scanning the payroll WAF at 02:00 on Friday, blocked at the edge"


async def main() -> None:
    pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
    ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = 'default'")
    existed = bool(await pool.fetchval(
        "SELECT count(*) FROM observables WHERE workspace_id = $1 AND value = $2", ws, IOC))
    print(f"observable in workspace before the turn: {existed}")
    try:
        async with httpx.AsyncClient(timeout=240) as http:
            token = (await http.post(f"{API}/auth/dev-login",
                                     json={"email": "analyst@auspex.dev"})).json()["access_token"]
            auth = {"Authorization": f"Bearer {token}"}
            before = {p["id"] for p in
                      (await http.get(f"{API}/proposals", headers=auth)).json()["proposals"]}
            frames = []
            async with http.stream("POST", f"{API}/chat", json={"message": MESSAGE},
                                   headers=auth) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        frames.append(json.loads(line[5:].strip()))
            done = frames[-1].get("done", {})
            print(f"path={done.get('path')} mode={done.get('mode')} "
                  f"contract_valid={done.get('contract_valid')} output_valid={done.get('output_valid')}")
            for f in frames:
                if "tool" in f:
                    t = f["tool"]
                    print(f"   tool: {t['call']} -> {t['status']}"
                          + (f"  PROPOSAL {t['proposal']['id'][:8]}: {t['proposal']['summary']}"
                             if "proposal" in t else ""))
            answer = "".join(f["content"] for f in frames if "content" in f)
            print("   answer: " + answer.replace("\n", "\n           "))
            queued = (await http.get(f"{API}/proposals", headers=auth)).json()["proposals"]
            filed = [p for p in queued if p["id"] not in before]
            print(f"proposals filed this turn: {len(filed)}")
            for p in filed:
                print(f"   {p['id'][:8]} {p['action']} summary={p['card']['summary']!r}")
                r = await http.post(f"{API}/proposals/{p['id']}/reject", headers=auth)
                print(f"      rejected (probe cleanup): {r.status_code}")
    finally:
        if not existed:
            await pool.execute(
                "DELETE FROM observables WHERE workspace_id = $1 AND value = $2", ws, IOC)
        await pool.close()


asyncio.run(main())
