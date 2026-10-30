"""S33 Step 0: reproduce PR #43 review findings 6, 7 and 8 against the catalogue,
on the host DB (synthetic MSSP under `t-s33-pr43`, dropped afterwards).

    python docs/probes/s33-pr43/repro_catalogue.py
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
from _tenancy import build_mssp, drop_orgs, make_workspace  # noqa: E402
from auspex_sdk.package import build_zip  # noqa: E402

from auspex.config import get_settings  # noqa: E402
from auspex.connectors.catalogue import available, register  # noqa: E402
from auspex.db import create_pool  # noqa: E402

P = "t-s33-pr43"


def package(cid, version="1.0.0", *, name="Repro", body=b"", raw=None):
    m = {"schema_version": 1, "id": cid, "version": version, "name": name,
         "description": "repro", "commands": {"test": {"handler": "pkg.h:test"}}}
    text = raw if raw is not None else json.dumps(m)
    return build_zip({"manifest.json": text.encode("utf-8", "surrogatepass"),
                      "pkg/h.py": body})


async def main():
    pool = await create_pool(get_settings().database_url)
    await drop_orgs(pool, P)
    try:
        m = await build_mssp(pool, P)
        # 6: a NUL (or lone surrogate) escaped in manifest.json
        for label, esc in (("\\u0000", "\\u0000"), ("lone surrogate", "\\ud800")):
            raw = json.dumps({"schema_version": 1, "id": "ts33.nul", "version": "1.0.0",
                              "name": "x", "description": "repro",
                              "commands": {"test": {"handler": "pkg.h:test"}}}
                             ).replace('"repro"', f'"re{esc}pro"')
            try:
                await register(pool, workspace_id=m.direct_ws, data=package("x", raw=raw),
                               registered_by=m.d_user, offered_to_clients=False)
                print(f"6 [{label}]: registered")
            except Exception as e:  # noqa: BLE001
                print(f"6 [{label}]: {type(e).__module__}.{type(e).__name__}: {str(e)[:90]}")
        # 7: same hash re-registered with a different offered_to_clients
        data = package("ts33.offer")
        a = await register(pool, workspace_id=m.provider_ws, data=data,
                           registered_by=m.p_admin, offered_to_clients=False)
        b = await register(pool, workspace_id=m.provider_ws, data=data,
                           registered_by=m.p_admin, offered_to_clients=True)
        print(f"7: first offered={a.offered_to_clients}, re-upload asked True, "
              f"returned offered={b.offered_to_clients}, same row={a.id == b.id}")
        # 8: two workspaces of one provider offer one id+version with different hashes
        second = await make_workspace(pool, f"{P}-provider-2", m.provider)
        await pool.execute("INSERT INTO memberships (workspace_id, user_id, role)"
                           " VALUES ($1, $2, 'admin')", second, m.p_admin)
        await register(pool, workspace_id=m.provider_ws, data=package("ts33.dup"),
                       registered_by=m.p_admin, offered_to_clients=True)
        try:
            await register(pool, workspace_id=second, data=package("ts33.dup", body=b"#2"),
                           registered_by=m.p_admin, offered_to_clients=True)
            listed = [(e.connector_id, e.version, e.content_hash[:16])
                      for e in await available(pool, workspace_id=m.client1_ws)
                      if e.connector_id == "ts33.dup"]
            print(f"8: both registered; client1 lists {listed}")
        except Exception as e:  # noqa: BLE001
            print(f"8: refused: {e}")
    finally:
        await drop_orgs(pool, P)
        await pool.close()


asyncio.run(main())
