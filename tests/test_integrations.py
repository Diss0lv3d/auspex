"""S33 Task 2: integrations (D-060, D-063). An admin configures a connector the
workspace may use, names the Edge Agent that runs it, and gives secret fields as
`secret:<name>` only. Removing one disables it; its prefix is never reused."""

import shutil
from pathlib import Path

import pytest
from _tenancy import build_mssp, drop_orgs, token
from auspex_sdk.build import build

from auspex.connectors.catalogue import register
from auspex.db import create_pool
from auspex.edge_api.agents import create_agent
from auspex.integrations.store import IntegrationRefused, create, disable, list_for, update
from auspex.tenancy.audit import list_events, person

PREFIX = "t-s33-integ"
REFERENCE = Path(__file__).resolve().parents[1] / "examples/connectors/mock_siem/yaml"
CONFIG = {"base_url": "https://siem.example:9443", "api_token": "secret:siem_token"}


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
        entry = await register(pool, workspace_id=m.direct_ws, data=reference_zip,
                               registered_by=m.d_user, offered_to_clients=False)
        agent, _ = await create_agent(pool, workspace_id=m.direct_ws,
                                      actor=person(m.d_user, m.direct), name="site")
        yield pool, m, entry.content_hash, agent.id
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


def _admin(m):
    return person(m.d_user, m.direct)


async def _make(pool, m, content_hash, agent_id, **over):
    kw = {"name": "SIEM", "prefix": "siem1", "content_hash": content_hash,
          "config": CONFIG, "agent_id": agent_id, **over}
    return await create(pool, workspace_id=m.direct_ws, actor=_admin(m), **kw)


async def test_an_admin_configures_an_available_connector(world):
    pool, m, content_hash, agent_id = world
    integ = await _make(pool, m, content_hash, agent_id)
    assert (integ.connector_id, integ.prefix, integ.enabled) == ("example.mock_siem",
                                                                 "siem1", True)
    assert integ.config == CONFIG
    assert [i.id for i in await list_for(pool, workspace_id=m.direct_ws)] == [integ.id]
    assert "integration.created" in [e["action"] for e in await list_events(pool, m.direct_ws)]


@pytest.mark.parametrize("config,reason", [
    ({"base_url": "https://siem.example", "api_token": "hunter2-placeholder"}, "secret:"),
    ({"base_url": "https://siem.example"}, "required"),
    ({**CONFIG, "nope": 1}, "not a config field"),
    ({**CONFIG, "base_url": "http://siem.example"}, "https"),
    ({**CONFIG, "base_url": "https://u:p@siem.example"}, "credentials"),
    ({**CONFIG, "tls": "off"}, "cannot be turned off"),
    ({**CONFIG, "api_token": "secret:has space"}, "secret:"),
], ids=["secret-value", "missing-required", "unknown-field", "http", "userinfo",
        "tls-off", "bad-secret-name"])
async def test_a_config_the_manifest_does_not_allow_is_refused(world, config, reason):
    """Review Focus 2: a secret VALUE, an unknown or missing field, a wrong type: refused
    at write, so no integration row (and no job made from one) can carry a secret."""
    pool, m, content_hash, agent_id = world
    with pytest.raises(IntegrationRefused, match=reason):
        await _make(pool, m, content_hash, agent_id, config=config)


async def test_a_pinned_certificate_is_accepted(world):
    pool, m, content_hash, agent_id = world
    pin = {"cert_sha256": "ab" * 32}
    integ = await _make(pool, m, content_hash, agent_id, config={**CONFIG, "tls": pin})
    assert integ.config["tls"] == pin


async def test_a_package_the_workspace_cannot_use_is_refused(world):
    pool, m, _, agent_id = world
    with pytest.raises(IntegrationRefused, match="not available"):
        await _make(pool, m, "sha256:" + "0" * 64, agent_id)


@pytest.mark.parametrize("prefix", ["1siem", "s" * 25, "si-em", ""])
async def test_a_prefix_that_is_not_a_short_wire_identifier_is_refused(world, prefix):
    pool, m, content_hash, agent_id = world
    with pytest.raises(IntegrationRefused, match="prefix"):
        await _make(pool, m, content_hash, agent_id, prefix=prefix)


async def test_disable_keeps_the_row_and_the_prefix_is_never_reused(world):
    """Hunaiza's call (spec decision 2): an approval can never point at a different
    integration under the same wire name."""
    pool, m, content_hash, agent_id = world
    integ = await _make(pool, m, content_hash, agent_id)
    await disable(pool, workspace_id=m.direct_ws, actor=_admin(m), integration_id=integ.id)
    [kept] = await list_for(pool, workspace_id=m.direct_ws)
    assert kept.id == integ.id and not kept.enabled
    with pytest.raises(IntegrationRefused, match="prefix"):
        await _make(pool, m, content_hash, agent_id, name="again")
    actions = [e["action"] for e in await list_events(pool, m.direct_ws)]
    assert "integration.disabled" in actions


async def test_an_agent_of_another_workspace_is_refused(world):
    pool, m, content_hash, _ = world
    foreign, _ = await create_agent(pool, workspace_id=m.client1_ws,
                                    actor=person(m.c1_user, m.client1), name="theirs")
    with pytest.raises(IntegrationRefused, match="agent"):
        await _make(pool, m, content_hash, foreign.id)


async def test_an_update_revalidates_and_is_audited(world):
    pool, m, content_hash, agent_id = world
    integ = await _make(pool, m, content_hash, agent_id)
    changed = await update(pool, workspace_id=m.direct_ws, actor=_admin(m),
                           integration_id=integ.id,
                           config={**CONFIG, "base_url": "https://other.example"})
    assert changed.config["base_url"] == "https://other.example"
    with pytest.raises(IntegrationRefused, match="secret:"):
        await update(pool, workspace_id=m.direct_ws, actor=_admin(m), integration_id=integ.id,
                     config={**CONFIG, "api_token": "a-value"})
    assert "integration.updated" in [e["action"] for e in await list_events(pool, m.direct_ws)]


async def test_the_routes_are_admin_written_and_never_cross_a_workspace(world, client,
                                                                         settings):
    pool, m, content_hash, agent_id = world
    admin = token(settings, m.d_user, m.direct_ws)
    body = {"name": "SIEM", "prefix": "siem1", "content_hash": content_hash,
            "config": CONFIG, "agent_id": str(agent_id)}
    made = client.post("/api/integrations", json=body, headers=admin)
    assert made.status_code == 201, made.text
    iid = made.json()["id"]
    refused = client.post("/api/integrations", json={**body, "prefix": "siem2",
                                                     "config": {**CONFIG, "api_token": "x"}},
                          headers=admin)
    assert refused.status_code == 422 and "secret:" in refused.json()["detail"]
    other = token(settings, m.c1_user, m.client1_ws)
    assert client.get("/api/integrations", headers=other).json() == {"integrations": []}
    assert client.post(f"/api/integrations/{iid}/disable", headers=other).status_code in (403,
                                                                                         404)
    assert client.post("/api/integrations", json=body, headers=other).status_code == 403
    listed = client.get("/api/integrations", headers=admin).json()["integrations"]
    assert [i["prefix"] for i in listed] == ["siem1"] and listed[0]["health"] == "never"
    assert client.patch(f"/api/integrations/{iid}", json={"name": "Main SIEM"},
                        headers=admin).json()["name"] == "Main SIEM"
    assert client.post(f"/api/integrations/{iid}/disable", headers=admin).status_code == 204


@pytest.mark.parametrize("field,value", [
    ("name", "SI\x00EM"), ("name", "SI\ud800EM"),
    ("config", {**CONFIG, "base_url": "https://siem.example/\x00"}),
], ids=["nul-name", "surrogate-name", "nul-config"])
async def test_text_postgres_cannot_store_is_refused_in_words(world, field, value):
    """PR #51 review s2: a NUL or a lone surrogate reached Postgres and answered 500."""
    pool, m, content_hash, agent_id = world
    with pytest.raises(IntegrationRefused, match="NUL or a lone surrogate"):
        await _make(pool, m, content_hash, agent_id, **{field: value})


async def test_an_agent_name_postgres_cannot_store_is_refused(world):
    pool, m, _, _ = world
    with pytest.raises(ValueError, match="NUL or a lone surrogate"):
        await create_agent(pool, workspace_id=m.direct_ws, actor=_admin(m), name="a\x00b")


async def test_a_malformed_base_url_is_refused_in_words(world):
    """PR #51 review s3: `urlsplit` raised outside any refusal, a 500."""
    pool, m, content_hash, agent_id = world
    with pytest.raises(IntegrationRefused, match="https"):
        await _make(pool, m, content_hash, agent_id,
                    config={**CONFIG, "base_url": "https://[siem.local/api"})
