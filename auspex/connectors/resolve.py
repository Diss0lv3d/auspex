"""Actions resolve by workspace (S34, design decision 5).

`resolve(name, workspace_id)` answers a built-in action anywhere, and, for
`<prefix>__<action>`, the compiled action of that workspace's ENABLED integration with
that prefix, if an admin GRANTED the action (none by default), compiled from the
manifest of the package the integration pins. Anything else is None. A prefix resolves
only in its own workspace; prefixes are never reused (S33), so workspace + prefix binds
an approval to the integration it was made for.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
from auspex_sdk.manifest import parse_manifest

from auspex.actions import ActionRegistry
from auspex.actions.types import ActionSpec
from auspex.connectors.compile import Dispatch, compile_action
from auspex.edge_api.agents import health
from auspex.integrations.store import Integration, _integration

SEPARATOR = "__"


class ActionResolver:
    """The built-ins, plus each workspace's granted connector actions. `dispatch` makes the
    dispatcher a compiled action's roles call, given the integration (Task 5)."""

    def __init__(self, builtins: ActionRegistry, pool: asyncpg.Pool, *,
                 dispatch: Callable[[Integration], Dispatch]) -> None:
        self.builtins = builtins
        self._pool = pool
        self._dispatch = dispatch

    # The built-ins' own reads, for callers that name a built-in or list them (the chat
    # manifest offers connector actions in Task 8).
    def get(self, name: str) -> ActionSpec | None:
        return self.builtins.get(name)

    def manifest(self, agent_mode: str):
        return self.builtins.manifest(agent_mode)

    async def resolve(self, name: str, workspace_id: UUID | str) -> ActionSpec | None:
        builtin = self.builtins.get(name)
        if builtin is not None:
            return builtin
        prefix, sep, action = name.partition(SEPARATOR)
        if not sep or not prefix or not action:
            return None
        found = await self.integration(workspace_id, prefix)
        if found is None or action not in found[0].grants:
            return None
        integration, manifest = found
        if not any(a.name == action for a in manifest.actions):
            return None
        return compile_action(
            manifest, action, content_hash=integration.content_hash, prefix=prefix,
            integration_id=integration.id, workspace_id=integration.workspace_id,
            dispatch=self._dispatch(integration))

    async def refusal(self, name: str, workspace_id: UUID | str) -> tuple[str, str] | None:
        """Why a connector action cannot run here now (design decision 7), as (reason,
        words), or None. Asked before an approved action is claimed, so each reason is
        its own refusal and nothing is dispatched. A name that matches no integration of
        this workspace is not answered here: it does not resolve at all."""
        if self.builtins.get(name) is not None:
            return None
        prefix, sep, action = name.partition(SEPARATOR)
        if not sep:
            return None
        row = await self._pool.fetchrow(
            "SELECT i.name, i.disabled_at, i.grants, a.name AS agent, a.revoked_at,"
            " a.last_heartbeat_at FROM integrations i"
            " LEFT JOIN edge_agents a ON a.id = i.agent_id AND a.workspace_id = i.workspace_id"
            " WHERE i.workspace_id = $1 AND i.prefix = $2",
            UUID(str(workspace_id)), prefix)
        if row is None:
            return None
        if row["disabled_at"] is not None:
            return ("integration_disabled",
                    f"the integration {row['name']!r} is disabled; enable it to run {name}")
        if action not in (row["grants"] or ()):
            return ("not_granted",
                    f"{action} is no longer granted to the integration {row['name']!r}")
        if row["agent"] is None or row["revoked_at"] is not None:
            return ("agent_offline",
                    f"the Edge Agent of {row['name']!r} was revoked; assign another agent")
        state = health(row["last_heartbeat_at"], datetime.now(UTC))
        if state in ("never", "offline"):
            words = "has never connected" if state == "never" else "is offline"
            return ("agent_offline", f"the Edge Agent {row['agent']!r} {words}")
        return None

    async def integration(self, workspace_id: UUID | str, prefix: str):
        """(the enabled integration with this prefix in this workspace, its manifest)."""
        row = await self._pool.fetchrow(
            "SELECT i.id, i.workspace_id, i.name, i.prefix, i.connector_id, i.content_hash,"
            " i.config, i.agent_id, i.created_at, i.disabled_at, i.grants,"
            " (SELECT p.manifest FROM connector_packages p"
            "   WHERE p.content_hash = i.content_hash LIMIT 1) AS manifest"
            " FROM integrations i WHERE i.workspace_id = $1 AND i.prefix = $2"
            " AND i.disabled_at IS NULL",
            UUID(str(workspace_id)), prefix)
        if row is None or row["manifest"] is None:
            return None
        manifest = row["manifest"]
        data = json.loads(manifest) if isinstance(manifest, str) else manifest
        return _integration(row), parse_manifest(data)


__all__ = ["SEPARATOR", "ActionResolver"]
