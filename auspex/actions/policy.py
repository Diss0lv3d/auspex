"""Who may approve an action, per workspace and risk level (S34, design decisions 1, 8).

A workspace with no rule of its own uses DEFAULT (Hunaiza's call): `write` by an analyst
or admin, `destructive` by an admin only, provider staff included. A workspace's admin
may set its own rule per risk level: which roles, and whether provider staff (people
whose home organization is not the workspace's own, an MSSP's working in a client's
workspace) may approve at all. The rule is applied in the same statement that claims
the proposal (`ProposalSettlement.settle`), and the rule in force is recorded there.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from auspex.auth import Admin, AnyRole
from auspex.tenancy import audit

RISKS = ("write", "destructive")
ROLES = ("admin", "analyst")  # a viewer approves nothing (every write needs a role)
DEFAULT: dict[str, tuple[tuple[str, ...], bool]] = {
    "write": (("admin", "analyst"), True),
    "destructive": (("admin",), True),
}

router = APIRouter(prefix="/api/approval-policy", tags=["approvals"])


async def rules(db, workspace_id: UUID) -> dict[str, dict]:
    """The rule in force for each risk level in this workspace."""
    rows = await db.fetch(
        "SELECT risk, roles, provider_staff FROM approval_policies WHERE workspace_id = $1",
        workspace_id)
    found = {r["risk"]: r for r in rows}
    out = {}
    for risk, (roles, staff) in DEFAULT.items():
        r = found.get(risk)
        out[risk] = ({"risk": risk, "roles": sorted(r["roles"]), "provider_staff":
                      r["provider_staff"], "source": "workspace"} if r else
                     {"risk": risk, "roles": list(roles), "provider_staff": staff,
                      "source": "default"})
    return out


async def approvable(db, *, workspace_id: UUID, role: str,
                     home_org_id: UUID | None) -> dict[str, dict]:
    """The risk levels this person may approve here, each with the rule that allows it."""
    org = await db.fetchval("SELECT org_id FROM workspaces WHERE id = $1", workspace_id)
    staff = org is not None and home_org_id != org
    return {risk: rule for risk, rule in (await rules(db, workspace_id)).items()
            if role in rule["roles"] and (rule["provider_staff"] or not staff)}


async def refusal(db, *, workspace_id: UUID, risk: str, role: str,
                  home_org_id: UUID | None) -> str:
    """Why this person may not approve this risk level here, in words."""
    rule = (await rules(db, workspace_id))[risk]
    org = await db.fetchval("SELECT org_id FROM workspaces WHERE id = $1", workspace_id)
    if org is not None and home_org_id != org and not rule["provider_staff"]:
        return (f"approving a {risk} action in this workspace is for its own people;"
                " provider staff may not approve here")
    return (f"approving a {risk} action here needs the role "
            f"{' or '.join(rule['roles'])}; yours is {role}")


class Rule(BaseModel):
    risk: str
    roles: list[str]
    provider_staff: bool


@router.get("")
async def read(request: Request, auth: AnyRole) -> dict:
    return {"rules": list((await rules(request.app.state.pool, auth.workspace_id)).values())}


@router.put("")
async def write(body: Rule, request: Request, auth: Admin) -> dict:
    """Set this workspace's rule for one risk level (audited)."""
    if body.risk not in RISKS:
        raise HTTPException(status_code=422, detail=f"risk must be one of {', '.join(RISKS)}")
    roles = sorted(set(body.roles))
    if not roles or set(roles) - set(ROLES):
        raise HTTPException(status_code=422,
                            detail=f"roles must be one or more of {', '.join(ROLES)}")
    pool = request.app.state.pool
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO approval_policies (workspace_id, risk, roles, provider_staff,"
            " updated_by) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (workspace_id, risk)"
            " DO UPDATE SET roles = EXCLUDED.roles, provider_staff = EXCLUDED.provider_staff,"
            " updated_by = EXCLUDED.updated_by, updated_at = now()",
            auth.workspace_id, body.risk, roles, body.provider_staff, auth.user_id)
        await audit.record(conn, workspace_id=auth.workspace_id,
                           action="approval_policy.updated",
                           actor=audit.person(auth.user_id, auth.home_org_id),
                           details={"risk": body.risk, "roles": roles,
                                    "provider_staff": body.provider_staff})
    return {"rules": list((await rules(pool, auth.workspace_id)).values())}
