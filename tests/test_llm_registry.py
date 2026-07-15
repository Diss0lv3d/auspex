"""Dev-endpoint registry (D-016 feature 2): dev-only, fail-safe, no secret leak."""

import json

from auspex.config import Settings
from auspex.llm.registry import DevEndpoint, load_dev_registry

REGISTRY = {
    "endpoints": [
        {"id": "scout", "label": "Fast", "base_url": "https://scout.test",
         "model": "some/model", "api_key_env": "SCOUT_KEY", "native_reasoning": False},
        {"id": "qwen", "label": "Deep — shows reasoning", "base_url": "http://localhost:11434",
         "model": "qwen3:14b", "api_key_env": None, "native_reasoning": True},
    ]
}


def _write(tmp_path, data) -> str:
    p = tmp_path / "dev-endpoints.json"
    p.write_text(json.dumps(data))
    return str(p)


def _settings(**kw) -> Settings:
    kw.setdefault("app_env", "dev")
    kw.setdefault("secret_key", "test-key")
    return Settings(**kw)


def test_disabled_without_file():
    assert load_dev_registry(_settings()) == {}


def test_disabled_in_prod_even_with_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_KEY", "x")
    path = _write(tmp_path, REGISTRY)
    # prod must never load the switcher registry, file or not
    reg = load_dev_registry(Settings(app_env="prod", secret_key="k", dev_llm_registry_file=path))
    assert reg == {}


def test_loads_endpoints_in_dev(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_KEY", "secret-value")
    path = _write(tmp_path, REGISTRY)
    reg = load_dev_registry(_settings(dev_llm_registry_file=path))
    assert set(reg) == {"scout", "qwen"}
    assert reg["qwen"].native_reasoning is True
    assert reg["scout"].native_reasoning is False


def test_entry_with_unset_key_env_is_dropped(tmp_path, monkeypatch):
    monkeypatch.delenv("SCOUT_KEY", raising=False)  # key env NOT set
    path = _write(tmp_path, REGISTRY)
    reg = load_dev_registry(_settings(dev_llm_registry_file=path))
    assert "scout" not in reg  # unusable (would 401) → dropped
    assert "qwen" in reg  # keyless entry still loads


def test_unreadable_file_is_fail_safe():
    reg = load_dev_registry(_settings(dev_llm_registry_file="/no/such/file.json"))
    assert reg == {}


def test_malformed_entry_skipped_not_fatal(tmp_path):
    path = _write(tmp_path, {"endpoints": [
        {"id": "ok", "label": "L", "base_url": "http://x", "model": "m"},
        {"label": "missing id/base_url"},  # invalid → skipped
    ]})
    reg = load_dev_registry(_settings(dev_llm_registry_file=path))
    assert set(reg) == {"ok"}


async def test_build_client_resolves_key_from_env_and_never_stores_it(monkeypatch):
    monkeypatch.setenv("SCOUT_KEY", "top-secret")
    ep = DevEndpoint(id="scout", label="Fast", base_url="https://scout.test",
                     model="m", api_key_env="SCOUT_KEY")
    # the key is not a field on the model → cannot be serialized/leaked
    assert "top-secret" not in ep.model_dump_json()
    assert "SCOUT_KEY" in ep.model_dump_json()  # only the var NAME, not the value
    client = ep.build_client()
    try:
        assert client._http.headers.get("Authorization") == "Bearer top-secret"
    finally:
        await client.aclose()
