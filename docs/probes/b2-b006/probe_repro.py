"""B2 — reproduce B-006: a follow-up on a no-signal IP calls it "clean".

B1's two turns (docs/probes/b1-b001/probe_app_dig_deeper.py), in a fresh chat
per run, through the app run in this process (uvicorn :8011, host-pinned, KB
on) so that what the MODEL READS is captured, not only what the page shows:

  1. "what do you know about this IP: 34.187.179.218"   (IOC check, no model)
  2. "dig deeper"                                        (deep turn)

For turn 2: path, mode, each tool frame, every tool result exactly as the next
endpoint call carried it (role "tool"), the answer, and the words in the answer
that call the address clean/benign/safe or say it is unknown. Raw text goes to
raw-repro-<label>.jsonl beside this file. The observable is deleted only if
this run created it; proposals filed are rejected. Do NOT run pytest at the
same time.

Run:  .venv/bin/python docs/probes/b2-b006/probe_repro.py --runs 3 --label before
"""

import argparse
import asyncio
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, ".")
os.environ["KB_ENABLED"] = "true"
os.environ["ENRICHMENT_ENABLED"] = "true"  # B-006 is about what the sources returned
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from auspex.config import Settings  # noqa: E402
from auspex.llm.client import LLMClient  # noqa: E402

HERE = Path(__file__).resolve().parent
PORT = 8011
API = f"http://127.0.0.1:{PORT}/api"
IOC = "34.187.179.218"
TURN1 = f"what do you know about this IP: {IOC}"
TURN2 = "dig deeper"
CLAIM_RE = re.compile(r"\b(clean|benign|safe|legitimate|harmless|no (?:known )?malicious\w*"
                      r"|unknown|not (?:been )?(?:checked|assessed)|no signals?)\b", re.IGNORECASE)

CALLS: list[list[dict]] = []
_orig_stream = LLMClient.chat_stream


def _captured_stream(self, messages, **kw):
    CALLS.append([dict(m) for m in messages])
    return _orig_stream(self, messages, **kw)


LLMClient.chat_stream = _captured_stream


def _start_server():
    os.environ["DEV_LLM_REGISTRY_FILE"] = ""
    from auspex.app import create_app

    app = create_app(Settings())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    deadline = time.monotonic() + 60
    while not app.state.kb.bootstrapped and time.monotonic() < deadline:
        time.sleep(0.25)
    return app


async def turn(http, auth, message, session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    frames = []
    async with http.stream("POST", f"{API}/chat", json=body, headers=auth) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[5:].strip()))
    return frames


async def main(args) -> None:
    app = _start_server()
    from auspex.db import create_pool

    pool = await create_pool(Settings().database_url, retries=2, delay=0.5)
    ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = 'default'")
    existed = bool(await pool.fetchval(
        "SELECT count(*) FROM observables WHERE workspace_id = $1 AND value = $2", ws, IOC))
    print(f"observable in workspace before: {existed}; kb={app.state.kb.bootstrapped}")
    out = (HERE / f"raw-repro-{args.label}.jsonl").open("w")
    try:
        async with httpx.AsyncClient(timeout=600) as http:
            token = (await http.post(f"{API}/auth/dev-login",
                                     json={"email": "b2-probe@auspex.dev"})).json()["access_token"]
            auth = {"Authorization": f"Bearer {token}"}
            for run in range(1, args.runs + 1):
                before = {p["id"] for p in
                          (await http.get(f"{API}/proposals", headers=auth)).json()["proposals"]}
                CALLS.clear()
                f1 = await turn(http, auth, TURN1)
                session = f1[0]["session"]
                d1 = f1[-1].get("done", {})
                a1 = "".join(f["content"] for f in f1 if "content" in f)
                calls_turn1 = len(CALLS)
                f2 = await turn(http, auth, TURN2, session)
                d2 = f2[-1].get("done", {})
                answer = "".join(f["content"] for f in f2 if "content" in f)
                tools = [f["tool"] for f in f2 if "tool" in f]
                turn2_calls = CALLS[calls_turn1:]
                tool_results = [m["content"] for m in (turn2_calls[-1] if turn2_calls else [])
                                if m.get("role") == "tool"]
                claims = sorted({m.lower() for m in CLAIM_RE.findall(answer)})
                print(f"\n=== run {run} · session {session[:8]} ===", flush=True)
                print(f"turn 1: path={d1.get('path')} model calls={calls_turn1}")
                print(f"turn 2: path={d2.get('path')} mode={d2.get('mode')} "
                      f"finish={d2.get('finish_reason')} calls={len(turn2_calls)}")
                for t in tools:
                    print(f"   tool: {t['call']} -> {t['status']}")
                for r in tool_results:
                    print(f"   tool result as the model read it: {r}")
                print(f"   answer words: {claims}")
                print("   answer: " + answer.strip().replace("\n", "\n           "), flush=True)
                out.write(json.dumps({
                    "run": run, "turn1": TURN1, "turn1_answer": a1, "turn1_done": d1,
                    "turn2": TURN2, "turn2_done": d2, "tools": tools,
                    "tool_results": tool_results, "answer": answer, "claims": claims,
                    "turn2_system": [m["content"] for m in (turn2_calls[0] if turn2_calls else [])
                                     if m.get("role") == "system"],
                }) + "\n")
                out.flush()
                queued = (await http.get(f"{API}/proposals", headers=auth)).json()["proposals"]
                for p in (p for p in queued if p["id"] not in before):
                    r = await http.post(f"{API}/proposals/{p['id']}/reject", headers=auth)
                    print(f"   proposal {p['id'][:8]} rejected (cleanup): {r.status_code}")
    finally:
        out.close()
        if not existed:
            await pool.execute(
                "DELETE FROM observables WHERE workspace_id = $1 AND value = $2", ws, IOC)
        await pool.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--label", default="before")
    asyncio.run(main(p.parse_args()))
