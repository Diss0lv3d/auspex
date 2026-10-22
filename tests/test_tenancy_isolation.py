"""S30's exit criteria, as an MSSP meets them (D-061): through the routes only."""

import json

import pytest
from _tenancy import build_mssp, drop_orgs, make_org, make_workspace, token
from auspex_sdk.package import build_zip

from auspex.connectors.catalogue import available, register
from auspex.db import create_pool

PREFIX = "t-s30-iso"


@pytest.fixture
async def world(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        yield pool, await build_mssp(pool, PREFIX)
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


def _switch(client, headers, ws):
    return client.post("/api/auth/switch", json={"workspace_id": str(ws)}, headers=headers)


def _me(client, headers):
    return {w["id"] for w in client.get("/api/auth/me", headers=headers).json()["workspaces"]}


async def test_a_client_user_reaches_neither_a_sibling_nor_the_provider(world, client, settings):
    pool, m = world
    headers = token(settings, m.c1_user, m.client1_ws)
    assert _switch(client, headers, m.client2_ws).status_code == 404
    assert _switch(client, headers, m.provider_ws).status_code == 404
    assert client.get("/api/auth/whoami",
                      headers=token(settings, m.c1_user, m.client2_ws)).status_code == 403
    assert _me(client, headers) == {str(m.client1_ws)}


async def test_an_mssp_analyst_without_a_membership_cannot_enter_a_client(world, client, settings):
    pool, m = world
    headers = token(settings, m.p_analyst, m.provider_ws)
    assert _switch(client, headers, m.client1_ws).status_code == 404
    assert client.get("/api/proposals",
                      headers=token(settings, m.p_analyst, m.client1_ws)).status_code == 403


async def test_a_grant_reaches_a_new_client_but_not_a_restricted_one(world, client, settings):
    pool, m = world
    late = await make_org(pool, f"{PREFIX}-late", "client", parent=m.provider)
    late_ws = await make_workspace(pool, f"{PREFIX}-late", late)
    headers = token(settings, m.p_admin, m.provider_ws)
    assert _switch(client, headers, late_ws).status_code == 200
    assert _switch(client, headers, m.client2_ws).status_code == 404


async def test_a_removed_membership_ends_access_at_the_next_request(world, client, settings):
    pool, m = world
    admin = token(settings, m.d_user, m.direct_ws)
    added = client.post("/api/workspace/members",
                        json={"email": f"temp@{PREFIX}.auspex.dev", "role": "analyst"},
                        headers=admin)
    temp = added.json()["user_id"]
    temp_headers = token(settings, temp, m.direct_ws)
    assert client.get("/api/proposals", headers=temp_headers).status_code == 200
    assert client.delete(f"/api/workspace/members/{temp}", headers=admin).status_code == 200
    assert client.get("/api/proposals", headers=temp_headers).status_code == 403


async def test_no_one_sets_their_own_role_or_grants_themselves(world, client, settings):
    pool, m = world
    for user, ws in ((m.p_admin, m.provider_ws), (m.d_user, m.direct_ws)):
        headers = token(settings, user, ws)
        assert client.patch(f"/api/workspace/members/{user}", json={"role": "viewer"},
                            headers=headers).status_code == 403
        assert client.patch(f"/api/workspace/members/{user}", json={"provider_wide": True},
                            headers=headers).status_code == 403
    analyst = token(settings, m.p_analyst, m.provider_ws)
    assert client.patch(f"/api/workspace/members/{m.p_analyst}",
                        json={"provider_wide": True}, headers=analyst).status_code == 403


async def test_a_client_admin_cannot_touch_the_providers_people(world, client, settings):
    pool, m = world
    await pool.execute("UPDATE memberships SET role = 'admin' WHERE user_id = $1", m.c1_user)
    headers = token(settings, m.c1_user, m.client1_ws)
    assert client.patch(f"/api/workspace/members/{m.p_admin}", json={"role": "viewer"},
                        headers=headers).status_code == 404
    assert client.delete(f"/api/workspace/members/{m.p_analyst}",
                         headers=headers).status_code == 404


async def test_data_written_in_one_client_is_invisible_in_the_other(world, client, settings):
    pool, m = world
    await pool.execute("UPDATE organizations SET restricted = false WHERE id = $1", m.client2)
    in_c1 = token(settings, m.p_admin, m.client1_ws)
    cef = ("CEF:0|Vendor|EDR|1.0|500|Beaconing detected|9|"
           "src=203.0.113.7 dst=evil-c2-server.biz")
    created = client.post("/api/investigations", json={"message": cef}, headers=in_c1)
    assert created.status_code == 201, created.text
    inv = created.json()["investigation_id"]
    in_c2 = token(settings, m.p_admin, m.client2_ws)
    assert client.get(f"/api/investigations/{inv}", headers=in_c2).status_code == 404
    assert client.get(f"/api/investigations/{inv}", headers=in_c1).status_code == 200


async def test_an_audit_event_in_one_workspace_is_absent_from_anothers_trail(
        world, client, settings):
    pool, m = world
    admin = token(settings, m.d_user, m.direct_ws)
    added = client.post("/api/workspace/members",
                        json={"email": f"audit-probe@{PREFIX}.auspex.dev", "role": "analyst"},
                        headers=admin)
    assert added.status_code == 201, added.text
    probe = added.json()["user_id"]
    own = client.get("/api/audit", headers=admin).json()["events"]
    assert any(e["action"] == "membership.add" and e["subject"]["user_id"] == probe
               for e in own), own
    in_c1 = token(settings, m.p_admin, m.client1_ws)
    seen = client.get("/api/audit", headers=in_c1)
    assert seen.status_code == 200, seen.text
    assert probe not in str(seen.json()), seen.json()
    assert all(e["subject"]["user_id"] != probe for e in seen.json()["events"])


async def test_a_connector_package_registered_in_one_client_is_listed_nowhere_else(world):
    """S32 (spec decision 3): the catalogue's cross-tenant row. The routes arrive with
    Task 11; the one listing function they call is held to the same line here."""
    pool, m = world
    manifest = {"schema_version": 1, "id": "tiso.private", "version": "1.0.0",
                "name": "Private", "description": "client1's own connector",
                "commands": {"test": {"handler": "pkg.h:test"}}}
    data = build_zip({"manifest.json": json.dumps(manifest).encode(), "pkg/h.py": b""})
    entry = await register(pool, workspace_id=m.client1_ws, data=data,
                           registered_by=m.c1_user, offered_to_clients=False)
    assert [e.id for e in await available(pool, workspace_id=m.client1_ws)
            if e.connector_id == "tiso.private"] == [entry.id]
    for ws in (m.client2_ws, m.provider_ws, m.direct_ws):
        assert all(e.connector_id != "tiso.private"
                   for e in await available(pool, workspace_id=ws))
