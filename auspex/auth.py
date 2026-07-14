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


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID
    workspace_id: UUID
    via: str  # "jwt" | "api_key"


async def resolve_user(request: Request) -> AuthContext:
    """The one place a request becomes an identity. All auth flows through here."""
    settings: Settings = request.app.state.settings
    pool: asyncpg.Pool = request.app.state.pool

    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        try:
            claims = decode_jwt(settings, token)
        except jwt.InvalidTokenError as err:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from err
        row = await pool.fetchrow(
            "SELECT id, workspace_id FROM users WHERE id = $1 AND workspace_id = $2",
            UUID(claims["sub"]),
            UUID(claims["wid"]),
        )
        if row is None:
            raise HTTPException(status_code=401, detail="Unknown user")
        return AuthContext(user_id=row["id"], workspace_id=row["workspace_id"], via="jwt")

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
        await pool.execute(
            "UPDATE api_keys SET last_used_at = now() WHERE key_hash = $1",
            hash_api_key(api_key),
        )
        return AuthContext(user_id=row["user_id"], workspace_id=row["workspace_id"], via="api_key")

    raise HTTPException(status_code=401, detail="Not authenticated")


# --- User provisioning (v0: single get-or-create default workspace) ------------


async def get_or_create_user(
    pool: asyncpg.Pool,
    email: str,
    display_name: str = "",
    google_sub: str | None = None,
    workspace_name: str = "default",
) -> tuple[UUID, UUID]:
    """Return (user_id, workspace_id), creating workspace/user rows as needed."""
    async with pool.acquire() as conn, conn.transaction():
        # Race-safe get-or-create: INSERT..ON CONFLICT DO NOTHING relies on the UNIQUE
        # index on workspaces.name; on conflict we re-SELECT the existing row.
        workspace_id = await conn.fetchval(
            "INSERT INTO workspaces (name) VALUES ($1) ON CONFLICT (name) DO NOTHING RETURNING id",
            workspace_name,
        )
        if workspace_id is None:
            workspace_id = await conn.fetchval(
                "SELECT id FROM workspaces WHERE name = $1", workspace_name
            )
        user_id = await conn.fetchval(
            """
            INSERT INTO users (workspace_id, email, display_name, google_sub)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (workspace_id, email) DO UPDATE
                SET display_name = CASE WHEN EXCLUDED.display_name <> ''
                                        THEN EXCLUDED.display_name
                                        ELSE users.display_name END,
                    google_sub = COALESCE(EXCLUDED.google_sub, users.google_sub)
            RETURNING id
            """,
            workspace_id,
            email,
            display_name,
            google_sub,
        )
    return user_id, workspace_id
