"""Approval flow — S18 (Phase 4), against live Postgres (compose dev DB).

S17 shipped a contract in which nothing executed. This is the session where a
human decides and something happens, so these tests are arranged around the four
claims S18 makes:

1. a proposal can be approved EXACTLY once, proven by racing it;
2. what the approver sees is compiled from the spec, not from model prose;
3. an approved action re-checks BOTH permission and the spec before running;
4. an executed action can be put back — by a test that actually runs the undo.

The action under test is `annotate_observable`, which writes to a table we own.
That is the point rather than a shortcut: an action reaching a third party needs
a real credential and a real blast radius, so the executor allow-lists `auspex`
and everything else stays proposal-only.
"""

import asyncio
import dataclasses
import json
import uuid
from unittest import mock

import pytest

from auspex.actions import (
    STALE_CLAIM_SECONDS,
    ActionExecutor,
    ActionOutcome,
    ActionParam,
    ActionRegistry,
    ActionRisk,
    ActionScope,
    ActionSpec,
    ActionSpecError,
    ExecutionRefused,
    ParamType,
    ProposalSettlement,
    Settlement,
    UndoSpec,
    canonical_spec,
    card,
    check_executable,
    fingerprint,
)
from auspex.actions import proposal as proposal_mod
from auspex.actions.builtin import NOTE_SOURCE, build_builtin_actions
from auspex.classify.observables import ObservableType, observable_id
from auspex.db import create_pool
from auspex.routes import proposals as proposals_route


@pytest.fixture
async def pool(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    yield pool
    await pool.close()


@pytest.fixture
async def workspace_id(pool):
    ws = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        "t-settlement",
    )
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


@pytest.fixture
async def other_workspace_id(pool):
    ws = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        "t-settlement-other",
    )
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


@pytest.fixture
async def an_observable(pool, workspace_id):
    """One real observable to annotate."""
    value = "evil-settlement.test"
    obs_id = observable_id(ObservableType.DOMAIN, value)
    await pool.execute(
        """
        INSERT INTO observables (workspace_id, obs_id, type, value)
        VALUES ($1, $2, 'domain', $3)
        ON CONFLICT (workspace_id, type, value) DO NOTHING
        """,
        workspace_id,
        obs_id,
        value,
    )
    return obs_id


@pytest.fixture
def registry(pool):
    r = ActionRegistry()
    r.register_all(build_builtin_actions(pool))
    return r


@pytest.fixture
def spec(registry):
    return registry.get("annotate_observable")


async def _file(pool, registry, spec, workspace_id, obs_id, note="looks like a staging domain"):
    """File a proposal the way the surface does: dry-run first, card from the
    spec, then persist."""
    settlement = ProposalSettlement(pool)
    args = {"observable_id": obs_id, "note": note}
    dry = await spec.dry_run(workspace_id=workspace_id, **args)
    return settlement, await settlement.file(
        workspace_id=workspace_id, spec=spec, arguments=args, dry_run=dry
    )


# -- 1. exactly once ----------------------------------------------------------


async def test_two_approvers_one_proposal_exactly_one_execution(
    pool, registry, spec, workspace_id, an_observable
):
    """The claim wins the row before anything runs. Eight concurrent approvals of
    one proposal: exactly one may be told it succeeded.

    This is the D-001 reason Postgres holds truth. A read-then-write would pass
    this test most of the time, which is precisely why the guarantee has to be in
    the WHERE clause instead of in the sequence of statements."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)

    results = await asyncio.gather(
        *[
            settlement.settle(
                workspace_id=workspace_id,
                proposal_id=proposal["id"],
                decision="approved",
                decided_by=None,
            )
            for _ in range(8)
        ]
    )
    winners = [r for r in results if r.won]
    losers = [r for r in results if not r.won]
    assert len(winners) == 1, [r.outcome for r in results]
    assert len(losers) == 7
    # and every loser is TOLD it lost, with the status that beat it
    assert all(r.outcome is Settlement.ALREADY_DECIDED for r in losers)
    assert all(r.current_status == "approved" for r in losers)
    # the row itself agrees
    row = await settlement.get(workspace_id=workspace_id, proposal_id=proposal["id"])
    assert row["status"] == "approved" and row["decided_at"] is not None


async def test_a_rejected_proposal_cannot_then_be_approved(
    pool, registry, spec, workspace_id, an_observable
):
    """Settlement is terminal in both directions — the loser of a reject/approve
    race is not special-cased into a second chance."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    first = await settlement.settle(
        workspace_id=workspace_id,
        proposal_id=proposal["id"],
        decision="rejected",
        decided_by=None,
    )
    assert first.won
    second = await settlement.settle(
        workspace_id=workspace_id,
        proposal_id=proposal["id"],
        decision="approved",
        decided_by=None,
    )
    assert not second.won and second.current_status == "rejected"


async def test_settlement_is_scoped_to_the_workspace(
    pool, registry, spec, workspace_id, other_workspace_id, an_observable
):
    """D-008: another tenant cannot settle this proposal, and does not learn that
    it exists — the same answer as a proposal that never existed."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    result = await settlement.settle(
        workspace_id=other_workspace_id,
        proposal_id=proposal["id"],
        decision="approved",
        decided_by=None,
    )
    assert result.outcome is Settlement.NOT_FOUND
    assert await settlement.get(
        workspace_id=other_workspace_id, proposal_id=proposal["id"]
    ) is None


# -- 2. the card is compiled from the spec ------------------------------------


async def test_the_card_says_what_the_action_would_do_from_its_own_declaration(
    pool, registry, spec, workspace_id, an_observable
):
    """D-007/D-023: every field an approver reads comes from the spec or from the
    action's own dry run against the REAL arguments. No model text anywhere."""
    _, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    stored = proposal["card"]

    assert stored["action"] == "annotate_observable"
    assert stored["risk"] == "write" and stored["requires_approval"] is True
    # what it would do, generated by the action against the real target
    assert "evil-settlement.test" in stored["summary"]
    assert stored["affects"] == [an_observable]
    # the systems it touches, named for the human consenting to them
    assert stored["systems"] == [
        {"system": "auspex", "writes": True, "detail": "observable_notes in this workspace"}
    ]
    # whether it can be taken back, and what the undo does NOT cover
    assert stored["reversible"] is True
    assert stored["undo"]["restores"].startswith("the observable's notes")
    assert stored["undo"]["cannot_restore"] == []
    # and the identity of the declaration this card was rendered from
    assert stored["spec_fingerprint"] == fingerprint(spec)


async def test_the_dry_run_wrote_nothing(pool, registry, spec, workspace_id, an_observable):
    """`dry_run` is required of every action precisely so this is checkable: the
    card exists and the note does not."""
    await _file(pool, registry, spec, workspace_id, an_observable)
    assert 0 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE workspace_id = $1", workspace_id
    )


async def test_a_partial_undo_reaches_the_card_as_not_reversible():
    """An action whose undo names what it cannot restore must not present itself
    as fully reversible at the moment someone is deciding — the card reads the
    SPEC's answer, not the outcome's optimistic default."""

    async def would(**kw):
        return ActionOutcome(would="would disable the account", reversible=True)

    async def run(**kw):  # pragma: no cover — never executed here
        raise AssertionError

    async def put_back(**kw):  # pragma: no cover
        raise AssertionError

    partial = ActionSpec(
        name="disable_account",
        description="Disable a user account",
        risk=ActionRisk.DESTRUCTIVE,
        scope=(ActionScope("idp", writes=True),),
        params=(ActionParam("user", ParamType.STRING, "the user"),),
        dry_run=would,
        execute=run,
        undo=UndoSpec(
            description="Re-enable the account",
            handler=put_back,
            restores="the account's ability to sign in",
            cannot_restore=("sessions killed at disable time",),
        ),
    )
    rendered = card(partial, arguments={"user": "u1"}, dry_run=await would())
    assert rendered["reversible"] is False
    assert rendered["undo"]["cannot_restore"] == ["sessions killed at disable time"]


# -- 3. the re-check at execute time ------------------------------------------


async def test_an_unapproved_proposal_cannot_execute(
    pool, registry, spec, workspace_id, an_observable
):
    _, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    with pytest.raises(ExecutionRefused) as err:
        await ActionExecutor(pool, registry).execute(
            workspace_id=workspace_id, proposal_id=proposal["id"]
        )
    assert err.value.reason == "not_approved"


async def test_an_action_approved_under_a_different_declaration_refuses_to_run(
    pool, registry, spec, workspace_id, an_observable
):
    """TD-023, the item this session owes: an hour can pass between the approval
    and the run, and a deploy can change the action in between. The approval was
    a decision about a specific declaration, so the fingerprint on the row must
    still match the one the registry holds."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    await settlement.settle(
        workspace_id=workspace_id,
        proposal_id=proposal["id"],
        decision="approved",
        decided_by=None,
    )
    # the deploy: same name, same handlers, but the undo no longer restores what
    # the approver was told it would
    changed = ActionSpec(
        name=spec.name,
        description=spec.description,
        risk=spec.risk,
        scope=spec.scope,
        params=spec.params,
        dry_run=spec.dry_run,
        execute=spec.execute,
        undo=UndoSpec(
            description=spec.undo.description,
            handler=spec.undo.handler,
            restores=spec.undo.restores,
            cannot_restore=("anything a colleague edited afterwards",),
        ),
    )
    assert fingerprint(changed) != fingerprint(spec)
    deployed = ActionRegistry()
    deployed.register(changed)

    with pytest.raises(ExecutionRefused) as err:
        await ActionExecutor(pool, deployed).execute(
            workspace_id=workspace_id, proposal_id=proposal["id"]
        )
    assert err.value.reason == "spec_changed"
    # and nothing was written
    assert 0 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE workspace_id = $1", workspace_id
    )


# ── S19 Step-0 review: the fingerprint's two blind spots ─────────────────────


def test_canonical_spec_covers_every_declared_field(spec):
    """The identity's field list is hand-written, and until S19 nothing enforced
    that. Verified by execution then: adding a field to `ActionSpec` left the
    fingerprint BYTE-IDENTICAL, so an approver could be shown a changed
    declaration while the execute-time re-check called it unchanged
    (docs/probes/2026-08-15-s19-step0-review.md §1).

    The comment said a new field "must be considered here on purpose". This is
    what makes that true: every declared field must appear in the canonical form
    or be named here as deliberately excluded. Adding a field now fails this test
    by name, which is the whole point — the decision still gets made by a human,
    it just cannot be made by forgetting.
    """
    canon = canonical_spec(spec)

    # Handlers are excluded on purpose: we cannot detect that someone changed
    # what a function BODY does, and pretending otherwise would make the check
    # look stronger than it is (proposal.py module docstring).
    # `observe` (S26, TD-028b) is a handler too: it says how to LOOK at effects,
    # and what it looks at is already declared by `scope`.
    assert {f.name for f in dataclasses.fields(ActionSpec)} - {
        "dry_run", "execute", "observe"
    } == (
        set(canon) - {"v"}
    )
    assert {f.name for f in dataclasses.fields(ActionParam)} == set(canon["params"][0])
    assert {f.name for f in dataclasses.fields(ActionScope)} == set(canon["scope"][0])
    assert {f.name for f in dataclasses.fields(UndoSpec)} - {"handler"} == set(canon["undo"])


def test_a_version_bump_is_reported_as_a_version_bump_not_a_changed_action(spec):
    """`FINGERPRINT_VERSION` has never been bumped, and S19 established what
    happens when it is: every approved-but-unexecuted proposal refuses, and the
    copy told the analyst the ACTION had changed when only our hashing had.

    Recoverable either way — re-propose — but a false reason sends someone
    diffing an action that never moved. The declaration is unchanged here; only
    the scheme is, and the refusal must say so.
    """
    stored_under_v1 = fingerprint(spec, version=1)
    with mock.patch.object(proposal_mod, "FINGERPRINT_VERSION", 2):
        assert fingerprint(spec) != stored_under_v1
        assert proposal_mod.matches_older_scheme(spec, stored_under_v1) == 1
        with pytest.raises(ExecutionRefused) as err:
            check_executable(spec, {"status": "approved", "spec_fingerprint": stored_under_v1})

    assert err.value.reason == "fingerprint_scheme_changed"
    assert "itself is unchanged" in err.value.detail
    assert "v1 → v2" in err.value.detail


def test_a_genuinely_changed_spec_is_still_reported_as_changed(spec):
    """The version-aware branch must not swallow the case it sits in front of:
    a spec that really did change, under the SAME version, still says so."""
    changed = ActionSpec(
        name=spec.name,
        description="a different declaration entirely",
        risk=spec.risk,
        scope=spec.scope,
        params=spec.params,
        dry_run=spec.dry_run,
        execute=spec.execute,
        undo=spec.undo,
    )
    with pytest.raises(ExecutionRefused) as err:
        check_executable(changed, {"status": "approved", "spec_fingerprint": fingerprint(spec)})
    assert err.value.reason == "spec_changed"
    assert proposal_mod.matches_older_scheme(changed, fingerprint(spec)) is None


def test_an_action_the_gate_would_auto_execute_is_refused_at_run_time():
    """The permission half of the same re-check. A declaration that is now READ
    would not be proposed at all today — so the approval on the row was granted
    under a different rule, and running it would launder a gate change into an
    execution."""

    async def would(**kw):
        return ActionOutcome(would="x")

    async def run(**kw):  # pragma: no cover
        raise AssertionError

    now_read = ActionSpec(
        name="annotate_observable",
        description="Attach a note",
        risk=ActionRisk.READ,
        scope=(ActionScope("auspex", writes=False),),
        params=(),
        dry_run=would,
        execute=run,
    )
    with pytest.raises(ExecutionRefused) as err:
        check_executable(
            now_read,
            {"status": "approved", "spec_fingerprint": fingerprint(now_read)},
        )
    assert err.value.reason == "risk_no_longer_gated"


def test_an_action_touching_a_system_we_do_not_own_never_executes():
    """S18's blast-radius rule, in code rather than in a comment. It may be
    declared, proposed, approved and rendered — it will not be run from here."""

    async def would(**kw):
        return ActionOutcome(would="would isolate the host")

    async def run(**kw):  # pragma: no cover
        raise AssertionError("a third-party system must never be reached in S18")

    async def release(**kw):  # pragma: no cover
        raise AssertionError

    edr = ActionSpec(
        name="isolate_host",
        description="Isolate a host at the EDR",
        risk=ActionRisk.DESTRUCTIVE,
        scope=(ActionScope("edr", writes=True),),
        params=(),
        dry_run=would,
        execute=run,
        undo=UndoSpec("Release the host", release, restores="network connectivity"),
    )
    with pytest.raises(ExecutionRefused) as err:
        check_executable(edr, {"status": "approved", "spec_fingerprint": fingerprint(edr)})
    assert err.value.reason == "system_not_executable"


# -- 4. it really runs, and it really comes back ------------------------------


async def test_an_approved_action_executes_and_the_undo_actually_runs(
    pool, registry, spec, workspace_id, an_observable
):
    """The whole session in one test: propose → approve → execute → undo, with
    the state checked after each step.

    TD-023 said an undo that is declared and never exercised is a promise nobody
    checked. This runs it."""
    settlement, proposal = await _file(
        pool, registry, spec, workspace_id, an_observable, note="staging domain, not malicious"
    )
    pid = proposal["id"]

    approved = await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    assert approved.won

    executor = ActionExecutor(pool, registry)
    outcome = await executor.execute(workspace_id=workspace_id, proposal_id=pid)
    assert "evil-settlement.test" in outcome.would

    notes = await pool.fetch(
        "SELECT note, source, proposal_id FROM observable_notes WHERE workspace_id = $1",
        workspace_id,
    )
    assert len(notes) == 1
    assert notes[0]["note"] == "staging domain, not malicious"
    assert notes[0]["source"] == NOTE_SOURCE
    assert str(notes[0]["proposal_id"]) == str(pid)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "executed" and row["result"]["would"]

    # ── and back again ──
    undone = await executor.undo(workspace_id=workspace_id, proposal_id=pid)
    assert undone.detail["removed"] == 1
    assert 0 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE workspace_id = $1", workspace_id
    )
    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "undone" and row["undone_at"] is not None


async def test_execution_cannot_happen_twice(
    pool, registry, spec, workspace_id, an_observable
):
    """The same claim-first device guards the run itself: two callers hitting
    execute on one approved proposal is the same race as two approvers."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    executor = ActionExecutor(pool, registry)
    results = await asyncio.gather(
        *[executor.execute(workspace_id=workspace_id, proposal_id=pid) for _ in range(5)],
        return_exceptions=True,
    )
    ran = [r for r in results if isinstance(r, ActionOutcome)]
    refused = [r for r in results if isinstance(r, ExecutionRefused)]
    assert len(ran) == 1, results
    assert len(refused) == 4
    # one note, not five
    assert 1 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE workspace_id = $1", workspace_id
    )


async def test_the_undo_removes_only_what_this_approval_added(
    pool, registry, spec, workspace_id, an_observable
):
    """An undo that deleted "the notes on this observable" would delete a
    colleague's note that arrived in between — a different action wearing an
    undo's clothes. Keyed on the proposal, so it removes exactly its own."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    executor = ActionExecutor(pool, registry)
    await executor.execute(workspace_id=workspace_id, proposal_id=pid)

    # a human writes their own note on the same observable, afterwards
    obs_uuid = await pool.fetchval(
        "SELECT id FROM observables WHERE workspace_id = $1 AND obs_id = $2",
        workspace_id,
        an_observable,
    )
    await pool.execute(
        """
        INSERT INTO observable_notes (workspace_id, observable_id, note, source)
        VALUES ($1, $2, 'a colleague typed this', 'human')
        """,
        workspace_id,
        obs_uuid,
    )

    await executor.undo(workspace_id=workspace_id, proposal_id=pid)
    left = await pool.fetch(
        "SELECT note, source FROM observable_notes WHERE workspace_id = $1", workspace_id
    )
    assert len(left) == 1
    assert left[0]["source"] == "human"


async def test_an_undo_cannot_run_before_an_execution(
    pool, registry, spec, workspace_id, an_observable
):
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    await settlement.settle(
        workspace_id=workspace_id,
        proposal_id=proposal["id"],
        decision="approved",
        decided_by=None,
    )
    with pytest.raises(ExecutionRefused) as err:
        await ActionExecutor(pool, registry).undo(
            workspace_id=workspace_id, proposal_id=proposal["id"]
        )
    assert err.value.reason == "not_executed"


# -- 5. the analyst surface ---------------------------------------------------

ROUTE_EMAIL = "analyst@auspex.dev"


def _hdr(client) -> dict:
    token = client.post("/api/auth/dev-login", json={"email": ROUTE_EMAIL}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def route_ws(pool, client):
    """The default workspace the dev login lands in, cleaned around the test.

    Provisioned here rather than SELECTed. It used to be a bare SELECT with an
    `assert ws is not None`, which passed only because a developer's long-lived
    dev database already had a `default` workspace from some earlier login: the
    fixture runs BEFORE the test body calls `_hdr()`, so on a fresh database
    nothing had created it yet. Three tests errored on the first CI run against
    an empty Postgres and were green on every laptop.

    Same get-or-create as `auth.py:135`, so the fixture provisions it exactly
    the way a real dev-login does instead of inventing a second shape.
    """
    ws = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ('default')"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
    )
    assert ws is not None
    value = "route-settlement.test"
    obs_id = observable_id(ObservableType.DOMAIN, value)
    await pool.execute(
        """
        INSERT INTO observables (workspace_id, obs_id, type, value)
        VALUES ($1, $2, 'domain', $3)
        ON CONFLICT (workspace_id, type, value) DO NOTHING
        """,
        ws,
        obs_id,
        value,
    )
    yield ws, obs_id
    await pool.execute(
        "DELETE FROM observables WHERE workspace_id = $1 AND value = $2", ws, value
    )
    await pool.execute("DELETE FROM proposals WHERE workspace_id = $1", ws)


async def test_the_approval_surface_carries_the_card_and_settles_once(
    pool, client, route_ws
):
    """The analyst's round trip: see what is waiting, approve it, and get back
    both the settlement and what actually happened."""
    ws, obs_id = route_ws
    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    spec = registry.get("annotate_observable")
    settlement, proposal = await _file(pool, registry, spec, ws, obs_id, note="route note")

    hdr = _hdr(client)
    listed = client.get("/api/proposals", headers=hdr).json()
    mine = [p for p in listed["proposals"] if p["id"] == str(proposal["id"])]
    assert len(mine) == 1
    card_seen = mine[0]["card"]
    assert card_seen["risk"] == "write"
    assert "route-settlement.test" in card_seen["summary"]
    assert card_seen["systems"][0]["system"] == "auspex"
    assert card_seen["reversible"] is True

    approved = client.post(f"/api/proposals/{proposal['id']}/approve", headers=hdr)
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["settled"] == "approved" and body["executed"] is True
    assert "route-settlement.test" in body["outcome"]["did"]
    assert body["proposal"]["status"] == "executed"

    # the note is really there
    assert 1 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid",
        str(proposal["id"]),
    )

    # a second approval is a 409, not a second execution
    again = client.post(f"/api/proposals/{proposal['id']}/approve", headers=hdr)
    assert again.status_code == 409
    assert "already" in again.json()["detail"]
    assert 1 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid",
        str(proposal["id"]),
    )

    # and it can be put back through the surface
    undone = client.post(f"/api/proposals/{proposal['id']}/undo", headers=hdr)
    assert undone.status_code == 200, undone.text
    assert undone.json()["proposal"]["status"] == "undone"
    assert 0 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid",
        str(proposal["id"]),
    )


async def test_rejecting_never_executes(pool, client, route_ws):
    ws, obs_id = route_ws
    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    spec = registry.get("annotate_observable")
    _, proposal = await _file(pool, registry, spec, ws, obs_id)

    hdr = _hdr(client)
    out = client.post(f"/api/proposals/{proposal['id']}/reject", headers=hdr)
    assert out.status_code == 200 and out.json()["settled"] == "rejected"
    assert 0 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE workspace_id = $1", ws
    )
    # and an approve afterwards cannot resurrect it
    assert client.post(f"/api/proposals/{proposal['id']}/approve", headers=hdr).status_code == 409


async def test_the_card_stream_replays_what_is_already_waiting(
    pool, client, route_ws, monkeypatch
):
    """Approval cards over SSE: a client that connects late is not told the queue
    is empty. One frame per waiting card, same single-key protocol as chat.

    The stream's lifetime is bounded in code, so this shortens it rather than
    relying on `is_disconnected()` — which is exactly the condition the bound
    exists because we cannot rely on."""
    monkeypatch.setattr(proposals_route, "STREAM_MAX_TICKS", 1)
    monkeypatch.setattr(proposals_route, "STREAM_POLL_SECONDS", 0.05)
    ws, obs_id = route_ws
    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    spec = registry.get("annotate_observable")
    _, proposal = await _file(pool, registry, spec, ws, obs_id, note="streamed")

    frames = []
    with client.stream("GET", "/api/proposals/stream", headers=_hdr(client)) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            frame = json.loads(line[6:])
            assert "proposal" in frame, frame
            assert frame["proposal"]["id"] == str(proposal["id"])
            assert frame["proposal"]["card"]["summary"]
            frames.append(frame)
            break
    assert frames, "the stream sent no card for a proposal that was already waiting"


# ── S21, TD-028a: a dead claim is visible, and only a human resolves it ───────


async def _wedge(pool, settlement, workspace_id, pid, *, age_seconds: float, state="executing"):
    """Put a row into the state a process death leaves behind: claimed, with a
    claim that old. Reproduced by writing the row rather than by killing a
    worker, because that is exactly what a killed worker leaves."""
    await pool.execute(
        """
        UPDATE proposals
           SET status = $2, claimed_at = now() - make_interval(secs => $3::double precision),
               -- a live claim keeps its own token; a simulated dead one gets one
               claim_token = COALESCE(claim_token, gen_random_uuid())
         WHERE id = $1::uuid
        """,
        str(pid),
        state,
        float(age_seconds),
    )
    return await settlement.get(workspace_id=workspace_id, proposal_id=pid)


async def test_a_dead_claim_has_no_door_out_except_abandon(
    pool, registry, spec, workspace_id, an_observable
):
    """The defect itself, reproduced: every other transition refuses a wedged
    row, which is why it could never be recovered."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    await _wedge(pool, settlement, workspace_id, pid, age_seconds=STALE_CLAIM_SECONDS + 60)
    executor = ActionExecutor(pool, registry)

    with pytest.raises(ExecutionRefused) as execute_refused:
        await executor.execute(workspace_id=workspace_id, proposal_id=pid)
    assert execute_refused.value.reason == "not_approved"
    with pytest.raises(ExecutionRefused) as undo_refused:
        await executor.undo(workspace_id=workspace_id, proposal_id=pid)
    assert undo_refused.value.reason == "not_executed"
    rejected = await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="rejected", decided_by=None
    )
    assert rejected.outcome is Settlement.ALREADY_DECIDED

    # The one door that does open.
    abandoned = await settlement.abandon(
        workspace_id=workspace_id, proposal_id=pid, decided_by=None
    )
    assert abandoned.won and abandoned.proposal["status"] == "abandoned"
    assert abandoned.proposal["claimed_at"] is None


async def test_a_stale_claim_is_visible_in_the_queue(
    pool, registry, spec, workspace_id, an_observable
):
    """The sharpest half of TD-028a: the row was not merely stuck, it was GONE
    from the approvals list, so a human watching the queue saw the action
    vanish with nothing to click."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    await _wedge(pool, settlement, workspace_id, pid, age_seconds=STALE_CLAIM_SECONDS + 60)

    waiting = await settlement.pending(workspace_id=workspace_id)
    stuck = [p for p in waiting if p["id"] == pid]
    assert stuck, "a wedged claim must be visible to the human who has to resolve it"
    assert stuck[0]["status"] == "executing"  # shown as what it is, not relabelled


async def test_a_fresh_claim_is_neither_visible_nor_abandonable(
    pool, registry, spec, workspace_id, an_observable
):
    """The counterweight. A claim seconds old belongs to a handler that is
    almost certainly still running: showing it would make every execution flicker
    through the approval queue, and abandoning it would manufacture exactly the
    half-executed row this state exists to describe."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    await _wedge(pool, settlement, workspace_id, pid, age_seconds=1)

    assert not [p for p in await settlement.pending(workspace_id=workspace_id) if p["id"] == pid]
    refused = await settlement.abandon(
        workspace_id=workspace_id, proposal_id=pid, decided_by=None
    )
    assert refused.outcome is Settlement.ALREADY_DECIDED
    assert refused.current_status == "executing"
    still = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert still["status"] == "executing"  # untouched


async def test_undoing_wedges_the_same_way_and_recovers_the_same_way(
    pool, registry, spec, workspace_id, an_observable
):
    """`undoing` is the other claim, and it had the same hole."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    await ActionExecutor(pool, registry).execute(workspace_id=workspace_id, proposal_id=pid)
    await _wedge(
        pool, settlement, workspace_id, pid,
        age_seconds=STALE_CLAIM_SECONDS + 60, state="undoing",
    )
    assert [p for p in await settlement.pending(workspace_id=workspace_id) if p["id"] == pid]
    result = await settlement.abandon(workspace_id=workspace_id, proposal_id=pid, decided_by=None)
    assert result.won and result.proposal["status"] == "abandoned"


async def test_a_completed_run_leaves_no_claim_behind(
    pool, registry, spec, workspace_id, an_observable
):
    """`claimed_at` means "a claim is outstanding right now", so every exit from
    a claim must clear it — otherwise a finished action drifts into the queue
    five minutes later and asks a human to resolve something that is done."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    executor = ActionExecutor(pool, registry)
    await executor.execute(workspace_id=workspace_id, proposal_id=pid)
    executed = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert executed["status"] == "executed" and executed["claimed_at"] is None
    await executor.undo(workspace_id=workspace_id, proposal_id=pid)
    undone = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert undone["status"] == "undone" and undone["claimed_at"] is None


async def test_a_failed_run_leaves_no_claim_behind(
    pool, registry, spec, workspace_id, an_observable
):
    """The failure path clears the claim too. A failed row is already terminal
    and visible; leaving its claim set would put it in the queue as well, asking
    a human to abandon something that already reported what happened."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    boom = dataclasses.replace(
        spec, execute=mock.AsyncMock(side_effect=RuntimeError("handler died"))
    )
    exploding = ActionRegistry()
    exploding.register(boom)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, exploding).execute(
            workspace_id=workspace_id, proposal_id=pid
        )
    failed = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert failed["status"] == "failed" and failed["claimed_at"] is None
    assert not [p for p in await settlement.pending(workspace_id=workspace_id) if p["id"] == pid]


async def test_a_late_handler_cannot_overwrite_the_human_who_abandoned_it(
    pool, registry, spec, workspace_id, an_observable
):
    """S22 review, measured against live Postgres.

    `abandon` guards on claim AGE, and an old claim is not the same fact as a
    dead process — a handler that is merely slow gets abandoned and then
    returns. The four completion statements were `WHERE id = $1` with no status
    guard, so the late handler moved the row `abandoned` -> `executed` while
    `decided_at`/`decided_by` still named the human who pressed abandon: an
    audit trail asserting a human had decided something they never saw.

    Raced with a real handler held open on an event, not simulated by writing
    the row — the row shape is the easy half, the ordering is the finding.
    """
    release, ran = asyncio.Event(), asyncio.Event()

    async def slow_execute(**kwargs):
        ran.set()
        await release.wait()
        return await spec.execute(**kwargs)

    slow = ActionRegistry()
    slow.register(dataclasses.replace(spec, execute=slow_execute))

    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    task = asyncio.create_task(
        ActionExecutor(pool, slow).execute(workspace_id=workspace_id, proposal_id=pid)
    )
    try:
        await asyncio.wait_for(ran.wait(), timeout=10)
        # It has now been running longer than the threshold: from the row alone
        # this is indistinguishable from a process that died holding the claim.
        await pool.execute(
            "UPDATE proposals SET claimed_at = now()"
            " - make_interval(secs => $2::double precision) WHERE id = $1::uuid",
            str(pid),
            float(STALE_CLAIM_SECONDS + 60),
        )
        abandoned = await settlement.abandon(
            workspace_id=workspace_id, proposal_id=pid, decided_by=None
        )
        assert abandoned.won
        decided_at = abandoned.proposal["decided_at"]
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=10)

    final = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert final["status"] == "abandoned", "the handler overwrote a human's decision"
    assert final["decided_at"] == decided_at
    # ...and the answer that arrived too late is recorded rather than dropped.
    # `abandoned` records that the answer was LOST; this is it turning up.
    assert final["result"], "the late handler's answer should be kept on the row"


async def test_a_late_handler_that_fails_cannot_claim_nothing_happened(
    pool, registry, spec, workspace_id, an_observable
):
    """The failure half, and the sharper one. `failed` is exactly the "nothing
    happened" assertion the no-reaper design refuses to let a timer make — a
    late handler must not make it either, on a row a human already resolved."""
    release, ran = asyncio.Event(), asyncio.Event()

    async def slow_boom(**_):
        ran.set()
        await release.wait()
        raise RuntimeError("handler died late")

    exploding = ActionRegistry()
    exploding.register(dataclasses.replace(spec, execute=slow_boom))

    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    task = asyncio.create_task(
        ActionExecutor(pool, exploding).execute(workspace_id=workspace_id, proposal_id=pid)
    )
    try:
        await asyncio.wait_for(ran.wait(), timeout=10)
        await _wedge(
            pool, settlement, workspace_id, pid, age_seconds=STALE_CLAIM_SECONDS + 60
        )
        assert (
            await settlement.abandon(
                workspace_id=workspace_id, proposal_id=pid, decided_by=None
            )
        ).won
    finally:
        release.set()
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(task, timeout=10)

    final = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert final["status"] == "abandoned"
    assert final["result"]["error"] == "RuntimeError"


async def test_eight_concurrent_abandons_settle_one_dead_claim_exactly_once(
    pool, registry, spec, workspace_id, an_observable
):
    """`abandon` is a state transition a human can trigger, so it is raced the
    way S18 raced approval. The age guard lives in the same UPDATE that moves
    the row, which is the whole guarantee — proven, not asserted."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    await _wedge(pool, settlement, workspace_id, pid, age_seconds=STALE_CLAIM_SECONDS + 60)
    results = await asyncio.gather(
        *[
            settlement.abandon(workspace_id=workspace_id, proposal_id=pid, decided_by=None)
            for _ in range(8)
        ]
    )
    assert sum(r.won for r in results) == 1
    assert {r.outcome for r in results if not r.won} == {Settlement.ALREADY_DECIDED}


async def test_the_stale_arm_is_tenant_scoped_like_the_pending_arm(
    pool, registry, spec, workspace_id, other_workspace_id, an_observable
):
    """`pending()` grew a second way for a row to enter it (TD-028a). D-008 has
    to hold on the NEW arm specifically, not only on the one it was written
    against."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    await _wedge(pool, settlement, workspace_id, pid, age_seconds=STALE_CLAIM_SECONDS + 60)
    assert [p for p in await settlement.pending(workspace_id=workspace_id) if p["id"] == pid]
    assert not [
        p for p in await settlement.pending(workspace_id=other_workspace_id)
        if p["id"] == pid
    ]


async def test_a_stale_claim_cannot_be_settled_through_the_ordinary_buttons(
    pool, registry, spec, workspace_id, an_observable
):
    """The stale row appears beside pending ones, so the approve/reject buttons
    are right there. Neither may move it — `abandon` exists precisely because
    those two would assert something nobody knows."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    await _wedge(pool, settlement, workspace_id, pid, age_seconds=STALE_CLAIM_SECONDS + 60)
    for decision in ("approved", "rejected"):
        result = await settlement.settle(
            workspace_id=workspace_id, proposal_id=pid, decision=decision, decided_by=None
        )
        assert result.outcome is Settlement.ALREADY_DECIDED
    assert (await settlement.get(workspace_id=workspace_id, proposal_id=pid))["status"] == (
        "executing"
    )


async def test_abandon_is_tenant_scoped_like_every_other_transition(
    pool, registry, spec, workspace_id, other_workspace_id, an_observable
):
    """D-008: the workspace is part of the key, not a filter applied after."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    await _wedge(pool, settlement, workspace_id, pid, age_seconds=STALE_CLAIM_SECONDS + 60)
    result = await settlement.abandon(
        workspace_id=other_workspace_id, proposal_id=pid, decided_by=None
    )
    assert result.outcome is Settlement.NOT_FOUND
    assert (await settlement.get(workspace_id=workspace_id, proposal_id=pid))["status"] == (
        "executing"
    )


async def test_the_abandon_route_refuses_a_fresh_claim_and_accepts_a_dead_one(
    pool, client, route_ws
):
    ws, obs_id = route_ws
    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    spec = registry.get("annotate_observable")
    settlement, proposal = await _file(pool, registry, spec, ws, obs_id)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=ws, proposal_id=pid, decision="approved", decided_by=None
    )
    hdr = _hdr(client)

    await _wedge(pool, settlement, ws, pid, age_seconds=1)
    early = client.post(f"/api/proposals/{pid}/abandon", headers=hdr)
    assert early.status_code == 409
    assert "nothing to abandon" in early.json()["detail"]

    await _wedge(pool, settlement, ws, pid, age_seconds=STALE_CLAIM_SECONDS + 60)
    listed = client.get("/api/proposals", headers=hdr).json()["proposals"]
    card_for_it = [p for p in listed if p["id"] == str(pid)]
    assert card_for_it, "the stale claim must reach the surface a human watches"
    assert card_for_it[0]["claimed_at"] is not None

    out = client.post(f"/api/proposals/{pid}/abandon", headers=hdr)
    assert out.status_code == 200
    assert out.json()["settled"] == "abandoned"
    assert out.json()["proposal"]["claimed_at"] is None
    assert not [
        p for p in client.get("/api/proposals", headers=hdr).json()["proposals"]
        if p["id"] == str(pid)
    ]


async def test_a_run_abandoned_mid_flight_can_be_put_back(
    pool, registry, spec, workspace_id, an_observable
):
    """TD-028(c), and the reversal of an S23 pin.

    Until S26 this test was "an undo cannot start on a row abandoned during
    execute": it kept TD-034's late-write unreachable by keeping the cleanup
    path shut, so a human who abandoned a run whose write HAD landed could see
    the note and could not remove it. TD-034 is now fixed structurally
    (`abandoned_from`, f263c1d), so the door opens: `abandoned` means nobody
    knows what landed, and an undo — keyed on this proposal, removing exactly
    what it created — is the cleanup a human chooses.
    """
    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    # The run's write landed, then the process holding the claim died.
    await spec.execute(workspace_id=workspace_id, proposal_id=str(pid),
                       observable_id=an_observable, note="landed before the crash")
    await _wedge(pool, settlement, workspace_id, pid,
                 age_seconds=STALE_CLAIM_SECONDS + 60, state="executing")
    assert (await settlement.abandon(workspace_id=workspace_id, proposal_id=pid,
                                     decided_by=None)).won

    outcome = await ActionExecutor(pool, registry).undo(
        workspace_id=workspace_id, proposal_id=pid)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "undone" and outcome.detail == {"removed": 1}
    assert row["abandoned_from"] == "executing"  # the history stays readable
    assert 0 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid", str(pid))


async def test_the_undo_claim_itself_refuses_an_abandoned_row(
    pool, registry, spec, workspace_id, an_observable
):
    """S24 review — pins the undo CLAIM itself, not the read before it.

    (S26: undo from `abandoned` is now allowed (TD-028c), so what this guards is
    the general form — the claim moves the row only out of the exact status the
    read saw. A stale read must never drag a row out of a status it did not see.)

    `test_an_undo_cannot_start_on_a_row_abandoned_during_execute` asserts
    `not_executed`, which is the READ-then-check at settlement.py:530. Its
    docstring, though, credits the guarantee to the atomic claim at :544 and
    promises that loosening that claim makes it fail. Measured in S24: it does
    not. Loosening the claim to `status IN ('executed','abandoned')` leaves all
    34 settlement tests green, because the pre-check refuses first — the pin
    guards the racy statement and leaves the atomic one bare.

    The claim exists precisely for what the pre-check cannot see: the row
    changing between the read and the write. So that is the shape tested here —
    a stale read says `executed` while the row is already `abandoned`. Nothing
    but the claim's own `AND status = 'executed'` stands between that and an
    `undo_result` stamped onto a row a human abandoned (TD-034).
    """
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await settlement.settle(
        workspace_id=workspace_id, proposal_id=pid, decision="approved", decided_by=None
    )
    await pool.execute(
        "UPDATE proposals SET status = 'executing', claimed_at = now() - interval '1 hour'"
        " WHERE id = $1::uuid",
        str(pid),
    )
    abandoned = await settlement.abandon(
        workspace_id=workspace_id, proposal_id=pid, decided_by=None
    )
    assert abandoned.won and abandoned.proposal["status"] == "abandoned"

    executor = ActionExecutor(pool, registry)
    fresh = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert fresh["status"] == "abandoned"  # control: the row really is abandoned

    # The stale read the claim is the backstop for. Only `get` is faked; the
    # claim runs against the real row.
    async def _stale_read(**_kwargs):
        return {**dict(fresh), "status": "executed"}

    executor._settlement.get = _stale_read

    with pytest.raises(ExecutionRefused) as caught:
        await executor.undo(workspace_id=workspace_id, proposal_id=pid)
    assert caught.value.reason == "already_undone"

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "abandoned"  # not dragged into 'undoing'
    assert row["undo_result"] is None  # TD-034's late-write never gets a row


# -- TD-034: the late-write knows WHICH operation was abandoned (S26) ----------


@pytest.mark.parametrize("state", ["executing", "undoing"])
async def test_abandon_records_which_operation_it_abandoned(
    pool, registry, spec, workspace_id, an_observable, state
):
    """`abandoned` alone does not say whether a run or a put-back was lost, and
    every later decision about the row — whose late answer may land, what a
    cleanup means — depends on which. Written by the same statement that moves
    the row, from the status it moved it out of."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await _wedge(pool, settlement, workspace_id, pid,
                 age_seconds=STALE_CLAIM_SECONDS + 60, state=state)

    abandoned = await settlement.abandon(workspace_id=workspace_id, proposal_id=pid,
                                         decided_by=None)

    assert abandoned.won
    assert abandoned.proposal["abandoned_from"] == state


async def test_a_late_undo_answer_never_lands_on_a_run_that_was_abandoned(
    pool, registry, spec, workspace_id, an_observable
):
    """TD-034, measured in docs/probes/s23-step0/probe_late_write.py and driven
    here the same way: an undo's late answer stamped `undo_result` onto a row
    abandoned during EXECUTE — an answer for an undo that never began. The
    late-write now matches the operation it belongs to."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await _wedge(pool, settlement, workspace_id, pid,
                 age_seconds=STALE_CLAIM_SECONDS + 60, state="executing")
    assert (await settlement.abandon(workspace_id=workspace_id, proposal_id=pid,
                                     decided_by=None)).won

    # An undo would hold a claim of its OWN — never the run's abandoned one.
    landed = await ActionExecutor(pool, registry)._finish_claim(
        pid, uuid.uuid4(), from_status="undoing", to_status="undone", column="undo_result",
        payload={"would": "an undo that never began"},
    )

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert landed is False
    assert row["status"] == "abandoned" and row["undo_result"] is None


async def test_a_late_run_answer_still_lands_on_the_run_that_was_abandoned(
    pool, registry, spec, workspace_id, an_observable
):
    """The control: the late-write S22 deliberately allowed still works for the
    operation it belongs to."""
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    pid = proposal["id"]
    await _wedge(pool, settlement, workspace_id, pid,
                 age_seconds=STALE_CLAIM_SECONDS + 60, state="executing")
    abandoned = await settlement.abandon(workspace_id=workspace_id, proposal_id=pid,
                                         decided_by=None)
    assert abandoned.won

    await ActionExecutor(pool, registry)._finish_claim(
        pid, abandoned.proposal["abandoned_token"], from_status="executing",
        to_status="executed", column="result", payload={"would": "the run, late"},
    )

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "abandoned" and row["result"] == {"would": "the run, late"}


# -- TD-028(b): a failed execute must not deny effects that landed (S26) -------


async def _approved(pool, registry, spec, workspace_id, an_observable):
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)
    await settlement.settle(workspace_id=workspace_id, proposal_id=proposal["id"],
                            decision="approved", decided_by=None)
    return settlement, proposal["id"]


def _with(spec, **changes) -> ActionRegistry:
    r = ActionRegistry()
    r.register(dataclasses.replace(spec, **changes))
    return r


async def test_a_run_that_failed_after_its_write_landed_says_so(
    pool, registry, spec, workspace_id, an_observable
):
    """TD-028(b), reproduced at S19 Step 0: the handler's INSERT landed, then it
    raised, and the row said `failed` — the surface reported that nothing
    happened while the note was really in the table. The executor now asks the
    action what of THIS proposal's effects exist, and a row with effects is
    `incomplete`: something happened, and a human has to decide about it."""
    async def writes_then_dies(**kwargs):
        await spec.execute(**kwargs)
        raise RuntimeError("died after the write")

    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _with(spec, execute=writes_then_dies)).execute(
            workspace_id=workspace_id, proposal_id=pid)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "incomplete"
    assert row["result"] == {"error": "RuntimeError", "effects": "present"}
    assert 1 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid", str(pid))
    queued = [p["id"] for p in await settlement.pending(workspace_id=workspace_id)]
    assert pid in queued, "a row whose effects landed needs a human"


async def test_a_run_that_failed_before_writing_is_failed_and_checked(
    pool, registry, spec, workspace_id, an_observable
):
    """`failed` now means what it says, because it was checked: the action
    looked, and nothing of this proposal's exists."""
    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _with(
            spec, execute=mock.AsyncMock(side_effect=RuntimeError("died first")))
        ).execute(workspace_id=workspace_id, proposal_id=pid)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "failed"
    assert row["result"] == {"error": "RuntimeError", "effects": "none"}


async def test_an_action_that_cannot_look_is_incomplete_never_failed(
    pool, registry, spec, workspace_id, an_observable
):
    """An action that declares no way to observe its effects cannot support
    "nothing happened", so the platform does not say it — the first third-party
    action will be exactly this shape."""
    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _with(
            spec, observe=None, execute=mock.AsyncMock(side_effect=RuntimeError("x")))
        ).execute(workspace_id=workspace_id, proposal_id=pid)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "incomplete"
    assert row["result"]["effects"] == "unknown"


async def test_a_look_that_itself_fails_is_unknown_not_none(
    pool, registry, spec, workspace_id, an_observable
):
    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _with(
            spec,
            observe=mock.AsyncMock(side_effect=ConnectionError("db away")),
            execute=mock.AsyncMock(side_effect=RuntimeError("x")),
        )).execute(workspace_id=workspace_id, proposal_id=pid)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert (row["status"], row["result"]["effects"]) == ("incomplete", "unknown")


def test_the_builtin_action_can_observe_its_own_effects(spec):
    """The one executable action ships able to look, so its `failed` is a
    checked fact rather than a hope."""
    assert spec.observe is not None


async def test_the_approval_surface_says_what_landed_when_a_run_fails(pool, client, route_ws):
    """The 500 used to name only the row's status; an analyst reading `failed`
    concluded nothing happened. Now it says what the action found."""
    ws, obs_id = route_ws
    app_spec = client.app.state.action_registry.get("annotate_observable")

    async def writes_then_dies(**kwargs):
        await app_spec.execute(**kwargs)
        raise RuntimeError("died after the write")

    real = client.app.state.action_registry
    client.app.state.action_registry = _with(app_spec, execute=writes_then_dies)
    try:
        registry = ActionRegistry()
        registry.register_all(build_builtin_actions(pool))
        _, proposal = await _file(pool, registry, registry.get("annotate_observable"), ws, obs_id)
        resp = client.post(f"/api/proposals/{proposal['id']}/approve", headers=_hdr(client))
    finally:
        client.app.state.action_registry = real

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "incomplete" in detail and "landed" in detail and "undo" in detail


# -- TD-028(c): the cleanup path is open where effects are unknown (S26) -------


async def _incomplete(pool, registry, spec, workspace_id, an_observable):
    """A run whose write landed and which then raised: `incomplete` (TD-028b)."""
    async def writes_then_dies(**kwargs):
        await spec.execute(**kwargs)
        raise RuntimeError("died after the write")

    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _with(spec, execute=writes_then_dies)).execute(
            workspace_id=workspace_id, proposal_id=pid)
    assert (await settlement.get(workspace_id=workspace_id, proposal_id=pid))[
        "status"] == "incomplete"
    return settlement, pid


async def test_an_incomplete_run_can_be_put_back(
    pool, registry, spec, workspace_id, an_observable
):
    """TD-028(c): `put_back` is keyed on the proposal and would delete exactly
    the orphaned row, and the gate (`status = 'executed'`) kept it shut. An
    incomplete run is precisely the case that needs it."""
    settlement, pid = await _incomplete(pool, registry, spec, workspace_id, an_observable)

    outcome = await ActionExecutor(pool, registry).undo(
        workspace_id=workspace_id, proposal_id=pid)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "undone" and outcome.detail == {"removed": 1}
    assert 0 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid", str(pid))
    assert pid not in [p["id"] for p in await settlement.pending(workspace_id=workspace_id)]


async def test_a_failed_cleanup_returns_to_where_it_started(
    pool, registry, spec, workspace_id, an_observable
):
    """An undo that raises used to put the row back to `executed` — true only
    when it started there. A cleanup of an incomplete run that fails is still
    an incomplete run; calling it executed would claim a success that never
    happened."""
    settlement, pid = await _incomplete(pool, registry, spec, workspace_id, an_observable)
    broken_undo = dataclasses.replace(
        spec.undo, handler=mock.AsyncMock(side_effect=RuntimeError("undo died")))

    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _with(spec, undo=broken_undo)).undo(
            workspace_id=workspace_id, proposal_id=pid)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "incomplete" and row["claimed_at"] is None
    assert row["undo_result"] == {"error": "RuntimeError"}


async def test_a_checked_failure_has_nothing_to_put_back(
    pool, registry, spec, workspace_id, an_observable
):
    """`failed` now means the action looked and nothing landed, so there is
    nothing to undo — and saying `undone` about it would report a put-back of
    nothing (the TD-028(c) question, answered)."""
    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _with(
            spec, execute=mock.AsyncMock(side_effect=RuntimeError("died first")))
        ).execute(workspace_id=workspace_id, proposal_id=pid)

    with pytest.raises(ExecutionRefused) as caught:
        await ActionExecutor(pool, registry).undo(workspace_id=workspace_id, proposal_id=pid)

    assert caught.value.reason == "nothing_to_undo"
    assert (await settlement.get(workspace_id=workspace_id, proposal_id=pid))[
        "status"] == "failed"


async def test_an_incomplete_run_is_put_back_through_the_surface(pool, client, route_ws):
    ws, obs_id = route_ws
    app_spec = client.app.state.action_registry.get("annotate_observable")

    async def writes_then_dies(**kwargs):
        await app_spec.execute(**kwargs)
        raise RuntimeError("died after the write")

    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    _, proposal = await _file(pool, registry, registry.get("annotate_observable"), ws, obs_id)
    hdr = _hdr(client)
    real = client.app.state.action_registry
    client.app.state.action_registry = _with(app_spec, execute=writes_then_dies)
    try:
        assert client.post(f"/api/proposals/{proposal['id']}/approve",
                           headers=hdr).status_code == 500
    finally:
        client.app.state.action_registry = real

    queued = client.get("/api/proposals", headers=hdr).json()["proposals"]
    assert [p["status"] for p in queued if p["id"] == str(proposal["id"])] == ["incomplete"]
    undone = client.post(f"/api/proposals/{proposal['id']}/undo", headers=hdr)
    assert undone.status_code == 200, undone.text
    assert undone.json()["proposal"]["status"] == "undone"


async def test_a_failed_cleanup_through_the_surface_says_where_the_row_is(
    pool, client, route_ws
):
    """The undo route's 500 said "the action remains executed" — false for a
    put-back that started from incomplete or abandoned."""
    ws, obs_id = route_ws
    app_spec = client.app.state.action_registry.get("annotate_observable")

    async def writes_then_dies(**kwargs):
        await app_spec.execute(**kwargs)
        raise RuntimeError("died after the write")

    broken_undo = dataclasses.replace(
        app_spec.undo, handler=mock.AsyncMock(side_effect=RuntimeError("undo died")))
    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    _, proposal = await _file(pool, registry, registry.get("annotate_observable"), ws, obs_id)
    hdr = _hdr(client)
    real = client.app.state.action_registry
    client.app.state.action_registry = _with(
        app_spec, execute=writes_then_dies, undo=broken_undo)
    try:
        client.post(f"/api/proposals/{proposal['id']}/approve", headers=hdr)
        resp = client.post(f"/api/proposals/{proposal['id']}/undo", headers=hdr)
    finally:
        client.app.state.action_registry = real

    assert resp.status_code == 500
    assert "incomplete" in resp.json()["detail"] and "executed" not in resp.json()["detail"]


# -- TD-028(d): the approver is told when they are asked the same thing twice --


async def test_two_identical_requests_each_name_the_other(
    pool, registry, spec, workspace_id, an_observable
):
    """A model calling one action twice files two rows an approver cannot tell
    apart. Deduping is deliberately NOT the fix (D-014: whether a second intent
    was a mistake is the human's call), so each card names its twins instead —
    same action, same arguments, same declaration, still awaiting a decision."""
    settlement, first = await _file(pool, registry, spec, workspace_id, an_observable,
                                    note="same words")
    _, second = await _file(pool, registry, spec, workspace_id, an_observable,
                            note="same words")
    _, other = await _file(pool, registry, spec, workspace_id, an_observable,
                           note="different words")

    queued = {p["id"]: p for p in await settlement.pending(workspace_id=workspace_id)}

    assert queued[first["id"]]["identical_pending"] == [second["id"]]
    assert queued[second["id"]]["identical_pending"] == [first["id"]]
    assert queued[other["id"]]["identical_pending"] == []


async def test_deciding_one_twin_leaves_the_other_waiting_and_alone(
    pool, registry, spec, workspace_id, an_observable
):
    """Not a dedupe: rejecting one leaves the other a real, separate request —
    and it stops naming a twin that no longer awaits a decision."""
    settlement, first = await _file(pool, registry, spec, workspace_id, an_observable,
                                    note="same words")
    _, second = await _file(pool, registry, spec, workspace_id, an_observable,
                            note="same words")
    await settlement.settle(workspace_id=workspace_id, proposal_id=first["id"],
                            decision="rejected", decided_by=None)

    queued = {p["id"]: p for p in await settlement.pending(workspace_id=workspace_id)}

    assert first["id"] not in queued
    assert queued[second["id"]]["identical_pending"] == []


async def test_a_twin_in_another_workspace_is_never_named(
    pool, registry, spec, workspace_id, other_workspace_id, an_observable
):
    """The twin lookup is a query across rows, so tenancy must be part of it
    (D-008): another workspace's identical request is not this approver's to
    know about, and its id must never reach this card."""
    settlement, mine = await _file(pool, registry, spec, workspace_id, an_observable,
                                   note="same words")
    await settlement.file(
        workspace_id=other_workspace_id, spec=spec,
        arguments={"observable_id": an_observable, "note": "same words"},
        dry_run=await spec.dry_run(workspace_id=workspace_id, observable_id=an_observable,
                                   note="same words"),
    )

    queued = {p["id"]: p for p in await settlement.pending(workspace_id=workspace_id)}

    assert queued[mine["id"]]["identical_pending"] == []


async def test_the_card_on_the_surface_names_its_twins(pool, client, route_ws):
    ws, obs_id = route_ws
    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    spec = registry.get("annotate_observable")
    _, first = await _file(pool, registry, spec, ws, obs_id, note="same words")
    _, second = await _file(pool, registry, spec, ws, obs_id, note="same words")

    listed = client.get("/api/proposals", headers=_hdr(client)).json()["proposals"]
    shown = {p["id"]: p for p in listed}

    assert shown[str(first["id"])]["identical_pending"] == [str(second["id"])]


# -- review of D-041: a claim is identified by a token, not by a status --------


async def test_an_abandoned_undo_cannot_finish_a_fresh_undo_s_claim(
    pool, registry, spec, workspace_id, an_observable
):
    """Review of 1c6c9bd, MEDIUM, reproduced. Since undo may start from
    `abandoned`, two undos can be in flight on one row, and a claim was known
    only by its status string: U1 (slow) is abandoned, U2 cleans up and removes
    the note, then U1 raises — and its finish matched U2's claim, putting the
    row back to `executed` while U2's own success was dropped. The row said
    `executed` with no note left."""
    release_u1, u1_ran = asyncio.Event(), asyncio.Event()
    release_u2, u2_removed = asyncio.Event(), asyncio.Event()

    async def slow_failing_undo(**_):
        u1_ran.set()
        await release_u1.wait()
        raise RuntimeError("U1 died late")

    async def removes_then_waits(**kwargs):
        out = await spec.undo.handler(**kwargs)  # the note is gone now
        u2_removed.set()
        await release_u2.wait()
        return out

    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    await ActionExecutor(pool, registry).execute(workspace_id=workspace_id, proposal_id=pid)
    u1 = ActionExecutor(pool, _with(spec, undo=dataclasses.replace(
        spec.undo, handler=slow_failing_undo)))
    u2 = ActionExecutor(pool, _with(spec, undo=dataclasses.replace(
        spec.undo, handler=removes_then_waits)))
    t1 = asyncio.create_task(u1.undo(workspace_id=workspace_id, proposal_id=pid))
    t2 = None
    try:
        await asyncio.wait_for(u1_ran.wait(), timeout=10)
        await pool.execute(
            "UPDATE proposals SET claimed_at = now() - interval '1 hour' WHERE id = $1::uuid",
            str(pid))
        assert (await settlement.abandon(workspace_id=workspace_id, proposal_id=pid,
                                         decided_by=None)).won
        t2 = asyncio.create_task(u2.undo(workspace_id=workspace_id, proposal_id=pid))
        await asyncio.wait_for(u2_removed.wait(), timeout=10)
        # U2 holds the claim mid-flight; NOW U1's late failure arrives.
        release_u1.set()
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(t1, timeout=10)
    finally:
        release_u1.set()
        release_u2.set()
        if t2 is not None:
            await asyncio.wait_for(t2, timeout=10)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "undone", "a late failure finished a claim it did not hold"
    assert row["undo_result"]["detail"] == {"removed": 1}
    assert 0 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid", str(pid))


async def test_a_run_s_late_answer_is_kept_even_after_its_clean_up(
    pool, registry, spec, workspace_id, an_observable
):
    """Review finding 6: D-041's stated bound — a slow run abandoned and put
    back can land its write afterwards — was real, and the one record that
    would show it happened was thrown away (the late-write required the row to
    still be `abandoned`). It lands now, without moving the row: `undone` with
    a `result` is a row that says the run finished after its put-back."""
    release, ran = asyncio.Event(), asyncio.Event()

    async def slow_run(**kwargs):
        ran.set()
        await release.wait()
        return await spec.execute(**kwargs)

    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    task = asyncio.create_task(ActionExecutor(pool, _with(spec, execute=slow_run)).execute(
        workspace_id=workspace_id, proposal_id=pid))
    try:
        await asyncio.wait_for(ran.wait(), timeout=10)
        await pool.execute(
            "UPDATE proposals SET claimed_at = now() - interval '1 hour' WHERE id = $1::uuid",
            str(pid))
        assert (await settlement.abandon(workspace_id=workspace_id, proposal_id=pid,
                                         decided_by=None)).won
        await ActionExecutor(pool, registry).undo(workspace_id=workspace_id, proposal_id=pid)
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=10)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert row["status"] == "undone"
    assert row["result"] and "Attached" in row["result"]["would"], "the late answer was dropped"


async def test_a_put_back_does_not_wear_the_previous_attempt_s_answer(
    pool, registry, spec, workspace_id, an_observable
):
    """Review finding 7: the undo claim kept the previous attempt's
    `undo_result`, so an in-flight (or abandoned) put-back showed an earlier
    attempt's error as if it were its own."""
    release, ran = asyncio.Event(), asyncio.Event()

    async def slow_undo(**kwargs):
        ran.set()
        await release.wait()
        return await spec.undo.handler(**kwargs)

    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    await ActionExecutor(pool, registry).execute(workspace_id=workspace_id, proposal_id=pid)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _with(spec, undo=dataclasses.replace(
            spec.undo, handler=mock.AsyncMock(side_effect=RuntimeError("first try"))))
        ).undo(workspace_id=workspace_id, proposal_id=pid)
    task = asyncio.create_task(ActionExecutor(pool, _with(spec, undo=dataclasses.replace(
        spec.undo, handler=slow_undo))).undo(workspace_id=workspace_id, proposal_id=pid))
    try:
        await asyncio.wait_for(ran.wait(), timeout=10)
        mid = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=10)

    assert mid["status"] == "undoing" and mid["undo_result"] is None


# -- review of D-041: an incomplete row has a way out besides undo ------------


async def test_an_incomplete_run_can_be_kept_as_it_is(
    pool, registry, spec, workspace_id, an_observable
):
    """Review finding 3. `incomplete` joined the queue with ONE door out — undo.
    A human who looks at what landed and wants it kept had no way to say so,
    and the row stayed in the queue forever: TD-028a's "every door shut",
    visible this time and still undismissable. `keep` is that decision,
    claim-first like every other, and recorded with who made it."""
    settlement, pid = await _incomplete(pool, registry, spec, workspace_id, an_observable)

    kept = await settlement.keep(workspace_id=workspace_id, proposal_id=pid, decided_by=None)

    assert kept.won and kept.proposal["status"] == "kept"
    assert pid not in [p["id"] for p in await settlement.pending(workspace_id=workspace_id)]
    assert 1 == await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid", str(pid))


async def test_an_incomplete_run_of_an_action_with_no_undo_is_not_stuck(
    pool, registry, spec, workspace_id, an_observable
):
    """The shape the reviewer named: a WRITE action that declares no undo (legal
    under validate_spec — the likely first third-party action). Undo refuses
    it, so keep is the only way out — and it must exist."""
    no_undo = _with(spec, undo=None)
    no_undo_spec = no_undo.get("annotate_observable")

    async def writes_then_dies(**kwargs):
        await spec.execute(**kwargs)
        raise RuntimeError("died after the write")

    # Filed AND run under the no-undo declaration — otherwise the fingerprint
    # check refuses the run as a changed action before it starts.
    settlement, pid = await _approved(pool, no_undo, no_undo_spec, workspace_id, an_observable)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _with(no_undo_spec, execute=writes_then_dies)).execute(
            workspace_id=workspace_id, proposal_id=pid)
    assert (await settlement.get(workspace_id=workspace_id, proposal_id=pid))[
        "status"] == "incomplete"
    with pytest.raises(ExecutionRefused) as refused:
        await ActionExecutor(pool, no_undo).undo(workspace_id=workspace_id, proposal_id=pid)
    assert refused.value.reason == "no_undo"

    assert (await settlement.keep(workspace_id=workspace_id, proposal_id=pid,
                                  decided_by=None)).won


async def test_only_an_incomplete_run_can_be_kept(
    pool, registry, spec, workspace_id, an_observable
):
    settlement, proposal = await _file(pool, registry, spec, workspace_id, an_observable)

    result = await settlement.keep(workspace_id=workspace_id, proposal_id=proposal["id"],
                                   decided_by=None)

    assert result.outcome is Settlement.ALREADY_DECIDED
    assert result.current_status == "pending_approval"


async def test_a_kept_run_can_still_be_put_back(
    pool, registry, spec, workspace_id, an_observable
):
    """Keeping is a decision about what landed, not a lock on it: the human who
    kept it can change their mind, and the put-back removes exactly this
    proposal's effects as it does from `executed`."""
    settlement, pid = await _incomplete(pool, registry, spec, workspace_id, an_observable)
    await settlement.keep(workspace_id=workspace_id, proposal_id=pid, decided_by=None)

    await ActionExecutor(pool, registry).undo(workspace_id=workspace_id, proposal_id=pid)

    assert (await settlement.get(workspace_id=workspace_id, proposal_id=pid))[
        "status"] == "undone"


async def test_keep_through_the_surface(pool, client, route_ws):
    ws, obs_id = route_ws
    app_spec = client.app.state.action_registry.get("annotate_observable")

    async def writes_then_dies(**kwargs):
        await app_spec.execute(**kwargs)
        raise RuntimeError("died after the write")

    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(pool))
    _, proposal = await _file(pool, registry, registry.get("annotate_observable"), ws, obs_id)
    _, pending = await _file(pool, registry, registry.get("annotate_observable"), ws, obs_id,
                             note="still pending")
    hdr = _hdr(client)
    real = client.app.state.action_registry
    client.app.state.action_registry = _with(app_spec, execute=writes_then_dies)
    try:
        client.post(f"/api/proposals/{proposal['id']}/approve", headers=hdr)
    finally:
        client.app.state.action_registry = real

    kept = client.post(f"/api/proposals/{proposal['id']}/keep", headers=hdr)
    early = client.post(f"/api/proposals/{pending['id']}/keep", headers=hdr)

    assert kept.status_code == 200 and kept.json()["proposal"]["status"] == "kept"
    assert early.status_code == 409


# -- review of D-041: what an effects probe may be, and what its answer means --


@pytest.mark.parametrize("slot", ["execute", "dry_run", "undo"])
def test_the_look_cannot_be_the_run_the_preview_or_the_put_back(spec, slot):
    """Review finding 4, reproduced: `observe=execute` registered happily, and
    when a run failed the platform's "look" ran the action a SECOND time,
    unapproved — one more note, and the row went `incomplete`. The same rails
    the undo slot has (S18 Step 0), for the same reason."""
    handler = {"execute": spec.execute, "dry_run": spec.dry_run,
               "undo": spec.undo.handler}[slot]

    with pytest.raises(ActionSpecError):
        dataclasses.replace(spec, observe=handler)


def test_the_look_must_be_callable(spec):
    with pytest.raises(ActionSpecError):
        dataclasses.replace(spec, observe=3)


@pytest.mark.parametrize("answer", [None, True, "0", 0.0, [], -1])
async def test_only_a_count_of_zero_means_nothing_landed(
    pool, registry, spec, workspace_id, an_observable, answer
):
    """Review finding 4, reproduced: an `observe` that forgot its `return` gave
    `None`, which read as falsy — `failed`, effects `none` — while the write was
    in the table. "Nothing landed" is a claim; only an int 0 makes it."""
    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    with pytest.raises(RuntimeError):
        await ActionExecutor(pool, _with(
            spec, observe=mock.AsyncMock(return_value=answer),
            execute=mock.AsyncMock(side_effect=RuntimeError("x")))
        ).execute(workspace_id=workspace_id, proposal_id=pid)

    row = await settlement.get(workspace_id=workspace_id, proposal_id=pid)
    assert (row["status"], row["result"]["effects"]) == ("incomplete", "unknown")


async def test_a_failure_recorded_before_anyone_looked_can_still_be_put_back(
    pool, registry, spec, workspace_id, an_observable
):
    """Review finding 5. A `failed` row written before 203cccc carries
    `{"error": ...}` and no `effects` — nothing was checked — and the S19
    reproduction of TD-028b is exactly such a row, with its note really in the
    table. Refusing it as "checked that nothing of it landed" told a falsehood
    about it. Only a failure that LOOKED is refused."""
    settlement, pid = await _approved(pool, registry, spec, workspace_id, an_observable)
    await spec.execute(workspace_id=workspace_id, proposal_id=str(pid),
                       observable_id=an_observable, note="written before S26")
    await pool.execute(
        "UPDATE proposals SET status = 'failed', result = '{\"error\": \"RuntimeError\"}'"
        " WHERE id = $1::uuid", str(pid))

    outcome = await ActionExecutor(pool, registry).undo(
        workspace_id=workspace_id, proposal_id=pid)

    assert outcome.detail == {"removed": 1}
    assert (await settlement.get(workspace_id=workspace_id, proposal_id=pid))[
        "status"] == "undone"
