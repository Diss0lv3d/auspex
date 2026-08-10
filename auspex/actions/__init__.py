"""Actions SDK — S17 (Phase 4).

The contract that lets the co-analyst ACT, and only the contract: an action can
be declared, registered and described to the planner, and nothing in this package
executes anything against a real system. Proposals and approvals are S18.

    from auspex.actions import ActionRegistry, ActionRisk, ActionScope, action

    @action(
        name="isolate_host",
        description="Isolate a host from the network at the EDR",
        risk=ActionRisk.DESTRUCTIVE,          # ⇒ undo is mandatory
        scope=[ActionScope(system="edr", writes=True)],
        params=[ActionParam("host_id", ParamType.STRING, "Short host id")],
        dry_run=would_isolate,                 # required, and never `execute`
        undo=UndoSpec("Release the host", release, restores="network connectivity"),
    )
    async def isolate_host(host_id: str) -> ActionOutcome: ...

    registry = ActionRegistry()
    registry.register(isolate_host)
    registry.manifest(agent_mode).directive()   # what the planner is told
"""

from auspex.actions.decorator import SPEC_ATTR, action, spec_of
from auspex.actions.registry import ActionManifest, ActionRegistry
from auspex.actions.types import (
    ActionOutcome,
    ActionParam,
    ActionRisk,
    ActionScope,
    ActionSpec,
    ActionSpecError,
    ParamType,
    UndoSpec,
    validate_spec,
)

__all__ = [
    "SPEC_ATTR",
    "ActionManifest",
    "ActionOutcome",
    "ActionParam",
    "ActionRegistry",
    "ActionRisk",
    "ActionScope",
    "ActionSpec",
    "ActionSpecError",
    "ParamType",
    "UndoSpec",
    "action",
    "spec_of",
    "validate_spec",
]
