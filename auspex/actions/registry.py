"""Action registry + planner manifest — S17.

The registry is where an action becomes visible to the agent loop, and it is the
second gate on the same rules the decorator already enforced: a spec that reached
here by any route other than `@action` meets an identical bar. Registration
FAILS — loudly, with the reason — rather than accepting an action and hoping the
loop is careful with it.

The manifest is what the loop is told it may propose, and it is compiled from the
capability the endpoint was MEASURED to have (`auspex/llm/scorecard.py`,
`decide_agent_mode`). Reusing that decision rather than inventing a second
manifest is deliberate: the platform already negotiates what a model can do, and
an actions surface that decided independently would be a second opinion about the
same endpoint — the failure mode D-022 exists to prevent for staleness and S16
Step 0 found in the falsifies link.

    native_tools    → wire specs. The model may CALL an action; the D-014 gate
                      turns every non-read call into a proposal.
    prompted_tools  → the same specs compiled to a text directive (D-007), for an
                      endpoint that cannot be trusted with the `tools` array.
    plan_only       → names and one-liners. The model may NAME an action in a
                      plan and cannot call one, because nothing is on the wire to
                      call.

In every mode the answer to "may the model perform this?" is no. The modes differ
in how an action is DESCRIBED, never in whether approval is required — that is
`auspex/agent/permissions.py`, and it reads the same `risk` this module carries.
"""

from __future__ import annotations

from collections.abc import Iterable

from auspex.actions.decorator import spec_of
from auspex.actions.types import (
    ActionRisk,
    ActionSpec,
    ActionSpecError,
    validate_spec,
)
from auspex.agent.permissions import PermissionOutcome, gate


class ActionRegistry:
    """Name → ActionSpec. Explicit registration, duplicate-safe, and it refuses
    anything the contract does not permit."""

    def __init__(self) -> None:
        self._actions: dict[str, ActionSpec] = {}
        # Which callable executes what, and which merely describes what would
        # happen. Kept because `dry_run is execute` inside one spec catches only
        # the copy-paste that names the SAME action twice — found by running the
        # contract in-container (S17) and passing another action's execute as a
        # dry_run, which the spec cannot see and this registry can.
        self._executes: dict[object, str] = {}
        self._dry_runs: dict[object, str] = {}

    def register(self, fn_or_spec: object) -> ActionSpec:
        """Register a decorated function or a bare spec. Returns the spec.

        Raises `ActionSpecError` for a duplicate name, for a function that is not
        an action, and for every spec rule in types.validate_spec — re-run here
        so this entry point cannot be more permissive than the decorator.
        """
        spec = fn_or_spec if isinstance(fn_or_spec, ActionSpec) else spec_of(fn_or_spec)
        if spec is None:
            raise ActionSpecError(
                f"{getattr(fn_or_spec, '__name__', fn_or_spec)!r} is not an action — "
                "decorate it with @action before registering it"
            )
        validate_spec(spec)
        if spec.name in self._actions:
            raise ActionSpecError(f"action {spec.name!r} already registered")

        # A dry run that is some OTHER action's execute would really perform that
        # action while reporting itself as a preview. Checked in both directions
        # so registration order cannot decide whether it is caught.
        owner = self._executes.get(spec.dry_run)
        if owner is not None:
            raise ActionSpecError(
                f"{spec.name}: dry_run is the execute handler of action {owner!r} — "
                "a dry run that performs another action is not a preview"
            )
        previewer = self._dry_runs.get(spec.execute)
        if previewer is not None:
            raise ActionSpecError(
                f"{spec.name}: its execute handler is already the dry_run of action "
                f"{previewer!r} — one of the two declarations is wrong"
            )

        self._actions[spec.name] = spec
        self._executes[spec.execute] = spec.name
        self._dry_runs[spec.dry_run] = spec.name
        return spec

    def register_all(self, fns: Iterable[object]) -> tuple[ActionSpec, ...]:
        """Register a batch. Not atomic on purpose: the first failure raises with
        the offending action named, and the ones already accepted stay — a
        half-registered surface that says which action broke is easier to fix
        than an empty one that does not."""
        return tuple(self.register(fn) for fn in fns)

    def get(self, name: str) -> ActionSpec | None:
        return self._actions.get(name)

    def names(self) -> list[str]:
        return list(self._actions)

    def risk(self, name: str) -> ActionRisk | None:
        spec = self._actions.get(name)
        return spec.risk if spec else None

    def requires_approval(self, name: str) -> bool:
        """Whether this action must become a proposal. Answered by the D-014 gate
        on the action's own risk — not by a second table here, and not by asking
        the model. An unknown action answers True: the gate fails safe, and so
        does a lookup miss."""
        return gate(self.risk(name)).outcome is PermissionOutcome.PROPOSE

    def __contains__(self, name: object) -> bool:
        return name in self._actions

    def __len__(self) -> int:
        return len(self._actions)

    # ── the planner manifest ─────────────────────────────────────────────────

    def manifest(self, agent_mode: str) -> ActionManifest:
        """What the loop may propose, in the form this endpoint can consume."""
        return ActionManifest(mode=agent_mode, actions=tuple(self._actions.values()))


class ActionManifest:
    """The compiled view of a registry for one agent mode.

    A class rather than a dict so the three renderings cannot drift apart: the
    wire specs, the prompt directive and the human-facing summary are all derived
    from the same `actions` tuple at the same moment.
    """

    def __init__(self, *, mode: str, actions: tuple[ActionSpec, ...]) -> None:
        self.mode = mode
        self.actions = actions

    def wire_specs(self) -> list[dict]:
        """Tool envelopes to put on the wire. EMPTY in plan_only — an endpoint
        that cannot be trusted to call tools is not handed a tools array, and a
        model that cannot call an action cannot mistakenly believe it did."""
        if self.mode != "native_tools":
            return []
        return [a.wire_spec for a in self.actions]

    def directive(self) -> str:
        """The system-prompt fragment describing the action surface (D-007:
        specs → prompts, exactly as ModeContract.system_directive does it).

        Rendered for prompted_tools and plan_only. In native_tools the wire specs
        carry the same descriptions, and repeating them in prose would be two
        copies of one contract — the thing this whole module is arranged to
        avoid."""
        if not self.actions:
            return (
                "No actions are available in this workspace. Say so plainly if the "
                "analyst asks for one; never describe an action as taken."
            )
        lines: list[str] = []
        if self.mode == "plan_only":
            lines.append(
                "You may NAME these actions in a plan for a human to run. You "
                "cannot perform them and no mechanism here will: describing one "
                "as done would be false."
            )
        else:
            lines.append(
                "You may PROPOSE these actions. A proposal is a request for human "
                "approval, not an execution — nothing happens until a person "
                "approves it, so never report an action as completed."
            )
        lines.append("")
        for a in self.actions:
            args = ", ".join(
                f"{p.name}: {p.type.value}{'' if p.required else '?'}" for p in a.params
            )
            lines.append(f"- {a.name}({args}) — {a.planner_description}")
        return "\n".join(lines)

    def summary(self) -> list[dict]:
        """Machine-readable, for a scorecard-style surface: what exists, how
        dangerous it is, and whether the platform can put it back. This is the
        row a capability panel renders next to the S13 model scorecard."""
        return [
            {
                "name": a.name,
                "risk": a.risk.value,
                "requires_approval": a.risk is not ActionRisk.READ,
                "reversible": a.reversible,
                "undo": a.undo.description if a.undo else None,
                "cannot_restore": list(a.undo.cannot_restore) if a.undo else [],
                "systems": [s.system for s in a.scope],
                "callable_by_model": self.mode == "native_tools",
            }
            for a in self.actions
        ]


__all__ = ["ActionManifest", "ActionRegistry"]
