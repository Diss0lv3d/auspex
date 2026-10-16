"""Reverse leak: a rehome that lands between enter()'s access check and its
home_org() read stamps the NEW home on a workspace.enter event in the OLD
home's workspace. Deterministic interleaving via a wrapper around home_org."""
import asyncio, sys
sys.path[:0] = ["/home/burhan/auspex-new", "/home/burhan/auspex-new/tests"]
from _tenancy import add_membership, drop_orgs, make_org, make_user, make_workspace
from auspex.db import create_pool
from auspex.tenancy import admin, entry
from auspex.tenancy.audit import list_events

URL = "postgresql://auspex:auspex@localhost:55432/auspex"
P = "t-s31-b021rev"

async def main():
    pool = await create_pool(URL, retries=2, delay=0.5)
    await drop_orgs(pool, P)
    try:
        prov = await make_org(pool, f"{P}-mssp", "provider")
        c1 = await make_org(pool, f"{P}-client1", "client", parent=prov)
        other = await make_org(pool, f"{P}-othercustomer", "direct")
        c1_ws = await make_workspace(pool, f"{P}-client1", c1)
        await make_workspace(pool, f"{P}-othercustomer", other)
        email = f"x@{P}.auspex.dev"
        x = await make_user(pool, email, c1)
        await add_membership(pool, c1_ws, x, "analyst")
        real = entry.home_org

        async def racing(db, uid):
            # after landing() said "client1": the membership goes, the CLI rehomes
            await pool.execute("DELETE FROM memberships WHERE user_id = $1", x)
            await admin.rehome_person(pool, email=email, org=f"{P}-othercustomer")
            return await real(db, uid)

        entry.home_org = racing
        try:
            acc = await entry.enter(pool, x, via="login")
        finally:
            entry.home_org = real
        ev = (await list_events(pool, c1_ws))[0]
        print("entered:", acc.workspace_name)
        print("client1's trail, newest:", ev["action"], "actor.organization =", ev["actor"]["organization"])
    finally:
        await drop_orgs(pool, P)
        left = await pool.fetchval("SELECT count(*) FROM organizations WHERE starts_with(name, $1)", P)
        print("cleanup, orgs left:", left)
        await pool.close()

asyncio.run(main())
