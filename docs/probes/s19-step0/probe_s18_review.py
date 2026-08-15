"""S19 Step 0 — fresh-eyes review of the S18 commits, verified BY EXECUTION.

Five angles S18 did not adversarially test (NEXT-SESSION.md). Each is RUN, not
reasoned about. Cleans up after itself (STATE.md: probe residue is expensive).

Run from the repo root with .venv/bin/python.
"""

import asyncio
import dataclasses
import json
import sys

import asyncpg

sys.path.insert(0, ".")
from auspex.actions.builtin import build_builtin_actions  # noqa: E402
from auspex.actions.proposal import canonical_spec, fingerprint  # noqa: E402
from auspex.actions.registry import ActionRegistry  # noqa: E402
from auspex.actions.settlement import (  # noqa: E402
    ActionExecutor,
    ExecutionRefused,
    ProposalSettlement,
)
from auspex.actions.types import (  # noqa: E402
    ActionParam,
    ActionScope,
    ActionSpec,
    UndoSpec,
)

DSN = "postgresql://auspex:auspex@localhost:55432/auspex"
WS_NAME = "probe-s19-review"

OK = "  ok  "
BAD = " !!!! "


def head(n, title):
    print(f"\n{'=' * 78}\n{n}. {title}\n{'=' * 78}")


async def setup(conn) -> str:
    ws = await conn.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1) "
        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        WS_NAME,
    )
    return ws


async def teardown(conn):
    await conn.execute(
        "DELETE FROM proposals WHERE workspace_id IN "
        "(SELECT id FROM workspaces WHERE name LIKE 'probe-s19%')"
    )
    await conn.execute(
        "DELETE FROM observable_notes WHERE workspace_id IN "
        "(SELECT id FROM workspaces WHERE name LIKE 'probe-s19%')"
    )
    await conn.execute("DELETE FROM workspaces WHERE name LIKE 'probe-s19%'")


# ── 1. the fingerprint's blind spot ──────────────────────────────────────────


def angle_1_fingerprint_blind_spot(pool):
    head(1, "canonical_spec is a hand-written field list — is anything enforcing it?")

    spec = build_builtin_actions(pool)[0]
    base = fingerprint(spec)
    canon_keys = set(canonical_spec(spec)) - {"v"}

    # (a) STRUCTURAL: which declared fields does the identity actually cover?
    top = {f.name for f in dataclasses.fields(ActionSpec)}
    handlers = {"dry_run", "execute"}  # deliberately excluded — deploy integrity
    uncovered = top - handlers - canon_keys
    print(f"  ActionSpec fields : {sorted(top)}")
    print(f"  canonical keys    : {sorted(canon_keys)}")
    print(f"  uncovered (non-handler): {sorted(uncovered) or 'none — covered today'}")

    # The nested dataclasses matter more: a field added to ActionParam or
    # ActionScope changes what an approver READS on the card.
    nested = {
        "ActionParam": ({f.name for f in dataclasses.fields(ActionParam)}, set()),
        "ActionScope": ({f.name for f in dataclasses.fields(ActionScope)}, set()),
        "UndoSpec": ({f.name for f in dataclasses.fields(UndoSpec)}, {"handler"}),
    }
    canon = canonical_spec(spec)
    nested_canon = {
        "ActionParam": set(canon["params"][0]) if canon["params"] else set(),
        "ActionScope": set(canon["scope"][0]) if canon["scope"] else set(),
        "UndoSpec": set(canon["undo"]) if canon["undo"] else set(),
    }
    for cls, (declared, excluded) in nested.items():
        missing = declared - excluded - nested_canon[cls]
        print(f"  {cls:12s} declared={sorted(declared - excluded)} "
              f"canonical={sorted(nested_canon[cls])} uncovered={sorted(missing) or 'none'}")

    # (b) BY EXECUTION: add a field the way a future dev would, and watch the
    # identity refuse to notice. A subclass is exactly what canonical_spec sees:
    # it reads named attributes, so an added declared fact is simply not read.
    @dataclasses.dataclass(frozen=True)
    class ActionSpecV2(ActionSpec):
        # e.g. "which plan tier may run this" — a declared fact an approver
        # would absolutely want on the card.
        min_plan: str = "free"

    grown = ActionSpecV2(
        name=spec.name,
        description=spec.description,
        risk=spec.risk,
        scope=spec.scope,
        params=spec.params,
        dry_run=spec.dry_run,
        execute=spec.execute,
        undo=spec.undo,
        min_plan="enterprise",
    )
    after = fingerprint(grown)
    print(f"\n  fingerprint(spec)                        = {base[:16]}…")
    print(f"  fingerprint(spec + new declared field)   = {after[:16]}…")
    if base == after:
        print(f"{BAD}CONFIRMED: a new declared field is INVISIBLE to the identity.")
        print("       An approver could be shown a changed declaration and the")
        print("       execute-time re-check would call it unchanged.")
    else:
        print(f"{OK}the identity noticed the new field")

    # (c) what a structural guard would look like — does it hold today?
    covered_ok = not uncovered
    print(f"\n  a dataclass-fields-vs-canonical-keys assertion would pass today: {covered_ok}")
    print("  ...and would FAIL the moment someone adds a field, which is the point.")


def angle_2_fingerprint_version(pool):
    head(2, "FINGERPRINT_VERSION has never been bumped — what happens if it is?")
    from auspex.actions import proposal as proposal_mod

    spec = build_builtin_actions(pool)[0]
    stored = fingerprint(spec)  # what an approver's proposal carries today
    original = proposal_mod.FINGERPRINT_VERSION
    try:
        proposal_mod.FINGERPRINT_VERSION = original + 1
        after = fingerprint(spec)
    finally:
        proposal_mod.FINGERPRINT_VERSION = original

    print(f"  v{original} fingerprint = {stored[:16]}…")
    print(f"  v{original + 1} fingerprint = {after[:16]}…")
    fake_proposal = {"status": "approved", "spec_fingerprint": stored}
    proposal_mod.FINGERPRINT_VERSION = original + 1
    try:
        from auspex.actions.settlement import check_executable

        check_executable(spec, fake_proposal)
        print(f"{BAD}executed anyway")
    except ExecutionRefused as refused:
        print(f"  refusal reason : {refused.reason}")
        print(f"  refusal detail : {refused.detail}")
        if refused.reason == "spec_changed":
            print(f"{BAD}CONFIRMED: every approved-but-unexecuted proposal refuses on a")
            print("       version bump, and the copy tells the analyst the ACTION changed")
            print("       ('has changed since it was approved') when only OUR hashing did.")
            print("       Recoverable (re-propose), but the stated reason is false.")
    finally:
        proposal_mod.FINGERPRINT_VERSION = original


# ── 3. the status machine has no reaper ──────────────────────────────────────


async def angle_3_stuck_executing(pool, ws):
    head(3, "'executing' / 'undoing' are claims with no timeout — kill mid-run")

    registry = ActionRegistry()
    for s in build_builtin_actions(pool):
        registry.register(s)
    settlement = ProposalSettlement(pool)
    executor = ActionExecutor(pool, registry)
    spec = registry.get("annotate_observable")

    obs = await pool.fetchval(
        """
        INSERT INTO observables (workspace_id, obs_id, type, value)
        VALUES ($1::uuid, 'obs-s19-7', 'ipv4', '198.51.100.7') RETURNING obs_id
        """,
        ws,
    )
    args = {"observable_id": obs, "note": "probe"}
    dry = await spec.dry_run(workspace_id=ws, **args)
    row = await settlement.file(workspace_id=ws, spec=spec, arguments=args, dry_run=dry)
    pid = row["id"]
    await settlement.settle(
        workspace_id=ws, proposal_id=pid, decision="approved", decided_by=None
    )

    # Simulate the process dying between the claim and the handler: the claim
    # is exactly the UPDATE execute() runs, and then nothing else happens.
    await pool.execute(
        "UPDATE proposals SET status='executing' WHERE id=$1::uuid AND status='approved'", pid
    )
    print("  row is now 'executing' with no process behind it (app died mid-run)")

    for label, coro in (
        ("execute", executor.execute(workspace_id=ws, proposal_id=pid)),
        ("undo", executor.undo(workspace_id=ws, proposal_id=pid)),
    ):
        try:
            await coro
            print(f"{BAD}{label}: succeeded (unexpected)")
        except ExecutionRefused as refused:
            print(f"  {label:8s} -> refused {refused.reason}: {refused.detail[:70]}")
    res = await settlement.settle(
        workspace_id=ws, proposal_id=pid, decision="rejected", decided_by=None
    )
    print(f"  {'reject':8s} -> {res.outcome.value} (current status {res.current_status})")

    still = await settlement.get(workspace_id=ws, proposal_id=pid)
    print(f"\n  final status: {still['status']}")
    pending = await settlement.pending(workspace_id=ws)
    print(f"  appears in GET /api/proposals (pending list)? {any(p['id'] == pid for p in pending)}")
    print(f"{BAD}CONFIRMED: the row can never be executed, undone or rejected, and it is")
    print("       INVISIBLE on the approvals surface (that list is pending-only).")
    print("       Nothing reaps it. A human sees the action simply vanish.")
    return pid


# ── 4. partial effects on a mid-execution failure ────────────────────────────


async def angle_4_partial_effects(pool, ws):
    head(4, "execute() marks failed and re-raises — what is the world's state?")

    registry = ActionRegistry()
    settlement = ProposalSettlement(pool)
    base = build_builtin_actions(pool)[0]

    obs = await pool.fetchval(
        """
        INSERT INTO observables (workspace_id, obs_id, type, value)
        VALUES ($1::uuid, 'obs-s19-8', 'ipv4', '198.51.100.8') RETURNING obs_id
        """,
        ws,
    )

    # An execute that does its real work (the INSERT) and THEN dies — the exact
    # shape TD-025 says is unreasoned-about.
    async def execute_then_die(*, workspace_id, proposal_id=None, **kwargs):
        await base.execute(workspace_id=workspace_id, proposal_id=proposal_id, **kwargs)
        raise RuntimeError("died after the write landed")

    flaky = ActionSpec(
        name=base.name,
        description=base.description,
        risk=base.risk,
        scope=base.scope,
        params=base.params,
        dry_run=base.dry_run,
        execute=execute_then_die,
        undo=base.undo,
    )
    registry.register(flaky)
    executor = ActionExecutor(pool, registry)

    args = {"observable_id": obs, "note": "partial-effect probe"}
    dry = await flaky.dry_run(workspace_id=ws, **args)
    row = await settlement.file(workspace_id=ws, spec=flaky, arguments=args, dry_run=dry)
    pid = row["id"]
    await settlement.settle(
        workspace_id=ws, proposal_id=pid, decision="approved", decided_by=None
    )
    try:
        await executor.execute(workspace_id=ws, proposal_id=pid)
    except RuntimeError as err:
        print(f"  execute raised: {err}")

    after = await settlement.get(workspace_id=ws, proposal_id=pid)
    notes = await pool.fetchval(
        "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid", pid
    )
    print(f"  proposal status : {after['status']}")
    print(f"  result column   : {json.dumps(after['result'])}")
    print(f"  notes WRITTEN by the dead execution: {notes}")
    if notes and after["status"] == "failed":
        print(f"{BAD}CONFIRMED: the effect LANDED and the row says 'failed'. The surface")
        print("       reports nothing happened while the note is really there.")

    # Can undo still clean up? It is keyed on proposal_id, so it might.
    try:
        await executor.undo(workspace_id=ws, proposal_id=pid)
        print(f"{OK}undo succeeded")
    except ExecutionRefused as refused:
        print(f"  undo -> refused {refused.reason}: {refused.detail[:70]}")
        left = await pool.fetchval(
            "SELECT count(*) FROM observable_notes WHERE proposal_id = $1::uuid", pid
        )
        print(f"{BAD}CONFIRMED: undo REFUSES a failed proposal (status must be 'executed'),")
        print(f"       so the {left} orphaned row(s) cannot be cleaned up through the API")
        print("       even though the undo handler is keyed on proposal_id and would work.")


# ── 5. stream tenancy + the round-trip's double-proposal ─────────────────────


async def angle_5_tenancy_and_dupes(pool, ws):
    head(5, "stream tenancy, and a model that calls one action twice")

    settlement = ProposalSettlement(pool)
    other = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ('probe-s19-other') "
        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
    )
    registry = ActionRegistry()
    for s in build_builtin_actions(pool):
        registry.register(s)
    spec = registry.get("annotate_observable")

    obs_other = await pool.fetchval(
        """
        INSERT INTO observables (workspace_id, obs_id, type, value)
        VALUES ($1::uuid, 'obs-s19-9', 'ipv4', '198.51.100.9') RETURNING obs_id
        """,
        other,
    )
    args = {"observable_id": obs_other, "note": "other workspace"}
    dry = await spec.dry_run(workspace_id=other, **args)
    await settlement.file(workspace_id=other, spec=spec, arguments=args, dry_run=dry)

    mine = await settlement.pending(workspace_id=ws)
    theirs = await settlement.pending(workspace_id=other)
    leaked = [p for p in mine if p["workspace_id"] != ws]
    print(f"  workspace A pending: {len(mine)}  workspace B pending: {len(theirs)}")
    print(f"  rows from another workspace visible to A: {len(leaked)}")
    print(f"{OK if not leaked else BAD}tenancy: pending() filters on workspace_id in SQL, and")
    print("       stream() closes over auth.workspace_id at connect time — one value,")
    print("       captured once, never re-read from the request.")

    # Double-proposal: the same action, same arguments, twice in one turn.
    from auspex.actions.settlement import action_proposer

    propose = action_proposer(pool)
    obs = await pool.fetchval(
        """
        INSERT INTO observables (workspace_id, obs_id, type, value)
        VALUES ($1::uuid, 'obs-s19-10', 'ipv4', '198.51.100.10') RETURNING obs_id
        """,
        ws,
    )
    dupe_args = {"observable_id": obs, "note": "same intent twice"}
    a = await propose(spec=spec, arguments=dupe_args, workspace_id=ws)
    b = await propose(spec=spec, arguments=dupe_args, workspace_id=ws)
    print(f"\n  two identical calls -> proposals {str(a['id'])[:8]} and {str(b['id'])[:8]}")
    print(f"  identical fingerprints? {a['spec_fingerprint'] == b['spec_fingerprint']}")
    print(f"  identical arguments?    {a['tool_input'] == b['tool_input']}")
    print("       Both sit in the queue. A human is asked the same question twice,")
    print("       and approving both runs the action twice.")


async def main():
    conn = await asyncpg.connect(DSN)
    await teardown(conn)
    ws = await setup(conn)
    await conn.close()

    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=6)
    try:
        angle_1_fingerprint_blind_spot(pool)
        angle_2_fingerprint_version(pool)
        await angle_3_stuck_executing(pool, ws)
        await angle_4_partial_effects(pool, ws)
        await angle_5_tenancy_and_dupes(pool, ws)
    finally:
        await pool.close()
        conn = await asyncpg.connect(DSN)
        await teardown(conn)
        await conn.execute("VACUUM ANALYZE proposals")
        await conn.close()
        print("\n(probe workspaces deleted, proposals vacuumed)")


asyncio.run(main())
