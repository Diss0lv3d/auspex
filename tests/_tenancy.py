"""Test plumbing for S30's tenancy (D-061). Raw SQL on purpose: a test must be
able to write a row the rules in auspex/tenancy/admin.py would refuse, to prove
the READ side still grants nothing for it."""

from dataclasses import dataclass
from uuid import UUID

from auspex.auth import issue_jwt


async def make_org(db, name: str, kind: str, *, parent: UUID | None = None,
                   restricted: bool = False) -> UUID:
    return await db.fetchval(
        "INSERT INTO organizations (name, kind, parent_id, restricted)"
        " VALUES ($1, $2, $3, $4) RETURNING id",
        name, kind, parent, restricted,
    )


async def make_workspace(db, name: str, org_id: UUID, *, region: str = "global") -> UUID:
    return await db.fetchval(
        "INSERT INTO workspaces (name, org_id, region) VALUES ($1, $2, $3) RETURNING id",
        name, org_id, region,
    )


async def make_user(db, email: str, home_org_id: UUID) -> UUID:
    return await db.fetchval(
        "INSERT INTO users (email, home_org_id) VALUES ($1, $2) RETURNING id",
        email, home_org_id,
    )


async def add_membership(db, workspace_id: UUID, user_id: UUID, role: str, *,
                         provider_wide: bool = False) -> None:
    await db.execute(
        "INSERT INTO memberships (workspace_id, user_id, role, provider_wide)"
        " VALUES ($1, $2, $3, $4)",
        workspace_id, user_id, role, provider_wide,
    )


async def ensure_workspace(db, name: str, *, region: str = "global") -> UUID:
    """A test workspace with its own direct organization, get-or-create: the
    shape of the `INSERT INTO workspaces … ON CONFLICT` lines it replaces (S30:
    a workspace belongs to an organization)."""
    org_id = await db.fetchval(
        "INSERT INTO organizations (name, kind) VALUES ($1, 'direct')"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        name,
    )
    return await db.fetchval(
        "INSERT INTO workspaces (name, org_id, region) VALUES ($1, $2, $3)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        name, org_id, region,
    )


async def ensure_member(db, workspace_id: UUID, email: str, *, role: str = "analyst",
                        display_name: str = "") -> UUID:
    """The person with this email, homed in the workspace's organization when
    new, with a membership there: what `INSERT INTO users (workspace_id, email)`
    meant before S30."""
    org_id = await db.fetchval("SELECT org_id FROM workspaces WHERE id = $1", workspace_id)
    user_id = await db.fetchval(
        "INSERT INTO users (email, display_name, home_org_id) VALUES ($1, $2, $3)"
        " ON CONFLICT ((lower(email))) DO UPDATE SET display_name = EXCLUDED.display_name"
        " RETURNING id",
        email, display_name, org_id,
    )
    await db.execute(
        "INSERT INTO memberships (workspace_id, user_id, role) VALUES ($1, $2, $3)"
        " ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = EXCLUDED.role",
        workspace_id, user_id, role,
    )
    return user_id


async def drop_orgs(db, prefix: str) -> None:
    """Delete every organization named `prefix…`, with its workspaces and the
    people homed in it. Clients go before providers (parent_id is RESTRICT)."""
    org_ids = [
        r["id"] for r in await db.fetch(
            "SELECT id FROM organizations WHERE starts_with(name, $1)", prefix
        )
    ]
    if not org_ids:
        return
    await db.execute("DELETE FROM workspaces WHERE org_id = ANY($1::uuid[])", org_ids)
    await db.execute("DELETE FROM users WHERE home_org_id = ANY($1::uuid[])", org_ids)
    await db.execute(
        "DELETE FROM organizations WHERE id = ANY($1::uuid[]) AND kind = 'client'", org_ids
    )
    await db.execute("DELETE FROM organizations WHERE id = ANY($1::uuid[])", org_ids)


@dataclass(frozen=True)
class Mssp:
    """One provider with two clients (client2 restricted) and one direct
    customer — the shape every S30 cross-tenant test reasons about."""

    provider: UUID
    provider_ws: UUID
    client1: UUID
    client1_ws: UUID
    client2: UUID
    client2_ws: UUID
    direct: UUID
    direct_ws: UUID
    p_admin: UUID  # home provider; admin in provider_ws, provider_wide
    p_analyst: UUID  # home provider; analyst in provider_ws, no grant
    c1_user: UUID  # home client1; analyst in client1_ws
    c2_user: UUID  # home client2; analyst in client2_ws
    d_user: UUID  # home direct; admin in direct_ws


async def build_mssp(db, prefix: str) -> Mssp:
    provider = await make_org(db, f"{prefix}-provider", "provider")
    client1 = await make_org(db, f"{prefix}-client1", "client", parent=provider)
    client2 = await make_org(db, f"{prefix}-client2", "client", parent=provider,
                             restricted=True)
    direct = await make_org(db, f"{prefix}-direct", "direct")
    provider_ws = await make_workspace(db, f"{prefix}-provider", provider)
    client1_ws = await make_workspace(db, f"{prefix}-client1", client1)
    client2_ws = await make_workspace(db, f"{prefix}-client2", client2)
    direct_ws = await make_workspace(db, f"{prefix}-direct", direct)
    domain = f"{prefix}.auspex.dev"
    p_admin = await make_user(db, f"p-admin@{domain}", provider)
    p_analyst = await make_user(db, f"p-analyst@{domain}", provider)
    c1_user = await make_user(db, f"c1-user@{domain}", client1)
    c2_user = await make_user(db, f"c2-user@{domain}", client2)
    d_user = await make_user(db, f"d-user@{domain}", direct)
    await add_membership(db, provider_ws, p_admin, "admin", provider_wide=True)
    await add_membership(db, provider_ws, p_analyst, "analyst")
    await add_membership(db, client1_ws, c1_user, "analyst")
    await add_membership(db, client2_ws, c2_user, "analyst")
    await add_membership(db, direct_ws, d_user, "admin")
    return Mssp(provider, provider_ws, client1, client1_ws, client2, client2_ws,
                direct, direct_ws, p_admin, p_analyst, c1_user, c2_user, d_user)


def token(settings, user_id: UUID, workspace_id: UUID) -> dict:
    return {"Authorization": f"Bearer {issue_jwt(settings, user_id, workspace_id)}"}
