"""The connector catalogue (S32, spec decision 3): which connectors a workspace has.

A package is registered into ONE workspace (D-008) and identified by its content hash
(D-064): the same hash twice is a no-op, and the same id and version with another hash is
refused. Three sources make up what a workspace may use, built here by one function
(`available`) so S33's integration form and S34's grant checks ask the same question
TD-023 asks:

- its own packages;
- its provider's packages registered with `offered_to_clients` (D-071), which every
  client of that provider lists read-only, restricted clients included: a listing is
  code, not access to any client's data;
- first-party packages, registered by the CLI only into the reserved `__deployment__`
  workspace (D-035, D-068), listed everywhere.

Who is whose provider is read from `organizations.kind`/`parent_id`, never from input.
The core only READS a package's bytes (`auspex_sdk.package.read_package`: zipfile and
hashing, no member is imported or executed; D-062).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import asyncpg
from auspex_sdk.package import PackageError, read_package

from auspex.llm.scorecard import DEPLOYMENT_WORKSPACE

Source = Literal["own", "provider", "first_party"]


class RegistrationRefused(ValueError):
    """A package the catalogue will not register. `reason` is safe to show the admin."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CatalogueEntry:
    """One registered package as a workspace sees it (never its bytes)."""

    id: UUID
    workspace_id: UUID
    connector_id: str
    version: str
    content_hash: str
    manifest: dict
    first_party: bool
    offered_to_clients: bool
    registered_by: UUID | None
    created_at: datetime
    source: Source


async def _by_hash(conn, workspace_id: UUID, content_hash: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, workspace_id, connector_id, version, content_hash, manifest, first_party,"
        " offered_to_clients, registered_by, created_at FROM connector_packages"
        " WHERE workspace_id = $1 AND content_hash = $2",
        workspace_id, content_hash,
    )


def _entry(row: asyncpg.Record, source: Source) -> CatalogueEntry:
    return CatalogueEntry(
        id=row["id"],
        workspace_id=row["workspace_id"],
        connector_id=row["connector_id"],
        version=row["version"],
        content_hash=row["content_hash"],
        manifest=json.loads(row["manifest"]),
        first_party=row["first_party"],
        offered_to_clients=row["offered_to_clients"],
        registered_by=row["registered_by"],
        created_at=row["created_at"],
        source=source,
    )


async def register(
    pool: asyncpg.Pool,
    *,
    workspace_id: UUID,
    data: bytes,
    registered_by: UUID | None,
    offered_to_clients: bool,
    first_party: bool = False,
) -> CatalogueEntry:
    """Validate a package's bytes and register it in `workspace_id`.

    `first_party` is the CLI's alone (the route always passes False, D-064), and it is
    true exactly when the workspace is `__deployment__`, so neither can stand without
    the other. Refusals raise `RegistrationRefused`; nothing is written then."""
    try:
        manifest, content_hash, files = read_package(data)
    except PackageError as err:
        raise RegistrationRefused(f"package refused: {err}") from err
    # read_package validated manifest.json; it is stored as uploaded (the hash covers it).
    manifest_json = files["manifest.json"].decode("utf-8")
    _refuse_unstorable(json.loads(manifest_json))
    async with pool.acquire() as conn, conn.transaction():
        ws = await conn.fetchrow(
            "SELECT w.name, w.org_id, o.kind, o.parent_id FROM workspaces w"
            " LEFT JOIN organizations o ON o.id = w.org_id WHERE w.id = $1",
            workspace_id,
        )
        if ws is None:
            raise RegistrationRefused("no such workspace")
        is_deployment = ws["org_id"] is None and ws["name"] == DEPLOYMENT_WORKSPACE
        if first_party != is_deployment:
            raise RegistrationRefused(
                f"a first-party package is registered into {DEPLOYMENT_WORKSPACE}"
                " by the CLI, and nothing else is registered there"
            )
        # Review Focus 5: decided by the organization's kind, whoever the caller is.
        if offered_to_clients and ws["kind"] != "provider":
            raise RegistrationRefused(
                "only a provider workspace may offer a connector to its clients"
            )
        same = await _by_hash(conn, workspace_id, content_hash)
        if same is not None:
            return _entry(same, "own")
        if await conn.fetchval(
            "SELECT 1 FROM connector_packages"
            " WHERE workspace_id = $1 AND connector_id = $2 AND version = $3",
            workspace_id, manifest.id, manifest.version,
        ):
            # An identical upload racing this one may have committed since the read above.
            if (same := await _by_hash(conn, workspace_id, content_hash)) is not None:
                return _entry(same, "own")
            raise _bump(manifest.id, manifest.version)
        await _refuse_a_taken_id(conn, ws, manifest.id, first_party)
        try:
            # A concurrent registration of this very hash wins quietly: DO NOTHING waits
            # for it, and the read below sees its row. The savepoint keeps the outer
            # transaction usable when the id+version index fires instead.
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO connector_packages (workspace_id, connector_id, version,"
                    " content_hash, manifest, package, first_party, offered_to_clients,"
                    " registered_by) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9)"
                    " ON CONFLICT (workspace_id, content_hash) DO NOTHING",
                    workspace_id, manifest.id, manifest.version, content_hash,
                    manifest_json, data, first_party, offered_to_clients, registered_by,
                )
        except asyncpg.UniqueViolationError as err:
            # The id+version index: either this very package committed first (one entry),
            # or another hash under this version did (refused).
            if (same := await _by_hash(conn, workspace_id, content_hash)) is not None:
                return _entry(same, "own")
            raise _bump(manifest.id, manifest.version) from err
        row = await _by_hash(conn, workspace_id, content_hash)
    return _entry(row, "own")


def _refuse_unstorable(value: Any) -> None:
    """Postgres `jsonb` cannot hold a NUL or a lone surrogate, though `json.loads`
    accepts both as escapes. Refused in words here, not as a database error (a 500 at
    the route; PR #43 review #6)."""
    if isinstance(value, str):
        if "\x00" in value or any("\ud800" <= c <= "\udfff" for c in value):
            raise RegistrationRefused(
                "manifest.json holds a NUL or a lone surrogate, which cannot be stored")
    elif isinstance(value, dict):
        for k, v in value.items():
            _refuse_unstorable(k)
            _refuse_unstorable(v)
    elif isinstance(value, list):
        for v in value:
            _refuse_unstorable(v)


def _bump(connector_id: str, version: str) -> RegistrationRefused:
    # A changed package is a new identity whatever its semver says (D-064).
    return RegistrationRefused(
        f"{connector_id} {version} is already registered with other content:"
        " bump the version"
    )


async def _refuse_a_taken_id(
    conn: asyncpg.Connection,
    ws: asyncpg.Record,
    connector_id: str,
    first_party: bool,
) -> None:
    """One id names one connector in a workspace's listing, so an id that arrives from
    another source (first-party, or this client's provider) cannot be registered here."""
    if not first_party and await conn.fetchval(
        "SELECT 1 FROM connector_packages WHERE first_party AND connector_id = $1",
        connector_id,
    ):
        raise RegistrationRefused(f"{connector_id} is a first-party connector's id")
    if ws["kind"] == "client" and await conn.fetchval(
        "SELECT 1 FROM connector_packages cp JOIN workspaces pw ON pw.id = cp.workspace_id"
        " WHERE pw.org_id = $1 AND cp.offered_to_clients AND cp.connector_id = $2",
        ws["parent_id"], connector_id,
    ):
        raise RegistrationRefused(f"{connector_id} is an id your provider offers")


async def available(pool: asyncpg.Pool, *, workspace_id: UUID) -> list[CatalogueEntry]:
    """What `workspace_id` may use: its own packages, its provider's offered ones and the
    first-party ones, each marked with its source. The provider is the workspace's own
    organization's `parent_id`, read here; a workspace that does not exist lists nothing.

    One source per connector id: first_party, then provider, then own. A shadowed package
    stays registered but is not listed (ruling c1, Task 10 fix round 1).
    """
    # Why the order: refusing a first-party or offered id a tenant already holds would let
    # any tenant squat on it, so the higher source registers anyway and wins the listing.
    rows = await pool.fetch(
        """
        WITH me AS (
            SELECT w.id, o.parent_id FROM workspaces w
              LEFT JOIN organizations o ON o.id = w.org_id
             WHERE w.id = $1
        ), visible AS (
            SELECT cp.id, cp.workspace_id, cp.connector_id, cp.version, cp.content_hash,
                   cp.manifest, cp.first_party, cp.offered_to_clients, cp.registered_by,
                   cp.created_at,
                   CASE WHEN cp.first_party THEN 0
                        WHEN cp.workspace_id = me.id THEN 2
                        ELSE 1 END AS rank
              FROM connector_packages cp
              CROSS JOIN me
              JOIN workspaces pw ON pw.id = cp.workspace_id
             WHERE cp.workspace_id = me.id
                OR cp.first_party
                OR (cp.offered_to_clients AND pw.org_id = me.parent_id)
        )
        SELECT v.*, CASE v.rank WHEN 0 THEN 'first_party' WHEN 1 THEN 'provider'
                                ELSE 'own' END AS source
          FROM visible v
         WHERE v.rank = (SELECT min(rank) FROM visible x
                          WHERE x.connector_id = v.connector_id)
         ORDER BY v.connector_id, v.created_at
        """,
        workspace_id,
    )
    return [_entry(r, r["source"]) for r in rows]
