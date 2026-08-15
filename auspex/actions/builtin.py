"""The actions Auspex can actually perform on itself — S18.

S18 is the first session where something really executes, and that is exactly why
this file is small. An action that touches a real external system needs a real
credential and a real blast radius; acquiring either as a side effect of the
session that builds the approval flow would be the wrong order. So the executor
allow-lists `auspex` (see `settlement.EXECUTABLE_SYSTEMS`) and the first real
action writes to a table we own.

`annotate_observable` is deliberately unglamorous and deliberately complete: it
writes state a colleague will read, it is gated (WRITE → the D-014 gate proposes
it), its dry run reports what it would write without writing it, and its undo
genuinely removes what it added. That last property is the point — TD-023's
complaint was that an undo declared and never run is a promise nobody checked, so
the first executable action ships with an undo the tests actually execute.

**The handlers close over their pool.** The first cut of this module kept it in a
module global, which a test caught immediately: two registries built against two
pools (the app's and a test's) silently shared the last one bound, and asyncpg
answered with "another operation is in progress" from two event loops. A factory
that returns specs bound to the pool it was handed has no such state, and it also
keeps the platform's pool out of the generic action signature — a third-party
action must not receive a handle to our database just by existing.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg

from auspex.actions.types import (
    ActionOutcome,
    ActionParam,
    ActionRisk,
    ActionScope,
    ActionSpec,
    ParamType,
    UndoSpec,
)

NOTE_SOURCE = "action:annotate_observable"
MAX_NOTE_CHARS = 2000


async def _resolve(pool: asyncpg.Pool, workspace_id: UUID | str, observable_id: str) -> dict | None:
    """Find the observable by its stable `obs_id`, inside this workspace only.

    D-008: tenancy is part of the lookup, not a check afterwards. An obs_id from
    another workspace resolves to nothing here, which is the same answer as one
    that does not exist — deliberately, because distinguishing them would leak
    the existence of another tenant's observable.
    """
    row = await pool.fetchrow(
        """
        SELECT id, obs_id, type, value FROM observables
        WHERE workspace_id = $1::uuid AND obs_id = $2
        """,
        str(workspace_id),
        observable_id,
    )
    return dict(row) if row else None


def _clean(note: str) -> str:
    """Analyst-supplied text, bounded and NUL-stripped before it reaches a row.

    Same posture as the S13 paste boundary: untrusted text is shaped where it
    ENTERS the system rather than where it is rendered.
    """
    text = note.replace("\x00", "").strip()
    if len(text) > MAX_NOTE_CHARS:
        text = text[:MAX_NOTE_CHARS].rstrip() + "…"
    return text


def annotate_observable_spec(pool: asyncpg.Pool) -> ActionSpec:
    """Build the annotate action bound to one pool."""

    async def would(*, workspace_id, observable_id: str, note: str, **_) -> ActionOutcome:
        """The dry run: resolve the target and say what would be written. Touches
        no state — the whole reason `dry_run` is required of every action."""
        target = await _resolve(pool, workspace_id, observable_id)
        text = _clean(note)
        if target is None:
            return ActionOutcome(
                would=f"Nothing: no observable {observable_id!r} in this workspace.",
                affects=(),
                reversible=True,
                detail={"resolved": False},
            )
        return ActionOutcome(
            would=(
                f"Attach an analyst note to {target['type']} {target['value']} "
                f"({len(text)} characters)."
            ),
            affects=(target["obs_id"],),
            reversible=True,
            detail={"resolved": True, "value": target["value"], "note": text},
        )

    async def run(*, workspace_id, proposal_id: str, observable_id: str, note: str, **_):
        target = await _resolve(pool, workspace_id, observable_id)
        if target is None:
            raise ValueError(f"no observable {observable_id!r} in this workspace")
        text = _clean(note)
        await pool.execute(
            """
            INSERT INTO observable_notes
                (workspace_id, observable_id, note, source, proposal_id)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5::uuid)
            """,
            str(workspace_id),
            str(target["id"]),
            text,
            NOTE_SOURCE,
            str(proposal_id),
        )
        return ActionOutcome(
            would=f"Attached an analyst note to {target['type']} {target['value']}.",
            affects=(target["obs_id"],),
            reversible=True,
            detail={"value": target["value"], "note": text},
        )

    async def put_back(*, workspace_id, proposal_id: str, observable_id: str, **_):
        """Remove exactly the notes this proposal created.

        Keyed on `proposal_id`, not on the note text or the observable: an undo
        that deleted "the notes on this observable" would delete a colleague's
        note that happened to arrive in between, which is a different action
        wearing an undo's clothes.
        """
        removed = await pool.fetch(
            """
            DELETE FROM observable_notes
             WHERE workspace_id = $1::uuid AND proposal_id = $2::uuid AND source = $3
            RETURNING id
            """,
            str(workspace_id),
            str(proposal_id),
            NOTE_SOURCE,
        )
        return ActionOutcome(
            would=f"Removed {len(removed)} note(s) this approval added.",
            affects=(observable_id,),
            reversible=True,
            detail={"removed": len(removed)},
        )

    return ActionSpec(
        name="annotate_observable",
        description="Attach an analyst note to an observable in this workspace",
        # WRITE, not READ: it changes state a colleague will read, so the D-014
        # gate must propose it. Not DESTRUCTIVE: it removes nothing, and
        # inflating risk to look careful would make that band mean less.
        risk=ActionRisk.WRITE,
        scope=(
            ActionScope(
                system="auspex",
                writes=True,
                detail="observable_notes in this workspace",
            ),
        ),
        params=(
            ActionParam("observable_id", ParamType.STRING, "The observable's short id"),
            ActionParam("note", ParamType.STRING, "The note to attach"),
        ),
        dry_run=would,
        execute=run,
        undo=UndoSpec(
            description="Remove the note this approval added",
            handler=put_back,
            restores="the observable's notes as they were before this action",
        ),
    )


def build_builtin_actions(pool: asyncpg.Pool) -> tuple[ActionSpec, ...]:
    """The actions this deployment can really run, bound to `pool`."""
    return (annotate_observable_spec(pool),)


__all__ = [
    "MAX_NOTE_CHARS",
    "NOTE_SOURCE",
    "annotate_observable_spec",
    "build_builtin_actions",
]
