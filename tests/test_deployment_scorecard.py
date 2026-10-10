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

from auspex.auth import get_or_create_user
from auspex.db import create_pool
from auspex.llm.scorecard import (
    DEPLOYMENT_WORKSPACE,
    CapabilityScorecard,
    endpoint_fingerprint,
    save_deployment_scorecard,
    save_scorecard,
)

TEST_BASE = "https://d035-deployment-scope.test/v1"
TEST_MODEL = "d035-model"
DEV_EMAIL = "analyst@auspex.dev"


def _sc(native_reasoning: bool) -> CapabilityScorecard:
    return CapabilityScorecard(
        base_url=TEST_BASE, model=TEST_MODEL, reachable=True, native_reasoning=native_reasoning
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
        _db(settings, lambda pool: pool.execute(
            "DELETE FROM llm_endpoint_scorecards WHERE endpoint_fingerprint = $1",
            endpoint_fingerprint(TEST_BASE, TEST_MODEL),
        ))


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
