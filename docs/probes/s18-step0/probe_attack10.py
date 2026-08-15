"""Re-run of attack 10 with GENUINELY distinct callables — the first version
shared `_exec` between the two specs, so it tripped the "undo cannot be the
action itself" rail and never tested the cross-action case at all.
"""

import asyncio
import sys

sys.path.insert(0, ".")

from auspex.actions import ActionRegistry
from auspex.actions.types import (
    ActionOutcome,
    ActionParam,
    ActionRisk,
    ActionScope,
    ActionSpec,
    ActionSpecError,
    ParamType,
    UndoSpec,
)

RAN = []


def mk(tag):
    async def dry(**kw):
        RAN.append(f"{tag}:dry")
        return ActionOutcome(would=f"{tag} would run")

    async def ex(**kw):
        RAN.append(f"{tag}:EXECUTE")
        return ActionOutcome(would=f"{tag} ran")

    async def un(**kw):
        RAN.append(f"{tag}:undo")
        return ActionOutcome(would=f"{tag} undone")

    return dry, ex, un


d1, e1, u1 = mk("delete_file")
d2, e2, u2 = mk("isolate_host")


def spec(name, dry, ex, undo_handler, restores="the state"):
    return ActionSpec(
        name=name,
        description=f"{name} does a thing",
        risk=ActionRisk.DESTRUCTIVE,
        scope=(ActionScope(system="edr", writes=True),),
        params=(ActionParam("target", ParamType.STRING, "the target"),),
        dry_run=dry,
        execute=ex,
        undo=UndoSpec(description="put it back", handler=undo_handler, restores=restores),
    )


print("[10-redo] undo.handler is ANOTHER action's execute (distinct callables)")
r = ActionRegistry()
r.register(spec("delete_file", d1, e1, u1))
try:
    # isolate_host's "undo" is delete_file's EXECUTE
    r.register(spec("isolate_host", d2, e2, e1))
    print("    >>> NOT REFUSED — isolate_host registered with delete_file's execute as its undo")
    asyncio.run(r.get("isolate_host").undo.handler())
    print(f"    running that undo actually ran: {RAN[-1]}")
    print("    => 'undoing' an isolation DELETES A FILE. The registry tracks")
    print("       dry_run/execute collisions across specs but never undo.handler.")
except ActionSpecError as e:
    print(f"    REFUSED: {e}")

print("\n[10b] undo.handler is another action's DRY_RUN (silently restores nothing)")
r2 = ActionRegistry()
r2.register(spec("delete_file", d1, e1, u1))
try:
    r2.register(spec("isolate_host", d2, e2, d1))
    print("    >>> NOT REFUSED — the undo is delete_file's dry_run: it previews and returns")
    RAN.clear()
    asyncio.run(r2.get("isolate_host").undo.handler())
    print(f"    running that undo actually ran: {RAN}  (nothing was restored)")
except ActionSpecError as e:
    print(f"    REFUSED: {e}")

print("\n[9-confirm] undo.handler is the action's OWN dry_run")
try:
    s = spec("quarantine", d2, e2, d2)
    print(f"    >>> NOT REFUSED — reversible={s.reversible}, "
          f"planner advertises an undo={'Undo:' in s.planner_description}")
    RAN.clear()
    asyncio.run(s.undo.handler())
    print(f"    the 'undo' ran: {RAN} — a PREVIEW, reported to the approver as reversal")
except ActionSpecError as e:
    print(f"    REFUSED: {e}")
