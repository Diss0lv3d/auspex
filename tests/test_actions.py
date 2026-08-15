"""Actions SDK contract — S17 (Phase 4). Hermetic: no DB, no LLM, no network.

The contract is the whole deliverable this session, so these tests are the
deliverable's proof. They are arranged around the three things S17 claims:

1. an action can be DECLARED, REGISTERED and DESCRIBED to the planner;
2. a destructive action without an undo cannot be registered at all;
3. nothing in the SDK executes anything.

`dry_run` and `execute` handlers here are ordinary async functions — the point of
the decorator returning the function unchanged is that a test can call them
without going through a registry.
"""

from __future__ import annotations

import pytest

from auspex.actions import (
    ActionManifest,
    ActionOutcome,
    ActionParam,
    ActionRegistry,
    ActionRisk,
    ActionScope,
    ActionSpec,
    ActionSpecError,
    ParamType,
    UndoSpec,
    action,
    spec_of,
)
from auspex.agent.permissions import PermissionOutcome, gate
from auspex.agent.registry import ToolLevel

EDR = ActionScope(system="edr", writes=True, detail="host isolation API")
TICKETS = ActionScope(system="tickets", writes=True)


async def _would(**kwargs) -> ActionOutcome:
    return ActionOutcome(would="would isolate host h-1", affects=("h-1",), reversible=True)


async def _run(**kwargs) -> ActionOutcome:
    raise AssertionError("no test may execute an action — S17 ships the contract only")


async def _release(**kwargs) -> ActionOutcome:
    raise AssertionError("no test may execute an undo either")


async def _run_other(**kwargs) -> ActionOutcome:
    raise AssertionError("no test may execute a second action either")


RELEASE = UndoSpec(
    description="Release the host from isolation",
    handler=_release,
    restores="network connectivity for the host",
)


def _spec(**overrides) -> ActionSpec:
    """A legal destructive action, with one field replaceable per test."""
    kwargs = dict(
        name="isolate_host",
        description="Isolate a host from the network at the EDR",
        risk=ActionRisk.DESTRUCTIVE,
        scope=(EDR,),
        params=(ActionParam("host_id", ParamType.STRING, "Short host id"),),
        dry_run=_would,
        execute=_run,
        undo=RELEASE,
    )
    kwargs.update(overrides)
    return ActionSpec(**kwargs)


# -- 1. declare, register, describe --------------------------------------------


def test_an_action_declares_itself_and_stays_an_ordinary_function():
    @action(
        name="close_ticket",
        description="Close a ticket",
        risk=ActionRisk.WRITE,
        scope=[TICKETS],
        params=[ActionParam("ticket_id", ParamType.STRING, "Ticket id")],
        dry_run=_would,
    )
    async def close_ticket(ticket_id: str) -> ActionOutcome:
        return ActionOutcome(would="closed")

    spec = spec_of(close_ticket)
    assert spec is not None
    assert spec.name == "close_ticket" and spec.risk is ActionRisk.WRITE
    # The decorator returns the function, not a wrapper object: the SDK's own
    # tests reach the code they test without a registry in the way.
    assert callable(close_ticket)
    assert spec.execute is close_ticket


def test_registration_is_explicit_and_duplicate_safe():
    r = ActionRegistry()
    r.register(_spec())
    assert len(r) == 1 and "isolate_host" in r
    with pytest.raises(ActionSpecError, match="already registered"):
        r.register(_spec())


def test_a_plain_function_is_not_an_action():
    async def helpful(**kwargs):  # never decorated
        return None

    with pytest.raises(ActionSpecError, match="is not an action"):
        ActionRegistry().register(helpful)


def test_the_wire_schema_is_compiled_from_the_declaration():
    """One declaration, three consumers — and the envelope is built by the same
    `tool_spec` builder the capability probe measured, never hand-rolled."""
    spec = _spec(
        params=(
            ActionParam("host_id", ParamType.STRING, "Short host id"),
            ActionParam("reason", ParamType.STRING, "Why", required=False),
            ActionParam(
                "mode", ParamType.STRING, "How hard", enum=("soft", "full")
            ),
        )
    )
    envelope = spec.wire_spec
    assert envelope["type"] == "function"
    fn = envelope["function"]
    assert fn["name"] == "isolate_host"
    props = fn["parameters"]["properties"]
    assert props["host_id"] == {"type": "string", "description": "Short host id"}
    assert props["mode"]["enum"] == ["soft", "full"]
    # required follows the declaration, and the optional param is absent from it
    assert fn["parameters"]["required"] == ["host_id", "mode"]
    # the description the model reads is generated, so it cannot drift from risk
    assert "requires human approval" in fn["description"]
    assert "edr (writes)" in fn["description"]
    assert "Release the host" in fn["description"]


def test_a_partial_undo_names_what_it_cannot_restore():
    """An undo that silently fails to restore something is worse than no undo:
    the approval was granted on the strength of it."""
    spec = _spec(
        undo=UndoSpec(
            description="Re-enable the account",
            handler=_release,
            restores="the account's ability to sign in",
            cannot_restore=("active sessions killed at disable time",),
        )
    )
    assert "Undo does NOT restore: active sessions killed at disable time" in (
        spec.planner_description
    )
    # and the platform does not claim it can put this back
    assert not spec.reversible


# -- 2. the rail: registration FAILS ------------------------------------------


def test_a_destructive_action_without_an_undo_cannot_be_declared():
    """The rule this session exists to make cheap. Not a lint, not a review
    note — the spec cannot be constructed."""
    with pytest.raises(ActionSpecError, match="destructive actions require an undo"):
        _spec(undo=None)


def test_the_registry_refuses_it_too_by_any_other_route():
    """The decorator is not the only door. A spec built by another route meets an
    identical bar, because the registry re-runs the same validation."""
    smuggled = _spec()
    # forge a destructive spec with no undo, bypassing __post_init__
    object.__setattr__(smuggled, "undo", None)
    with pytest.raises(ActionSpecError, match="destructive actions require an undo"):
        ActionRegistry().register(smuggled)


def test_dry_run_is_required_of_everything():
    with pytest.raises(ActionSpecError, match="dry_run is required"):
        _spec(dry_run=None)


def test_a_dry_run_that_performs_the_action_is_not_a_dry_run():
    """The most likely way this guarantee gets quietly dropped: pass the same
    callable twice and the signature still looks satisfied."""
    with pytest.raises(ActionSpecError, match="same callable"):
        _spec(dry_run=_run)


def test_an_undo_cannot_be_the_action_itself():
    with pytest.raises(ActionSpecError, match="undo cannot be the action itself"):
        _spec(undo=UndoSpec("Re-run it", _run, restores="nothing really"))


def test_an_undo_must_say_what_it_restores():
    with pytest.raises(ActionSpecError, match="must say what it restores"):
        _spec(undo=UndoSpec("Something", _release, restores="   "))


def test_a_read_action_that_writes_is_refused():
    """The gate reads `risk` and nothing else (D-014), so a write mislabelled
    read would AUTO-EXECUTE. Caught where the two claims sit next to each other."""
    with pytest.raises(ActionSpecError, match="risk is read but scope"):
        _spec(risk=ActionRisk.READ, undo=None, scope=(EDR,))


def test_a_read_action_with_an_undo_is_probably_mislabelled():
    with pytest.raises(ActionSpecError, match="read action declared an undo"):
        _spec(risk=ActionRisk.READ, scope=(ActionScope("edr", writes=False),))


def test_an_action_must_name_a_system_it_touches():
    with pytest.raises(ActionSpecError, match="declare at least one scope"):
        _spec(scope=())


def test_an_action_name_must_survive_the_wire():
    with pytest.raises(ActionSpecError, match="must be a wire identifier"):
        _spec(name="isolate host!")
    # `str.isalnum()` is true for every unicode letter, so the original spelling
    # of this rule read as ASCII-only and was not (S18 Step 0).
    for bad in ("", "   ", "2fast", "isolate-host", "π"):
        with pytest.raises(ActionSpecError, match="must be a wire identifier"):
            _spec(name=bad)


def test_parameters_must_be_distinct_and_self_describing():
    with pytest.raises(ActionSpecError, match="duplicate parameter"):
        _spec(
            params=(
                ActionParam("host_id", ParamType.STRING, "one"),
                ActionParam("host_id", ParamType.STRING, "two"),
            )
        )
    with pytest.raises(ActionSpecError, match="must describe itself"):
        _spec(params=(ActionParam("host_id", ParamType.STRING, "  "),))
    with pytest.raises(ActionSpecError, match="enum is only meaningful"):
        _spec(params=(ActionParam("n", ParamType.INTEGER, "count", enum=("1", "2")),))


# -- 3. risk is the permission level, not a second opinion ---------------------


def test_action_risk_is_the_gate_s_own_vocabulary():
    """An action carrying a parallel notion of danger would be a second opinion
    about whether a human must approve it."""
    assert ActionRisk is ToolLevel


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        (ActionRisk.READ, PermissionOutcome.ALLOW),
        (ActionRisk.WRITE, PermissionOutcome.PROPOSE),
        (ActionRisk.DESTRUCTIVE, PermissionOutcome.PROPOSE),
    ],
)
def test_every_non_read_action_is_gated_into_a_proposal(risk, expected):
    assert gate(risk).outcome is expected


def test_the_registry_answers_approval_from_the_gate_and_fails_safe():
    r = ActionRegistry()
    r.register(_spec())
    assert r.requires_approval("isolate_host")
    # An action nobody registered is not a licence to act.
    assert r.requires_approval("no_such_action")


# -- the planner manifest (reusing the S13 capability decision) ----------------


def _registry() -> ActionRegistry:
    r = ActionRegistry()
    r.register(_spec())
    r.register(
        _spec(
            name="close_ticket",
            description="Close a ticket",
            risk=ActionRisk.WRITE,
            scope=(TICKETS,),
            undo=None,
            params=(ActionParam("ticket_id", ParamType.STRING, "Ticket id"),),
        )
    )
    return r


def test_native_tools_puts_actions_on_the_wire():
    m = _registry().manifest("native_tools")
    assert [s["function"]["name"] for s in m.wire_specs()] == ["isolate_host", "close_ticket"]
    assert all(row["callable_by_model"] for row in m.summary())


@pytest.mark.parametrize("mode", ["prompted_tools", "plan_only"])
def test_a_model_that_cannot_call_tools_is_handed_none(mode):
    """An endpoint the probe could not trust with the tools array does not get
    one — a model that cannot call an action cannot believe it did."""
    m = _registry().manifest(mode)
    assert m.wire_specs() == []
    assert not any(row["callable_by_model"] for row in m.summary())


def test_the_directive_is_compiled_from_the_same_specs():
    """D-007 in the shape S9 established: the spec generates the prompt."""
    d = _registry().manifest("prompted_tools").directive()
    assert "isolate_host(host_id: string)" in d
    assert "close_ticket(ticket_id: string)" in d
    assert "PROPOSE" in d and "never report an action as completed" in d


def test_plan_only_tells_the_model_it_cannot_act():
    d = _registry().manifest("plan_only").directive()
    assert "NAME these actions in a plan" in d
    assert "describing one as done would be false" in d


def test_an_empty_surface_says_so_rather_than_inventing_one():
    """The S16 lesson applied to a different absence: an empty action surface is
    a claim, and the honest version of it is stated."""
    d = ActionRegistry().manifest("native_tools").directive()
    assert "No actions are available" in d
    assert "never describe an action as taken" in d


def test_the_summary_is_what_a_capability_panel_renders():
    rows = {row["name"]: row for row in _registry().manifest("native_tools").summary()}
    assert rows["isolate_host"] == {
        "name": "isolate_host",
        "risk": "destructive",
        "requires_approval": True,
        "reversible": True,
        "undo": "Release the host from isolation",
        "cannot_restore": [],
        "systems": ["edr"],
        "callable_by_model": True,
    }
    # a write with no undo is honest about being one-way, and is still gated
    assert rows["close_ticket"]["requires_approval"] is True
    assert rows["close_ticket"]["reversible"] is False
    assert rows["close_ticket"]["undo"] is None


# -- nothing executes this session --------------------------------------------


def test_the_sdk_exposes_no_way_to_execute_an_action():
    """S17's hard constraint. The registry holds handlers so S18 can reach them
    through an approved proposal; it offers no method that runs one, and the
    manifest describes actions without invoking them."""
    forbidden = {"execute", "run", "perform", "invoke", "call", "apply"}
    for surface in (ActionRegistry, ActionManifest):
        assert not forbidden & {n for n in dir(surface) if not n.startswith("_")}, surface

    # Every handler in this module raises if called, and a full pass over the
    # registry + manifest touches none of them.
    m = _registry().manifest("native_tools")
    m.wire_specs()
    m.directive()
    m.summary()


def test_a_dry_run_that_is_another_action_s_execute_is_refused():
    """Found by running the contract in-container rather than by reading it: the
    spec's own `dry_run is execute` check sees one action at a time, so
    `dry_run=some_other_action` slips past it and would really perform that other
    action while reporting itself as a preview. The registry sees every spec."""
    r = ActionRegistry()
    r.register(_spec())  # isolate_host, execute=_run
    with pytest.raises(ActionSpecError, match="dry_run is the execute handler of action"):
        r.register(
            _spec(
                name="close_ticket",
                risk=ActionRisk.WRITE,
                scope=(TICKETS,),
                undo=None,
                dry_run=_run,  # the previously registered action's execute
                execute=_would,
            )
        )


def test_the_same_confusion_is_caught_in_the_other_order():
    """Registration order must not decide whether a mistake is found."""
    r = ActionRegistry()
    r.register(_spec(dry_run=_would, execute=_run))
    with pytest.raises(ActionSpecError, match="already the dry_run of action"):
        r.register(
            _spec(
                name="close_ticket",
                risk=ActionRisk.WRITE,
                scope=(TICKETS,),
                undo=None,
                execute=_would,  # the previously registered action's dry_run
                dry_run=_release,
            )
        )


def test_two_actions_may_share_a_dry_run():
    """Not every collision is a mistake: a shared "would do nothing" preview is a
    legitimate pattern, and only execute-vs-dry_run confusion is dangerous.

    This test used `_release` — the FIRST action's undo handler — as the second
    action's execute, which is the hazard S18 Step 0 found rather than the
    sharing this test is about (undoing the isolation would have closed a
    ticket). A distinct callable keeps the stated point and drops the accident.
    """
    r = ActionRegistry()
    r.register(_spec(dry_run=_would))
    r.register(
        _spec(
            name="close_ticket",
            risk=ActionRisk.WRITE,
            scope=(TICKETS,),
            undo=None,
            dry_run=_would,
            execute=_run_other,
        )
    )
    assert len(r) == 2


# -- S18 Step 0: the slots S17's rails did not cover ---------------------------
#
# Every refusal in `validate_spec` is a claim that something cannot be built, so
# Step 0 tried to build each one. Three got through, all confirmed by RUNNING the
# result rather than by reading it (probe: docs/probes/2026-08-15-s18-step0-review.md).


def test_an_undo_that_is_this_actions_own_dry_run_is_refused():
    """`undo.handler is execute` was the only guard on the undo slot, so an undo
    that was the action's own dry_run registered happily — reported
    `reversible=True`, put "Undo: ..." in front of an approver, and then restored
    nothing when run, because not doing anything is a dry run's whole job.

    Same shape as the `dry_run=another_action` case S17 caught by execution: the
    dangerous value is a legal callable that reads correctly at the call site."""
    with pytest.raises(ActionSpecError, match="undo.handler is this action's dry_run"):
        _spec(undo=UndoSpec(description="put it back", handler=_would, restores="connectivity"))


def test_an_undo_may_not_be_another_actions_execute():
    """Verified by execution before it was fixed: registering this and then
    calling `isolate_host`'s undo really ran `close_ticket`'s execute. A spec
    sees one action, so only the registry can catch it."""
    r = ActionRegistry()
    r.register(
        _spec(
            name="close_ticket",
            risk=ActionRisk.WRITE,
            scope=(TICKETS,),
            undo=None,
            dry_run=_would,
            execute=_run_other,
        )
    )
    with pytest.raises(ActionSpecError, match="undo.handler is the execute handler"):
        r.register(
            _spec(undo=UndoSpec(description="reconnect", handler=_run_other, restores="network"))
        )


def test_an_undo_may_not_be_another_actions_dry_run():
    """The quieter half: this one performs nothing at all, reports success, and
    the approval it unlocked was granted on its strength."""
    r = ActionRegistry()
    r.register(
        _spec(
            name="close_ticket",
            risk=ActionRisk.WRITE,
            scope=(TICKETS,),
            undo=None,
            dry_run=_run_other,
            execute=_release,
        )
    )
    with pytest.raises(ActionSpecError, match="undo.handler is the dry_run of action"):
        r.register(
            _spec(
                dry_run=_would,
                execute=_run,
                undo=UndoSpec(description="reconnect", handler=_run_other, restores="network"),
            )
        )


def test_a_later_action_may_not_claim_a_handler_an_undo_depends_on():
    """Registration order must not decide whether the collision is caught — the
    same reasoning S17 applied to dry_run/execute in both directions."""
    r = ActionRegistry()
    r.register(_spec())  # its undo is _release
    with pytest.raises(ActionSpecError, match="already the undo of action"):
        r.register(
            _spec(
                name="close_ticket",
                risk=ActionRisk.WRITE,
                scope=(TICKETS,),
                undo=None,
                dry_run=_would,
                execute=_release,  # the undo isolate_host promised its approver
            )
        )


def test_parameter_names_must_survive_the_wire_too():
    """The action NAME was checked because "it is a tool name on the wire"; a
    parameter name is a JSON-schema property key on the SAME wire and was checked
    by nothing. All of these reached `wire_spec` and landed in `properties` AND
    `required` — a model cannot reliably emit an argument named ''."""
    for bad in ("", "   ", "host id", "host-id", "π", "2fast"):
        with pytest.raises(ActionSpecError, match="must be a wire identifier"):
            _spec(params=(ActionParam(bad, ParamType.STRING, "the host"),))


def test_a_legal_parameter_name_still_compiles_to_the_wire():
    """The rail must not have eaten the ordinary case."""
    spec = _spec(
        params=(
            ActionParam("host_id", ParamType.STRING, "Short host id"),
            ActionParam("_internal2", ParamType.INTEGER, "Second one"),
        )
    )
    props = spec.wire_spec["function"]["parameters"]["properties"]
    assert set(props) == {"host_id", "_internal2"}
