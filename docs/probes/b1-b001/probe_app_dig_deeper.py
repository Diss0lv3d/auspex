"""B1 — B-001 reproduced through the running container.

Burhan's two turns, verbatim, in a fresh chat session per run:
  1. "what do you know about this IP: 34.187.179.218"   (IOC check, no model)
  2. "dig deeper"                                        (deep turn)

For turn 2 this records the path, the mode, contract_valid, every tool frame,
and what the answer and the reasoning ASSERT about the address: an owner named,
a hostname, or a source the platform does not have (WHOIS, RDAP, reverse DNS,
geolocation, ASN). The registry says Google LLC (ARIN RDAP, NET-34-128-0-0-1);
the platform has no source that says so, so ANY owner named is unsourced.

`endpoint` is the dev switcher id: `default` (glm-4.5-air, D-034) or `qwen`
(local qwen3:14b, D-013 — slow, run it in the background). Proposals filed are
rejected afterwards; the observable is deleted only if this run created it.
Do NOT run pytest at the same time (it purges the shared analyst user).

Run:  .venv/bin/python docs/probes/b1-b001/probe_app_dig_deeper.py <endpoint> <runs>
"""

import asyncio
import json
import re
import sys
import time

import httpx

sys.path.insert(0, ".")
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

API = "http://localhost:8000/api"
IOC = "34.187.179.218"
TURN1 = f"what do you know about this IP: {IOC}"
TURN2 = "dig deeper"

OWNER_RE = re.compile(
    r"\b(amazon\w*|aws|google\w*|gcp|microsoft|azure|cloudflare|digitalocean|ovh|"
    r"hetzner|linode|akamai|oracle|alibaba|tencent|comcast|verizon|at&t)\b",
    re.IGNORECASE,
)
SOURCE_RE = re.compile(
    r"\b(whois|rdap|reverse[- ]dns|rdns|ptr|geolocat\w*|geo-?ip|asn|as\d{3,}|arin|ripe|apnic|"
    r"virustotal|shodan|censys|greynoise|passive dns)\b",
    re.IGNORECASE,
)
HOST_RE = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|cloud|internal|goog)\b", re.IGNORECASE)


def flags(text: str) -> str:
    owners = sorted({m.lower() for m in OWNER_RE.findall(text)})
    sources = sorted({m.lower() for m in SOURCE_RE.findall(text)})
    hosts = sorted({m.lower() for m in HOST_RE.findall(text)})
    return f"owners={owners} sources={sources} hosts={hosts}"


async def turn(http, auth, message, session_id, endpoint):
    body = {"message": message, "endpoint_id": endpoint}
    if session_id:
        body["session_id"] = session_id
    frames = []
    t0 = time.monotonic()
    async with http.stream("POST", f"{API}/chat", json=body, headers=auth) as resp:
        if resp.status_code != 200:
            await resp.aread()
            raise SystemExit(f"/api/chat {resp.status_code}: {resp.text}")
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[5:].strip()))
    return frames, time.monotonic() - t0


async def main(endpoint: str, runs: int) -> None:
    pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
    ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = 'default'")
    existed = bool(await pool.fetchval(
        "SELECT count(*) FROM observables WHERE workspace_id = $1 AND value = $2", ws, IOC))
    print(f"endpoint={endpoint} runs={runs} observable in workspace before: {existed}")
    try:
        async with httpx.AsyncClient(timeout=600) as http:
            token = (await http.post(f"{API}/auth/dev-login",
                                     json={"email": "analyst@auspex.dev"})).json()["access_token"]
            auth = {"Authorization": f"Bearer {token}"}
            for run in range(1, runs + 1):
                before = {p["id"] for p in
                          (await http.get(f"{API}/proposals", headers=auth)).json()["proposals"]}
                f1, _ = await turn(http, auth, TURN1, None, endpoint)
                session = f1[0]["session"]
                d1 = f1[-1].get("done", {})
                a1 = "".join(f["content"] for f in f1 if "content" in f)
                f2, secs = await turn(http, auth, TURN2, session, endpoint)
                d2 = f2[-1].get("done", {})
                answer = "".join(f["content"] for f in f2 if "content" in f)
                reasoning = "".join(f["reasoning"] for f in f2 if "reasoning" in f)
                tools = [f["tool"] for f in f2 if "tool" in f]
                print(f"\n=== run {run} · session {session[:8]} ===")
                print(f"turn 1: path={d1.get('path')} | {a1.strip().splitlines()[-1]}")
                print(f"turn 2: path={d2.get('path')} mode={d2.get('mode')} "
                      f"contract_valid={d2.get('contract_valid')} "
                      f"finish={d2.get('finish_reason')} {secs:.0f}s "
                      f"tokens={(d2.get('usage') or {}).get('total_tokens')}")
                for t in tools:
                    print(f"   tool: {t['call']} -> {t['status']}")
                if not tools:
                    print("   tool: (none)")
                print(f"   ANSWER    {flags(answer)}")
                print(f"   REASONING {flags(reasoning)} ({len(reasoning)} chars)")
                print("   answer: " + answer.strip().replace("\n", "\n           "))
                queued = (await http.get(f"{API}/proposals", headers=auth)).json()["proposals"]
                for p in (p for p in queued if p["id"] not in before):
                    r = await http.post(f"{API}/proposals/{p['id']}/reject", headers=auth)
                    print(f"   proposal {p['id'][:8]} {p['action']} rejected (cleanup): {r.status_code}")
    finally:
        if not existed:
            await pool.execute(
                "DELETE FROM observables WHERE workspace_id = $1 AND value = $2", ws, IOC)
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2])))
