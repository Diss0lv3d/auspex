"""S34 live check (Task 9): a chat turn proposes a reference-connector action, it is
approved under the policy, runs on a REAL Edge Agent container against the dev
`mock-siem` stub, and is undone.

Run from the repo root after the gate rebuilt the app:

    .venv/bin/python docs/probes/s34-live/live_connector_action.py

Synthetic only (D-067): an MSSP under `t-s34-live`, the reference connector, the stub
SIEM (self-signed certificate, pinned), synthetic alerts, a placeholder secret. All
removed at the end, `.edge-dev/` included, whether it passes or not.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
from _tenancy import build_mssp, drop_orgs  # noqa: E402
from auspex_sdk.build import build  # noqa: E402

from auspex.auth import issue_jwt  # noqa: E402
from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

PREFIX = "t-s34-live"
APP = "http://localhost:8000"
SECRET = "s34-live-placeholder-token"  # noqa: S105 -- a placeholder, scanned for
EDGE_DEV = ROOT / ".edge-dev"
DEV = ["docker", "compose", "--profile", "dev"]
ASK = "Alert A-1001 in our SIEM is a false positive from a service account. Please close it."


def sh(*args: str, check: bool = True) -> str:
    return subprocess.run(args, cwd=ROOT, check=check, capture_output=True,  # noqa: S603
                          text=True).stdout


def say(step: str, value: object = "") -> None:
    print(f"{step:48} {value}")


async def db(fn):
    pool = await create_pool(get_settings().database_url)
    try:
        return await fn(pool)
    finally:
        await pool.close()


def writes() -> list[str]:
    return sh(*DEV, "exec", "-T", "mock-siem", "sh", "-c",
              "cat /certs/writes.log 2>/dev/null || true", check=False).split("\n")[:-1]


def chat(headers: dict, message: str) -> dict:
    res = httpx.post(f"{APP}/api/chat", headers=headers, json={"message": message},
                     timeout=300)
    text, done, tools = "", None, []
    for line in res.text.splitlines():
        if not line.startswith("data:"):
            continue
        d = json.loads(line[5:])
        if "content" in d:
            text += d["content"]
        elif "done" in d:
            done = d["done"]
        elif "tool" in d:
            tools.append(d["tool"])
    return {"status": res.status_code, "text": text, "done": done, "tools": tools}


def main() -> int:
    settings = get_settings()
    m = asyncio.run(db(lambda p: _setup(p)))
    admin = {"Authorization": f"Bearer {issue_jwt(settings, m.d_user, m.direct_ws)}"}
    ok = False
    try:
        sh(*DEV, "rm", "-sf", "mock-siem", check=False)
        sh(*DEV, "up", "-d", "--build", "mock-siem")
        served = ("import ssl, hashlib; print(hashlib.sha256(ssl.PEM_cert_to_DER_cert("
                  "ssl.get_server_certificate(('localhost', 8443)))).hexdigest())")
        for _ in range(30):
            pin = sh(*DEV, "exec", "-T", "mock-siem", "python", "-c", served,
                     check=False).strip()
            if len(pin) == 64:
                break
            time.sleep(1)
        sh(*DEV, "exec", "-T", "mock-siem", "rm", "-f", "/certs/writes.log", check=False)
        say("mock-siem certificate SHA-256", pin[:16] + "…")

        copy = Path("/tmp") / "s34-live-ref"  # noqa: S108 -- a scratch build dir
        shutil.rmtree(copy, ignore_errors=True)
        shutil.copytree(ROOT / "examples/connectors/mock_siem/yaml", copy,
                        ignore=shutil.ignore_patterns("dist", "__pycache__"))
        zip_path, digest = build(copy)
        res = httpx.post(f"{APP}/api/connectors", headers=admin,
                         files={"package": (zip_path.name, zip_path.read_bytes())})
        say("register the reference connector", res.status_code)
        res = httpx.post(f"{APP}/api/edge/agents", headers=admin, json={"name": "live-site"})
        say("create an Edge Agent", res.status_code)
        agent_id, enrollment = res.json()["agent"]["id"], res.json()["enrollment_token"]
        EDGE_DEV.mkdir(mode=0o700, exist_ok=True)
        (EDGE_DEV / "token").write_text(enrollment)
        (EDGE_DEV / "secrets.json").write_text(json.dumps({"siem_token": SECRET}))
        for f in ("token", "secrets.json"):
            (EDGE_DEV / f).chmod(0o600)
        body = {"name": "Live SIEM", "prefix": "live1", "content_hash": digest,
                "agent_id": agent_id,
                "config": {"base_url": "https://mock-siem:8443",
                           "api_token": "secret:siem_token",
                           "tls": {"cert_sha256": pin}}}
        res = httpx.post(f"{APP}/api/integrations", headers=admin, json=body)
        say("create the integration (pinned TLS)", res.status_code)
        integration = res.json()["id"]
        res = httpx.put(f"{APP}/api/integrations/{integration}/grants", headers=admin,
                        json={"actions": ["close_alert"]})
        say("grant close_alert", f"{res.status_code} {res.json().get('grants')}")

        env = {**os.environ, "AGENT_UID": str(os.getuid()), "AGENT_GID": str(os.getgid())}
        subprocess.run([*DEV, "up", "-d", "--build", "--force-recreate", "edge"], cwd=ROOT,
                       env=env, check=True, capture_output=True)  # noqa: S603
        for _ in range(40):
            agents = httpx.get(f"{APP}/api/edge/agents", headers=admin).json()["agents"]
            if agents and agents[0]["health"] == "online":
                break
            time.sleep(1)
        say("the agent enrolled and is", agents[0]["health"])

        turn = chat(admin, ASK)
        done = turn["done"] or {}
        say("chat turn", f"{turn['status']} path={done.get('path')} "
                         f"finish={done.get('finish_reason')} output_valid={done.get('output_valid')}")
        say("  the answer begins", turn["text"][:110].replace("\n", " "))
        row = asyncio.run(db(lambda p: p.fetchrow(
            "SELECT id, tool_name, status, card FROM proposals WHERE workspace_id = $1"
            " ORDER BY created_at DESC LIMIT 1", m.direct_ws)))
        if row is None:
            say("a proposal was filed", "NO")
            return 1
        card = json.loads(row["card"]) if isinstance(row["card"], str) else row["card"]
        say("the proposal filed", f"{row['tool_name']} {row['status']}")
        say("  its card (from the agent's dry run)", card.get("summary"))
        say("SIEM writes after proposing", writes())

        res = httpx.post(f"{APP}/api/proposals/{row['id']}/approve", headers=admin, timeout=120)
        out = res.json()
        say("approve (admin, default policy)",
            f"{res.status_code} executed={out.get('executed')} did={out.get('outcome', {}).get('did')}")
        say("SIEM writes after approving", writes())
        res = httpx.post(f"{APP}/api/proposals/{row['id']}/undo", headers=admin, timeout=120)
        say("undo", f"{res.status_code} {res.json().get('proposal', {}).get('status')}")
        after = writes()
        say("SIEM writes after undo", after)
        jobs = asyncio.run(db(lambda p: p.fetch(
            "SELECT kind, status FROM jobs WHERE workspace_id = $1 ORDER BY created_at",
            m.direct_ws)))
        say("jobs", [f"{j['kind'].rsplit('.', 1)[1]}:{j['status']}" for j in jobs])
        logs = sh(*DEV, "logs", "--no-color", "app", "edge", check=False)
        say("the secret's value in app/edge logs", SECRET in logs)
        ok = after == ["close A-1001", "reopen A-1001"] and SECRET not in logs
        return 0 if ok else 1
    finally:
        sh(*DEV, "rm", "-sf", "edge", "mock-siem", check=False)
        shutil.rmtree(EDGE_DEV, ignore_errors=True)
        asyncio.run(db(lambda p: drop_orgs(p, PREFIX)))
        say("cleanup: orgs, packages, .edge-dev, containers", "done")
        say("RESULT", "PASS" if ok else "FAIL")


async def _setup(pool):
    await drop_orgs(pool, PREFIX)
    return await build_mssp(pool, PREFIX)


if __name__ == "__main__":
    _ = uuid
    sys.exit(main())
