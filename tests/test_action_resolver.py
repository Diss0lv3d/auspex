"""S34 Task 3: actions resolve by workspace (design decision 5). A built-in resolves
anywhere; `<prefix>__<action>` resolves only in its own workspace, for an ENABLED
integration with that action GRANTED, compiled from its pinned package. Prefixes are
never reused (S33), so workspace + prefix binds an approval to its integration."""

import shutil
from pathlib import Path

import pytest
from _tenancy import build_mssp, drop_orgs
from auspex_sdk.build import build

from auspex.actions import ActionRegistry
from auspex.actions.builtin import build_builtin_actions
from auspex.connectors.catalogue import register
from auspex.connectors.resolve import ActionResolver
from auspex.db import create_pool
from auspex.edge_api.agents import create_agent
from auspex.integrations.store import create, disable, set_grants
from auspex.tenancy.audit import person

PREFIX = "t-s34-resolve"
REFERENCE = Path(__file__).resolve().parents[1] / "examples/connectors/mock_siem/yaml"
CONFIG = {"base_url": "https://siem.example:9443", "api_token": "secret:siem_token"}


async def _never(kind, payload):  # the resolver only compiles; nothing runs here
    raise AssertionError("dispatched")


@pytest.fixture(scope="module")
def reference_zip(tmp_path_factory) -> bytes:
    copy = tmp_path_factory.mktemp("ref") / "c"
    shutil.copytree(REFERENCE, copy, ignore=shutil.ignore_patterns("dist", "__pycache__"))
    zip_path, _ = build(copy)
    return zip_path.read_bytes()


@pytest.fixture
async def world(client, settings, reference_zip):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        m = await build_mssp(pool, PREFIX)
        admin = person(m.d_user, m.direct)
        entry = await register(pool, workspace_id=m.direct_ws, data=reference_zip,
                               registered_by=m.d_user, offered_to_clients=False)
        agent, _ = await create_agent(pool, workspace_id=m.direct_ws, actor=admin, name="a")
        integ = await create(pool, workspace_id=m.direct_ws, actor=admin, name="SIEM",
                             prefix="siem1", content_hash=entry.content_hash, config=CONFIG,
                             agent_id=agent.id)
        builtins = ActionRegistry()
        builtins.register_all(build_builtin_actions(pool))
        resolver = ActionResolver(builtins, pool, dispatch=lambda integration: _never)
        yield pool, m, admin, integ, resolver
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


async def test_a_built_in_resolves_in_any_workspace(world):
    _, m, _, _, resolver = world
    for ws in (m.direct_ws, m.client1_ws):
        assert (await resolver.resolve("annotate_observable", ws)).name == "annotate_observable"


async def test_a_granted_action_of_an_enabled_integration_resolves_in_its_workspace(world):
    pool, m, admin, integ, resolver = world
    assert await resolver.resolve("siem1__close_alert", m.direct_ws) is None  # not granted
    await set_grants(pool, workspace_id=m.direct_ws, actor=admin, integration_id=integ.id,
                     actions=["close_alert"])
    spec = await resolver.resolve("siem1__close_alert", m.direct_ws)
    assert spec is not None and spec.name == "siem1__close_alert"
    assert spec.origin.content_hash == integ.content_hash


@pytest.mark.parametrize("case", ["other-workspace", "disabled", "unknown-prefix",
                                  "unknown-action", "no-separator"])
async def test_nothing_else_resolves(world, case):
    """Review Focus 1."""
    pool, m, admin, integ, resolver = world
    await set_grants(pool, workspace_id=m.direct_ws, actor=admin, integration_id=integ.id,
                     actions=["close_alert"])
    name, ws = "siem1__close_alert", m.direct_ws
    if case == "other-workspace":
        ws = m.client1_ws
    elif case == "disabled":
        await disable(pool, workspace_id=m.direct_ws, actor=admin, integration_id=integ.id)
    elif case == "unknown-prefix":
        name = "siem9__close_alert"
    elif case == "unknown-action":
        name = "siem1__delete_everything"
    else:
        name = "siem1close_alert"
    assert await resolver.resolve(name, ws) is None


async def test_the_compiled_action_belongs_to_its_integration_s_workspace(world):
    """Its roles refuse any other workspace (PR #43 review #2), before dispatch."""
    from auspex.connectors.compile import WorkspaceMismatch

    pool, m, admin, integ, resolver = world
    await set_grants(pool, workspace_id=m.direct_ws, actor=admin, integration_id=integ.id,
                     actions=["close_alert"])
    spec = await resolver.resolve("siem1__close_alert", m.direct_ws)
    with pytest.raises(WorkspaceMismatch):
        await spec.dry_run(workspace_id=m.client1_ws, alert_id="A-1")
