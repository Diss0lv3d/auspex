"""Every write to organizations, workspaces and memberships (D-061; S30 design §3).

The CLI, the membership API and the tests all come through here, so the rules
live once: a membership's workspace belongs to the person's home organization
or to a client of it; `provider_wide` only on a provider's own workspace;
nobody changes their own membership. Each write records its audit event in the
same transaction as the change. Membership writes by a person or the CLI hold
their workspace while they run, so writes to one workspace go one at a time, and
a person acting is re-checked as that workspace's admin inside the write, not
trusted from the request's start. A dev login's first membership
(`provision_dev_user`) holds no workspace: it adds a brand-new person as an
analyst, which no admin count depends on.
"""

from typing import NamedTuple
from uuid import UUID

import asyncpg

from auspex.llm.scorecard import DEPLOYMENT_WORKSPACE
from auspex.tenancy import audit
from auspex.tenancy.access import ROLES, enterable_workspaces
from auspex.tenancy.audit import CLI, SYSTEM, Actor
from auspex.tenancy.region import GLOBAL, check_region, storage_refusal


class TenancyError(ValueError):
    """A refused tenancy write. `status` is the HTTP status the API answers with."""

    status = 400


class NotFound(TenancyError):
    status = 404


class Conflict(TenancyError):
    status = 409


class Refused(TenancyError):
    status = 403


class Invalid(TenancyError):
    status = 422


def _clean_email(email: str) -> str:
    cleaned = email.strip()
    local, at, domain = cleaned.partition("@")
    if not at or not local or not domain or any(c.isspace() for c in cleaned):
        raise Invalid("Not an email address")
    return cleaned


async def _ensure_direct_workspace(conn: asyncpg.Connection, name: str) -> tuple[UUID, UUID]:
    """(org_id, workspace_id) of the workspace `name`, made with its own direct
    organization when absent. Dev provisioning only."""
    row = await conn.fetchrow("SELECT id, org_id FROM workspaces WHERE name = $1", name)
    if row is not None:
        return row["org_id"], row["id"]
    org = await conn.fetchrow(
        "INSERT INTO organizations (name, kind) VALUES ($1, 'direct')"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id, kind",
        name,
    )
    if org["kind"] != "direct":
        raise Conflict(f"An organization named {name!r} exists and is not a direct customer")
    ws = await conn.fetchrow(
        "INSERT INTO workspaces (name, org_id) VALUES ($1, $2)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name"
        " RETURNING id, org_id, (xmax = 0) AS inserted",
        name, org["id"],
    )
    if ws["inserted"]:
        await audit.record(conn, workspace_id=ws["id"], action="org.create", actor=SYSTEM,
                           details={"organization": name, "kind": "direct"})
        await audit.record(conn, workspace_id=ws["id"], action="workspace.create",
                           actor=SYSTEM, details={"workspace": name, "region": GLOBAL})
    return ws["org_id"], ws["id"]


async def provision_dev_user(
    pool: asyncpg.Pool, email: str, display_name: str = "", workspace_name: str = "default"
) -> UUID:
    """The person with this email; a new one (dev login only, S30 call 2) is homed
    in `workspace_name`'s organization with an analyst membership there. An
    existing person gains nothing: they enter what they already may."""
    if workspace_name == DEPLOYMENT_WORKSPACE:
        # D-035: a user inside the deployment's system workspace could read, and
        # a later writer could poison, what every tenant's turn is compiled from.
        raise Refused(f"{DEPLOYMENT_WORKSPACE!r} is reserved for the deployment")
    email = _clean_email(email)
    async with pool.acquire() as conn, conn.transaction():
        existing = await conn.fetchval(
            "SELECT id FROM users WHERE lower(email) = lower($1)", email
        )
        if existing is not None:
            if display_name:
                await conn.execute(
                    "UPDATE users SET display_name = $2 WHERE id = $1", existing, display_name
                )
            return existing
        org_id, workspace_id = await _ensure_direct_workspace(conn, workspace_name)
        user_id = await conn.fetchval(
            "INSERT INTO users (email, display_name, home_org_id) VALUES ($1, $2, $3)"
            " ON CONFLICT ((lower(email))) DO NOTHING RETURNING id",
            email, display_name, org_id,
        )
        if user_id is None:
            # A concurrent first login committed the person first.
            return await conn.fetchval(
                "SELECT id FROM users WHERE lower(email) = lower($1)", email
            )
        await conn.execute(
            "INSERT INTO memberships (workspace_id, user_id, role)"
            " VALUES ($1, $2, 'analyst') ON CONFLICT (workspace_id, user_id) DO NOTHING",
            workspace_id, user_id,
        )
        await audit.record(conn, workspace_id=workspace_id, action="membership.add",
                           actor=SYSTEM, subject_user_id=user_id,
                           details={"role": "analyst", "provider_wide": False, "via": "dev-login"})
        return user_id


SELF_CHANGE = "You cannot change your own membership; another admin can."


def _check_name(name: str, what: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise Invalid(f"A {what} needs a name")
    if cleaned == DEPLOYMENT_WORKSPACE:
        raise Refused(f"{DEPLOYMENT_WORKSPACE!r} is reserved for the deployment")
    return cleaned


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise Invalid(f"Unknown role {role!r}; the roles are {', '.join(ROLES)}")
    return role


def _check_region(region: str) -> str:
    try:
        return check_region(region)
    except ValueError as err:
        raise Invalid(str(err)) from err


def _check_storage(region: str, storage_region: str) -> None:
    """D-069: a workspace is made only where the deployment's storage may hold it."""
    try:
        reason = storage_refusal(region, storage_region)
    except ValueError as err:
        raise Invalid(str(err)) from err
    if reason is not None:
        raise Refused(reason)


_WORKSPACE_SQL = (
    "SELECT w.id, w.name, w.org_id, o.kind AS org_kind, o.parent_id"
    " FROM workspaces w LEFT JOIN organizations o ON o.id = w.org_id"
)


def _not_reserved(row: asyncpg.Record) -> asyncpg.Record:
    """D-035: no membership is ever written into the deployment's system workspace."""
    if row["name"] == DEPLOYMENT_WORKSPACE:
        raise Refused(f"{DEPLOYMENT_WORKSPACE!r} is reserved for the deployment")
    return row


NOT_AN_ADMIN = "Only a current admin of this workspace can change its memberships."


async def _hold(conn, workspace_id: UUID, actor: Actor) -> None:
    """Inside the write's transaction, before anything else is read: one
    membership write per workspace at a time, and a person acting must be that
    workspace's admin NOW. Without it two admins removing or demoting each other
    at once both succeed and leave none, and a just-removed admin's in-flight
    request still writes. NO KEY, so rows that only reference the workspace
    (memberships, messages, audit events) are not blocked. The CLI is the
    recovery path: it takes the lock but is not re-checked."""
    await conn.execute("SELECT 1 FROM workspaces WHERE id = $1 FOR NO KEY UPDATE", workspace_id)
    if actor.kind != "user":
        return
    access = await enterable_workspaces(conn, actor.user_id, only=workspace_id)
    if workspace_id not in access or access[workspace_id].role != "admin":
        raise Refused(NOT_AN_ADMIN)


async def _workspace(conn, workspace_id: UUID, actor: Actor) -> asyncpg.Record:
    """The workspace a membership write acts on, held for the write (`_hold`)."""
    row = await conn.fetchrow(f"{_WORKSPACE_SQL} WHERE w.id = $1", workspace_id)
    if row is None:
        raise NotFound("No such workspace")
    await _hold(conn, _not_reserved(row)["id"], actor)
    return row


async def _workspace_named(conn, name: str, actor: Actor) -> asyncpg.Record:
    row = await conn.fetchrow(f"{_WORKSPACE_SQL} WHERE w.name = $1", name)
    if row is None:
        raise NotFound(f"No workspace named {name!r}")
    await _hold(conn, _not_reserved(row)["id"], actor)
    return row


async def _organization_named(conn, name: str) -> asyncpg.Record:
    row = await conn.fetchrow("SELECT id, name, kind FROM organizations WHERE name = $1", name)
    if row is None:
        raise NotFound(f"No organization named {name!r}")
    return row


async def _insert_org(conn, name: str, kind: str, parent_id: UUID | None = None,
                      restricted: bool = False) -> UUID:
    try:
        return await conn.fetchval(
            "INSERT INTO organizations (name, kind, parent_id, restricted)"
            " VALUES ($1, $2, $3, $4) RETURNING id",
            name, kind, parent_id, restricted,
        )
    except asyncpg.UniqueViolationError as err:
        raise Conflict(f"An organization named {name!r} already exists") from err


async def _insert_workspace(conn, name: str, org_id: UUID, region: str) -> UUID:
    try:
        return await conn.fetchval(
            "INSERT INTO workspaces (name, org_id, region) VALUES ($1, $2, $3) RETURNING id",
            name, org_id, region,
        )
    except asyncpg.UniqueViolationError as err:
        raise Conflict(f"A workspace named {name!r} already exists") from err


async def _person(conn, email: str, home_org_id: UUID) -> UUID:
    """The person with this email, or a new one homed in `home_org_id`."""
    existing = await conn.fetchval("SELECT id FROM users WHERE lower(email) = lower($1)", email)
    if existing is not None:
        return existing
    created = await conn.fetchval(
        "INSERT INTO users (email, home_org_id) VALUES ($1, $2)"
        " ON CONFLICT ((lower(email))) DO NOTHING RETURNING id",
        email, home_org_id,
    )
    if created is not None:
        return created
    return await conn.fetchval("SELECT id FROM users WHERE lower(email) = lower($1)", email)


async def _add(conn, workspace: asyncpg.Record, user_id: UUID, role: str,
               provider_wide: bool, actor: Actor) -> None:
    """The membership rules, once (D-061 decision 3)."""
    if actor.user_id == user_id:
        raise Refused(SELF_CHANGE)
    # FOR SHARE: a rehome of this person in flight (rehome_person) finishes
    # first, and this reads where it put them.
    home = await conn.fetchval(
        "SELECT home_org_id FROM users WHERE id = $1 FOR SHARE", user_id)
    if workspace["org_id"] != home and workspace["parent_id"] != home:
        raise Conflict("This person belongs to another organization")
    if provider_wide and workspace["org_kind"] != "provider":
        raise Invalid("Provider-wide applies only on a provider's own workspace")
    added = await conn.fetchval(
        "INSERT INTO memberships (workspace_id, user_id, role, provider_wide)"
        " VALUES ($1, $2, $3, $4) ON CONFLICT (workspace_id, user_id) DO NOTHING RETURNING id",
        workspace["id"], user_id, role, provider_wide,
    )
    if added is None:
        raise Conflict("Already a member; change the role instead")
    await audit.record(conn, workspace_id=workspace["id"], action="membership.add", actor=actor,
                       subject_user_id=user_id,
                       details={"role": role, "provider_wide": provider_wide})


async def _change(conn, workspace: asyncpg.Record, user_id: UUID, actor: Actor,
                  role: str | None, provider_wide: bool | None) -> None:
    if actor.user_id == user_id:
        raise Refused(SELF_CHANGE)
    if role is None and provider_wide is None:
        raise Invalid("Nothing to change")
    current = await conn.fetchrow(
        "SELECT role, provider_wide FROM memberships"
        " WHERE workspace_id = $1 AND user_id = $2 FOR UPDATE",
        workspace["id"], user_id,
    )
    if current is None:
        raise NotFound("Not a member of this workspace")
    if provider_wide and workspace["org_kind"] != "provider":
        raise Invalid("Provider-wide applies only on a provider's own workspace")
    if role is not None and role != current["role"]:
        await conn.execute(
            "UPDATE memberships SET role = $3, updated_at = now()"
            " WHERE workspace_id = $1 AND user_id = $2",
            workspace["id"], user_id, role,
        )
        await audit.record(conn, workspace_id=workspace["id"], action="membership.role",
                           actor=actor, subject_user_id=user_id,
                           details={"from": current["role"], "to": role})
    if provider_wide is not None and provider_wide != current["provider_wide"]:
        await conn.execute(
            "UPDATE memberships SET provider_wide = $3, updated_at = now()"
            " WHERE workspace_id = $1 AND user_id = $2",
            workspace["id"], user_id, provider_wide,
        )
        await audit.record(conn, workspace_id=workspace["id"],
                           action="membership.provider_wide", actor=actor,
                           subject_user_id=user_id, details={"provider_wide": provider_wide})


async def _remove(conn, workspace: asyncpg.Record, user_id: UUID, actor: Actor) -> None:
    if actor.user_id == user_id:
        raise Refused(SELF_CHANGE)
    role = await conn.fetchval(
        "DELETE FROM memberships WHERE workspace_id = $1 AND user_id = $2 RETURNING role",
        workspace["id"], user_id,
    )
    if role is None:
        raise NotFound("Not a member of this workspace")
    await audit.record(conn, workspace_id=workspace["id"], action="membership.remove",
                       actor=actor, subject_user_id=user_id, details={"role": role})


async def _create(conn, *, org_id: UUID, org_name: str, kind: str, workspace: str,
                  region: str, admin_email: str | None, actor: Actor) -> UUID:
    workspace_id = await _insert_workspace(conn, workspace, org_id, region)
    await audit.record(conn, workspace_id=workspace_id, action="org.create", actor=actor,
                       details={"organization": org_name, "kind": kind})
    await audit.record(conn, workspace_id=workspace_id, action="workspace.create", actor=actor,
                       details={"workspace": workspace, "region": region})
    if admin_email is not None:
        user_id = await _person(conn, admin_email, org_id)
        await _add(conn, await _workspace(conn, workspace_id, actor), user_id, "admin", False,
                   actor)
    return workspace_id


async def create_org(pool, *, kind: str, name: str, workspace: str, admin_email: str,
                     region: str = GLOBAL, storage_region: str = GLOBAL,
                     actor: Actor = CLI) -> tuple[UUID, UUID]:
    """A direct or provider organization, its own workspace and its first admin.
    `storage_region` is the deployment's STORAGE_REGION (the CLI passes it);
    left out it is `global`, which holds no ksa workspace (D-069)."""
    if kind not in ("direct", "provider"):
        raise Invalid("create-org makes a direct or a provider organization;"
                      " a client is made with create-client")
    name, workspace = _check_name(name, "organization"), _check_name(workspace, "workspace")
    region, admin_email = _check_region(region), _clean_email(admin_email)
    _check_storage(region, storage_region)
    async with pool.acquire() as conn, conn.transaction():
        org_id = await _insert_org(conn, name, kind)
        workspace_id = await _create(conn, org_id=org_id, org_name=name, kind=kind,
                                     workspace=workspace, region=region,
                                     admin_email=admin_email, actor=actor)
    return org_id, workspace_id


async def create_client(pool, *, provider: str, name: str, workspace: str,
                        region: str = GLOBAL, admin_email: str | None = None,
                        restricted: bool = False, storage_region: str = GLOBAL,
                        actor: Actor = CLI) -> tuple[UUID, UUID]:
    """A client organization under `provider`, with its workspace.
    `storage_region` as for `create_org` (D-069)."""
    name, workspace = _check_name(name, "organization"), _check_name(workspace, "workspace")
    region = _check_region(region)
    _check_storage(region, storage_region)
    admin_email = _clean_email(admin_email) if admin_email is not None else None
    async with pool.acquire() as conn, conn.transaction():
        parent = await _organization_named(conn, provider)
        if parent["kind"] != "provider":
            raise Invalid(f"{provider!r} is not a provider organization")
        org_id = await _insert_org(conn, name, "client", parent["id"], restricted)
        workspace_id = await _create(conn, org_id=org_id, org_name=name, kind="client",
                                     workspace=workspace, region=region,
                                     admin_email=admin_email, actor=actor)
    return org_id, workspace_id


async def set_restricted(pool, *, client: str, restricted: bool, actor: Actor = CLI) -> None:
    async with pool.acquire() as conn, conn.transaction():
        org = await _organization_named(conn, client)
        if org["kind"] != "client":
            raise Invalid("Only a client organization can be restricted")
        await conn.execute("UPDATE organizations SET restricted = $2 WHERE id = $1",
                           org["id"], restricted)
        for row in await conn.fetch("SELECT id FROM workspaces WHERE org_id = $1", org["id"]):
            await audit.record(conn, workspace_id=row["id"], action="org.restricted",
                               actor=actor, details={"restricted": restricted})


class Rehomed(NamedTuple):
    user_id: UUID
    previous_org: str  # for the operator's output only, never an audit event


async def rehome_person(pool, *, email: str, org: str, actor: Actor = CLI) -> Rehomed:
    """The recovery for a person homed in the wrong organization (an admin
    added an email that belongs to another customer): a new home, only while
    they hold no membership anywhere, so nothing they can reach moves with
    them. Audited in every workspace of the new home organization."""
    email, org = _clean_email(email), _check_name(org, "organization")
    async with pool.acquire() as conn, conn.transaction():
        target = await _organization_named(conn, org)
        # NO KEY UPDATE: an add of this person in flight (`_add` reads the home
        # FOR SHARE) commits first, and the count below sees its membership.
        # `users` alone: a lock through a join drops a row a concurrent rehome
        # moved, which would read as NotFound (B-021).
        found = await conn.fetchrow(
            "SELECT id, home_org_id FROM users WHERE lower(email) = lower($1)"
            " FOR NO KEY UPDATE",
            email,
        )
        if found is None:
            raise NotFound("No person with that email")
        if found["home_org_id"] == target["id"]:
            raise Invalid("This person is already homed in that organization")
        held = await conn.fetchval(
            "SELECT count(*) FROM memberships WHERE user_id = $1", found["id"])
        if held:
            raise Conflict(f"This person still holds {held} membership(s);"
                           " each must be removed before a new home is set")
        previous = await conn.fetchval(
            "SELECT name FROM organizations WHERE id = $1", found["home_org_id"])
        await conn.execute("UPDATE users SET home_org_id = $2 WHERE id = $1",
                           found["id"], target["id"])
        for row in await conn.fetch("SELECT id FROM workspaces WHERE org_id = $1", target["id"]):
            # Only `to`: the new home's admins read this trail, and the old
            # home is another customer (B-021). The operator gets it instead.
            await audit.record(conn, workspace_id=row["id"], action="person.rehome",
                               actor=actor, subject_user_id=found["id"],
                               details={"to": target["name"]})
        return Rehomed(found["id"], previous)


async def add_member(pool, *, workspace_id: UUID, email: str, role: str, actor: Actor) -> UUID:
    email, role = _clean_email(email), _check_role(role)
    async with pool.acquire() as conn, conn.transaction():
        workspace = await _workspace(conn, workspace_id, actor)
        user_id = await _person(conn, email, workspace["org_id"])
        await _add(conn, workspace, user_id, role, False, actor)
        return user_id


async def change_member(pool, *, workspace_id: UUID, user_id: UUID, actor: Actor,
                        role: str | None = None, provider_wide: bool | None = None) -> None:
    if role is not None:
        _check_role(role)
    async with pool.acquire() as conn, conn.transaction():
        await _change(conn, await _workspace(conn, workspace_id, actor), user_id, actor,
                      role, provider_wide)


async def remove_member(pool, *, workspace_id: UUID, user_id: UUID, actor: Actor) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await _remove(conn, await _workspace(conn, workspace_id, actor), user_id, actor)


async def set_member(pool, *, workspace: str, email: str, role: str,
                     provider_wide: bool | None = None, actor: Actor = CLI) -> UUID:
    """The CLI's upsert: add, or change role and grant, by names. `provider_wide`
    None leaves an existing member's grant alone (a new member gets none)."""
    email, role = _clean_email(email), _check_role(role)
    async with pool.acquire() as conn, conn.transaction():
        ws = await _workspace_named(conn, workspace, actor)
        user_id = await _person(conn, email, ws["org_id"])
        member = await conn.fetchval(
            "SELECT 1 FROM memberships WHERE workspace_id = $1 AND user_id = $2",
            ws["id"], user_id,
        )
        if member is None:
            await _add(conn, ws, user_id, role, bool(provider_wide), actor)
        else:
            await _change(conn, ws, user_id, actor, role, provider_wide)
        return user_id


async def remove_member_by_email(pool, *, workspace: str, email: str,
                                 actor: Actor = CLI) -> None:
    email = _clean_email(email)
    async with pool.acquire() as conn, conn.transaction():
        ws = await _workspace_named(conn, workspace, actor)
        user_id = await conn.fetchval(
            "SELECT id FROM users WHERE lower(email) = lower($1)", email)
        if user_id is None:
            raise NotFound("Not a member of this workspace")
        await _remove(conn, ws, user_id, actor)


async def list_members(db, workspace_id: UUID) -> list[dict]:
    rows = await db.fetch(
        "SELECT u.id, u.email, u.display_name, o.name AS home_org, m.role, m.provider_wide"
        "  FROM memberships m"
        "  JOIN users u ON u.id = m.user_id"
        "  JOIN organizations o ON o.id = u.home_org_id"
        " WHERE m.workspace_id = $1"
        " ORDER BY lower(u.email)",
        workspace_id,
    )
    return [
        {
            "user_id": str(r["id"]),
            "email": r["email"],
            "display_name": r["display_name"],
            "home_organization": r["home_org"],
            "role": r["role"],
            "provider_wide": r["provider_wide"],
        }
        for r in rows
    ]


async def misplaced_workspaces(pool, storage_region: str) -> list[tuple[str, str]]:
    """(name, region) of each workspace this deployment's storage may not hold:
    made before D-069's build, or by SQL. Startup names them (Burhan's call,
    S31); nothing is moved or refused."""
    rows = await pool.fetch("SELECT name, region FROM workspaces ORDER BY name")
    return [(r["name"], r["region"]) for r in rows
            if storage_refusal(r["region"], storage_region) is not None]


async def overview(db) -> list[dict]:
    """Organizations, their workspaces, regions and member counts. No emails."""
    rows = await db.fetch(
        "SELECT o.name AS org, o.kind, p.name AS parent, o.restricted,"
        "       w.name AS workspace, w.region,"
        "       (SELECT count(*) FROM memberships m WHERE m.workspace_id = w.id) AS members"
        "  FROM organizations o"
        "  LEFT JOIN organizations p ON p.id = o.parent_id"
        "  LEFT JOIN workspaces w ON w.org_id = o.id"
        " ORDER BY coalesce(p.name, o.name), o.kind <> 'provider', o.name, w.name"
    )
    return [dict(r) for r in rows]
