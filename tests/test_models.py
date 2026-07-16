"""Model switcher (D-016 feature 2): /api/models + endpoint selection.

Dev-only, inert in prod, never leaks secrets. Hermetic."""

import json
from uuid import uuid4

import pytest
from _fakes import StreamingFakeLLMClient
from fastapi import HTTPException
from fastapi.testclient import TestClient

from auspex.app import create_app
from auspex.auth import AuthContext, resolve_user
from auspex.config import Settings
from auspex.llm.client import StreamEvent
from auspex.llm.registry import DevEndpoint
from auspex.routes.chat import select_dev_endpoint

DEV_EMAIL = "analyst@auspex.dev"

# Distinctive secret-ish values so the no-leak assertions are unambiguous.
REG = {
    "qwen": DevEndpoint(id="qwen", label="Deep — shows reasoning",
                        base_url="https://leak-host-A.test", model="LEAK-MODEL-A",
                        native_reasoning=True),
    "scout": DevEndpoint(id="scout", label="Fast",
                         base_url="https://leak-host-B.test", model="LEAK-MODEL-B",
                         api_key_env="LEAK_KEY_ENV", native_reasoning=False),
}

FORBIDDEN_ENGINE_NAMES = ["qwen", "llama", "scout", "vllm", "gpt", "openai", "nvidia"]


def _token(client) -> str:
    return client.post("/api/auth/dev-login", json={"email": DEV_EMAIL}).json()["access_token"]


class _FakeEntry:
    """Duck-typed registry entry whose build_client returns a fake (no network)."""

    def __init__(self, fake, *, native_reasoning, id="qwen", label="Deep"):
        self._fake = fake
        self.native_reasoning = native_reasoning
        self.id = id
        self.label = label

    def build_client(self):
        return self._fake


# -- select_dev_endpoint (the dev-only gate, pure) ---------------------------


def test_select_ignored_in_prod():
    assert select_dev_endpoint(REG, "prod", "qwen") is None  # D-005: inert in prod


def test_select_none_for_no_id_or_default():
    assert select_dev_endpoint(REG, "dev", None) is None
    assert select_dev_endpoint(REG, "dev", "default") is None


def test_select_returns_entry_in_dev():
    assert select_dev_endpoint(REG, "dev", "qwen") is REG["qwen"]


def test_select_unknown_id_is_404():
    with pytest.raises(HTTPException) as exc:
        select_dev_endpoint(REG, "dev", "ghost")
    assert exc.value.status_code == 404


# -- GET /api/models ---------------------------------------------------------


def test_models_dev_lists_default_plus_registry_without_secrets(client):
    client.app.state.dev_llm_registry = REG
    try:
        r = client.get("/api/models", headers={"Authorization": f"Bearer {_token(client)}"})
        assert r.status_code == 200
        data = r.json()
        ids = [e["id"] for e in data["endpoints"]]
        assert ids[0] == "default"
        assert {"qwen", "scout"} <= set(ids)
        assert data["endpoints"][1 + ids[1:].index("qwen")]["capabilities"]["native_reasoning"]

        blob = json.dumps(data)
        for secret in ["leak-host", "LEAK-MODEL", "LEAK_KEY_ENV", "api_key", "base_url"]:
            assert secret not in blob, f"leaked {secret!r} to the client"
        # labels are brand-safe (no engine names in the displayed strings)
        labels = " ".join(e["label"] for e in data["endpoints"]).lower()
        for name in FORBIDDEN_ENGINE_NAMES:
            assert name not in labels
    finally:
        client.app.state.dev_llm_registry = {}


def test_models_requires_auth(client):
    assert client.get("/api/models").status_code == 401


def test_models_404_in_prod():
    app = create_app(Settings(app_env="prod", secret_key="test-prod-secret"))
    with TestClient(app) as prod_client:
        # bypass auth so we reach (and prove) the dev-only gate itself
        app.dependency_overrides[resolve_user] = lambda: AuthContext(
            user_id=uuid4(), workspace_id=uuid4(), via="jwt"
        )
        try:
            assert prod_client.get("/api/models").status_code == 404
        finally:
            app.dependency_overrides.clear()


# -- endpoint_id routing (integration, no network) ---------------------------


def _frames(body: str):
    return [json.loads(ln[len("data:"):].strip())
            for ln in body.splitlines() if ln.strip().startswith("data:")]


def test_endpoint_id_routes_to_selected_client(client):
    fake = StreamingFakeLLMClient([
        StreamEvent(kind="content", text="routed"),
        StreamEvent(kind="finish", finish_reason="stop"),
    ])
    client.app.state.dev_llm_registry = {"qwen": _FakeEntry(fake, native_reasoning=True)}
    try:
        resp = client.post(
            "/api/chat", json={"message": "hi", "endpoint_id": "qwen"},
            headers={"Authorization": f"Bearer {_token(client)}"},
        )
        assert resp.status_code == 200
        content = "".join(f["content"] for f in _frames(resp.text) if "content" in f)
        assert content == "routed"
        assert fake.stream_calls, "selected endpoint's client was not used"
        assert fake.closed is True
    finally:
        client.app.state.dev_llm_registry = {}


def test_unknown_endpoint_id_is_404(client):
    client.app.state.dev_llm_registry = {}
    resp = client.post(
        "/api/chat", json={"message": "hi", "endpoint_id": "ghost"},
        headers={"Authorization": f"Bearer {_token(client)}"},
    )
    assert resp.status_code == 404
