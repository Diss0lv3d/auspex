"""S28 — D-049 live: an indicator the agent looks up is recorded, so the same
turn can propose an action on it.

Before D-049 only the 92/8 IOC check recorded an observable, so S27's probe
had to run a shortcut turn first (D-045's bound). Here there is no shortcut
turn: one deep message names an indicator that has never been seen in the
workspace and asks for it to be checked AND annotated. Through `/api/chat`
against the rebuilt container:
- does `enrich_observable` run, and is the observable then in the workspace?
- does the same turn file the annotate proposal (not `NothingToPropose`)?

Every proposal this probe files is REJECTED afterwards. The observable is
deleted only if the probe created it. About 3-6 inference calls on the shared
`default` workspace. Do NOT run pytest at the same time.

Run:  .venv/bin/python docs/probes/s28-candidates/probe_app_agent_records.py
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
# A routable address never seen in this workspace. The first run used TEST-NET-3
# (203.0.113.84): enrichment skips reserved space, so nothing was looked up,
# nothing recorded, and the annotate call was refused as NothingToPropose --
# correct, and the same as the IOC check (raw log, run 1).
IOC = "185.220.101.47"
MESSAGE = (f"We saw {IOC} beaconing every 60s from the finance workstation fin-ws-12 since "
           "Tuesday. Check it, and add a note to it saying it was seen beaconing from "
           "fin-ws-12, so the next analyst has the context.")


async def observable_exists(pool, ws) -> bool:
    return bool(await pool.fetchval(
        "SELECT count(*) FROM observables WHERE workspace_id = $1 AND value = $2", ws, IOC))


async def main() -> None:
    pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
    ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = 'default'")
    existed = await observable_exists(pool, ws)
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
                  f"output_valid={done.get('output_valid')}")
            for f in frames:
                if "tool" in f:
                    t = f["tool"]
                    print(f"   tool: {t['call']} -> {t['status']}"
                          + (f"  PROPOSAL {t['proposal']['id'][:8]}: {t['proposal']['summary']}"
                             if "proposal" in t else ""))
            answer = "".join(f["content"] for f in frames if "content" in f)
            print("   answer: " + answer.replace("\n", "\n           "))
            print(f"observable in workspace after the turn: {await observable_exists(pool, ws)}")
            queued = (await http.get(f"{API}/proposals", headers=auth)).json()["proposals"]
            filed = [p for p in queued if p["id"] not in before]
            print(f"proposals filed this turn: {len(filed)}")
            for p in filed:
                print(f"   {p['id'][:8]} {p['action']} args={p['arguments']} "
                      f"summary={p['card']['summary']!r}")
                r = await http.post(f"{API}/proposals/{p['id']}/reject", headers=auth)
                print(f"      rejected (probe cleanup): {r.status_code}")
    finally:
        if not existed:
            await pool.execute(
                "DELETE FROM observables WHERE workspace_id = $1 AND value = $2", ws, IOC)
        await pool.close()


asyncio.run(main())
