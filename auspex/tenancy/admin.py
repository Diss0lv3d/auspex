"""Every write to organizations, workspaces and memberships (D-061; S30 design §3).

The CLI, the membership API and the tests all come through here, so the rules
live once: a membership's workspace belongs to the person's home organization
or to a client of it; `provider_wide` only on a provider's own workspace;
nobody changes their own membership. Each write records its audit event in the
same transaction as the change.
"""

from uuid import UUID

import asyncpg

from auspex.llm.scorecard import DEPLOYMENT_WORKSPACE


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
    workspace_id = await conn.fetchval(
        "INSERT INTO workspaces (name, org_id) VALUES ($1, $2)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        name, org["id"],
    )
    return org["id"], workspace_id


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
        return user_id
