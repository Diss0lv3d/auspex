"""UI shell smoke test (S3 step 5): served, on-brand, engine never named."""

# Engine/provider names that must NEVER appear in a user-facing string
# (CLAUDE.md brand rule: the customer-facing model is "the platform's engine").
FORBIDDEN_ENGINE_NAMES = ["qwen", "ollama", "llama", "vllm", "northflank", "gpt", "openai"]


def test_index_served_dark_first_and_on_brand(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "Auspex" in body
    assert "the flock sees first" in body
    # dark-first palette present (Night bg + Aurora accent, CLAUDE.md D-002)
    assert "#0A0D12" in body
    assert "#4FF2C0" in body


def test_index_has_hidden_switcher_scaffolding(client):
    """The model switcher ships hidden with NO options in static HTML (populated
    only from /api/models when the server offers >1 endpoint)."""
    body = client.get("/").text
    assert 'id="endpoint"' in body and "hidden" in body
    assert "/api/models" in body  # populated after sign-in
    assert "<option" not in body  # no engine names baked into the static page


def test_index_never_names_the_engine(client):
    body = client.get("/").text.lower()
    for name in FORBIDDEN_ENGINE_NAMES:
        assert name not in body, f"engine/provider name leaked into UI: {name!r}"
