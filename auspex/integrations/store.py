"""Integrations: create, update, disable, list (S33, D-060, D-063).

An integration pins one package (`content_hash`) the workspace's catalogue lists, and
names the one Edge Agent of its workspace that runs it (Hunaiza's call). Its config is
checked against the pinned manifest's config schema on every write: a secret field holds
`secret:<name>` only, so no row (and no job made from one) ever carries a secret value.
Removing one disables it; its prefix stays taken (spec decision 2).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
from auspex_sdk.manifest import Manifest, ManifestError, parse_manifest, parse_tls_value
from auspex_sdk.vocab import MAX_PREFIX, WIRE_NAME

from auspex.connectors.catalogue import available
from auspex.tenancy import audit
from auspex.untrusted import unstorable

# `secret:<name>`: the name the agent looks up in its own secrets file (D-063).
SECRET_REF = re.compile(r"secret:[A-Za-z0-9_.-]{1,64}")
MAX_NAME = 80


class IntegrationRefused(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Integration:
    id: UUID
    workspace_id: UUID
    name: str
    prefix: str
    connector_id: str
    content_hash: str
    config: dict
    agent_id: UUID
    created_at: datetime
    disabled_at: datetime | None

    @property
    def enabled(self) -> bool:
        return self.disabled_at is None


def _integration(row: asyncpg.Record) -> Integration:
    config = row["config"]
    return Integration(
        row["id"], row["workspace_id"], row["name"], row["prefix"], row["connector_id"],
        row["content_hash"], json.loads(config) if isinstance(config, str) else config,
        row["agent_id"], row["created_at"], row["disabled_at"])


def check_config(manifest: Manifest, config: Any) -> dict:
    """The config as the manifest allows it, or IntegrationRefused naming the field. The
    agent checks it again with the SDK's `load_config` before it runs anything."""
    if not isinstance(config, dict):
        raise IntegrationRefused("config must be an object of field name to value")
    if unstorable(config):
        raise IntegrationRefused("config holds a NUL or a lone surrogate, which cannot be"
                                 " stored")
    fields = {f.name: f for f in manifest.config}
    for key in config:
        if key not in fields:
            raise IntegrationRefused(f"config.{key}: not a config field of this connector")
    for name, f in fields.items():
        value = config.get(name)
        if value is None:
            if f.required:
                raise IntegrationRefused(f"config.{name}: required")
            continue
        _check_field(f.name, f.type, f.values, value)
    return {k: v for k, v in config.items() if v is not None}


def _check_field(name: str, kind: str, values: tuple[str, ...] | None, value: Any) -> None:
    where = f"config.{name}"
    if kind == "secret":
        if not isinstance(value, str) or not SECRET_REF.fullmatch(value):
            raise IntegrationRefused(
                f"{where}: a secret is given as secret:<name>, the name of a secret on the"
                " Edge Agent's host, never its value")
    elif kind == "tls":
        try:
            parse_tls_value(value, where)
        except ManifestError as err:
            raise IntegrationRefused(f"{where}: {err.message}") from err
    elif kind == "url":
        parts = urlsplit(value) if isinstance(value, str) else None
        if parts is None or parts.scheme != "https" or not parts.hostname:
            raise IntegrationRefused(f"{where}: expected an https:// URL")
        if "@" in parts.netloc:
            raise IntegrationRefused(
                f"{where}: a URL must not carry credentials; use a secret field")
    elif kind == "enum":
        if value not in (values or ()):
            raise IntegrationRefused(f"{where}: expected one of {', '.join(values or ())}")
    elif not {"string": isinstance(value, str),
              "integer": isinstance(value, int) and not isinstance(value, bool),
              "boolean": isinstance(value, bool)}.get(kind, False):
        raise IntegrationRefused(f"{where}: expected a {kind}")


def _check_name(name: str) -> str:
    if unstorable(name):
        raise IntegrationRefused("name holds a NUL or a lone surrogate, which cannot be"
                                 " stored")
    name = " ".join(str(name).split())
    if not name or len(name) > MAX_NAME:
        raise IntegrationRefused(f"name: required, at most {MAX_NAME} characters")
    return name


def _check_prefix(prefix: str) -> str:
    if not isinstance(prefix, str) or not WIRE_NAME.fullmatch(prefix) or len(prefix) > MAX_PREFIX:
        raise IntegrationRefused(
            f"prefix: a wire identifier (letters, digits, _) of at most {MAX_PREFIX} characters,"
            " like siem1")
    return prefix


async def _pinned_manifest(pool, workspace_id: UUID, content_hash: str) -> tuple[str, Manifest]:
    for entry in await available(pool, workspace_id=workspace_id):
        if entry.content_hash == content_hash:
            return entry.connector_id, parse_manifest(entry.manifest)
    raise IntegrationRefused(f"package {content_hash} is not available to this workspace")


async def _check_agent(conn, workspace_id: UUID, agent_id: UUID) -> None:
    if not await conn.fetchval(
        "SELECT 1 FROM edge_agents WHERE id = $1 AND workspace_id = $2",
        agent_id, workspace_id,
    ):
        raise IntegrationRefused("agent_id: no Edge Agent of this workspace has that id")


async def cancel_queued_tests(conn, integration_id: UUID, why: str) -> None:
    """Queued tests of an integration that changed under them can no longer run as asked:
    they end now, in the change's transaction. A running one finishes (spec, builder
    check 5)."""
    await conn.execute(
        "UPDATE jobs SET status = 'failed', last_error = $2, finished_at = now()"
        " WHERE integration_id = $1 AND kind = 'connector.test' AND status = 'queued'",
        integration_id, f"cancelled: {why}")


async def create(pool, *, workspace_id: UUID, actor: audit.Actor, name: str, prefix: str,
                 content_hash: str, config: Any, agent_id: UUID) -> Integration:
    name, prefix = _check_name(name), _check_prefix(prefix)
    connector_id, manifest = await _pinned_manifest(pool, workspace_id, content_hash)
    config = check_config(manifest, config)
    async with pool.acquire() as conn, conn.transaction():
        await _check_agent(conn, workspace_id, agent_id)
        try:
            row = await conn.fetchrow(
                "INSERT INTO integrations (workspace_id, name, prefix, connector_id,"
                " content_hash, config, agent_id, created_by)"
                " VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)"
                " RETURNING id, workspace_id, name, prefix, connector_id, content_hash,"
                " config, agent_id, created_at, disabled_at",
                workspace_id, name, prefix, connector_id, content_hash, json.dumps(config),
                agent_id, actor.user_id)
        except asyncpg.UniqueViolationError as err:
            raise IntegrationRefused(
                f"prefix: {prefix} is taken in this workspace (a removed integration keeps"
                " its prefix, so an old approval never points at a new one)") from err
        await audit.record(conn, workspace_id=workspace_id, action="integration.created",
                           actor=actor, details={"integration_id": str(row["id"]),
                                                 "prefix": prefix, "content_hash": content_hash})
    return _integration(row)


async def get(pool, *, workspace_id: UUID, integration_id: UUID) -> Integration | None:
    row = await pool.fetchrow(
        "SELECT id, workspace_id, name, prefix, connector_id, content_hash, config, agent_id,"
        " created_at, disabled_at FROM integrations WHERE id = $1 AND workspace_id = $2",
        integration_id, workspace_id)
    return _integration(row) if row else None


async def update(pool, *, workspace_id: UUID, actor: audit.Actor, integration_id: UUID,
                 name: str | None = None, content_hash: str | None = None,
                 config: Any = None, agent_id: UUID | None = None) -> Integration:
    """Change an enabled integration; the config is re-checked against the (possibly new)
    pinned manifest. The prefix never changes."""
    current = await get(pool, workspace_id=workspace_id, integration_id=integration_id)
    if current is None:
        raise LookupError("no such integration in this workspace")
    if not current.enabled:
        raise IntegrationRefused("this integration is disabled")
    name = _check_name(name) if name is not None else current.name
    content_hash = content_hash or current.content_hash
    connector_id, manifest = await _pinned_manifest(pool, workspace_id, content_hash)
    config = check_config(manifest, current.config if config is None else config)
    agent_id = agent_id or current.agent_id
    async with pool.acquire() as conn, conn.transaction():
        await _check_agent(conn, workspace_id, agent_id)
        row = await conn.fetchrow(
            "UPDATE integrations SET name = $3, connector_id = $4, content_hash = $5,"
            " config = $6::jsonb, agent_id = $7 WHERE id = $1 AND workspace_id = $2"
            " AND disabled_at IS NULL"
            " RETURNING id, workspace_id, name, prefix, connector_id, content_hash,"
            " config, agent_id, created_at, disabled_at",
            integration_id, workspace_id, name, connector_id, content_hash,
            json.dumps(config), agent_id)
        if row is None:
            raise IntegrationRefused("this integration is disabled")
        if agent_id != current.agent_id or content_hash != current.content_hash:
            await cancel_queued_tests(conn, integration_id,
                                      "the integration's agent or package changed")
        await audit.record(conn, workspace_id=workspace_id, action="integration.updated",
                           actor=actor, details={"integration_id": str(integration_id)})
    return _integration(row)


async def disable(pool, *, workspace_id: UUID, actor: audit.Actor,
                  integration_id: UUID) -> None:
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "UPDATE integrations SET disabled_at = coalesce(disabled_at, now())"
            " WHERE id = $1 AND workspace_id = $2 RETURNING id", integration_id, workspace_id)
        if row is None:
            raise LookupError("no such integration in this workspace")
        await cancel_queued_tests(conn, integration_id, "the integration was disabled")
        await audit.record(conn, workspace_id=workspace_id, action="integration.disabled",
                           actor=actor, details={"integration_id": str(integration_id)})


async def list_for(pool, *, workspace_id: UUID) -> list[Integration]:
    rows = await pool.fetch(
        "SELECT id, workspace_id, name, prefix, connector_id, content_hash, config, agent_id,"
        " created_at, disabled_at FROM integrations WHERE workspace_id = $1"
        " ORDER BY disabled_at NULLS FIRST, name", workspace_id)
    return [_integration(r) for r in rows]
