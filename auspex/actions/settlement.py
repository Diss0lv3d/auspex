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

# The statuses a put-back may start from (TD-028c): the action ran, or what it
# left behind is unknown. Not `failed` — that one looked and found nothing.
UNDOABLE_FROM = frozenset({"executed", "incomplete", "kept", "abandoned"})

# How long a proposal waits for a decision (TD-025, D-066; Burhan's call, S31:
# 24 h). Past it, approve and reject refuse it in the same UPDATE that would
# have settled it (the guarantee), and the row reads `expired`, moved there by
# the refusing door itself or by the `proposals.expire` job, whichever comes
# first (the visibility). An action proposed mid-incident and approved a day
# later is an approval of a world that has moved on.
PROPOSAL_TTL_SECONDS = 24 * 3600


def operation_key(proposal_id: UUID | str, operation: str) -> str:
    """The idempotency key of one operation on one proposal (TD-025, D-066;
    Burhan's call, S31). Stable across every attempt at that operation, so a
    re-run, a stale approval's run, or (S34) a re-claimed job hands the handler
    the same key, and the handler can drop the repeat. Derived, not stored."""
    if operation not in ("execute", "undo"):
        raise ValueError(f"unknown operation {operation!r}; an attempt executes or undoes")
    return f"proposal:{proposal_id}:{operation}"


class Settlement(StrEnum):
    """Why a settle attempt ended the way it did — distinguishable in code, so a
    caller never has to parse a message to know whether it lost a race."""

    CLAIMED = "claimed"  # this caller won the row
    ALREADY_DECIDED = "already_decided"  # someone else got there first
    NOT_FOUND = "not_found"  # no such proposal in this workspace
    EXPIRED = "expired"  # nobody decided within PROPOSAL_TTL_SECONDS


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

        Each pending row carries `identical_pending` (TD-028d): the other
        requests awaiting a decision in this workspace for the same action, with
        the same arguments, under the same declaration. Not a dedupe — whether a
        second identical intent was a mistake is the human's call (D-014) — but
        an approver must be able to see they are being asked twice. Only a
        pending row is looked up; every other row carries NULL, not an empty
        list, because nobody looked (S27 review of 0a5c5b1).

        An `incomplete` row belongs here as well (TD-028b): a run failed after
        some of its effects landed, or the action cannot look, and only a human
        can decide whether to put them back.

        So does an `approved` row that no run has claimed for longer than
        `STALE_CLAIM_SECONDS` (TD-042, D-048). The approve request runs the
        action a few awaits after settling it; a process that died in between,
        or an execute-time refusal (the declaration or risk changed), leaves the
        approval standing with nothing coming to move it. Its doors are
        `ActionExecutor.run_stale_approval` and `withdraw`.

        Deliberately NOT a reaper. A timer cannot know whether the handler ran
        before the process died, so anything it decided would be a guess: back
        to `approved` invites a second run of a half-run action, `failed` claims
        nothing happened, `executed` claims it did. D-014 reserves that
        judgement for the human, so the row is surfaced and `abandon` is theirs
        to call.

        An `expired` row is listed for PROPOSAL_TTL_SECONDS after it expired
        (Burhan's call, S31): a card that silently left the panel would read as
        an action that disappeared.
        """
        rows = await self._pool.fetch(
            """
            SELECT p.*,
                   CASE WHEN p.status = 'pending_approval' THEN ARRAY(
                       SELECT q.id FROM proposals q
                        WHERE q.workspace_id = p.workspace_id
                          AND q.status = 'pending_approval'
                          AND q.id <> p.id
                          AND q.tool_name = p.tool_name
                          AND md5(q.tool_input::text) = md5(p.tool_input::text)
                          AND q.tool_input = p.tool_input
                          AND q.spec_fingerprint IS NOT DISTINCT FROM p.spec_fingerprint
                        ORDER BY q.created_at
                        LIMIT 20
                   ) END AS identical_pending
              FROM proposals p
             WHERE p.workspace_id = $1::uuid
               AND (p.status IN ('pending_approval', 'incomplete')
                    OR (p.claimed_at IS NOT NULL
                        AND p.claimed_at < now() - make_interval(secs => $3::double precision))
                    OR (p.status = 'approved' AND p.claimed_at IS NULL
                        AND p.decided_at < now() - make_interval(secs => $3::double precision))
                    OR (p.status = 'expired'
                        AND p.resolved_at > now() - make_interval(secs => $4::double precision)))
             ORDER BY p.created_at DESC
             LIMIT $2
            """,
            str(workspace_id),
            limit,
            float(STALE_CLAIM_SECONDS),
            float(PROPOSAL_TTL_SECONDS),
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

        `abandoned_from` records WHICH operation was given up on (TD-034): the
        SET list reads the row as it was, so `status` there is the claim's —
        `executing` or `undoing` — at the instant it is replaced. And
        `abandoned_token` records WHICH CLAIM: the only one whose late answer
        may still land (S26 review of D-041).

        `decided_by` is the human abandoning, and it lands in `resolved_by`:
        `decided_by`/`decided_at` hold the APPROVAL, and before S27 this
        overwrote them, so an abandoned row no longer said who had approved the
        run that was lost.
        """
        row = await self._pool.fetchrow(
            """
            UPDATE proposals
               SET status = 'abandoned', abandoned_from = status,
                   abandoned_token = claim_token, claim_token = NULL, claimed_at = NULL,
                   resolved_at = now(), resolved_by = $3::uuid
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

    async def keep(
        self,
        *,
        workspace_id: UUID | str,
        proposal_id: UUID | str,
        decided_by: UUID | str | None,
    ) -> SettleResult:
        """A human looked at an incomplete run and keeps what landed.

        `incomplete` joined the queue with ONE door out — undo — so a human who
        wanted what landed to stay had no way to say so, and an action that
        declares no undo could never leave the queue at all (S26 review of
        D-041). This is that decision, claim-first like `settle` and `abandon`,
        recorded with who made it — in `resolved_by`, beside the approval rather
        than over it (S27 review: a kept row had stopped saying who approved the
        run). It is not a lock: a kept run can still be put back (UNDOABLE_FROM).
        """
        row = await self._pool.fetchrow(
            """
            UPDATE proposals
               SET status = 'kept', resolved_at = now(), resolved_by = $3::uuid
             WHERE id = $1::uuid AND workspace_id = $2::uuid AND status = 'incomplete'
            RETURNING *
            """,
            str(proposal_id),
            str(workspace_id),
            str(decided_by) if decided_by is not None else None,
        )
        if row is not None:
            return SettleResult(Settlement.CLAIMED, _as_dict(row))
        current = await self.get(workspace_id=workspace_id, proposal_id=proposal_id)
        if current is None:
            return SettleResult(Settlement.NOT_FOUND)
        return SettleResult(
            Settlement.ALREADY_DECIDED, current, current_status=current["status"]
        )

    async def withdraw(
        self,
        *,
        workspace_id: UUID | str,
        proposal_id: UUID | str,
        decided_by: UUID | str | None,
    ) -> SettleResult:
        """Retract an approval no run ever claimed (TD-042, D-048).

        Only once it is stale: within `STALE_CLAIM_SECONDS` the approve request's
        own run may still be about to claim it, and withdrawing it out from
        under that claim would turn a run into a refusal nobody asked for. No
        claim was ever taken, so nothing ran and there is nothing to put back.
        `withdrawn`, not `rejected`: the row WAS approved, and `decided_by`
        keeps saying by whom; the human withdrawing it lands in `resolved_by`.
        """
        row = await self._pool.fetchrow(
            """
            UPDATE proposals
               SET status = 'withdrawn', resolved_at = now(), resolved_by = $3::uuid
             WHERE id = $1::uuid AND workspace_id = $2::uuid
               AND status = 'approved' AND claimed_at IS NULL
               AND decided_at < now() - make_interval(secs => $4::double precision)
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

        **Only inside the TTL** (S31): the same WHERE refuses a proposal nobody
        decided within PROPOSAL_TTL_SECONDS, so the refusal never waits on the sweep.
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
               AND created_at > now() - make_interval(secs => $5::double precision)
            RETURNING *
            """,
            str(proposal_id),
            str(workspace_id),
            decision,
            str(decided_by) if decided_by is not None else None,
            float(PROPOSAL_TTL_SECONDS),
        )
        if row is not None:
            return SettleResult(Settlement.CLAIMED, _as_dict(row))
        # Lost, never existed, or too late. One more read to say WHICH — after
        # the fact, so it cannot widen the window that matters.
        current = await self.get(workspace_id=workspace_id, proposal_id=proposal_id)
        if current is None:
            return SettleResult(Settlement.NOT_FOUND)
        if current["status"] == "pending_approval":
            # Still pending, so the TTL refused it: the door that noticed records
            # it, by the sweep's own condition (S31).
            current = await self._expire_one(workspace_id, proposal_id) or await self.get(
                workspace_id=workspace_id, proposal_id=proposal_id)
            if current is None:
                return SettleResult(Settlement.NOT_FOUND)
        if current["status"] == "expired":
            return SettleResult(Settlement.EXPIRED, current, current_status="expired")
        return SettleResult(
            Settlement.ALREADY_DECIDED, current, current_status=current["status"]
        )

    async def _expire_one(self, workspace_id: UUID | str, proposal_id: UUID | str) -> dict | None:
        """One overdue pending proposal to `expired`: `expire_overdue`'s
        condition, for the row a decision just found too late."""
        return _as_dict(await self._pool.fetchrow(
            """
            UPDATE proposals SET status = 'expired', resolved_at = now()
             WHERE id = $1::uuid AND workspace_id = $2::uuid
               AND status = 'pending_approval'
               AND created_at <= now() - make_interval(secs => $3::double precision)
            RETURNING *
            """,
            str(proposal_id), str(workspace_id), float(PROPOSAL_TTL_SECONDS),
        ))

    async def expire_overdue(self, *, workspace_id: UUID | str) -> int:
        """The sweep (the `proposals.expire` job, S31): every proposal in this
        workspace nobody decided within the TTL becomes `expired`. The exact
        complement of `settle`'s TTL clause, so a row is never both decidable and
        expirable, and a retry changes nothing twice. `resolved_by` stays NULL:
        nobody decided; time did."""
        rows = await self._pool.fetch(
            """
            UPDATE proposals SET status = 'expired', resolved_at = now()
             WHERE workspace_id = $1::uuid AND status = 'pending_approval'
               AND created_at <= now() - make_interval(secs => $2::double precision)
            RETURNING id
            """,
            str(workspace_id), float(PROPOSAL_TTL_SECONDS),
        )
        return len(rows)


class NothingToPropose(RuntimeError):
    """The dry run says the action would change nothing, so no proposal is filed
    (D-045). `model_feedback` is the sentence the agent loop hands back to the
    model in place of a proposal id: code-written, and carrying the action's own
    dry-run sentence so the model can correct the call or say so."""

    def __init__(self, would: str) -> None:
        super().__init__(would)
        self.model_feedback = f"not proposed: the action would change nothing. {would}"


class UndeclaredArgument(NothingToPropose):
    """The call carries an argument key the action does not declare (B-026, S32).

    Refused, never stripped: dropping the key would file a card for a call the
    model did not make. A declined proposal like `NothingToPropose`, so the agent
    loop hands the model `model_feedback` (code-written, naming the keys) and no
    row exists. `names` is sorted so the sentence is stable."""

    def __init__(self, names) -> None:
        self.names = tuple(sorted(names))
        listed = ", ".join(self.names)
        RuntimeError.__init__(self, f"undeclared argument(s): {listed}")
        self.model_feedback = (
            f"not proposed: the action does not take argument(s) {listed}. "
            "Call it again with only the parameters it declares."
        )


def action_proposer(pool: asyncpg.Pool):
    """The seam the agent loop calls when a model calls an action.

    Returns a coroutine function matching `loop.ActionProposer`: dry-run the
    action against the real arguments, then file the proposal carrying the card
    that dry run produced. Nothing here executes — this IS the round-trip S17
    deferred, and its whole output is a row with an id.

    **A dry run that affects nothing is not filed** (D-045). Once the chat agent
    could call actions, an argument the workspace does not resolve (an
    observable it has never seen) would file a card a human can only reject and
    whose execution can only fail — a human's decision spent on nothing.
    """
    settlement = ProposalSettlement(pool)

    async def propose(*, spec: ActionSpec, arguments: dict, workspace_id, session_id=None):
        # B-026: before the dry run, which would swallow a stray key in `**_`, and
        # before any row. The approved run passes the platform's own keywords too,
        # so a key named like one of them would collide there.
        declared = {p.name for p in spec.params}
        undeclared = [k for k in arguments if k not in declared]
        if undeclared:
            raise UndeclaredArgument(undeclared)
        outcome = await spec.dry_run(workspace_id=workspace_id, **arguments)
        if not outcome.affects:
            raise NothingToPropose(outcome.would)
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
            UPDATE proposals
               SET status = 'executing', claimed_at = now(), claim_token = gen_random_uuid()
             WHERE id = $1::uuid AND workspace_id = $2::uuid AND status = 'approved'
            RETURNING claim_token
            """,
            str(proposal_id),
            str(workspace_id),
        )
        if claimed is None:
            raise ExecutionRefused(
                "already_running",
                "this proposal is already executing or has executed",
            )
        return await self._run_claimed(
            spec, proposal, claimed["claim_token"],
            workspace_id=workspace_id, proposal_id=proposal_id,
        )

    async def run_stale_approval(
        self,
        *,
        workspace_id: UUID | str,
        proposal_id: UUID | str,
        run_by: UUID | str | None,
    ) -> ActionOutcome:
        """Run an approval that no run ever started (TD-042, D-048).

        The row is `approved` with no claim, older than `STALE_CLAIM_SECONDS`:
        the process died between approve's settle and its run, or the run was
        refused at execute time. No claim was ever taken, so no handler ever
        started — there is nothing half-done to fear, and this is safe to run.

        It is the same run `approve` makes: `check_executable` again (the
        declaration and risk must still be the ones approved), then the claim,
        then the handler. What differs is the claim: only a STALE approval —
        within the threshold the approve request's own run may still be about
        to claim it — and it records the human pressing it now in
        `resolved_by`, because running an old approval is a decision made now.
        The approval stays in `decided_by`.
        """
        proposal = await self._settlement.get(
            workspace_id=workspace_id, proposal_id=proposal_id
        )
        if proposal is None:
            raise ExecutionRefused("not_found", "no such proposal in this workspace")
        if proposal["status"] != "approved":
            raise ExecutionRefused(
                "not_approved",
                f"proposal is {proposal['status']} — only an approval that no run has "
                "started can be run from here",
            )
        spec = self._registry.get(proposal["tool_name"])
        if spec is None:
            raise ExecutionRefused(
                "unknown_action",
                f"{proposal['tool_name']!r} is not a registered action — it may have "
                "been removed since it was approved",
            )
        check_executable(spec, proposal)
        claimed = await self._pool.fetchrow(
            """
            UPDATE proposals
               SET status = 'executing', claimed_at = now(), claim_token = gen_random_uuid(),
                   resolved_at = now(), resolved_by = $3::uuid
             WHERE id = $1::uuid AND workspace_id = $2::uuid
               AND status = 'approved' AND claimed_at IS NULL
               AND decided_at < now() - make_interval(secs => $4::double precision)
            RETURNING claim_token
            """,
            str(proposal_id),
            str(workspace_id),
            str(run_by) if run_by is not None else None,
            float(STALE_CLAIM_SECONDS),
        )
        if claimed is None:
            # Lost, or early. One more read to say which — after the fact, so it
            # cannot widen the window that matters.
            now = await self._settlement.get(workspace_id=workspace_id, proposal_id=proposal_id)
            if now is None:
                raise ExecutionRefused("not_found", "no such proposal in this workspace")
            if now["status"] == "approved":
                raise ExecutionRefused(
                    "not_stale",
                    f"approved less than {STALE_CLAIM_SECONDS}s ago — its own run may "
                    "still be starting; look again after that",
                )
            raise ExecutionRefused(
                "status_changed",
                f"the proposal moved from approved to {now['status']} while this run "
                "was starting — re-read it before deciding again",
            )
        return await self._run_claimed(
            spec, proposal, claimed["claim_token"],
            workspace_id=workspace_id, proposal_id=proposal_id,
        )

    async def _run_claimed(
        self, spec, proposal: dict, token, *, workspace_id, proposal_id
    ) -> ActionOutcome:
        """The handler, under a claim this caller holds, and the claim closed
        with what happened. Shared by `execute` and `run_stale_approval`, so the
        two doors cannot run an action two different ways."""
        args = dict(proposal["tool_input"] or {})
        try:
            outcome = await spec.execute(
                workspace_id=workspace_id, proposal_id=str(proposal_id),
                idempotency_key=operation_key(proposal_id, "execute"), **args
            )
        except Exception as exc:
            # TD-028b: a raise is not "nothing happened". The handler may have
            # written before it died, so ask the action what of THIS proposal's
            # exists. Only a look that found nothing earns `failed`.
            effects = await _effects(spec, workspace_id, proposal_id, args)
            await self._finish_claim(
                proposal_id,
                token,
                from_status="executing",
                to_status="failed" if effects == "none" else "incomplete",
                column="result",
                payload={"error": type(exc).__name__, "effects": effects},
            )
            raise
        await self._finish_claim(
            proposal_id,
            token,
            from_status="executing",
            to_status="executed",
            column="result",
            payload=_outcome_json(outcome),
        )
        return outcome

    async def _finish_claim(
        self,
        proposal_id: UUID | str,
        token: UUID,
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
        arriving late, which is strictly more than the human had before. Only
        the answer for the operation that WAS abandoned (TD-034): an undo's late
        answer on a row whose run was abandoned is an answer for an undo that
        never began.

        **Which claim is a TOKEN, not a status** (S26 review of D-041). Once
        undo could start from `abandoned`, two undos could be in flight on one
        row, and matching the claim by `status = 'undoing'` let an abandoned
        undo's late failure finish the FRESH undo's claim — the row went back
        to `executed` with the note already removed. The first statement now
        lands only for the claim that still holds the row; the late-write only
        for the claim a human abandoned (`abandoned_token`), into its own
        column if that is still empty, WHATEVER the row has become since — an
        `undone` row whose run answered late is a row that says so (D-041's
        stated bound, made visible instead of dropped).

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
                   claimed_at = NULL,
                   claim_token = NULL
             WHERE id = $1::uuid AND status = $4 AND claim_token = $7::uuid
            RETURNING id
            """,
            str(proposal_id),
            json.dumps(payload),
            to_status,
            from_status,
            is_result,
            stamp_undone_at,
            str(token),
        )
        if won is not None:
            return True
        await self._pool.execute(
            """
            UPDATE proposals
               SET result = CASE WHEN $3 THEN $2::jsonb ELSE result END,
                   undo_result = CASE WHEN $3 THEN undo_result ELSE $2::jsonb END
             WHERE id = $1::uuid
               AND abandoned_token = $4::uuid
               AND (CASE WHEN $3 THEN result ELSE undo_result END) IS NULL
            """,
            str(proposal_id),
            json.dumps(payload),
            is_result,
            str(token),
        )
        return False

    async def undo(self, *, workspace_id: UUID | str, proposal_id: UUID | str) -> ActionOutcome:
        """Put an action back — an executed one, or one whose effects are
        unknown (TD-028c).

        An undo that is declared and never run is a promise nobody checked, which
        is why TD-023 called this out and why the executed path ships with a test
        that actually runs it.

        **Where a put-back may start.** `executed` (the S18 path); `incomplete`,
        a run that failed after something of it landed or could not look
        (TD-028b); and `abandoned`, a claim a human gave up on, whose effects
        nobody knows. The last two are exactly the rows whose cleanup the old
        gate (`status = 'executed'`) shut — while `put_back`, keyed on the
        proposal, would have removed exactly the orphaned effects. Not
        `failed`: the action looked and nothing of it landed, so there is
        nothing to put back, and `undone` would report a put-back of nothing.

        **The claim moves the row only out of the status the read saw.** That
        status is also where a failed put-back RETURNS: before S26 every failed
        undo went back to `executed`, which for a cleanup of an incomplete run
        would claim a success that never happened.

        Bound, stated: a row abandoned during a run whose handler is merely slow
        (TD-028a) can be put back while that handler is still alive, and a write
        it lands afterwards outlives the undo. Abandon requires a claim older
        than STALE_CLAIM_SECONDS, and every action that can run today is a single
        local statement.
        """
        proposal = await self._settlement.get(
            workspace_id=workspace_id, proposal_id=proposal_id
        )
        if proposal is None:
            raise ExecutionRefused("not_found", "no such proposal in this workspace")
        was = proposal["status"]
        if was == "failed" and (proposal["result"] or {}).get("effects") == "none":
            raise ExecutionRefused(
                "nothing_to_undo",
                "the action failed and checked that nothing of it landed — there is "
                "nothing to put back",
            )
        # A `failed` row with no `effects` predates the look (written before
        # 203cccc): nothing was checked, so it is treated like `incomplete` —
        # the S19 reproduction of TD-028b is exactly such a row (S26 review).
        legacy_failure = was == "failed"
        if was not in UNDOABLE_FROM and not legacy_failure:
            raise ExecutionRefused(
                "not_executed",
                f"proposal is {was} — only an executed, incomplete, kept or "
                "abandoned action can be put back",
            )
        spec = self._registry.get(proposal["tool_name"])
        if spec is None or spec.undo is None:
            raise ExecutionRefused(
                "no_undo",
                f"{proposal['tool_name']} declares no undo — it cannot be put back",
            )
        # A fresh put-back starts with an empty answer: an earlier attempt's
        # result is not this attempt's (S26 review of D-041).
        claimed = await self._pool.fetchrow(
            """
            UPDATE proposals
               SET status = 'undoing', claimed_at = now(),
                   claim_token = gen_random_uuid(), undo_result = NULL
             WHERE id = $1::uuid AND workspace_id = $2::uuid AND status = $3
            RETURNING claim_token
            """,
            str(proposal_id),
            str(workspace_id),
            was,
        )
        if claimed is None:
            # Lost the row between the read and the claim. Since `keep` exists
            # that is not only another undo, so say where the row went rather
            # than assume (S27 review of 20fefc0) — after the fact, so it cannot
            # widen the window that matters.
            now = await self._settlement.get(workspace_id=workspace_id, proposal_id=proposal_id)
            if now is None:
                raise ExecutionRefused("not_found", "no such proposal in this workspace")
            if now["status"] == "undoing":
                raise ExecutionRefused("already_undone", "this proposal is already being undone")
            if now["status"] == "undone":
                raise ExecutionRefused("already_undone", "this proposal has already been undone")
            if now["status"] == was:
                # Taken and given back between the claim and this read — another
                # put-back that failed returns the row to where it started (S28
                # review of 94abbeb: this said "moved from X to X").
                raise ExecutionRefused(
                    "contended",
                    f"another operation held this proposal while this undo was starting; "
                    f"it is {was} again — try again",
                )
            raise ExecutionRefused(
                "status_changed",
                f"the proposal moved from {was} to {now['status']} while this undo was "
                "starting — re-read it before deciding again",
            )
        args = dict(proposal["tool_input"] or {})
        try:
            outcome = await spec.undo.handler(
                workspace_id=workspace_id, proposal_id=str(proposal_id),
                idempotency_key=operation_key(proposal_id, "undo"), **args
            )
        except Exception as exc:
            await self._finish_claim(
                proposal_id,
                claimed["claim_token"],
                from_status="undoing",
                to_status=was,
                column="undo_result",
                payload={"error": type(exc).__name__},
            )
            raise
        await self._finish_claim(
            proposal_id,
            claimed["claim_token"],
            from_status="undoing",
            to_status="undone",
            column="undo_result",
            payload=_outcome_json(outcome),
            stamp_undone_at=True,
        )
        return outcome


async def _effects(
    spec: ActionSpec, workspace_id: UUID | str, proposal_id: UUID | str, args: dict
) -> str:
    """What of one proposal's effects exist after its handler raised: 'none',
    'present', or 'unknown'. Unknown whenever the action cannot look, or the
    look itself fails — a failed look is not evidence of absence. It looks for the
    execute's effects, so it carries the execute's key."""
    if spec.observe is None:
        return "unknown"
    try:
        found = await spec.observe(
            workspace_id=workspace_id, proposal_id=str(proposal_id),
            idempotency_key=operation_key(proposal_id, "execute"), **args
        )
    except Exception:
        return "unknown"
    # "Nothing landed" is a claim, and only a count of zero makes it: a probe
    # that forgot its `return` gives None, which is falsy and would read as
    # `failed` while the write sits in the table (S26 review). bool is an int
    # subclass and is not a count either.
    if type(found) is not int or found < 0:
        return "unknown"
    return "present" if found > 0 else "none"


def _outcome_json(outcome: ActionOutcome) -> dict:
    return {
        "would": outcome.would,
        "affects": list(outcome.affects),
        "reversible": outcome.reversible,
        "detail": dict(outcome.detail),
    }


__all__ = [
    "EXECUTABLE_SYSTEMS",
    "PROPOSAL_TTL_SECONDS",
    "STALE_CLAIM_SECONDS",
    "UNDOABLE_FROM",
    "ActionExecutor",
    "ExecutionRefused",
    "NothingToPropose",
    "ProposalSettlement",
    "SettleResult",
    "Settlement",
    "UndeclaredArgument",
    "check_executable",
    "operation_key",
]
