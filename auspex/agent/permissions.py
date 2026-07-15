"""Permission gate + proposal store (S3 step 3, D-014).

The gate is the single code-owned chokepoint that decides, per tool call,
whether it may auto-execute or must become a human-approval PROPOSAL. It reads
exactly one input — the tool's `ToolLevel` — and nothing about the model's
text. This is the enforcement half of D-014:

    A write/destructive action counts as performed ONLY when its tool call
    actually executed and returned a result. Model-asserted completion text
    ("ticket created", a made-up ID) is never treated as execution.

The loop honours the gate structurally: READ → run the handler; WRITE/
DESTRUCTIVE → file a proposal and DO NOT run the handler. Because action records
are derived solely from real tool calls routed through here, a fabricated
"done" sentence can never mint one. Thresholds/tiers (S18) will refine this;
the invariant does not.

SARA pattern reference (reused, not copied): sara/core/permissions.py:70-177.
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

import asyncpg

from auspex.agent.registry import ToolLevel


class PermissionOutcome(StrEnum):
    ALLOW = "allow"  # READ — auto-execute
    PROPOSE = "propose"  # WRITE/DESTRUCTIVE — file for human approval, never auto-execute


@dataclass(frozen=True)
class PermissionDecision:
    outcome: PermissionOutcome
    reason: str


def gate(level: ToolLevel | None) -> PermissionDecision:
    """Compile a tool level to a gate decision. Fail safe: anything that is not
    unambiguously READ is proposed, never executed."""
    if level is ToolLevel.READ:
        return PermissionDecision(PermissionOutcome.ALLOW, "read-only tool; auto-executed")
    if level is ToolLevel.WRITE:
        return PermissionDecision(
            PermissionOutcome.PROPOSE, "write action requires human approval (D-014)"
        )
    if level is ToolLevel.DESTRUCTIVE:
        return PermissionDecision(
            PermissionOutcome.PROPOSE, "destructive action requires human approval (D-014)"
        )
    # Unknown/unclassified level: never auto-execute.
    return PermissionDecision(PermissionOutcome.PROPOSE, "unclassified tool; gated by default")


# --- Proposal persistence ----------------------------------------------------


class ProposalStore(Protocol):
    """Sink for gated write/destructive actions. The loop depends on this
    interface, not on Postgres — tests inject an in-memory double."""

    async def create(
        self,
        *,
        workspace_id: UUID | str,
        tool_name: str,
        tool_level: str,
        tool_input: dict,
        session_id: UUID | str | None = None,
    ) -> str:
        """Persist a pending_approval proposal; return its id as a string."""
        ...


class PgProposalStore:
    """Postgres-backed proposal store. One row per gated action, status
    starts 'pending_approval' — nothing here executes anything."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def create(
        self,
        *,
        workspace_id: UUID | str,
        tool_name: str,
        tool_level: str,
        tool_input: dict,
        session_id: UUID | str | None = None,
    ) -> str:
        # Explicit ::uuid / ::jsonb casts so callers may pass UUID or str.
        proposal_id = await self._pool.fetchval(
            """
            INSERT INTO proposals
                (workspace_id, session_id, tool_name, tool_level, tool_input)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5::jsonb)
            RETURNING id
            """,
            str(workspace_id),
            str(session_id) if session_id is not None else None,
            tool_name,
            tool_level,
            json.dumps(tool_input),
        )
        return str(proposal_id)
