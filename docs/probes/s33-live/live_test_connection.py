"""S33 live check (Task 9): "Test connection" through a REAL Edge Agent container.

Run from the repo root with the .venv active, after `./ci.sh` rebuilt the app:

    python docs/probes/s33-live/live_test_connection.py

Synthetic only (D-067): an MSSP under the `t-s33-live` prefix, the reference
connector, the dev `mock-siem` stub (a self-signed certificate, pinned by its
SHA-256), and a placeholder secret. Everything it creates is removed at the end,
`.edge-dev/` included, whether it passes or not.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
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

PREFIX = "t-s33-live"
APP = "http://localhost:8000"
SECRET = "s33-live-placeholder-token"  # noqa: S105 -- a placeholder, scanned for
EDGE_DEV = ROOT / ".edge-dev"
DEV = ["docker", "compose", "--profile", "dev"]


def sh(*args: str, check: bool = True) -> str:
    return subprocess.run(args, cwd=ROOT, check=check, capture_output=True,  # noqa: S603
                          text=True).stdout


def say(step: str, value: object = "") -> None:
    print(f"{step:46} {value}")


async def db(fn):
    pool = await create_pool(get_settings().database_url)
    try:
        return await fn(pool)
    finally:
        await pool.close()


def main() -> int:
    settings = get_settings()
    m = asyncio.run(db(lambda p: _setup(p)))
    admin = {"Authorization": f"Bearer {issue_jwt(settings, m.d_user, m.direct_ws)}"}
    try:
        sh(*DEV, "up", "-d", "--build", "mock-siem")
        # The pin is taken from the certificate the stub SERVES, not a file: its volume
        # outlives a run, and a file read before the new certificate exists is stale.
        served = ("import ssl, hashlib; print(hashlib.sha256(ssl.PEM_cert_to_DER_cert("
                  "ssl.get_server_certificate(('localhost', 8443)))).hexdigest())")
        for _ in range(30):
            pin = sh(*DEV, "exec", "-T", "mock-siem", "python", "-c", served,
                     check=False).strip()
            if len(pin) == 64:
                break
            time.sleep(1)
        say("mock-siem certificate SHA-256", pin[:16] + "…")

        copy = Path("/tmp") / "s33-live-ref"  # noqa: S108 -- a scratch build dir
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

        env = {**os.environ, "AGENT_UID": str(os.getuid()), "AGENT_GID": str(os.getgid())}
        subprocess.run([*DEV, "up", "-d", "--build", "edge"], cwd=ROOT, env=env,  # noqa: S603
                       check=True, capture_output=True)
        for _ in range(40):
            agents = httpx.get(f"{APP}/api/edge/agents", headers=admin).json()["agents"]
            if agents and agents[0]["health"] == "online":
                break
            time.sleep(1)
        say("the agent enrolled and is", agents[0]["health"])

        job = httpx.post(f"{APP}/api/integrations/{integration}/test", headers=admin)
        say("press Test connection", job.status_code)
        job_id = job.json()["job_id"]
        for _ in range(60):
            state = httpx.get(f"{APP}/api/integrations/{integration}/test/{job_id}",
                              headers=admin).json()
            if state["state"] not in ("queued", "running"):
                break
            time.sleep(1)
        say("the test answered", f"{state['state']}: {state['detail']}")

        sh(*DEV, "stop", "edge")
        asyncio.run(db(lambda p: p.execute(
            "UPDATE edge_agents SET last_heartbeat_at = now() - interval '6 minutes'"
            " WHERE id = $1", __import__("uuid").UUID(agent_id))))
        refused = httpx.post(f"{APP}/api/integrations/{integration}/test", headers=admin)
        say("with the agent offline (heartbeat aged by SQL)",
            f"{refused.status_code}: {refused.json()['detail']['reason']}")

        logs = sh(*DEV, "logs", "--no-color", "app", "edge", check=False)
        rows = asyncio.run(db(lambda p: p.fetchval(
            "SELECT count(*) FROM (SELECT payload::text t FROM jobs UNION ALL"
            " SELECT result::text FROM jobs UNION ALL SELECT last_error FROM jobs"
            " UNION ALL SELECT config::text FROM integrations UNION ALL"
            " SELECT details::text FROM audit_events) x WHERE t LIKE '%' || $1 || '%'",
            SECRET)))
        say("the secret's value in app/edge logs", SECRET in logs)
        say("the secret's value in jobs/integrations/audit", rows)
        return 0 if state["state"] == "ok" and not (SECRET in logs) and rows == 0 else 1
    finally:
        sh(*DEV, "rm", "-sf", "edge", "mock-siem", check=False)
        shutil.rmtree(EDGE_DEV, ignore_errors=True)
        asyncio.run(db(lambda p: _cleanup(p)))
        say("cleanup: orgs, packages, .edge-dev, containers", "done")


async def _setup(pool):
    await drop_orgs(pool, PREFIX)
    return await build_mssp(pool, PREFIX)


async def _cleanup(pool):
    await drop_orgs(pool, PREFIX)


if __name__ == "__main__":
    sys.exit(main())
