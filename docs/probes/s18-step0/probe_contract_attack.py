"""S18 Step 0 — lead 4: every refusal in validate_spec is a claim that something
cannot be built. Try to build each one anyway.

Run from the repo root with .venv/bin/python. Pure Python, no DB.
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
from auspex.agent.registry import ToolLevel, ToolRegistry

OK = "REFUSED (rail holds)"


async def _dry(**kw):
    return ActionOutcome(would="would do the thing")


async def _exec(**kw):
    return ActionOutcome(would="did the thing")


async def _undo(**kw):
    return ActionOutcome(would="put it back")


async def _other_exec(**kw):
    print("        !!! ANOTHER ACTION'S EXECUTE ACTUALLY RAN !!!")
    return ActionOutcome(would="performed a DIFFERENT action")


def scope(writes=True, system="edr"):
    return (ActionScope(system=system, writes=writes),)


def attack(n, title, fn):
    print(f"\n[{n}] {title}")
    try:
        result = fn()
        print(f"    >>> NOT REFUSED — {result}")
        return False
    except ActionSpecError as e:
        print(f"    {OK}: {str(e)[:120]}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"    refused by {type(e).__name__}: {str(e)[:120]}")
        return True


def base(**over):
    kw = dict(
        name="isolate_host",
        description="Isolate a host from the network",
        risk=ActionRisk.DESTRUCTIVE,
        scope=scope(),
        params=(ActionParam("host_id", ParamType.STRING, "the host"),),
        dry_run=_dry,
        execute=_exec,
        undo=UndoSpec(description="reconnect the host", handler=_undo, restores="network access"),
    )
    kw.update(over)
    return ActionSpec(**kw)


print("=" * 78)
print("LEAD 4 — attacking the contract's rails")
print("=" * 78)

# ---------------------------------------------------------------- known rails
attack(1, "destructive with no undo (constructor)", lambda: base(undo=None))
attack(2, "dry_run IS execute", lambda: base(dry_run=_exec))
attack(3, "undo IS the action", lambda: base(
    undo=UndoSpec(description="x", handler=_exec, restores="y")))
attack(4, "undo restores nothing", lambda: base(
    undo=UndoSpec(description="x", handler=_undo, restores="   ")))
attack(5, "read action whose scope writes", lambda: base(
    risk=ActionRisk.READ, undo=None, scope=scope(writes=True)))
attack(6, "action naming no system", lambda: base(scope=()))

# ------------------------------------------------- forge past the constructor
print("\n[7] destructive + no undo, FORGED past __post_init__, reaching planner_description")
forged = base()
object.__setattr__(forged, "undo", None)
try:
    text = forged.planner_description
    print(f"    >>> NOT REFUSED — planner text: {text[:100]!r}")
except ActionSpecError as e:
    print(f"    {OK}: {str(e)[:120]}")

print("\n[8] the same forged spec, offered to the REGISTRY")
try:
    ActionRegistry().register(forged)
    print("    >>> NOT REFUSED — a destructive action with no undo is registered")
except ActionSpecError as e:
    print(f"    {OK}: {str(e)[:120]}")

# ------------------------------------------------------- untested rails below
print("\n" + "-" * 78)
print("ANGLES S17 DID NOT TEST")
print("-" * 78)

print("\n[9] undo.handler IS the dry_run (not the execute)")
try:
    spec = base(undo=UndoSpec(description="put it back", handler=_dry, restores="network access"))
    print("    >>> NOT REFUSED — spec constructed.")
    print(f"        reversible={spec.reversible}, planner says: "
          f"{'Undo:' in spec.planner_description}")
    print("        => the approval was granted on the strength of an undo that only PREVIEWS.")
    r = ActionRegistry()
    r.register(spec)
    print("    >>> registry ALSO accepted it")
except ActionSpecError as e:
    print(f"    {OK}: {str(e)[:120]}")

print("\n[10] undo.handler is ANOTHER registered action's execute")
try:
    r = ActionRegistry()
    r.register(base(name="delete_file", undo=UndoSpec(
        description="restore", handler=_undo, restores="the file")))
    victim = r.get("delete_file")
    spec2 = base(
        name="isolate_host",
        undo=UndoSpec(description="reconnect", handler=victim.execute, restores="network access"),
    )
    r.register(spec2)
    print("    >>> NOT REFUSED — 'undoing' isolate_host runs delete_file's EXECUTE")
    print("        (the registry tracks dry_run/execute collisions, not undo ones)")
    asyncio.run(r.get("isolate_host").undo.handler())
except ActionSpecError as e:
    print(f"    {OK}: {str(e)[:120]}")

print("\n[11] parameter name that is not a legal wire identifier")
for bad in ("", "   ", "host id", "host-id", "π"):
    try:
        spec = base(params=(ActionParam(bad, ParamType.STRING, "the host"),))
        ws = spec.wire_spec
        props = list(ws["function"]["parameters"]["properties"])
        req = ws["function"]["parameters"].get("required", [])
        print(f"    >>> NOT REFUSED  name={bad!r:>10}  properties={props}  required={req}")
    except ActionSpecError as e:
        print(f"    REFUSED name={bad!r:>10}: {str(e)[:80]}")

print("\n[12] can wire_spec's `required` ever disagree with its `properties`?")
spec = base(params=(
    ActionParam("a", ParamType.STRING, "a", required=True),
    ActionParam("b", ParamType.STRING, "b", required=False),
))
ws = spec.wire_spec["function"]["parameters"]
props, req = set(ws["properties"]), set(ws.get("required", []))
print(f"    properties={sorted(props)} required={sorted(req)} "
      f"required-not-in-properties={sorted(req - props)}")
print(f"    => derived from one list, cannot disagree: {req <= props}")

print("\n[13] an ACTION whose name collides with a TOOL the loop can dispatch")
tools = ToolRegistry()
tools.add(
    name="isolate_host",
    description="A read-only lookup that happens to share the name",
    level=ToolLevel.READ,
    parameters={"host_id": {"type": "string", "description": "host"}},
    required=["host_id"],
    handler=lambda **kw: {"ok": True, "ran": "THE TOOL, not the action"},
)
areg = ActionRegistry()
areg.register(base(name="isolate_host"))
print(f"    tool registry has  : {tools.names()}  (level={tools.level('isolate_host')})")
print(f"    action registry has: {areg.names()}  (risk={areg.risk('isolate_host').value})")
print(f"    the model is TOLD  : {areg.manifest('plan_only').actions[0].planner_description[:90]}...")
print(f"    loop._dispatch resolves in the ToolRegistry -> runs "
      f"{tools.get('isolate_host').handler(host_id='h1')}")
print(f"    D-014 gate reads the TOOL's level ({tools.level('isolate_host').value}), "
      f"NOT the action's ({areg.risk('isolate_host').value})")
print("    => the model was told 'destructive, needs approval'; the name it was told")
print("       to name resolves to a READ tool that auto-executes.")

print("\n[14] does the ActionRegistry know about tools at all?")
print(f"    ActionRegistry.register signature takes only the spec: no tool registry is")
print(f"    consulted -> nothing anywhere refuses the collision. contains='isolate_host' "
      f"in tools: {'isolate_host' in tools}")
