"""B2 — reproduce B-004: a note on a RECORDED indicator refused as "doesn't exist".

F1's two turns, through the running container's `/api/chat` (agent path, the
dev endpoint), each in a NEW chat as the page sends them:

  turn 1 (once): F1's "check it, and add a note" — the agent looks the
          indicator up, which records it (D-049), and proposes the note;
  turn 2 (x3):   F1's note-only request, in a fresh chat with no history.

For every turn: path, mode, each tool line as the page shows it (the
arguments the model passed, and the tool's status), the answer, and whether a
proposal was filed. Before turn 2 the observable's row is read back, so
"it existed" is a fact of this run, not of F1's.

Every proposal filed is REJECTED afterwards; the observable is deleted only if
this probe created it. About 10-15 inference calls on the shared `default`
workspace. Do NOT run pytest at the same time.

Run:  .venv/bin/python docs/probes/b2-b004/probe_repro.py --runs 3
"""

import argparse
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
IOC = "185.220.101.52"
TURN1 = (f"We saw {IOC} beaconing every 60s from the finance workstation fin-ws-12 since "
         "Tuesday. Check it, and add a note to it saying it was seen beaconing from "
         "fin-ws-12, so the next analyst has the context.")
TURN2 = f"Add a note to {IOC} saying the beaconing stopped after fin-ws-12 was reimaged."


async def turn(http, auth, message) -> dict:
    frames = []
    async with http.stream("POST", f"{API}/chat", json={"message": message},
                           headers=auth) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[5:].strip()))
    done = next((f["done"] for f in frames if "done" in f), {})
    tools = [f["tool"] for f in frames if "tool" in f]
    return {
        "path": done.get("path"), "mode": done.get("mode"),
        "finish": done.get("finish_reason"), "output_valid": done.get("output_valid"),
        "tools": [{"call": t.get("call"), "status": t.get("status"),
                   "proposal": (t.get("proposal") or {}).get("summary")} for t in tools],
        "answer": "".join(f["content"] for f in frames if "content" in f),
        "errors": [f["error"] for f in frames if "error" in f],
    }


async def main(args) -> None:
    pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
    ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = 'default'")
    existed = bool(await pool.fetchval(
        "SELECT count(*) FROM observables WHERE workspace_id = $1 AND value = $2", ws, IOC))
    print(f"observable in workspace before the probe: {existed}")
    rows = []
    try:
        async with httpx.AsyncClient(timeout=600) as http:
            token = (await http.post(f"{API}/auth/dev-login",
                                     json={"email": "b2-probe@auspex.dev"})).json()["access_token"]
            auth = {"Authorization": f"Bearer {token}"}
            before = {p["id"] for p in
                      (await http.get(f"{API}/proposals", headers=auth)).json()["proposals"]}
            plan = [("turn1", TURN1)] + [("turn2", TURN2)] * args.runs
            for i, (label, message) in enumerate(plan, 1):
                if label == "turn2":
                    row = await pool.fetchrow(
                        "SELECT obs_id, value FROM observables "
                        "WHERE workspace_id = $1 AND value = $2", ws, IOC)
                    print(f"  [row before {label}] {dict(row) if row else None}")
                r = await turn(http, auth, message)
                rows.append({"n": i, "turn": label, "message": message, **r})
                print(f"{i} {label}: path={r['path']} mode={r['mode']} finish={r['finish']} "
                      f"output_valid={r['output_valid']}", flush=True)
                for t in r["tools"]:
                    print(f"     tool: {t['call']} -> {t['status']}"
                          + (f"  PROPOSAL: {t['proposal']}" if t["proposal"] else ""))
                print("     answer: " + r["answer"].strip().replace("\n", "\n             "))
            queued = (await http.get(f"{API}/proposals", headers=auth)).json()["proposals"]
            filed = [p for p in queued if p["id"] not in before]
            print(f"\nproposals filed by this probe: {len(filed)}")
            for p in filed:
                r = await http.post(f"{API}/proposals/{p['id']}/reject", headers=auth)
                print(f"   {p['id'][:8]} {p['action']} -> rejected (cleanup): {r.status_code}")
    finally:
        (args.out).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        if not existed:
            await pool.execute(
                "DELETE FROM observables WHERE workspace_id = $1 AND value = $2", ws, IOC)
            print("observable deleted (this probe created it)")
        await pool.close()


if __name__ == "__main__":
    from pathlib import Path

    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--out", type=Path,
                   default=Path(__file__).resolve().parent / "raw-repro-before.jsonl")
    asyncio.run(main(p.parse_args()))
