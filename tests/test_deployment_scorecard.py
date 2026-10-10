"""D-035: the default endpoint's scorecard is the DEPLOYMENT's.

Before D-035 the only writer (scripts/llm_harness.py) saved to a workspace named
'dev' and the only reader (`_default_native_reasoning`) read the analyst's own
workspace — so the configured endpoint never found its own scorecard, and every
deep turn on a thinking model paid for a two-pass whose first pass its own
thinking emptied (docs/probes/2026-10-10-zai-endpoint.md, "Through the running
app"). These pin the writer and the reader to one scope, and that scope to one
that no tenant can reach.

Runs against the live dev DB like test_llm_scorecard.py, under a fingerprint no
real endpoint has, and deletes exactly the rows it wrote — the dev deployment's
real scorecard is never touched.
"""

import asyncio

import asyncpg
import pytest
from starlette.requests import Request

from auspex.auth import AuthContext, get_or_create_user
from auspex.db import create_pool
from auspex.llm.scorecard import (
    DEPLOYMENT_WORKSPACE,
    CapabilityScorecard,
    endpoint_fingerprint,
    save_deployment_scorecard,
    save_scorecard,
)
from auspex.routes.chat import get_endpoint_resolver

TEST_BASE = "https://d035-deployment-scope.test/v1"
TEST_MODEL = "d035-model"
DEV_EMAIL = "analyst@auspex.dev"
TENANT_B_EMAIL = "d035-tenant-b@auspex.dev"
# Every workspace these tests create, so the fixture can remove them.
SCRATCH_WORKSPACES = ["d035-tenant-b", "d035-userless"]


def _sc(native_reasoning: bool, *, model: str = TEST_MODEL, base_url: str = TEST_BASE):
    return CapabilityScorecard(
        base_url=base_url, model=model, reachable=True, native_reasoning=native_reasoning
    )


def _db(settings, op):
    """Run one async DB operation against a fresh pool from a sync test."""

    async def run():
        pool = await create_pool(settings.database_url, retries=2, delay=0.5)
        try:
            return await op(pool)
        finally:
            await pool.close()

    return asyncio.run(run())


@pytest.fixture
def default_endpoint_is_the_test_one(client, settings):
    """Point the app's configured endpoint at the test fingerprint for one test,
    then delete every scorecard row written under it."""
    real = client.app.state.settings
    client.app.state.settings = real.model_copy(
        update={"llm_base_url": TEST_BASE, "llm_model": TEST_MODEL}
    )
    try:
        yield client
    finally:
        client.app.state.settings = real

        async def cleanup(pool):
            await pool.execute(
                "DELETE FROM llm_endpoint_scorecards WHERE base_url LIKE $1",
                "%d035-%",
            )
            await pool.execute("DELETE FROM users WHERE email = $1", TENANT_B_EMAIL)
            await pool.execute(
                "DELETE FROM workspaces WHERE name = ANY($1::text[])", SCRATCH_WORKSPACES
            )

        _db(settings, cleanup)


def _shown(client) -> bool:
    """What the route believes about the default endpoint — the same function
    the chat resolver uses to pick native vs two-pass."""
    token = client.post("/api/auth/dev-login", json={"email": DEV_EMAIL}).json()["access_token"]
    r = client.get("/api/models", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    default = r.json()["endpoints"][0]
    assert default["id"] == "default"
    return default["capabilities"]["native_reasoning"]


def test_a_deployment_probe_is_what_the_default_endpoint_reports(
    default_endpoint_is_the_test_one, settings
):
    client = default_endpoint_is_the_test_one
    # Control first: never probed reads as unknown → False. Without it, a True
    # below could come from anything but the write.
    assert _shown(client) is False

    _db(settings, lambda pool: save_deployment_scorecard(pool, _sc(native_reasoning=True)))

    assert _shown(client) is True


def test_a_scorecard_in_the_analysts_own_workspace_is_not_the_deployments(
    default_endpoint_is_the_test_one, settings
):
    """The pre-D-035 reader's scope. A row there — the analyst's workspace, or by
    extension any tenant's — must not decide what the deployment's endpoint is."""
    client = default_endpoint_is_the_test_one

    async def write_in_analyst_workspace(pool):
        _, workspace_id = await get_or_create_user(pool, email=DEV_EMAIL)
        await save_scorecard(pool, workspace_id, _sc(native_reasoning=True))

    _db(settings, write_in_analyst_workspace)

    assert _shown(client) is False


@pytest.mark.parametrize("other", ["another tenant", "a userless workspace"])
def test_no_other_workspace_decides_the_deployments_endpoint(
    default_endpoint_is_the_test_one, settings, other
):
    """D-035 rejects "look the fingerprint up in any workspace" as a cross-tenant
    read. A reader that widened the scope — any workspace but the caller's, or
    any workspace nobody belongs to (the legacy `dev` one is exactly that) — would
    let tenant B's probe decide tenant A's turn."""
    client = default_endpoint_is_the_test_one
    assert _shown(client) is False  # control

    async def write_elsewhere(pool):
        if other == "another tenant":
            _, ws = await get_or_create_user(
                pool, email=TENANT_B_EMAIL, workspace_name="d035-tenant-b"
            )
        else:
            ws = await pool.fetchval(
                "INSERT INTO workspaces (name) VALUES ('d035-userless') RETURNING id"
            )
        await save_scorecard(pool, ws, _sc(native_reasoning=True))

    _db(settings, write_elsewhere)

    assert _shown(client) is False


def test_a_deployment_probe_of_another_model_is_not_the_defaults(
    default_endpoint_is_the_test_one, settings
):
    """The deployment workspace holds one row per FINGERPRINT. When LLM_MODEL
    changes — Scout to glm-4.5-air, this very session — the previous model's
    probe must not decide the new one's mode."""
    client = default_endpoint_is_the_test_one
    _db(settings, lambda pool: save_deployment_scorecard(
        pool, _sc(native_reasoning=True, model=TEST_MODEL + "-previous")
    ))

    assert _shown(client) is False


def test_a_probe_dialled_by_another_name_is_recorded_as_the_deployments(
    default_endpoint_is_the_test_one, settings
):
    """Local Ollama: the container is configured with host.docker.internal, the
    host-side harness can only dial localhost. Recorded under the dialled name,
    the probe is one the route never looks up."""
    client = default_endpoint_is_the_test_one
    dialled = _sc(native_reasoning=True, base_url="http://d035-dialled-by-host.test/v1")

    _db(settings, lambda pool: save_deployment_scorecard(pool, dialled))
    assert _shown(client) is False  # the bug, as a control

    _db(settings, lambda pool: save_deployment_scorecard(pool, dialled, as_base_url=TEST_BASE))
    assert _shown(client) is True


def test_the_chat_resolver_itself_reads_the_deployment_scorecard(
    default_endpoint_is_the_test_one, settings
):
    """/api/models reports the same function, but the defect lived in the path a
    deep turn takes: `get_endpoint_resolver` → `resolve()`. Driven directly (no
    model call — resolve() only builds a client) so a refactor of that path
    cannot drift back to the analyst's workspace while /api/models stays right."""
    client = default_endpoint_is_the_test_one
    _db(settings, lambda pool: save_deployment_scorecard(pool, _sc(native_reasoning=True)))

    endpoint_id, native, base_url, *_ = _resolve_as_the_analyst(client)

    assert (endpoint_id, base_url) == ("default", TEST_BASE.rstrip("/"))  # it IS the default
    assert native is True


def _resolve_as_the_analyst(client):
    """`get_endpoint_resolver` → `resolve()`, the path a deep turn takes, driven
    directly (no model call — resolve() only builds a client)."""

    async def resolve():
        pool = client.app.state.pool
        user_id, workspace_id = await get_or_create_user(pool, email=DEV_EMAIL)

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        request = Request(
            {"type": "http", "method": "POST", "path": "/api/chat", "headers": [],
             "app": client.app},
            receive,
        )
        auth = AuthContext(user_id=user_id, workspace_id=workspace_id, via="jwt")
        endpoint = await (await get_endpoint_resolver(request, auth)).resolve()
        try:
            return (endpoint.id, endpoint.native_reasoning, endpoint.client.base_url,
                    endpoint.agent_mode, endpoint.streams_tools)
        finally:
            await endpoint.client.aclose()

    return client.portal.call(resolve)


def test_the_resolver_carries_the_mode_the_deployment_scorecard_compiles_to(
    default_endpoint_is_the_test_one, settings
):
    """D-037 clause 2 is read from here: the agent path runs only when the
    deployment's scorecard compiles to native_tools. Unprobed must reach the
    route as None — unknown, never assumed — and a probe that found no native
    tool calling must not."""
    client = default_endpoint_is_the_test_one
    assert _resolve_as_the_analyst(client)[3] is None  # nothing has probed it

    _db(settings, lambda pool: save_deployment_scorecard(pool, _sc(native_reasoning=True)))
    assert _resolve_as_the_analyst(client)[3] == "plan_only"  # reachable, no tools

    tools = _sc(native_reasoning=True).model_copy(update={"native_tool_calling": True})
    _db(settings, lambda pool: save_deployment_scorecard(pool, tools))
    assert _resolve_as_the_analyst(client)[3] == "native_tools"


def test_the_resolver_carries_whether_the_endpoint_streams_its_tool_calls(
    default_endpoint_is_the_test_one, settings
):
    """The agent path streams; `native_tools` is decided non-streaming. The
    resolver carries the streaming measurement so the route can require both."""
    client = default_endpoint_is_the_test_one
    assert _resolve_as_the_analyst(client)[4] is False  # unprobed: not measured

    calls = _sc(native_reasoning=True).model_copy(update={"native_tool_calling": True})
    _db(settings, lambda pool: save_deployment_scorecard(pool, calls))
    assert _resolve_as_the_analyst(client)[3:] == ("native_tools", False)

    streams = calls.model_copy(update={"streaming_tool_deltas": True})
    _db(settings, lambda pool: save_deployment_scorecard(pool, streams))
    assert _resolve_as_the_analyst(client)[3:] == ("native_tools", True)


def test_the_newest_deployment_probe_wins(default_endpoint_is_the_test_one, settings):
    """A re-probe after the endpoint changed must replace the old answer — and
    both probes land in ONE system workspace, not one per write."""
    client = default_endpoint_is_the_test_one

    async def probe_twice(pool):
        await save_deployment_scorecard(pool, _sc(native_reasoning=True))
        await save_deployment_scorecard(pool, _sc(native_reasoning=False))
        return await pool.fetch(
            "SELECT w.name FROM llm_endpoint_scorecards s JOIN workspaces w"
            " ON w.id = s.workspace_id WHERE s.endpoint_fingerprint = $1",
            endpoint_fingerprint(TEST_BASE, TEST_MODEL),
        )

    rows = _db(settings, probe_twice)

    assert [r["name"] for r in rows] == [DEPLOYMENT_WORKSPACE, DEPLOYMENT_WORKSPACE]
    assert _shown(client) is False


async def test_no_user_can_be_provisioned_into_the_deployment_workspace(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    conn = await asyncpg.connect(settings.database_url)
    try:
        with pytest.raises(ValueError, match="reserved"):
            await get_or_create_user(
                pool, email="d035-intruder@auspex.dev", workspace_name=DEPLOYMENT_WORKSPACE
            )
        members = await conn.fetchval(
            "SELECT count(*) FROM users u JOIN workspaces w ON w.id = u.workspace_id"
            " WHERE w.name = $1",
            DEPLOYMENT_WORKSPACE,
        )
        assert members == 0
    finally:
        await conn.execute("DELETE FROM users WHERE email = 'd035-intruder@auspex.dev'")
        await conn.close()
        await pool.close()
