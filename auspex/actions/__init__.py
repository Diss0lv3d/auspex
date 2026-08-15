"""Actions SDK — S17 (the contract) + S18 (the decision), Phase 4.

S17 made an action declarable: it can be declared, registered and described to
the planner, and the declaration is the source of truth for the wire schema, the
planner directive and the approval text (D-007, D-023).

S18 is where the declaration stops being a document. A proposal carries the card
a human sees and the IDENTITY of the declaration it was rendered from
(`proposal.py`); settlement claims the row before anything runs, and execution
re-checks both the D-014 gate and that identity before it touches anything
(`settlement.py`). What actually executes is limited to systems Auspex owns
(`builtin.py`) — anything reaching a third party stays proposal-only.

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
from auspex.actions.proposal import canonical_spec, card, fingerprint
from auspex.actions.registry import ActionManifest, ActionRegistry
from auspex.actions.settlement import (
    EXECUTABLE_SYSTEMS,
    STALE_CLAIM_SECONDS,
    ActionExecutor,
    ExecutionRefused,
    ProposalSettlement,
    Settlement,
    SettleResult,
    check_executable,
)
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
    "EXECUTABLE_SYSTEMS",
    "STALE_CLAIM_SECONDS",
    "SPEC_ATTR",
    "ActionExecutor",
    "ActionManifest",
    "ActionOutcome",
    "ActionParam",
    "ActionRegistry",
    "ActionRisk",
    "ActionScope",
    "ActionSpec",
    "ActionSpecError",
    "ExecutionRefused",
    "ParamType",
    "ProposalSettlement",
    "SettleResult",
    "Settlement",
    "UndoSpec",
    "action",
    "canonical_spec",
    "card",
    "check_executable",
    "fingerprint",
    "spec_of",
    "validate_spec",
]
