"""S30 (D-061; design §2): one workspace per token, a switch that mints a new
one only for an enterable workspace, every entry audited, and /me for F4."""

from uuid import uuid4

import pytest
from _tenancy import build_mssp, drop_orgs, token

from auspex.db import create_pool
from auspex.tenancy.audit import list_events

PREFIX = "t-s30-entry"


@pytest.fixture
async def world(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        yield pool, await build_mssp(pool, PREFIX)
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


def _switch(client, headers, workspace_id):
    return client.post("/api/auth/switch", json={"workspace_id": str(workspace_id)},
                       headers=headers)


async def test_a_switch_mints_a_token_for_the_new_workspace_and_is_audited(world, client, settings):
    pool, m = world
    resp = _switch(client, token(settings, m.p_admin, m.provider_ws), m.client1_ws)
    assert resp.status_code == 200, resp.text
    new = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    assert client.get("/api/auth/whoami", headers=new).json()["workspace_id"] == str(m.client1_ws)
    entered = await list_events(pool, m.client1_ws)
    assert entered[0]["action"] == "workspace.enter"
    assert entered[0]["details"] == {"via": "switch"}
    assert entered[0]["actor"]["organization"] == f"{PREFIX}-provider"


async def test_the_old_token_still_sees_only_its_own_workspace(world, client, settings):
    pool, m = world
    old = token(settings, m.p_admin, m.provider_ws)
    assert _switch(client, old, m.client1_ws).status_code == 200
    assert client.get("/api/auth/whoami", headers=old).json()["workspace_id"] == str(m.provider_ws)


async def test_switch_edges(world, client, settings):
    pool, m = world
    headers = token(settings, m.c1_user, m.client1_ws)
    foreign = _switch(client, headers, m.client2_ws)
    missing = _switch(client, headers, uuid4())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    bad = client.post("/api/auth/switch", json={"workspace_id": "not-a-uuid"}, headers=headers)
    assert bad.status_code == 422
    same = _switch(client, headers, m.client1_ws)
    assert same.status_code == 200
    assert (await list_events(pool, m.client1_ws))[0]["details"] == {"via": "switch"}


async def test_an_api_key_cannot_switch(world, client, settings):
    pool, m = world
    created = client.post("/api/auth/api-keys", json={"name": "k"},
                          headers=token(settings, m.p_admin, m.provider_ws))
    resp = _switch(client, {"X-API-Key": created.json()["api_key"]}, m.client1_ws)
    assert resp.status_code == 403


async def test_me_describes_the_person_and_where_they_may_go(world, client, settings):
    pool, m = world
    body = client.get("/api/auth/me", headers=token(settings, m.p_admin, m.client1_ws)).json()
    assert body["user"]["id"] == str(m.p_admin)
    assert body["organization"] == {"id": str(m.provider), "name": f"{PREFIX}-provider",
                                    "kind": "provider"}
    assert body["workspace"]["id"] == str(m.client1_ws)
    assert body["workspace"]["role"] == "admin"
    assert body["workspace"]["region"] == "global"
    listed = {w["id"]: (w["role"], w["via"]) for w in body["workspaces"]}
    assert listed == {str(m.provider_ws): ("admin", "membership"),
                      str(m.client1_ws): ("admin", "provider_wide")}
    assert body["workspaces"][0]["id"] == str(m.provider_ws)  # home organization first


async def test_dev_login_is_audited_as_an_entry(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    try:
        resp = client.post("/api/auth/dev-login", json={"email": "analyst@auspex.dev"})
        assert resp.status_code == 200
        ws = client.get("/api/auth/whoami", headers={
            "Authorization": f"Bearer {resp.json()['access_token']}"}).json()["workspace_id"]
        events = await pool.fetch(
            "SELECT details FROM audit_events WHERE workspace_id = $1"
            " AND action = 'workspace.enter' ORDER BY created_at DESC LIMIT 1", ws)
        assert '"login"' in events[0]["details"]
    finally:
        await pool.close()


async def test_a_person_with_no_workspace_left_gets_a_clear_403(world, client):
    pool, m = world
    email = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.c1_user)
    await pool.execute("DELETE FROM memberships WHERE user_id = $1", m.c1_user)
    resp = client.post("/api/auth/dev-login", json={"email": email})
    assert resp.status_code == 403
    assert "no workspace" in resp.json()["detail"].lower()


async def test_a_rehome_racing_a_sign_in_never_names_the_new_home_in_the_old_trail(world):
    """B-025: a rehome that lands while `enter()` runs must not stamp the NEW home on
    the `workspace.enter` event in the OLD home's workspace (another customer's name in
    that organization's audit). The rehome waits for the entry, or the entry sees it."""
    import asyncio

    from _tenancy import add_membership, make_org, make_user, make_workspace

    from auspex.tenancy import admin, entry

    pool, _ = world
    client_org = await make_org(pool, f"{PREFIX}-b025-client", "direct")
    other = await make_org(pool, f"{PREFIX}-b025-other", "direct")
    ws = await make_workspace(pool, f"{PREFIX}-b025-client", client_org)
    await make_workspace(pool, f"{PREFIX}-b025-other", other)
    email = f"b025-{uuid4().hex[:8]}@{PREFIX}.auspex.dev"
    person = await make_user(pool, email, client_org)
    await add_membership(pool, ws, person, "analyst")

    async def remove_and_rehome():
        await pool.execute("DELETE FROM memberships WHERE user_id = $1", person)
        await admin.rehome_person(pool, email=email, org=f"{PREFIX}-b025-other")

    real_landing = entry.landing
    racer: list[asyncio.Task] = []

    async def landing_then_race(db, user_id):
        access = await real_landing(db, user_id)
        racer.append(asyncio.create_task(remove_and_rehome()))
        await asyncio.wait(racer, timeout=0.5)  # time for an unblocked rehome to land
        return access

    entry.landing = landing_then_race
    try:
        access = await entry.enter(pool, person, via="login")
    finally:
        entry.landing = real_landing
    await asyncio.wait_for(racer[0], timeout=10)

    assert access.workspace_id == ws
    event = (await list_events(pool, ws))[0]
    assert event["action"] == "workspace.enter"
    assert event["actor"]["organization"] == f"{PREFIX}-b025-client"
