"""Auth primitives + the single `resolve_user` chokepoint.

Every authenticated route depends on `resolve_user` — there is exactly one
place where a request becomes a (user_id, workspace_id) pair. Two credential
shapes are accepted:

  * `Authorization: Bearer <jwt>`  — session token issued by our own endpoints
  * `X-API-Key: apx_...`           — long-lived key; only its SHA-256 lands in Postgres

API keys are stored as sha256(raw) + a display prefix. The raw key is shown
once at creation and never persisted.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import jwt
from fastapi import HTTPException, Request

from auspex.config import Settings
from auspex.tenancy.access import enterable_workspaces, home_org

API_KEY_PREFIX = "apx_"
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "auspex"


# --- API keys -----------------------------------------------------------------


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return (raw_key, prefix, key_hash). Raw key exists only in this return value."""
    raw_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw_key, raw_key[:12], hash_api_key(raw_key)


# --- JWT ----------------------------------------------------------------------


def issue_jwt(settings: Settings, user_id: UUID, workspace_id: UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": JWT_ISSUER,
        "sub": str(user_id),
        "wid": str(workspace_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_jwt(settings: Settings, token: str) -> dict:
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        options={"require": ["exp", "sub", "wid", "iss"]},
    )


# --- The chokepoint -----------------------------------------------------------


NO_ACCESS = "You no longer have access to this workspace."
NO_WORKSPACE = "There is no workspace you may enter. Ask an administrator to add you."


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID
    workspace_id: UUID
    via: str  # "jwt" | "api_key"
    role: str  # admin | analyst | viewer — resolved live, never from the token
    home_org_id: UUID
    region: str  # the active workspace's region (D-061's guard reads it)


async def _context(pool: asyncpg.Pool, user_id: UUID, workspace_id: UUID, via: str) -> AuthContext:
    """D-061: a token names one workspace, and access to it is re-checked on
    EVERY request, so a removed membership ends access at the next request."""
    home = await home_org(pool, user_id)
    if home is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    access = (await enterable_workspaces(pool, user_id, only=workspace_id)).get(workspace_id)
    if access is None:
        raise HTTPException(status_code=403, detail=NO_ACCESS)
    return AuthContext(
        user_id=user_id,
        workspace_id=workspace_id,
        via=via,
        role=access.role,
        home_org_id=home,
        region=access.region,
    )


async def resolve_user(request: Request) -> AuthContext:
    """The one place a request becomes an identity. All auth flows through here."""
    settings: Settings = request.app.state.settings
    pool: asyncpg.Pool = request.app.state.pool

    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        try:
            claims = decode_jwt(settings, token)
            user_id, workspace_id = UUID(claims["sub"]), UUID(claims["wid"])
        except (jwt.InvalidTokenError, ValueError) as err:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from err
        return await _context(pool, user_id, workspace_id, "jwt")

    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        row = await pool.fetchrow(
            """
            SELECT user_id, workspace_id FROM api_keys
            WHERE key_hash = $1 AND revoked_at IS NULL
            """,
            hash_api_key(api_key),
        )
        if row is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        context = await _context(pool, row["user_id"], row["workspace_id"], "api_key")
        await pool.execute(
            "UPDATE api_keys SET last_used_at = now() WHERE key_hash = $1",
            hash_api_key(api_key),
        )
        return context

    raise HTTPException(status_code=401, detail="Not authenticated")

