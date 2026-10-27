"""S32 live check (Task 13): the reference connector is built, registered by a provider's
admin through the REAL `POST /api/connectors`, offered to clients, listed from the
clients and not from a direct customer, then registered first-party with the CLI inside
the app container and listed everywhere.

Run from the repo root with the .venv active, after `./ci.sh` rebuilt the app container:

    python docs/probes/s32-live/probe_connectors_live.py run       # build, register, list
    python docs/probes/s32-live/probe_connectors_live.py cleanup   # delete what it made

Everything lives under the `t-s32-live` prefix (an MSSP: a provider, two clients, a
direct customer, their users); cleanup drops those organizations, which cascades to
their packages, and deletes the first-party row by its content hash. Synthetic data only.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()  # host DSN (port 55432), as the suite does

from _tenancy import build_mssp, drop_orgs  # noqa: E402
from auspex_sdk.build import build  # noqa: E402

from auspex.auth import issue_jwt  # noqa: E402
from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

PREFIX = "t-s32-live"
APP = "http://localhost:8000"
SOURCE = ROOT / "examples" / "connectors" / "mock_siem" / "python"


def _listed(settings, user, ws) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {issue_jwt(settings, user, ws)}"}
    res = httpx.get(f"{APP}/api/connectors", headers=headers)
    res.raise_for_status()
    return {c["connector_id"]: c["source"] for c in res.json()["connectors"]}


async def run(pool) -> None:
    settings = get_settings()
    await drop_orgs(pool, PREFIX)
    m = await build_mssp(pool, PREFIX)
    zip_path, digest = build(SOURCE)
    print(f"built {zip_path.name}  hash {digest[:16]}…")

    headers = {"Authorization": f"Bearer {issue_jwt(settings, m.p_admin, m.provider_ws)}"}
    res = httpx.post(f"{APP}/api/connectors", headers=headers,
                     files={"package": (zip_path.name, zip_path.read_bytes(),
                                        "application/zip")},
                     data={"offered_to_clients": "true"})
    print(f"POST as the provider's admin, offered → {res.status_code}")
    res.raise_for_status()
    cid = res.json()["connector_id"]

    analyst = {"Authorization": f"Bearer {issue_jwt(settings, m.c1_user, m.client1_ws)}"}
    res = httpx.post(f"{APP}/api/connectors", headers=analyst,
                     files={"package": (zip_path.name, zip_path.read_bytes(),
                                        "application/zip")})
    print(f"POST as a client's analyst → {res.status_code} (expected 403)")

    for label, user, ws in (("provider", m.p_admin, m.provider_ws),
                            ("client1", m.c1_user, m.client1_ws),
                            ("client2 (restricted)", m.c2_user, m.client2_ws),
                            ("direct", m.d_user, m.direct_ws)):
        print(f"  {label:22} lists it as: {_listed(settings, user, ws).get(cid, '—')}")

    subprocess.run(["docker", "compose", "cp", str(zip_path), "app:/tmp/s32-live.zip"],
                   check=True, cwd=ROOT)
    out = subprocess.run(["docker", "compose", "exec", "-T", "app", "python", "-m",
                          "auspex.connectors", "register", "--first-party",
                          "/tmp/s32-live.zip"],
                         capture_output=True, text=True, cwd=ROOT)
    print(f"CLI first-party → exit {out.returncode}: {out.stdout.strip() or out.stderr.strip()}")
    for label, user, ws in (("client1", m.c1_user, m.client1_ws),
                            ("direct", m.d_user, m.direct_ws)):
        print(f"  {label:22} now lists it as: {_listed(settings, user, ws).get(cid, '—')}")


async def cleanup(pool) -> None:
    _, digest = build(SOURCE)
    gone = await pool.execute(
        "DELETE FROM connector_packages WHERE first_party AND content_hash = $1", digest)
    await drop_orgs(pool, PREFIX)
    subprocess.run(["docker", "compose", "exec", "-T", "app", "rm", "-f",
                    "/tmp/s32-live.zip"], cwd=ROOT)
    print(f"first-party rows: {gone}; organizations under {PREFIX} dropped")


async def main(step: str) -> None:
    pool = await create_pool(get_settings().database_url)
    try:
        await {"run": run, "cleanup": cleanup}[step](pool)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
