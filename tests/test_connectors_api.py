"""POST and GET /api/connectors (S32, spec decision 3; Review Focus 5): admin-registered,
workspace-scoped, the body capped while it streams."""

import json
from uuid import uuid4

import pytest
from _tenancy import add_membership, build_mssp, drop_orgs, make_user, token
from auspex_sdk.package import MAX_PACKAGE_BYTES, build_zip
from starlette.requests import Request

from auspex.connectors import routes
from auspex.connectors.catalogue import available
from auspex.db import create_pool

PREFIX = "t-s32-api"


def package(connector_id: str, version: str = "1.0.0") -> bytes:
    manifest = {
        "schema_version": 1, "id": connector_id, "version": version,
        "name": "API test", "description": "A package the connector routes tests upload.",
        "commands": {"test": {"handler": "pkg.handlers:test"}},
    }
    return build_zip({"manifest.json": json.dumps(manifest).encode(), "pkg/handlers.py": b""})


def fresh_id() -> str:
    return f"tapi.c{uuid4().hex[:12]}"


@pytest.fixture
async def world(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        m = await build_mssp(pool, PREFIX)
        c1_admin = await make_user(pool, f"c1-admin@{PREFIX}.auspex.dev", m.client1)
        await add_membership(pool, m.client1_ws, c1_admin, "admin")
        yield pool, m, c1_admin
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


def _post(client, headers, data: bytes, **form):
    return client.post("/api/connectors", headers=headers, data=form,
                       files={"package": ("pkg.zip", data, "application/zip")})


def _ids(response):
    return {c["connector_id"] for c in response.json()["connectors"]}


async def test_an_analyst_cannot_register_and_an_admin_can(world, client, settings):
    pool, m, _ = world
    cid = fresh_id()
    denied = _post(client, token(settings, m.c1_user, m.client1_ws), package(cid))
    assert denied.status_code == 403
    assert cid not in {e.connector_id for e in await available(pool, workspace_id=m.client1_ws)}
    ok = _post(client, token(settings, m.d_user, m.direct_ws), package(cid))
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["connector_id"] == cid and body["source"] == "own"
    assert body["workspace_id"] == str(m.direct_ws)
    assert body["registered_by"] == str(m.d_user)
    assert body["content_hash"].startswith("sha256:")


async def test_the_workspace_and_registrar_come_from_the_session_not_the_form(
        world, client, settings):
    pool, m, _ = world
    cid = fresh_id()
    admin = token(settings, m.d_user, m.direct_ws)
    res = _post(client, admin, package(cid), first_party="true",
                workspace_id=str(m.client1_ws), registered_by=str(m.c1_user))
    assert res.status_code == 201, res.text
    assert res.json()["first_party"] is False
    assert res.json()["workspace_id"] == str(m.direct_ws)
    assert res.json()["registered_by"] == str(m.d_user)
    assert not await pool.fetchval("SELECT first_party FROM connector_packages"
                                   " WHERE connector_id = $1", cid)
    assert cid not in {e.connector_id for e in await available(pool, workspace_id=m.client1_ws)}


async def test_a_client_admin_cannot_offer_to_clients(world, client, settings):
    pool, m, c1_admin = world
    res = _post(client, token(settings, c1_admin, m.client1_ws), package(fresh_id()),
                offered_to_clients="true")
    assert res.status_code == 422
    assert "provider" in res.json()["detail"]


async def test_a_refusal_is_422_in_words(world, client, settings):
    pool, m, _ = world
    admin = token(settings, m.d_user, m.direct_ws)
    res = _post(client, admin, b"not a zip")
    assert res.status_code == 422 and res.json()["detail"].startswith("package refused")
    cid = fresh_id()
    assert _post(client, admin, package(cid)).status_code == 201
    other = build_zip({"manifest.json": json.dumps({
        "schema_version": 1, "id": cid, "version": "1.0.0", "name": "x", "description": "y",
        "commands": {"test": {"handler": "pkg.other:test"}}}).encode(), "pkg/other.py": b""})
    again = _post(client, admin, other)
    assert again.status_code == 422 and "bump the version" in again.json()["detail"]
    assert client.post("/api/connectors", headers=admin, data={"x": "1"}).status_code == 422
    flag = _post(client, admin, package(fresh_id()), offered_to_clients="maybe")
    assert flag.status_code == 422 and "true or false" in flag.json()["detail"]


async def test_an_oversize_upload_is_413_before_it_is_parsed(world, client, settings, monkeypatch):
    pool, m, _ = world

    async def never(*_a, **_k):
        raise AssertionError("an oversize body reached the multipart parser")

    monkeypatch.setattr(Request, "form", never)
    monkeypatch.setattr(routes, "register", never)
    admin = token(settings, m.d_user, m.direct_ws)
    over = b"0" * (routes.MAX_BODY_BYTES + 1)
    # Declared: refused from the header alone.
    res = client.post("/api/connectors", headers={**admin, "Content-Type": "multipart/form-data"},
                      content=over)
    assert res.status_code == 413 and str(MAX_PACKAGE_BYTES) in res.json()["detail"]

    # Undeclared (chunked): refused by the streaming cap.
    def chunks():
        for _ in range(routes.MAX_BODY_BYTES // 65536 + 2):
            yield b"0" * 65536

    res = client.post("/api/connectors", headers={**admin, "Content-Type": "multipart/form-data"},
                      content=chunks())
    assert res.status_code == 413


async def test_the_cap_stops_reading_at_the_first_chunk_past_it():
    pulled = 0

    class Body:
        async def stream(self):
            nonlocal pulled
            for _ in range(10_000):  # ~640 MB if it were all read
                pulled += 1
                yield b"0" * 65536

    with pytest.raises(routes.HTTPException) as err:
        await routes.read_capped(Body())
    assert err.value.status_code == 413
    assert pulled == routes.MAX_BODY_BYTES // 65536 + 1


async def test_a_package_just_inside_the_cap_is_read_whole():
    class Body:
        async def stream(self):
            yield b"a" * 10
            yield b"b" * 10

    assert await routes.read_capped(Body(), limit=20) == b"a" * 10 + b"b" * 10


async def test_listing_per_role_and_workspace(world, client, settings):
    pool, m, c1_admin = world
    own, offered = fresh_id(), fresh_id()
    assert _post(client, token(settings, c1_admin, m.client1_ws), package(own)).status_code == 201
    assert _post(client, token(settings, m.p_admin, m.provider_ws), package(offered),
                 offered_to_clients="true").status_code == 201
    for user, ws in ((m.c1_user, m.client1_ws), (c1_admin, m.client1_ws)):
        listed = client.get("/api/connectors", headers=token(settings, user, ws))
        assert listed.status_code == 200
        assert {own, offered} <= _ids(listed)
    assert client.get("/api/connectors").status_code == 401
    # Not the sibling, not another organization.
    for user, ws in ((m.c2_user, m.client2_ws), (m.d_user, m.direct_ws)):
        ids = _ids(client.get("/api/connectors", headers=token(settings, user, ws)))
        assert own not in ids
    assert offered not in _ids(client.get("/api/connectors",
                                          headers=token(settings, m.d_user, m.direct_ws)))
    assert offered in _ids(client.get("/api/connectors",
                                      headers=token(settings, m.c2_user, m.client2_ws)))


async def test_a_listed_provider_package_exposes_neither_workspace_nor_registrar(
        world, client, settings):
    pool, m, _ = world
    offered = fresh_id()
    res = _post(client, token(settings, m.p_admin, m.provider_ws), package(offered),
                offered_to_clients="true")
    assert res.status_code == 201
    assert res.json()["workspace_id"] == str(m.provider_ws)  # the owner sees its own
    row = next(c for c in client.get("/api/connectors",
                                     headers=token(settings, m.c1_user, m.client1_ws)
                                     ).json()["connectors"] if c["connector_id"] == offered)
    assert row["source"] == "provider"
    assert "workspace_id" not in row and "registered_by" not in row
    assert str(m.provider_ws) not in json.dumps(row) and str(m.p_admin) not in json.dumps(row)
