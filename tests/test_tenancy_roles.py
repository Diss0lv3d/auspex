"""S30 (D-061): roles are enforced by code, every write needs one, no route
takes a workspace id from input but the switch, and a removed member's open
stream ends."""

import asyncio
import json
import re
import threading
import typing
from pathlib import Path

import asyncpg
import pytest
from _tenancy import build_mssp, drop_orgs, token
from fastapi import Body, FastAPI, Header, Query
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import BaseModel

from auspex.app import create_app
from auspex.auth import NO_ACCESS, require_admin, require_analyst
from auspex.db import create_pool
from auspex.routes import proposals as proposals_route

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "t-s30-roles"
ROLE_FREE_WRITES = {
    ("POST", "/api/auth/dev-login"),
    ("POST", "/api/auth/api-keys"),
    ("POST", "/api/auth/switch"),
}
TENANT_ID = re.compile(
    r"(^|_)(wid|ws|workspace|workspaces|tenant|tenants|org|orgs|organization|organizations)(_|$)",
    re.IGNORECASE,
)
ID_FROM_INPUT_ALLOWED = {("POST", "/api/auth/switch", "workspace_id")}


def _api_routes():
    for ctx in iter_route_contexts(create_app().routes):
        if isinstance(ctx.route, APIRoute) and ctx.path.startswith("/api"):
            yield ctx


def _calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def _is_tenant_name(name):
    """Match a name however it is spelled: `X-Workspace-Id`, `workspaceId`, `ws_id`."""
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).replace("-", "_").lower()
    return bool(TENANT_ID.search(snake))


def _models_in(annotation, seen=()):
    """Every Pydantic model an annotation carries: bare, Optional/union, list/dict, nested."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation not in seen:
            yield annotation
            for field in annotation.model_fields.values():
                yield from _models_in(field.annotation, (*seen, annotation))
        return
    for arg in typing.get_args(annotation):
        yield from _models_in(arg, seen)


def _inputs(dependant):
    for p in (*dependant.path_params, *dependant.query_params,
              *dependant.header_params, *dependant.cookie_params):
        yield p.name
        yield p.alias or p.name
    for p in dependant.body_params:
        yield p.name
        yield p.alias or p.name
        for model in _models_in(p.field_info.annotation):
            for name, field in model.model_fields.items():
                yield name
                yield field.alias or name
    for dep in dependant.dependencies:
        yield from _inputs(dep)


def test_every_write_needs_an_analyst_or_an_admin():
    checked, missing = 0, []
    for ctx in _api_routes():
        for method in ctx.methods - {"GET", "HEAD"}:
            if (method, ctx.path) in ROLE_FREE_WRITES:
                continue
            checked += 1
            if not set(_calls(ctx.route.dependant)) & {require_admin, require_analyst}:
                missing.append((method, ctx.path))
    assert checked >= 12, f"the walk found only {checked} writes; it is checking nothing"
    assert not missing, f"writes any role may make: {missing}"


def test_no_route_takes_a_workspace_or_tenant_id_from_input():
    seen, offending = 0, []
    for ctx in _api_routes():
        for method in ctx.methods:
            for name in _inputs(ctx.route.dependant):
                seen += 1
                if _is_tenant_name(name) and (method, ctx.path, name) not in ID_FROM_INPUT_ALLOWED:
                    offending.append((method, ctx.path, name))
    assert seen >= 20, f"the walk saw only {seen} inputs; it is checking nothing"
    assert not offending, f"workspace/tenant ids read from input: {offending}"


def test_no_handler_reads_raw_input_around_the_walk():
    sources = {p.name: p.read_text() for p in (ROOT / "auspex" / "routes").glob("*.py")}
    for name, text in sources.items():
        assert "query_params" not in text and "path_params" not in text, name
        assert "request.headers" not in text, name
    # chat's endpoint resolver reads only the dev `endpoint_id` from the body.
    assert sum(text.count("request.json()") for text in sources.values()) == 1


@pytest.mark.parametrize("name", [
    "X-Workspace-Id", "X-Tenant", "workspace-id", "workspaceId", "tenantId",
    "orgId", "organizationId", "ws_id", "wid", "workspace_id",
])
def test_the_tenant_pattern_catches_every_spelling(name):
    assert _is_tenant_name(name), name


@pytest.mark.parametrize("name", [
    "session_id", "endpoint_id", "obs_id", "user_id", "proposal_id",
    "investigation_id", "match_id", "provider_wide", "display_name", "before",
    "limit", "email", "role",
])
def test_the_tenant_pattern_leaves_real_names_alone(name):
    assert not _is_tenant_name(name), name


def test_the_input_walk_unwraps_every_body_shape():
    class Inner(BaseModel):
        workspace_id: str

    class Scope(BaseModel):
        inner: Inner

    class Camel(BaseModel):
        tenantId: str  # noqa: N815

    app = FastAPI()

    @app.post("/optional")
    def optional(body: Inner | None = None): ...

    @app.post("/listed")
    def listed(body: list[Inner]): ...

    @app.post("/nested")
    def nested(body: Scope): ...

    @app.post("/camel")
    def camel(body: Camel): ...

    @app.post("/header")
    def header(x: typing.Annotated[str, Header(alias="X-Workspace-Id")]): ...

    @app.post("/query")
    def query(x: typing.Annotated[str, Query(alias="orgId")]): ...

    @app.post("/embedded")
    def embedded(x: typing.Annotated[str, Body(alias="ws_id")]): ...

    walked = 0
    for ctx in iter_route_contexts(app.routes):
        if not isinstance(ctx.route, APIRoute):
            continue
        walked += 1
        names = list(_inputs(ctx.route.dependant))
        assert any(_is_tenant_name(n) for n in names), (ctx.path, names)
    assert walked == 7


@pytest.fixture
async def world(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        yield pool, await build_mssp(pool, PREFIX)
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


async def test_a_viewer_reads_but_never_writes(world, client, settings):
    pool, m = world
    await pool.execute("UPDATE memberships SET role = 'viewer' WHERE user_id = $1", m.c1_user)
    headers = token(settings, m.c1_user, m.client1_ws)
    assert client.get("/api/proposals", headers=headers).status_code == 200
    resp = client.post("/api/chat", json={"message": "what is CVE-2021-44228?"},
                       headers=headers)
    assert resp.status_code == 403
    assert "analyst" in resp.json()["detail"]
    assert await pool.fetchval(
        "SELECT count(*) FROM chat_sessions WHERE user_id = $1", m.c1_user) == 0


async def test_a_removed_member_s_open_stream_ends(world, client, settings, monkeypatch):
    pool, m = world
    monkeypatch.setattr(proposals_route, "STREAM_POLL_SECONDS", 0.05)
    monkeypatch.setattr(proposals_route, "STREAM_MAX_TICKS", 100)
    headers = token(settings, m.c1_user, m.client1_ws)

    def _remove_later():
        async def _run():
            conn = await asyncpg.connect(settings.database_url)
            try:
                await conn.execute("DELETE FROM memberships WHERE user_id = $1", m.c1_user)
            finally:
                await conn.close()
        asyncio.run(_run())

    timer = threading.Timer(0.3, _remove_later)
    timer.start()
    frames = []
    with client.stream("GET", "/api/proposals/stream", headers=headers) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data: "):
                frames.append(json.loads(line[6:]))
    timer.join()
    assert {"error": NO_ACCESS} in frames
    assert not any("reconnect" in f for f in frames)
