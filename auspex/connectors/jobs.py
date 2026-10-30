"""The connector job kinds and their one payload (S32, spec decision 4).

Five generic kinds plus `observe` (spec, "Observe"), named in code: a connector command
becomes a job of one of these kinds, never a kind of its own. One kind per manifest
action was refused: it would make job kinds tenant data and grow this code-declared
list with every upload. S32 declares them; S33 handles them.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

CONNECTOR_KINDS: tuple[str, ...] = (
    "connector.test",
    "connector.fetch",
    "connector.action.dry_run",
    "connector.action.execute",
    "connector.action.undo",
    "connector.action.observe",
)


@dataclass(frozen=True)
class ConnectorJobPayload:
    """What one connector job asks the agent to run.

    `content_hash` is the package the agent must run (D-062), not whatever the id
    currently resolves to. `integration_id` is what the job row's claim is scoped by
    (S31's `ClaimScope`). `command` names the handler: `test`, `fetch`, or, inside
    `action`, one of `dry_run`, `execute`, `undo`, `observe`. `arguments` are typed
    by the manifest. `proposal_id` and `idempotency_key` (S31's `operation_key`) let
    a connector de-duplicate on the vendor's side; `cursor` and `limit` are `fetch`'s.
    """

    integration_id: UUID
    content_hash: str
    command: str
    action: str | None
    arguments: dict
    proposal_id: UUID | None
    idempotency_key: str | None
    cursor: str | None
    limit: int | None


__all__ = ["CONNECTOR_KINDS", "ConnectorJobPayload"]
