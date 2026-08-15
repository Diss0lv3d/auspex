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

from auspex.actions import proposal as proposal_mod
from auspex.actions.proposal import card, fingerprint, matches_older_scheme
from auspex.actions.registry import ActionRegistry
from auspex.actions.types import ActionOutcome, ActionSpec
from auspex.agent.permissions import PermissionOutcome, gate

# Systems Auspex itself owns. An action whose scope names anything else may be
# proposed, approved and rendered — and will refuse to run, loudly. Widening this
# set is a decision with a blast radius, so it is a code change and a review.
EXECUTABLE_SYSTEMS = frozenset({"auspex"})

# How long a claim may be outstanding before a human is allowed to call it dead
# (TD-028a). Not a timeout on the action — nothing is cancelled when this
# elapses, and a slow handler that finishes at minute nine still lands its own
# terminal status. It is the age at which "still running" stops being the more
# likely explanation than "the process died", which is what makes the row worth
# a human's attention.
#
# Five minutes because every action that can run today is a single local
# statement against our own Postgres (EXECUTABLE_SYSTEMS is {"auspex"}), so the
# real distribution is milliseconds. The moment a network integration ships this
# wants to come from the action's own declaration instead of a module constant —
# a firewall rule change has a different honest ceiling than a note.
STALE_CLAIM_SECONDS = 300


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
        """Everything in this workspace that needs a human — which is not the
        same set as "everything pending approval" (TD-028a).

        A row whose claim is older than `STALE_CLAIM_SECONDS` belongs here too.
        The claim says a handler is running; if the process that took it died,
        nothing will ever move that row, and every door out is shut — `execute`
        refuses it as not_approved, `undo` as not_executed, `reject` as
        already_decided. Before S21 it was also invisible, so an approver simply
        watched the action disappear. It is a decision waiting on a human like
        any other, so it comes back from the same query rather than from a
        second endpoint nobody would call.

        Deliberately NOT a reaper. A timer cannot know whether the handler ran
        before the process died, so anything it decided would be a guess: back
        to `approved` invites a second run of a half-run action, `failed` claims
        nothing happened, `executed` claims it did. D-014 reserves that
        judgement for the human, so the row is surfaced and `abandon` is theirs
        to call.
        """
        rows = await self._pool.fetch(
            """
            SELECT * FROM proposals
            WHERE workspace_id = $1::uuid
              AND (status = 'pending_approval'
                   OR (claimed_at IS NOT NULL
                       AND claimed_at < now() - make_interval(secs => $3::double precision)))
            ORDER BY created_at DESC
            LIMIT $2
            """,
            str(workspace_id),
            limit,
            float(STALE_CLAIM_SECONDS),
        )
        return [_as_dict(r) for r in rows]

    async def abandon(
        self,
        *,
        workspace_id: UUID | str,
        proposal_id: UUID | str,
        decided_by: UUID | str | None,
    ) -> SettleResult:
        """A human declares a stale claim dead. Terminal, and honestly named.

        `abandoned` does not mean "it did not run" — nobody knows whether it
        ran, and that is precisely what the state records. The alternative was a
        status that asserts one of the two, which would be a lie half the time
        on a row that exists *because* the truth was lost.

        Guarded on age in the same statement that moves the row: a claim younger
        than the threshold belongs to a handler that is very likely still
        working, and killing it from under itself would manufacture the
        half-executed row this state exists to describe. Same claim-first device
        as `settle` — the WHERE clause is the whole guarantee.
        """
        row = await self._pool.fetchrow(
            """
            UPDATE proposals
               SET status = 'abandoned', claimed_at = NULL,
                   decided_at = now(), decided_by = $3::uuid
             WHERE id = $1::uuid
               AND workspace_id = $2::uuid
               AND claimed_at IS NOT NULL
               AND claimed_at < now() - make_interval(secs => $4::double precision)
            RETURNING *
            """,
            str(proposal_id),
            str(workspace_id),
            str(decided_by) if decided_by is not None else None,
            float(STALE_CLAIM_SECONDS),
        )
        if row is not None:
            return SettleResult(Settlement.CLAIMED, _as_dict(row))
        current = await self.get(workspace_id=workspace_id, proposal_id=proposal_id)
        if current is None:
            return SettleResult(Settlement.NOT_FOUND)
        return SettleResult(
            Settlement.ALREADY_DECIDED, current, current_status=current["status"]
        )

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
        # A mismatch alone cannot say WHY, and the two reasons want different
        # words. If this same unchanged spec hashed to `stored` under an older
        # FINGERPRINT_VERSION, the declaration never moved — we changed how we
        # identify declarations. Saying "the action changed" there would be
        # false, and an analyst who re-reads the card looking for the change
        # would find nothing (S19 Step-0 review, angle 2).
        older = matches_older_scheme(spec, stored)
        if older is not None:
            raise ExecutionRefused(
                "fingerprint_scheme_changed",
                f"{spec.name} itself is unchanged, but Auspex changed how it "
                f"identifies declarations (v{older} → v{proposal_mod.FINGERPRINT_VERSION}) "
                "after this was approved — re-propose it so the approval carries an "
                "identity this version can verify",
            )
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
            UPDATE proposals SET status = 'executing', claimed_at = now()
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
            await self._finish_claim(
                proposal_id,
                from_status="executing",
                to_status="failed",
                column="result",
                payload={"error": type(exc).__name__},
            )
            raise
        await self._finish_claim(
            proposal_id,
            from_status="executing",
            to_status="executed",
            column="result",
            payload=_outcome_json(outcome),
        )
        return outcome

    async def _finish_claim(
        self,
        proposal_id: UUID | str,
        *,
        from_status: str,
        to_status: str,
        column: str,
        payload: dict,
        stamp_undone_at: bool = False,
    ) -> bool:
        """Close out a claim — and only the claim this handler still holds.

        S22 review, measured: these four statements were `WHERE id = $1` with no
        status guard. That was harmless while the handler was the only writer,
        and TD-028a added a second one. `abandon` moves a claim older than
        `STALE_CLAIM_SECONDS`, and an old claim is not the same fact as a dead
        process — a handler that is merely SLOW gets abandoned and then returns.
        Probed: the row went `abandoned` -> `executed` while `decided_at` and
        `decided_by` still named the human who pressed abandon, so the audit
        trail asserted that a human had decided `executed`. On the failure path
        it is worse: `failed` is precisely the "nothing happened" claim the
        no-reaper design refuses to let a timer make, made here by a handler.

        The claim is the right to write the answer. When it has been taken, the
        answer is still recorded — on the row the human already owns, without
        moving it. `abandoned` says the answer was lost; this is that answer
        arriving late, which is strictly more than the human had before.

        Returns True if the claim was still held.
        """
        if column not in ("result", "undo_result"):
            raise ValueError(f"unknown result column {column!r}")
        # Which column to write is a PARAMETER, not string construction: this
        # module's contract is that no query in it is assembled from Python
        # strings (see the note above `_as_dict`), and a helper shared by four
        # call sites is exactly where that would otherwise start.
        is_result = column == "result"
        won = await self._pool.fetchrow(
            """
            UPDATE proposals
               SET status = $3,
                   result = CASE WHEN $5 THEN $2::jsonb ELSE result END,
                   undo_result = CASE WHEN $5 THEN undo_result ELSE $2::jsonb END,
                   undone_at = CASE WHEN $6 THEN now() ELSE undone_at END,
                   claimed_at = NULL
             WHERE id = $1::uuid AND status = $4
            RETURNING id
            """,
            str(proposal_id),
            json.dumps(payload),
            to_status,
            from_status,
            is_result,
            stamp_undone_at,
        )
        if won is not None:
            return True
        await self._pool.execute(
            """
            UPDATE proposals
               SET result = CASE WHEN $3 THEN $2::jsonb ELSE result END,
                   undo_result = CASE WHEN $3 THEN undo_result ELSE $2::jsonb END
             WHERE id = $1::uuid
               AND status = 'abandoned'
               AND (CASE WHEN $3 THEN result ELSE undo_result END) IS NULL
            """,
            str(proposal_id),
            json.dumps(payload),
            is_result,
        )
        return False

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
            UPDATE proposals SET status = 'undoing', claimed_at = now()
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
            await self._finish_claim(
                proposal_id,
                from_status="undoing",
                to_status="executed",
                column="undo_result",
                payload={"error": type(exc).__name__},
            )
            raise
        await self._finish_claim(
            proposal_id,
            from_status="undoing",
            to_status="undone",
            column="undo_result",
            payload=_outcome_json(outcome),
            stamp_undone_at=True,
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
    "STALE_CLAIM_SECONDS",
    "ActionExecutor",
    "ExecutionRefused",
    "ProposalSettlement",
    "SettleResult",
    "Settlement",
    "check_executable",
]
