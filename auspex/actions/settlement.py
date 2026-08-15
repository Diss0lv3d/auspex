"""Approve, execute, undo — S18 (Phase 4).

This is where the S17 contract stops being a contract. Three rules decide
everything in this module, and each is a rule because the alternative is a class
of bug rather than a style preference:

1. **The claim wins the row before anything runs.** Settlement is a single
   `UPDATE ... WHERE status = 'pending_approval' RETURNING`, so two approvers
   racing one proposal are resolved by Postgres, not by a read-then-write in the
   app. The loser gets `None` and is TOLD it lost. This is the D-001 reason
   Postgres holds truth: a double-approve must be provably impossible rather
   than unlikely, and "we check first" is not a mechanism — it is a window.

2. **Approval is not permission to run forever.** An approved proposal is
   re-checked at execute time against the CURRENT declaration: the D-014 gate is
   re-run on today's risk, and the spec fingerprint the approver saw must still
   match (TD-023). An action approved an hour ago must not execute against a
   changed declaration — a deploy that turned a write into something destructive,
   or removed the undo the approval was granted on the strength of.

3. **The platform only executes what it owns.** `EXECUTABLE_SYSTEMS` is a code
   allow-list, not a config value. An action scoped to a third-party system stays
   proposal-only until there is a sandbox to point it at: a real credential and a
   real blast radius is not something to acquire as a side effect of a session
   about approval flow.

Nothing here trusts the model for anything. The arguments were captured when the
proposal was filed, the card was rendered from the spec, and the execute path
never reads a sentence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

import asyncpg

from auspex.actions.proposal import card, fingerprint
from auspex.actions.registry import ActionRegistry
from auspex.actions.types import ActionOutcome, ActionSpec
from auspex.agent.permissions import PermissionOutcome, gate

# Systems Auspex itself owns. An action whose scope names anything else may be
# proposed, approved and rendered — and will refuse to run, loudly. Widening this
# set is a decision with a blast radius, so it is a code change and a review.
EXECUTABLE_SYSTEMS = frozenset({"auspex"})


class Settlement(StrEnum):
    """Why a settle attempt ended the way it did — distinguishable in code, so a
    caller never has to parse a message to know whether it lost a race."""

    CLAIMED = "claimed"  # this caller won the row
    ALREADY_DECIDED = "already_decided"  # someone else got there first
    NOT_FOUND = "not_found"  # no such proposal in this workspace


@dataclass(frozen=True)
class SettleResult:
    outcome: Settlement
    proposal: dict | None = None
    current_status: str | None = None

    @property
    def won(self) -> bool:
        return self.outcome is Settlement.CLAIMED


class ExecutionRefused(RuntimeError):
    """The proposal was approved and still must not run. Carries a machine
    reason so a surface can say WHICH guarantee stopped it."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# Every read here wants the whole row: the caller decides what to expose
# (`routes/proposals._public`), and `_as_dict` decodes by key. Spelled `*`
# rather than interpolating a column-list constant, so no query in this module
# is built by string construction at all.


def _as_dict(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key in ("tool_input", "result", "card", "undo_result"):
        if isinstance(out.get(key), str):
            out[key] = json.loads(out[key])
    return out


class ProposalSettlement:
    """Claim-first settlement over the proposals table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def file(
        self,
        *,
        workspace_id: UUID | str,
        spec: ActionSpec,
        arguments: dict,
        dry_run: ActionOutcome,
        session_id: UUID | str | None = None,
    ) -> dict:
        """File an action proposal, carrying the card a human will see and the
        identity of the declaration it was rendered from.

        The card is STORED rather than re-rendered on read: re-deriving it later
        would show today's declaration for yesterday's decision, and an audit
        trail that quietly updates itself is worse than none.
        """
        rendered = card(spec, arguments=arguments, dry_run=dry_run)
        row = await self._pool.fetchrow(
            """
            INSERT INTO proposals
                (workspace_id, session_id, tool_name, tool_level, tool_input,
                 spec_fingerprint, card)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5::jsonb, $6, $7::jsonb)
            RETURNING *
            """,
            str(workspace_id),
            str(session_id) if session_id is not None else None,
            spec.name,
            spec.risk.value,
            json.dumps(arguments),
            rendered["spec_fingerprint"],
            json.dumps(rendered),
        )
        return _as_dict(row)

    async def get(self, *, workspace_id: UUID | str, proposal_id: UUID | str) -> dict | None:
        return _as_dict(
            await self._pool.fetchrow(
                "SELECT * FROM proposals WHERE id = $1::uuid AND workspace_id = $2::uuid",
                str(proposal_id),
                str(workspace_id),
            )
        )

    async def pending(self, *, workspace_id: UUID | str, limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT * FROM proposals
            WHERE workspace_id = $1::uuid AND status = 'pending_approval'
            ORDER BY created_at DESC
            LIMIT $2
            """,
            str(workspace_id),
            limit,
        )
        return [_as_dict(r) for r in rows]

    async def settle(
        self,
        *,
        workspace_id: UUID | str,
        proposal_id: UUID | str,
        decision: str,
        decided_by: UUID | str | None,
    ) -> SettleResult:
        """Approve or reject, exactly once.

        The whole guarantee is in the WHERE clause: the row moves out of
        `pending_approval` in the same statement that reads it, so the second
        approver's UPDATE matches zero rows. No advisory lock, no SELECT ... FOR
        UPDATE, no read-then-write — those all work too, and all of them are a
        wider window than this.
        """
        if decision not in ("approved", "rejected"):
            raise ValueError(f"decision must be 'approved' or 'rejected', got {decision!r}")
        row = await self._pool.fetchrow(
            """
            UPDATE proposals
               SET status = $3, decided_at = now(), decided_by = $4::uuid
             WHERE id = $1::uuid
               AND workspace_id = $2::uuid
               AND status = 'pending_approval'
            RETURNING *
            """,
            str(proposal_id),
            str(workspace_id),
            decision,
            str(decided_by) if decided_by is not None else None,
        )
        if row is not None:
            return SettleResult(Settlement.CLAIMED, _as_dict(row))
        # Lost, or never existed. One more read to say WHICH — after the fact, so
        # it cannot widen the window that matters.
        current = await self.get(workspace_id=workspace_id, proposal_id=proposal_id)
        if current is None:
            return SettleResult(Settlement.NOT_FOUND)
        return SettleResult(
            Settlement.ALREADY_DECIDED, current, current_status=current["status"]
        )


def action_proposer(pool: asyncpg.Pool):
    """The seam the agent loop calls when a model calls an action.

    Returns a coroutine function matching `loop.ActionProposer`: dry-run the
    action against the real arguments, then file the proposal carrying the card
    that dry run produced. Nothing here executes — this IS the round-trip S17
    deferred, and its whole output is a row with an id.
    """
    settlement = ProposalSettlement(pool)

    async def propose(*, spec: ActionSpec, arguments: dict, workspace_id, session_id=None):
        outcome = await spec.dry_run(workspace_id=workspace_id, **arguments)
        return await settlement.file(
            workspace_id=workspace_id,
            spec=spec,
            arguments=arguments,
            dry_run=outcome,
            session_id=session_id,
        )

    return propose


def check_executable(spec: ActionSpec, proposal: dict) -> None:
    """Everything that must still be true at execute time. Raises, never returns
    a bool — a caller cannot forget to look at an exception.

    Ordered cheapest-first, but every one of these is a separate guarantee:
    the approval happened, the risk is still what the gate saw, the declaration
    is still the one that was approved, and the target is ours to touch.
    """
    if proposal["status"] != "approved":
        raise ExecutionRefused(
            "not_approved",
            f"proposal is {proposal['status']}, not approved — only an approved "
            "proposal may execute",
        )

    # Re-run the D-014 gate on TODAY's declared risk. The approval was granted
    # under the risk shown on the card; if a deploy raised it, the human approved
    # something else.
    if gate(spec.risk).outcome is not PermissionOutcome.PROPOSE:
        raise ExecutionRefused(
            "risk_no_longer_gated",
            f"{spec.name} is now risk {spec.risk.value}, which does not require "
            "approval — the proposal was filed under a different declaration",
        )

    stored = proposal.get("spec_fingerprint")
    if not stored:
        raise ExecutionRefused(
            "no_fingerprint",
            "proposal carries no spec fingerprint, so what was approved cannot be "
            "identified — refusing rather than assuming it is unchanged",
        )
    current = fingerprint(spec)
    if stored != current:
        raise ExecutionRefused(
            "spec_changed",
            f"{spec.name} has changed since it was approved "
            f"({stored[:12]}… → {current[:12]}…) — re-propose it so a human "
            "approves what would actually run",
        )

    outside = sorted({s.system for s in spec.scope} - EXECUTABLE_SYSTEMS)
    if outside:
        raise ExecutionRefused(
            "system_not_executable",
            f"{spec.name} touches {', '.join(outside)}, which Auspex does not own — "
            "it may be proposed and approved, and it will not be run from here",
        )


class ActionExecutor:
    """Runs an approved action, and can put it back.

    Holds the registry and the pool; every state change goes through a status
    transition that is itself claim-first, so an execute cannot happen twice for
    the same reason an approval cannot.
    """

    def __init__(self, pool: asyncpg.Pool, registry: ActionRegistry) -> None:
        self._pool = pool
        self._registry = registry
        self._settlement = ProposalSettlement(pool)

    async def execute(
        self, *, workspace_id: UUID | str, proposal_id: UUID | str
    ) -> ActionOutcome:
        proposal = await self._settlement.get(
            workspace_id=workspace_id, proposal_id=proposal_id
        )
        if proposal is None:
            raise ExecutionRefused("not_found", "no such proposal in this workspace")
        spec = self._registry.get(proposal["tool_name"])
        if spec is None:
            raise ExecutionRefused(
                "unknown_action",
                f"{proposal['tool_name']!r} is not a registered action — it may have "
                "been removed since it was approved",
            )
        check_executable(spec, proposal)

        # Claim the run itself. Two callers hitting execute on one approved
        # proposal is the same race as two approvers, and gets the same answer.
        claimed = await self._pool.fetchrow(
            """
            UPDATE proposals SET status = 'executing'
             WHERE id = $1::uuid AND workspace_id = $2::uuid AND status = 'approved'
            RETURNING id
            """,
            str(proposal_id),
            str(workspace_id),
        )
        if claimed is None:
            raise ExecutionRefused(
                "already_running",
                "this proposal is already executing or has executed",
            )

        args = dict(proposal["tool_input"] or {})
        try:
            outcome = await spec.execute(
                workspace_id=workspace_id, proposal_id=str(proposal_id), **args
            )
        except Exception as exc:
            await self._pool.execute(
                """
                UPDATE proposals SET status = 'failed', result = $2::jsonb
                 WHERE id = $1::uuid
                """,
                str(proposal_id),
                json.dumps({"error": type(exc).__name__}),
            )
            raise
        await self._pool.execute(
            """
            UPDATE proposals SET status = 'executed', result = $2::jsonb
             WHERE id = $1::uuid
            """,
            str(proposal_id),
            json.dumps(_outcome_json(outcome)),
        )
        return outcome

    async def undo(self, *, workspace_id: UUID | str, proposal_id: UUID | str) -> ActionOutcome:
        """Put an executed action back.

        An undo that is declared and never run is a promise nobody checked, which
        is why TD-023 called this out and why the executed path ships with a test
        that actually runs it.
        """
        proposal = await self._settlement.get(
            workspace_id=workspace_id, proposal_id=proposal_id
        )
        if proposal is None:
            raise ExecutionRefused("not_found", "no such proposal in this workspace")
        if proposal["status"] != "executed":
            raise ExecutionRefused(
                "not_executed",
                f"proposal is {proposal['status']} — only an executed action can be undone",
            )
        spec = self._registry.get(proposal["tool_name"])
        if spec is None or spec.undo is None:
            raise ExecutionRefused(
                "no_undo",
                f"{proposal['tool_name']} declares no undo — it cannot be put back",
            )
        claimed = await self._pool.fetchrow(
            """
            UPDATE proposals SET status = 'undoing'
             WHERE id = $1::uuid AND workspace_id = $2::uuid AND status = 'executed'
            RETURNING id
            """,
            str(proposal_id),
            str(workspace_id),
        )
        if claimed is None:
            raise ExecutionRefused("already_undone", "this proposal is already being undone")
        args = dict(proposal["tool_input"] or {})
        try:
            outcome = await spec.undo.handler(
                workspace_id=workspace_id, proposal_id=str(proposal_id), **args
            )
        except Exception as exc:
            await self._pool.execute(
                """
                UPDATE proposals SET status = 'executed', undo_result = $2::jsonb
                 WHERE id = $1::uuid
                """,
                str(proposal_id),
                json.dumps({"error": type(exc).__name__}),
            )
            raise
        await self._pool.execute(
            """
            UPDATE proposals
               SET status = 'undone', undone_at = now(), undo_result = $2::jsonb
             WHERE id = $1::uuid
            """,
            str(proposal_id),
            json.dumps(_outcome_json(outcome)),
        )
        return outcome


def _outcome_json(outcome: ActionOutcome) -> dict:
    return {
        "would": outcome.would,
        "affects": list(outcome.affects),
        "reversible": outcome.reversible,
        "detail": dict(outcome.detail),
    }


__all__ = [
    "EXECUTABLE_SYSTEMS",
    "ActionExecutor",
    "ExecutionRefused",
    "ProposalSettlement",
    "SettleResult",
    "Settlement",
    "check_executable",
]
