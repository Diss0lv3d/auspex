"""S30 (D-061; design §4): a workspace whose region the engine may not serve
gets no engine turn, refused by code with the reason and nothing stored; a
third-party lookup its region forbids is refused too; LLM-free paths work."""

import ast
from pathlib import Path

import pytest
from _fakes import StreamingFakeLLMClient
from _tenancy import drop_orgs, make_membership_world, token

from auspex.app import create_app
from auspex.classify.observables import ObservableType
from auspex.config import Settings
from auspex.db import create_pool
from auspex.enrich import EnrichmentService
from auspex.enrich.providers.base import Provider
from auspex.enrich.types import ProviderSignal, VerdictLabel
from auspex.llm.client import StreamEvent
from auspex.routes.chat import ChatEndpoint, ChatEndpointResolver, get_endpoint_resolver
from auspex.routes.investigations import get_summary_client_factory

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "t-s30-region"
CEF = ("CEF:0|Vendor|EDR|1.0|500|Beaconing detected|9|"
       "src=203.0.113.7 dst=evil-c2-server.biz")


class _CountingProvider(Provider):
    name = "Counting"
    region = "global"
    accepts = frozenset({ObservableType.IPV4})

    def __init__(self):
        self.lookups = 0

    async def lookup(self, client, observable):
        self.lookups += 1
        return ProviderSignal("Counting", VerdictLabel.MALICIOUS, 0.9, "listed")


@pytest.fixture
async def ksa(client, settings):
    """A ksa workspace with one analyst, on the suite's global engine."""
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        ws, user = await make_membership_world(pool, PREFIX, region="ksa")
        yield pool, ws, user
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


def _fake_endpoint(app):
    fake = StreamingFakeLLMClient([StreamEvent(kind="content", text="an answer"),
                                   StreamEvent(kind="finish", finish_reason="stop")])
    app.dependency_overrides[get_endpoint_resolver] = lambda: ChatEndpointResolver.fixed(
        ChatEndpoint(client=fake, native_reasoning=True, id="test"))
    return fake


async def test_a_ksa_turn_on_a_global_engine_is_refused_with_nothing_stored(ksa, client, settings):
    pool, ws, user = ksa
    fake = _fake_endpoint(client.app)  # a seam that WOULD answer
    try:
        resp = client.post("/api/chat", json={"message": "summarize the overnight alerts"},
                           headers=token(settings, user, ws))
    finally:
        client.app.dependency_overrides.clear()
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "ksa" in detail and "global" in detail and "platform's engine" in detail
    assert fake.turns == 0
    assert await pool.fetchval("SELECT count(*) FROM chat_sessions WHERE workspace_id = $1",
                               ws) == 0


async def test_a_ksa_workspace_still_gets_answers_that_need_no_engine(ksa, client, settings):
    pool, ws, user = ksa
    resp = client.post("/api/chat", json={"message": "what is CVE-2021-44228?"},
                       headers=token(settings, user, ws))
    assert resp.status_code == 200
    assert '"path": "shortcut"' in resp.text


async def test_a_ksa_ioc_check_makes_no_third_party_lookup(ksa, client, settings):
    pool, ws, user = ksa
    provider = _CountingProvider()
    saved = client.app.state.enrichment
    client.app.state.enrichment = EnrichmentService([provider])
    try:
        resp = client.post("/api/chat", json={"message": "check 185.220.101.45"},
                           headers=token(settings, user, ws))
    finally:
        await client.app.state.enrichment.aclose()
        client.app.state.enrichment = saved
    assert resp.status_code == 200
    assert provider.lookups == 0
    assert "region (ksa)" in resp.text
    assert await pool.fetchval("SELECT count(*) FROM observables WHERE workspace_id = $1",
                               ws) == 0


async def test_a_global_workspace_still_looks_up():
    provider = _CountingProvider()
    service = EnrichmentService([provider])
    try:
        from auspex.classify.observables import extract_observables
        outcome = await service.enrich(tuple(extract_observables("185.220.101.45")),
                                       region="global")
    finally:
        await service.aclose()
    assert provider.lookups == 1
    assert outcome.enriched


async def test_a_ksa_lookup_reaches_only_the_providers_in_its_region():
    """Mixed set: the in-region provider answers, the global one is never called."""
    class _KsaProvider(_CountingProvider):
        name = "InKsa"
        region = "ksa"

    far, near = _CountingProvider(), _KsaProvider()
    service = EnrichmentService([far, near])
    try:
        from auspex.classify.observables import extract_observables
        await service.enrich(tuple(extract_observables("185.220.101.45")), region="ksa")
    finally:
        await service.aclose()
    assert far.lookups == 0
    assert near.lookups == 1


async def test_a_ksa_investigation_lookup_and_summary_are_refused(ksa, client, settings):
    pool, ws, user = ksa
    headers = token(settings, user, ws)
    created = client.post("/api/investigations", json={"message": CEF},
                          headers=headers)
    assert created.status_code == 201, created.text
    inv = created.json()["investigation_id"]
    saved = client.app.state.enrichment
    client.app.state.enrichment = EnrichmentService([_CountingProvider()])
    client.app.dependency_overrides[get_summary_client_factory] = lambda: (
        lambda: pytest.fail("the summary built an engine client for a ksa workspace"))
    try:
        lookup = client.post(f"/api/investigations/{inv}/lookups", json={}, headers=headers)
        summary = client.post(f"/api/investigations/{inv}/summary", headers=headers)
    finally:
        client.app.dependency_overrides.clear()
        await client.app.state.enrichment.aclose()
        client.app.state.enrichment = saved
    assert lookup.status_code == 403 and "ksa" in lookup.json()["detail"]
    assert summary.status_code == 403 and "platform's engine" in summary.json()["detail"]


async def test_a_ksa_engine_serves_a_ksa_workspace(settings):
    from fastapi.testclient import TestClient

    # The suite signs tokens with its own settings' key; a fresh dev Settings
    # would mint an ephemeral one and every token would be a 401.
    app = create_app(Settings(engine_region="ksa", secret_key=settings.secret_key))
    with TestClient(app) as ksa_client:
        pool = await create_pool(settings.database_url, retries=2, delay=0.5)
        await drop_orgs(pool, f"{PREFIX}-k")
        try:
            ws, user = await make_membership_world(pool, f"{PREFIX}-k", region="ksa")
            fake = _fake_endpoint(app)
            resp = ksa_client.post("/api/chat", json={"message": "summarize the overnight alerts"},
                                   headers=token(settings, user, ws))
            assert resp.status_code == 200, resp.text
            assert fake.turns == 1
        finally:
            app.dependency_overrides.clear()
            await drop_orgs(pool, f"{PREFIX}-k")
            await pool.close()


def test_every_provider_declares_its_region():
    import importlib
    import pkgutil

    import auspex.enrich.providers as package

    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"auspex.enrich.providers.{info.name}")
    found = [c for c in Provider.__subclasses__() if c.__module__.startswith(package.__name__)]
    assert len(found) >= 7, f"found only {found}"
    for cls in found:
        assert "region" in vars(cls), f"{cls.__name__} inherits its region instead of declaring it"


def test_engine_clients_are_built_only_where_the_guard_stands():
    allowed = {
        "auspex/llm/autoprobe.py",  # the deployment's own probe: no tenant data
        "auspex/llm/registry.py",  # dev endpoints, reached only through chat's guarded route
        "auspex/llm/client.py",
        "auspex/routes/chat.py",
        "auspex/routes/investigations.py",
    }
    builders = set()
    for path in (ROOT / "auspex").rglob("*.py"):
        text = path.read_text()
        if "LLMClient(" in text or "LLMClient.from_settings" in text:
            builders.add(str(path.relative_to(ROOT)))
    assert builders <= allowed, f"new engine client site(s): {builders - allowed}"
    for route in ("chat.py", "investigations.py"):
        source = (ROOT / "auspex" / "routes" / route).read_text()
        assert "engine_refusal(auth.region" in source, route


def test_every_enrich_call_passes_the_region():
    calls = 0
    for path in (ROOT / "auspex").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "enrich"):
                calls += 1
                assert any(k.arg == "region" for k in node.keywords), path
    assert calls >= 3
