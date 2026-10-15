"""Auth endpoints: Google OAuth (config-stubbed until a client ID exists),
dev login (APP_ENV=dev only), API key management, whoami, the workspace switch
and me.

JWT issuance happens in exactly three places — the OAuth callback, dev login and
the workspace switch — all funnel through `issue_jwt`, and each mints a token
for a workspace `enter` returned (auspex/tenancy/entry.py).
"""

from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

from auspex.auth import (
    NO_WORKSPACE,
    AuthContext,
    generate_api_key,
    issue_jwt,
    resolve_user,
)
from auspex.config import Settings
from auspex.tenancy.access import enterable_workspaces, user_by_email
from auspex.tenancy.admin import TenancyError, provision_dev_user
from auspex.tenancy.entry import NoAccess, enter

router = APIRouter(prefix="/api/auth", tags=["auth"])

Auth = Annotated[AuthContext, Depends(resolve_user)]

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — public endpoint URL
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _require_google(settings: Settings) -> None:
    if not settings.google_oauth_configured:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)",
        )


@router.get("/google/login")
async def google_login(request: Request) -> RedirectResponse:
    settings = _settings(request)
    _require_google(settings)
    params = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "prompt": "select_account",
        }
    )
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{params}", status_code=307)


@router.get("/google/callback")
async def google_callback(request: Request, code: str) -> dict:
    settings = _settings(request)
    _require_google(settings)
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Google code exchange failed")
        access_token = token_resp.json().get("access_token")
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Google userinfo fetch failed")
    info = userinfo_resp.json()
    if not info.get("email"):
        raise HTTPException(status_code=401, detail="Google account has no email")
    # Never key identity on an unverified email: an attacker can register a Google
    # account claiming a victim's address without proving control of it. Google's
    # OIDC userinfo returns email_verified=false for exactly those accounts.
    if info.get("email_verified") is not True:
        raise HTTPException(status_code=401, detail="Google email not verified")
    # S30 call 2: Google sign-in never provisions. The person must already
    # exist (an admin added them). TD-001 still gates configuring Google at all:
    # the immutable `sub` is not yet compared.
    pool = request.app.state.pool
    user_id = await user_by_email(pool, info["email"])
    if user_id is None:
        raise HTTPException(
            status_code=403,
            detail="No account exists for this email. Ask an administrator to add you.",
        )
    try:
        access = await enter(pool, user_id, via="login")
    except NoAccess as err:
        raise HTTPException(status_code=403, detail=NO_WORKSPACE) from err
    return {
        "access_token": issue_jwt(settings, user_id, access.workspace_id),
        "token_type": "bearer",
    }


class DevLoginBody(BaseModel):
    email: EmailStr
    display_name: str = ""


@router.post("/dev-login")
async def dev_login(request: Request, body: DevLoginBody) -> dict:
    """Issue a JWT without Google — dev environments only, 404 elsewhere."""
    settings = _settings(request)
    if settings.app_env != "dev":
        raise HTTPException(status_code=404, detail="Not found")
    pool = request.app.state.pool
    try:
        user_id = await provision_dev_user(pool, body.email, body.display_name)
    except TenancyError as err:
        raise HTTPException(status_code=err.status, detail=str(err)) from err
    try:
        access = await enter(pool, user_id, via="login")
    except NoAccess as err:
        raise HTTPException(status_code=403, detail=NO_WORKSPACE) from err
    return {
        "access_token": issue_jwt(settings, user_id, access.workspace_id),
        "token_type": "bearer",
    }


class ApiKeyBody(BaseModel):
    name: str = ""


@router.post("/api-keys", status_code=201)
async def create_api_key(request: Request, body: ApiKeyBody, auth: Auth) -> dict:
    """Create an API key for the caller. The raw key is returned once, never stored.

    Key management requires an interactive (JWT) session: a leaked API key must not
    be able to mint fresh keys that would survive revocation of the original.
    """
    if auth.via != "jwt":
        raise HTTPException(status_code=403, detail="API-key management requires a login session")
    raw_key, prefix, key_hash = generate_api_key()
    await request.app.state.pool.execute(
        """
        INSERT INTO api_keys (workspace_id, user_id, name, key_prefix, key_hash)
        VALUES ($1, $2, $3, $4, $5)
        """,
        auth.workspace_id,
        auth.user_id,
        body.name,
        prefix,
        key_hash,
    )
    return {"api_key": raw_key, "prefix": prefix, "name": body.name}


@router.get("/whoami")
async def whoami(auth: Auth) -> dict:
    return {
        "user_id": str(auth.user_id),
        "workspace_id": str(auth.workspace_id),
        "via": auth.via,
    }


class SwitchBody(BaseModel):
    workspace_id: UUID


@router.post("/switch")
async def switch(request: Request, body: SwitchBody, auth: Auth) -> dict:
    """The ONE route that takes a workspace id from input (D-061). It reaches only
    what enterable_workspaces returns: anything else is the same 404 whether the
    workspace is someone else's or does not exist. A login session only, so a
    leaked API key cannot become a session."""
    if auth.via != "jwt":
        raise HTTPException(status_code=403, detail="Switching requires a login session")
    try:
        access = await enter(request.app.state.pool, auth.user_id, via="switch",
                             workspace_id=body.workspace_id)
    except NoAccess as err:
        raise HTTPException(status_code=404, detail="Unknown workspace") from err
    return {
        "access_token": issue_jwt(_settings(request), auth.user_id, access.workspace_id),
        "token_type": "bearer",
        "workspace": {"id": str(access.workspace_id), "name": access.workspace_name,
                      "role": access.role, "region": access.region},
    }


@router.get("/me")
async def me(request: Request, auth: Auth) -> dict:
    """Who the caller is, where they are, and where they may go (F4's switcher)."""
    pool: asyncpg.Pool = request.app.state.pool
    user = await pool.fetchrow(
        "SELECT u.email, u.display_name, o.id AS org_id, o.name AS org_name, o.kind"
        " FROM users u JOIN organizations o ON o.id = u.home_org_id WHERE u.id = $1",
        auth.user_id,
    )
    reachable = sorted(
        (await enterable_workspaces(pool, auth.user_id)).values(),
        key=lambda a: (a.org_id != auth.home_org_id, a.workspace_name),
    )
    active = next(a for a in reachable if a.workspace_id == auth.workspace_id)
    return {
        "user": {"id": str(auth.user_id), "email": user["email"],
                 "display_name": user["display_name"]},
        "organization": {"id": str(user["org_id"]), "name": user["org_name"],
                         "kind": user["kind"]},
        "workspace": {"id": str(active.workspace_id), "name": active.workspace_name,
                      "region": active.region, "role": active.role,
                      "organization": active.org_name},
        "workspaces": [
            {"id": str(a.workspace_id), "name": a.workspace_name, "region": a.region,
             "role": a.role, "via": a.via,
             "organization": {"id": str(a.org_id), "name": a.org_name, "kind": a.org_kind}}
            for a in reachable
        ],
    }
