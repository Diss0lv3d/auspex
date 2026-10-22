"""S32 Task 8: a connector's manifest action compiles to today's ActionSpec (D-064).

The core side of a connector begins here. Nothing is dispatched for real (that is S33's
job runner): `dispatch` is a fake that records what it was asked to run and returns the
canned SDK envelope the reference connector's handlers return. What these tests hold:

- the compiled spec passes `validate_spec` unchanged, so the approvals contract (D-023,
  D-024) does not grow a connector-shaped exception;
- dry_run, execute, undo and observe are four distinct callables, each dispatching its own
  job kind, and validate_spec's identity rules can tell them apart;
- the fingerprint names the connector and the package hash (v2), while a stored v1
  fingerprint of an unchanged built-in is still reported as a scheme change.
"""

import dataclasses
import uuid
from pathlib import Path

import pytest
from auspex_sdk.build import load_manifest
from auspex_sdk.manifest import MAX_DESCRIPTION

from auspex.actions.builtin import annotate_observable_spec
from auspex.actions.proposal import (
    FINGERPRINT_VERSION,
    canonical_spec,
    fingerprint,
    matches_older_scheme,
)
from auspex.actions.types import (
    ActionOutcome,
    ActionRisk,
    ActionScope,
    ConnectorOrigin,
    ParamType,
    validate_spec,
)
from auspex.connectors.compile import ConnectorResultError, compile_action
from auspex.connectors.jobs import CONNECTOR_KINDS, ConnectorJobPayload

REFERENCE = Path(__file__).resolve().parents[1] / "examples/connectors/mock_siem/yaml"
HASH_A = "a" * 64
HASH_B = "b" * 64
INTEGRATION = uuid.UUID("00000000-0000-0000-0000-0000000000aa")

# The built-in annotate action's fingerprint, computed with the code as it stood BEFORE
# this change (FINGERPRINT_VERSION = 1, no `origin` in the canonical form). An approval
# filed before v2 deploys carries exactly this string.
ANNOTATE_V1 = "ff1f9d9a3399204fb56ba47433506e1856f9c3cd07c7c3e75b69e47951ae38d6"


def _envelope(would: str, *, status: str = "open") -> dict:
    return {"would": would, "affects": ["A-1"], "reversible": True, "detail": {"status": status}}


class FakeDispatch:
    """Records (kind, payload) and returns a canned result per kind."""

    def __init__(self, results: dict | None = None) -> None:
        self.calls: list[tuple[str, ConnectorJobPayload]] = []
        self.results = {
            "connector.action.dry_run": _envelope("close alert A-1"),
            "connector.action.execute": _envelope("closed alert A-1", status="closed"),
            "connector.action.undo": _envelope("reopen alert A-1"),
            "connector.action.observe": 1,
            **(results or {}),
        }

    async def __call__(self, kind: str, payload: ConnectorJobPayload):
        self.calls.append((kind, payload))
        return self.results[kind]


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(REFERENCE)


def _compile(manifest, dispatch, *, content_hash=HASH_A, prefix="siem1"):
    return compile_action(
        manifest, "close_alert", content_hash=content_hash, prefix=prefix,
        integration_id=INTEGRATION, dispatch=dispatch,
    )


def test_the_compiled_spec_passes_validate_spec(manifest):
    spec = _compile(manifest, FakeDispatch())
    validate_spec(spec)  # again, explicitly: construction already ran it
    assert spec.name == "siem1__close_alert"
    assert spec.risk is ActionRisk.WRITE
    assert spec.scope == (ActionScope(system="example.mock_siem", writes=True, detail="siem1"),)
    assert spec.origin == ConnectorOrigin("example.mock_siem", HASH_A)
    assert [(p.name, p.type, p.required) for p in spec.params] == [
        ("alert_id", ParamType.STRING, True),
        ("note", ParamType.STRING, False),
    ]
    assert spec.undo is not None
    assert spec.undo.restores == "the alert's open status"
    assert spec.undo.cannot_restore == ("the closing note, if the SIEM keeps one",)
    assert spec.description and len(spec.description) <= MAX_DESCRIPTION


async def test_four_distinct_callables_each_dispatch_their_own_kind(manifest):
    dispatch = FakeDispatch()
    spec = _compile(manifest, dispatch)
    handlers = [spec.dry_run, spec.execute, spec.undo.handler, spec.observe]
    assert len({id(h) for h in handlers}) == 4

    ws = uuid.uuid4()
    pid = uuid.uuid4()
    await spec.dry_run(workspace_id=ws, alert_id="A-1")
    await spec.execute(workspace_id=ws, proposal_id=str(pid),
                       idempotency_key=f"proposal:{pid}:execute", alert_id="A-1", note="fp")
    await spec.undo.handler(workspace_id=ws, proposal_id=str(pid),
                            idempotency_key=f"proposal:{pid}:undo", alert_id="A-1")
    await spec.observe(workspace_id=ws, proposal_id=str(pid),
                       idempotency_key=f"proposal:{pid}:execute", alert_id="A-1")

    assert [k for k, _ in dispatch.calls] == [
        "connector.action.dry_run",
        "connector.action.execute",
        "connector.action.undo",
        "connector.action.observe",
    ]
    assert all(k in CONNECTOR_KINDS for k, _ in dispatch.calls)
    dry, exe, und, obs = (p for _, p in dispatch.calls)
    for p in (dry, exe, und, obs):
        assert p.integration_id == INTEGRATION
        assert p.content_hash == HASH_A
        assert p.action == "close_alert"
        assert p.cursor is None and p.limit is None
    # `command` names the handler the agent runs inside the action, so the payload alone
    # says what to run; the kind says the same thing to the queue.
    assert [p.command for p in (dry, exe, und, obs)] == ["dry_run", "execute", "undo", "observe"]
    # A dry run is filed before there is a proposal, so it carries neither id nor key.
    assert dry.proposal_id is None and dry.idempotency_key is None
    assert dry.arguments == {"alert_id": "A-1"}
    assert exe.proposal_id == pid and exe.idempotency_key == f"proposal:{pid}:execute"
    assert exe.arguments == {"alert_id": "A-1", "note": "fp"}
    assert und.idempotency_key == f"proposal:{pid}:undo"
    assert obs.idempotency_key == f"proposal:{pid}:execute"


async def test_the_envelope_maps_to_an_action_outcome(manifest):
    spec = _compile(manifest, FakeDispatch())
    out = await spec.execute(workspace_id=uuid.uuid4(), proposal_id=str(uuid.uuid4()),
                             idempotency_key="k", alert_id="A-1")
    assert out == ActionOutcome(
        would="closed alert A-1", affects=("A-1",), reversible=True, detail={"status": "closed"}
    )
    assert await spec.observe(workspace_id=uuid.uuid4(), proposal_id=str(uuid.uuid4()),
                              idempotency_key="k", alert_id="A-1") == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"would": "x", "affects": "A-1", "reversible": True, "detail": {}},
        {"would": 3, "affects": [], "reversible": True, "detail": {}},
        {"would": "x", "affects": [], "reversible": "yes", "detail": {}},
        {"would": "x", "affects": [], "reversible": True, "detail": []},
        {"would": "x", "affects": [1], "reversible": True, "detail": {}},
        {"would": "x", "affects": []},
        "closed",
    ],
)
async def test_a_malformed_envelope_is_refused(manifest, bad):
    spec = _compile(manifest, FakeDispatch({"connector.action.dry_run": bad}))
    with pytest.raises(ConnectorResultError):
        await spec.dry_run(workspace_id=uuid.uuid4(), alert_id="A-1")


@pytest.mark.parametrize("bad", [True, -1, "1", None, 1.0])
async def test_observe_must_return_a_count(manifest, bad):
    spec = _compile(manifest, FakeDispatch({"connector.action.observe": bad}))
    with pytest.raises(ConnectorResultError):
        await spec.observe(workspace_id=uuid.uuid4(), proposal_id=str(uuid.uuid4()),
                           idempotency_key="k", alert_id="A-1")


@pytest.mark.parametrize("prefix", ["", "1siem", "siem-1", "siem 1", "π", "s" * 25, "siem\n"])
def test_a_prefix_that_is_not_a_short_wire_identifier_is_refused(manifest, prefix):
    with pytest.raises(ValueError):
        _compile(manifest, FakeDispatch(), prefix=prefix)


def test_a_24_character_prefix_is_accepted(manifest):
    spec = _compile(manifest, FakeDispatch(), prefix="s" * 24)
    assert spec.name == "s" * 24 + "__close_alert"


def test_an_unknown_action_is_refused(manifest):
    with pytest.raises(ValueError):
        compile_action(manifest, "nope", content_hash=HASH_A, prefix="siem1",
                       integration_id=INTEGRATION, dispatch=FakeDispatch())


def test_long_text_is_capped(manifest):
    long = "word " * 1000
    action = dataclasses.replace(manifest.actions[0], description=long)
    m = dataclasses.replace(manifest, actions=(action,))
    spec = _compile(m, FakeDispatch())
    assert len(spec.description) <= MAX_DESCRIPTION


def test_specs_differing_only_in_content_hash_have_different_fingerprints(manifest):
    a = _compile(manifest, FakeDispatch(), content_hash=HASH_A)
    b = _compile(manifest, FakeDispatch(), content_hash=HASH_B)
    assert canonical_spec(a)["origin"] == {"connector_id": "example.mock_siem",
                                           "content_hash": HASH_A}
    assert fingerprint(a) != fingerprint(b)
    # Under v1 the origin was not part of the identity, so the two were one.
    assert fingerprint(a, version=1) == fingerprint(b, version=1)


def test_a_builtin_v1_fingerprint_is_reported_as_a_scheme_change():
    """D-024's refusal path after the bump: an approval stored under v1 for an unchanged
    built-in is a scheme change (re-propose), not a changed action."""
    assert FINGERPRINT_VERSION == 2
    spec = annotate_observable_spec(None)  # the pool is only closed over, never touched here
    assert spec.origin is None
    assert canonical_spec(spec)["origin"] is None
    assert "origin" not in canonical_spec(spec, version=1)
    assert fingerprint(spec, version=1) == ANNOTATE_V1
    assert fingerprint(spec) != ANNOTATE_V1
    assert matches_older_scheme(spec, ANNOTATE_V1) == 1


def test_connector_kinds_are_the_six_the_spec_names():
    assert CONNECTOR_KINDS == (
        "connector.test",
        "connector.fetch",
        "connector.action.dry_run",
        "connector.action.execute",
        "connector.action.undo",
        "connector.action.observe",
    )
    assert [f.name for f in dataclasses.fields(ConnectorJobPayload)] == [
        "integration_id", "content_hash", "command", "action", "arguments",
        "proposal_id", "idempotency_key", "cursor", "limit",
    ]
