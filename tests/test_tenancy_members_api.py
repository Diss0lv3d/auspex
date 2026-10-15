"""S30 (D-061; design §3): admins manage memberships of their active workspace
only, and read its audit trail; every admin route refuses an analyst and a
viewer (found by walking the app, not by a list)."""

from uuid import uuid4

import pytest
from _tenancy import build_mssp, drop_orgs, token
from fastapi.routing import APIRoute, iter_route_contexts

from auspex.app import create_app
from auspex.auth import require_admin
from auspex.db import create_pool

PREFIX = "t-s30-members"
DOMAIN = f"{PREFIX}.auspex.dev"


@pytest.fixture
async def world(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        yield pool, await build_mssp(pool, PREFIX)
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


def _admin_routes():
    for ctx in iter_route_contexts(create_app().routes):
        if not isinstance(ctx.route, APIRoute):
            continue

        def _walk(dependant):
            for dep in dependant.dependencies:
                yield dep.call
                yield from _walk(dep)

        if require_admin in set(_walk(ctx.route.dependant)):
            for method in ctx.methods - {"HEAD"}:
                yield method, ctx.path


async def test_every_admin_route_refuses_an_analyst_and_a_viewer(world, client, settings):
    pool, m = world
    await pool.execute("UPDATE memberships SET role = 'viewer' WHERE user_id = $1", m.c2_user)
    routes = sorted(set(_admin_routes()))
    assert len(routes) >= 5, f"found only {routes}; the walk is checking nothing"
    for user, ws in ((m.c1_user, m.client1_ws), (m.c2_user, m.client2_ws)):
        headers = token(settings, user, ws)
        for method, path in routes:
            concrete = path.replace("{user_id}", str(uuid4()))
            resp = client.request(method, concrete, headers=headers, json={})
            assert resp.status_code == 403, (method, path, resp.status_code)


async def test_an_admin_adds_changes_and_removes_a_member(world, client, settings):
    pool, m = world
    headers = token(settings, m.d_user, m.direct_ws)
    added = client.post("/api/workspace/members",
                        json={"email": f"new@{DOMAIN}", "role": "viewer"}, headers=headers)
    assert added.status_code == 201, added.text
    uid = added.json()["user_id"]
    listed = client.get("/api/workspace/members", headers=headers).json()["members"]
    assert {r["email"]: r["role"] for r in listed}[f"new@{DOMAIN}"] == "viewer"
    assert client.patch(f"/api/workspace/members/{uid}", json={"role": "analyst"},
                        headers=headers).status_code == 200
    assert client.delete(f"/api/workspace/members/{uid}", headers=headers).status_code == 200
    actions = [e["action"] for e in
               client.get("/api/audit", headers=headers).json()["events"]]
    assert {"membership.add", "membership.role", "membership.remove"} <= set(actions)


async def test_the_api_refuses_self_changes_and_strangers(world, client, settings):
    pool, m = world
    headers = token(settings, m.p_admin, m.provider_ws)
    me = client.patch(f"/api/workspace/members/{m.p_admin}", json={"role": "viewer"},
                      headers=headers)
    assert me.status_code == 403
    grant = client.patch(f"/api/workspace/members/{m.p_admin}", json={"provider_wide": False},
                         headers=headers)
    assert grant.status_code == 403
    sibling = await pool.fetchval("SELECT email FROM users WHERE id = $1", m.c2_user)
    other = client.post("/api/workspace/members", json={"email": sibling, "role": "viewer"},
                        headers=token(settings, m.p_admin, m.client1_ws))
    assert other.status_code == 409
    assert "another organization" in other.json()["detail"]
    stranger = client.delete(f"/api/workspace/members/{m.c1_user}", headers=headers)
    assert stranger.status_code == 404


async def test_provider_wide_is_refused_on_a_client_workspace(world, client, settings):
    pool, m = world
    resp = client.patch(f"/api/workspace/members/{m.c1_user}", json={"provider_wide": True},
                        headers=token(settings, m.p_admin, m.client1_ws))
    assert resp.status_code == 422


async def test_the_audit_read_pages_and_caps(world, client, settings):
    pool, m = world
    headers = token(settings, m.d_user, m.direct_ws)
    for i in range(3):
        client.post("/api/workspace/members", json={"email": f"p{i}@{DOMAIN}", "role": "viewer"},
                    headers=headers)
    first = client.get("/api/audit?limit=2", headers=headers).json()["events"]
    assert len(first) == 2
    older = client.get("/api/audit", params={"limit": 2, "before": first[-1]["at"]},
                       headers=headers)
    assert older.status_code == 200
    assert {e["id"] for e in older.json()["events"]}.isdisjoint({e["id"] for e in first})
    assert client.get("/api/audit?limit=101", headers=headers).status_code == 422
    assert client.get("/api/audit?limit=0", headers=headers).status_code == 422
    assert client.get("/api/audit?before=yesterday", headers=headers).status_code == 422


async def test_an_admin_sees_only_their_active_workspace(world, client, settings):
    pool, m = world
    in_provider = client.get("/api/workspace/members",
                             headers=token(settings, m.p_admin, m.provider_ws)).json()
    in_client = client.get("/api/workspace/members",
                           headers=token(settings, m.p_admin, m.client1_ws)).json()
    assert {r["user_id"] for r in in_provider["members"]} == {str(m.p_admin), str(m.p_analyst)}
    assert {r["user_id"] for r in in_client["members"]} == {str(m.c1_user)}
