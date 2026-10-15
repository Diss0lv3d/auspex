"""The admin surface of the active workspace (D-061; S30 design §3): its
memberships and its audit trail. Every route here is Admin, and acts only on
`auth.workspace_id`; no other workspace id appears in any of them."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, EmailStr

from auspex.auth import Admin, AuthContext
from auspex.tenancy import admin
from auspex.tenancy.audit import AUDIT_PAGE_MAX, Actor, list_events, person

router = APIRouter(prefix="/api", tags=["workspace"])

Role = Literal["admin", "analyst", "viewer"]


class AddMemberBody(BaseModel):
    email: EmailStr
    role: Role


class ChangeMemberBody(BaseModel):
    role: Role | None = None
    provider_wide: bool | None = None


def _actor(auth: AuthContext) -> Actor:
    return person(auth.user_id, auth.home_org_id)


def _refusal(err: admin.TenancyError) -> HTTPException:
    return HTTPException(status_code=err.status, detail=str(err))


@router.get("/workspace/members")
async def list_workspace_members(request: Request, auth: Admin) -> dict:
    return {"members": await admin.list_members(request.app.state.pool, auth.workspace_id)}


@router.post("/workspace/members", status_code=201)
async def add_workspace_member(request: Request, body: AddMemberBody, auth: Admin) -> dict:
    try:
        user_id = await admin.add_member(request.app.state.pool, workspace_id=auth.workspace_id,
                                         email=body.email, role=body.role, actor=_actor(auth))
    except admin.TenancyError as err:
        raise _refusal(err) from err
    return {"user_id": str(user_id)}


@router.patch("/workspace/members/{user_id}")
async def change_workspace_member(request: Request, user_id: UUID, body: ChangeMemberBody,
                                  auth: Admin) -> dict:
    try:
        await admin.change_member(request.app.state.pool, workspace_id=auth.workspace_id,
                                  user_id=user_id, actor=_actor(auth), role=body.role,
                                  provider_wide=body.provider_wide)
    except admin.TenancyError as err:
        raise _refusal(err) from err
    return {"ok": True}


@router.delete("/workspace/members/{user_id}")
async def remove_workspace_member(request: Request, user_id: UUID, auth: Admin) -> dict:
    try:
        await admin.remove_member(request.app.state.pool, workspace_id=auth.workspace_id,
                                  user_id=user_id, actor=_actor(auth))
    except admin.TenancyError as err:
        raise _refusal(err) from err
    return {"ok": True}


@router.get("/audit")
async def workspace_audit(
    request: Request,
    auth: Admin,
    # Aware only: an offset-less value would be read in the server's timezone.
    before: AwareDatetime | None = None,
    limit: int = Query(50, ge=1, le=AUDIT_PAGE_MAX),
) -> dict:
    return {
        "events": await list_events(request.app.state.pool, auth.workspace_id,
                                    before=before, limit=limit)
    }
