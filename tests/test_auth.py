"""Auth: JWT round-trip, API keys stored as SHA-256 hash + prefix, the
resolve_user chokepoint, and the config-stubbed Google OAuth endpoints."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import jwt
from _tenancy import ensure_member, ensure_workspace
from fastapi.testclient import TestClient

from auspex.app import create_app
from auspex.auth import (
    API_KEY_PREFIX,
    JWT_ALGORITHM,
    JWT_ISSUER,
    NO_ACCESS,
    generate_api_key,
    hash_api_key,
    issue_jwt,
)
from auspex.config import Settings
from auspex.db import create_pool
from auspex.tenancy.admin import provision_dev_user

# .test/.example TLDs are rejected by email-validator; use a real-shaped domain.
DEV_EMAIL = "analyst@auspex.dev"


def _dev_token(client) -> str:
    resp = client.post("/api/auth/dev-login", json={"email": DEV_EMAIL, "display_name": "Analyst"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# --- primitives ---------------------------------------------------------------


def test_generate_api_key_shape():
    raw, prefix, key_hash = generate_api_key()
    assert raw.startswith(API_KEY_PREFIX)
    assert prefix == raw[:12]
    assert key_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert hash_api_key(raw) == key_hash


# --- chokepoint ---------------------------------------------------------------


def test_no_credentials_is_401(client):
    resp = client.get("/api/auth/whoami")
    assert resp.status_code == 401


def test_garbage_jwt_is_401(client):
    resp = client.get("/api/auth/whoami", headers={"Authorization": "Bearer not-a-token"})
    assert resp.status_code == 401


def test_expired_jwt_is_401(client, settings):
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": JWT_ISSUER,
            "sub": "00000000-0000-0000-0000-000000000000",
            "wid": "00000000-0000-0000-0000-000000000000",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        settings.secret_key,
        algorithm=JWT_ALGORITHM,
    )
    resp = client.get("/api/auth/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_dev_login_jwt_roundtrip(client):
    token = _dev_token(client)
    resp = client.get("/api/auth/whoami", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["via"] == "jwt"
    assert body["user_id"] and body["workspace_id"]


# --- API keys -----------------------------------------------------------------


async def test_api_key_roundtrip_and_hash_at_rest(client, settings):
    token = _dev_token(client)
    resp = client.post(
        "/api/auth/api-keys",
        json={"name": "s1-test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    raw_key = resp.json()["api_key"]
    assert raw_key.startswith(API_KEY_PREFIX)

    # The key authenticates via the chokepoint.
    who = client.get("/api/auth/whoami", headers={"X-API-Key": raw_key})
    assert who.status_code == 200, who.text
    assert who.json()["via"] == "api_key"

    # At rest: SHA-256 + prefix only — the raw key must not exist in the row.
    conn = await asyncpg.connect(settings.database_url)
    try:
        row = await conn.fetchrow(
            "SELECT key_hash, key_prefix, last_used_at FROM api_keys WHERE key_hash = $1",
            hash_api_key(raw_key),
        )
        assert row is not None
        assert row["key_hash"] == hashlib.sha256(raw_key.encode()).hexdigest()
        assert row["key_prefix"] == raw_key[:12]
        assert row["last_used_at"] is not None  # chokepoint stamped usage
    finally:
        await conn.close()


async def test_revoked_api_key_is_401(client, settings):
    token = _dev_token(client)
    resp = client.post(
        "/api/auth/api-keys",
        json={"name": "s1-revoked"},
        headers={"Authorization": f"Bearer {token}"},
    )
    raw_key = resp.json()["api_key"]
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute(
            "UPDATE api_keys SET revoked_at = now() WHERE key_hash = $1", hash_api_key(raw_key)
        )
    finally:
        await conn.close()
    who = client.get("/api/auth/whoami", headers={"X-API-Key": raw_key})
    assert who.status_code == 401


def test_wrong_api_key_is_401(client):
    resp = client.get("/api/auth/whoami", headers={"X-API-Key": "apx_definitely-not-real"})
    assert resp.status_code == 401


def test_api_key_cannot_mint_api_keys(client):
    """A leaked key must not be able to create fresh keys that outlive its revocation."""
    token = _dev_token(client)
    minted = client.post(
        "/api/auth/api-keys",
        json={"name": "s1-parent"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["api_key"]
    resp = client.post(
        "/api/auth/api-keys", json={"name": "s1-child"}, headers={"X-API-Key": minted}
    )
    assert resp.status_code == 403


# --- Google OAuth callback identity checks -------------------------------------


class _FakeResp:
    def __init__(self, payload: dict, status: int = 200):
        self.status_code = status
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _fake_google_client(userinfo: dict):
    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None):
            return _FakeResp({"access_token": "fake-access-token"})

        async def get(self, url, headers=None):
            return _FakeResp(userinfo)

    return _FakeClient


def _oauth_app():
    return create_app(Settings(google_client_id="test-client-id", google_client_secret="test"))


def test_google_callback_rejects_unverified_email(monkeypatch):
    monkeypatch.setattr(
        "auspex.routes.auth.httpx.AsyncClient",
        _fake_google_client({"email": "victim@auspex.dev", "email_verified": False, "sub": "1"}),
    )
    with TestClient(_oauth_app()) as oauth:
        resp = oauth.get("/api/auth/google/callback?code=x")
        assert resp.status_code == 401
        assert "not verified" in resp.json()["detail"].lower()


def _provision(settings, email: str) -> None:
    async def _run():
        pool = await create_pool(settings.database_url, retries=2, delay=0.5)
        try:
            await provision_dev_user(pool, email)
        finally:
            await pool.close()

    asyncio.run(_run())


def test_google_callback_signs_in_an_existing_person(monkeypatch, settings):
    _provision(settings, "victim@auspex.dev")
    monkeypatch.setattr(
        "auspex.routes.auth.httpx.AsyncClient",
        _fake_google_client(
            {"email": "victim@auspex.dev", "email_verified": True, "sub": "1", "name": "Victim"}
        ),
    )
    with TestClient(_oauth_app()) as oauth:
        resp = oauth.get("/api/auth/google/callback?code=x")
        assert resp.status_code == 200, resp.text
        assert resp.json()["token_type"] == "bearer"


async def test_google_callback_never_provisions(monkeypatch, settings):
    email = "nobody-yet@auspex.dev"
    monkeypatch.setattr(
        "auspex.routes.auth.httpx.AsyncClient",
        _fake_google_client({"email": email, "email_verified": True, "sub": "2"}),
    )
    with TestClient(_oauth_app()) as oauth:
        resp = oauth.get("/api/auth/google/callback?code=x")
    assert resp.status_code == 403
    assert "administrator" in resp.json()["detail"]
    conn = await asyncpg.connect(settings.database_url)
    try:
        assert await conn.fetchval("SELECT count(*) FROM users WHERE email = $1", email) == 0
    finally:
        await conn.close()


async def test_a_token_for_a_workspace_without_access_is_403(client, settings):
    token = _dev_token(client)
    claims = jwt.decode(token, options={"verify_signature": False})
    conn = await asyncpg.connect(settings.database_url)
    try:
        foreign = await ensure_workspace(conn, "t-s30-auth-foreign")
        forged = issue_jwt(settings, UUID(claims["sub"]), foreign)
        resp = client.get("/api/auth/whoami", headers={"Authorization": f"Bearer {forged}"})
        assert resp.status_code == 403
        assert resp.json()["detail"] == NO_ACCESS
    finally:
        await conn.execute("DELETE FROM workspaces WHERE name = 't-s30-auth-foreign'")
        await conn.close()


async def test_a_removed_membership_ends_access_at_the_next_request(client, settings):
    conn = await asyncpg.connect(settings.database_url)
    try:
        ws = await ensure_workspace(conn, "t-s30-auth-removed")
        uid = await ensure_member(conn, ws, "removed@s30-auth.auspex.dev")
        headers = {"Authorization": f"Bearer {issue_jwt(settings, uid, ws)}"}
        assert client.get("/api/auth/whoami", headers=headers).status_code == 200
        await conn.execute("DELETE FROM memberships WHERE user_id = $1", uid)
        assert client.get("/api/auth/whoami", headers=headers).status_code == 403
    finally:
        await conn.execute("DELETE FROM workspaces WHERE name = 't-s30-auth-removed'")
        await conn.execute("DELETE FROM users WHERE email = 'removed@s30-auth.auspex.dev'")
        await conn.close()


async def test_an_api_key_is_re_checked_like_a_token(client, settings):
    conn = await asyncpg.connect(settings.database_url)
    try:
        ws = await ensure_workspace(conn, "t-s30-auth-key")
        uid = await ensure_member(conn, ws, "keyholder@s30-auth.auspex.dev")
        jwt_headers = {"Authorization": f"Bearer {issue_jwt(settings, uid, ws)}"}
        raw = client.post("/api/auth/api-keys", json={"name": "k"}, headers=jwt_headers)
        assert raw.status_code == 201, raw.text
        key_headers = {"X-API-Key": raw.json()["api_key"]}
        assert client.get("/api/auth/whoami", headers=key_headers).status_code == 200
        await conn.execute("DELETE FROM memberships WHERE user_id = $1", uid)
        assert client.get("/api/auth/whoami", headers=key_headers).status_code == 403
    finally:
        await conn.execute("DELETE FROM workspaces WHERE name = 't-s30-auth-key'")
        await conn.execute("DELETE FROM users WHERE email = 'keyholder@s30-auth.auspex.dev'")
        await conn.close()


# --- config fail-closed --------------------------------------------------------


def test_config_defaults_to_prod_failing_closed(monkeypatch):
    """Missing APP_ENV must NOT enable dev surfaces: the default is prod (fail closed)."""
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=None, secret_key="unit-test")
    assert settings.app_env == "prod"


def test_config_rejects_unknown_app_env(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    import pytest

    with pytest.raises(RuntimeError):
        Settings(_env_file=None, app_env="staging", secret_key="unit-test")


# --- Google OAuth (config-stubbed) ---------------------------------------------


def test_google_login_unconfigured_is_503():
    app = create_app(Settings(google_client_id="", google_client_secret=""))
    with TestClient(app) as unconfigured:
        resp = unconfigured.get("/api/auth/google/login", follow_redirects=False)
        assert resp.status_code == 503
        resp = unconfigured.get("/api/auth/google/callback?code=x", follow_redirects=False)
        assert resp.status_code == 503


def test_google_login_configured_redirects_to_google():
    app = create_app(Settings(google_client_id="test-client-id", google_client_secret="test"))
    with TestClient(app) as configured:
        resp = configured.get("/api/auth/google/login", follow_redirects=False)
        assert resp.status_code == 307
        location = resp.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=test-client-id" in location


# --- environment gating ---------------------------------------------------------


def test_dev_login_hidden_in_prod():
    app = create_app(Settings(app_env="prod", secret_key="test-prod-secret"))
    with TestClient(app) as prod_client:
        resp = prod_client.post("/api/auth/dev-login", json={"email": DEV_EMAIL})
        assert resp.status_code == 404


# --- where a token is minted ----------------------------------------------------


def test_the_auth_routes_name_every_place_a_token_is_minted():
    """F4 (S30 final review): the module said "exactly two places"; the switch
    is a third. Found by walking the code, so a fourth cannot hide."""
    import ast
    from pathlib import Path

    import auspex.routes.auth as routes

    root = Path(__file__).resolve().parents[1] / "auspex"
    minting = set()
    for path in root.rglob("*.py"):
        for fn in ast.walk(ast.parse(path.read_text())):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) and any(
                isinstance(n, ast.Call) and getattr(n.func, "id", None) == "issue_jwt"
                for n in ast.walk(fn)
            ):
                minting.add((path.name, fn.name))
    assert minting == {("auth.py", "google_callback"), ("auth.py", "dev_login"),
                       ("auth.py", "switch")}
    doc = " ".join(routes.__doc__.split())
    assert "exactly three places" in doc
    for named in ("the OAuth callback", "dev login", "the workspace switch"):
        assert named in doc, named
