"""Per-workspace spend limits — S19 (Hardening), TD-018.

Against live Postgres, because the whole guarantee is in one SQL statement: the
ceiling is enforced in the same UPSERT that reads the counter. A test that
mocked the pool would prove the arithmetic and miss the only interesting
property — that two concurrent turns cannot both spend the last unit.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from auspex.db import create_pool
from auspex.limits import (
    PLANS,
    WINDOW,
    Meter,
    UsageLimiter,
    plan_for,
    window_start,
)


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
        "t-limits",
    )
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


async def _set_plan(pool, workspace_id, plan: str):
    await pool.execute("UPDATE workspaces SET plan = $2 WHERE id = $1", workspace_id, plan)


# -- the plan seam -------------------------------------------------------------


def test_an_unknown_plan_resolves_to_the_most_restrictive_one():
    """A typo in a plan column must never be a way to buy unlimited inference.
    Unknown ⇒ the tightest plan, never unmetered — the same posture as the D-014
    gate defaulting to 'requires approval'."""
    assert plan_for("enterprise").inference_calls_per_hour is None
    assert plan_for("typo").inference_calls_per_hour == PLANS["free"].inference_calls_per_hour
    assert plan_for(None).inference_calls_per_hour == PLANS["free"].inference_calls_per_hour
    assert plan_for("").inference_calls_per_hour == PLANS["free"].inference_calls_per_hour


async def test_a_new_workspace_is_on_the_default_plan(workspace_id, pool):
    """The migration's DEFAULT does the work — a workspace created by any route,
    including ones written before S19, is metered rather than unmetered."""
    plan = await pool.fetchval("SELECT plan FROM workspaces WHERE id = $1", workspace_id)
    assert plan == "free"


def test_windows_are_truncated_so_every_replica_agrees():
    """No coordination: the boundary is a function of the clock, so two app
    replicas counting the same workspace land on the same row."""
    moment = datetime(2026, 8, 15, 14, 37, 12, 500, tzinfo=UTC)
    assert window_start(moment) == datetime(2026, 8, 15, 14, 0, 0, 0, tzinfo=UTC)
    assert window_start(moment) + WINDOW == datetime(2026, 8, 15, 15, 0, tzinfo=UTC)


# -- counting and refusing -----------------------------------------------------


async def test_claims_count_up_and_then_refuse(pool, workspace_id):
    limiter = UsageLimiter(pool)
    limit = PLANS["free"].inference_calls_per_hour

    for expected in (1, 2, 3):
        allowance = await limiter.claim(workspace_id=workspace_id)
        assert allowance.allowed
        assert allowance.used == expected
        assert allowance.remaining == limit - expected

    # jump to the ceiling
    await limiter.claim(workspace_id=workspace_id, units=limit - 3)
    assert await limiter.usage(workspace_id=workspace_id) == limit

    refused = await limiter.claim(workspace_id=workspace_id)
    assert not refused.allowed
    assert refused.used == limit  # NOT limit+1 — a refused claim spends nothing
    assert refused.remaining == 0


async def test_a_refused_claim_does_not_increment(pool, workspace_id):
    """The counter is evidence. If a refusal still incremented, a workspace at
    its ceiling would drift further from it on every retry and the reported
    'used' would stop meaning anything."""
    limiter = UsageLimiter(pool)
    limit = PLANS["free"].inference_calls_per_hour
    await limiter.claim(workspace_id=workspace_id, units=limit)

    for _ in range(5):
        assert not (await limiter.claim(workspace_id=workspace_id)).allowed
    assert await limiter.usage(workspace_id=workspace_id) == limit


async def test_a_multi_unit_claim_is_all_or_nothing(pool, workspace_id):
    """The two-pass turn claims 2. With one unit left it must be refused whole,
    not half-served — the endpoint would be called twice or not at all."""
    limiter = UsageLimiter(pool)
    limit = PLANS["free"].inference_calls_per_hour
    await limiter.claim(workspace_id=workspace_id, units=limit - 1)

    refused = await limiter.claim(workspace_id=workspace_id, units=2)
    assert not refused.allowed
    assert refused.used == limit - 1  # the room that IS left, reported honestly
    assert (await limiter.claim(workspace_id=workspace_id, units=1)).allowed


async def test_concurrent_claims_cannot_both_spend_the_last_unit(pool, workspace_id):
    """The property the whole design exists for, raced rather than reasoned
    about. Eight concurrent claims with one unit of headroom: exactly one wins.

    'Read the count, decide, then increment' would pass a sequential test and
    fail this one — and its failure mode is serving free inference.
    """
    limiter = UsageLimiter(pool)
    limit = PLANS["free"].inference_calls_per_hour
    await limiter.claim(workspace_id=workspace_id, units=limit - 1)

    results = await asyncio.gather(
        *[UsageLimiter(pool).claim(workspace_id=workspace_id) for _ in range(8)]
    )
    assert sum(1 for r in results if r.allowed) == 1, [r.used for r in results]
    assert await limiter.usage(workspace_id=workspace_id) == limit


async def test_an_unmetered_plan_still_counts(pool, workspace_id):
    """Enterprise is unmetered, not unmeasured. A plan that stopped counting
    could not answer 'what did this workspace spend?' — which is exactly what
    the gating skeleton exists to make answerable later."""
    await _set_plan(pool, workspace_id, "enterprise")
    limiter = UsageLimiter(pool)
    for _ in range(3):
        allowance = await limiter.claim(workspace_id=workspace_id)
        assert allowance.allowed
        assert allowance.limit is None
        assert allowance.remaining is None
    assert await limiter.usage(workspace_id=workspace_id) == 3


async def test_workspaces_are_metered_independently(pool, workspace_id):
    """D-008 tenancy, applied to spend: one workspace exhausting its plan must
    not affect another's."""
    other = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ('t-limits-other')"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
    )
    try:
        limiter = UsageLimiter(pool)
        limit = PLANS["free"].inference_calls_per_hour
        await limiter.claim(workspace_id=workspace_id, units=limit)
        assert not (await limiter.claim(workspace_id=workspace_id)).allowed
        assert (await limiter.claim(workspace_id=other)).allowed
        assert await limiter.usage(workspace_id=other) == 1
    finally:
        await pool.execute("DELETE FROM workspaces WHERE id = $1", other)


async def test_a_new_window_starts_clean(pool, workspace_id):
    """The limit is per window. An exhausted workspace recovers on the hour
    without anyone resetting anything."""
    limiter = UsageLimiter(pool)
    limit = PLANS["free"].inference_calls_per_hour
    now = datetime.now(UTC)
    await limiter.claim(workspace_id=workspace_id, units=limit, now=now)
    assert not (await limiter.claim(workspace_id=workspace_id, now=now)).allowed

    later = now + WINDOW
    fresh = await limiter.claim(workspace_id=workspace_id, now=later)
    assert fresh.allowed and fresh.used == 1


# -- honest degradation --------------------------------------------------------


async def test_the_refusal_names_the_meter_the_ceiling_and_the_reset(pool, workspace_id):
    """S19 constraint: never a silent truncation, never a generic 500. An
    analyst who hits this has to be able to tell whether to wait or to ask for a
    bigger plan."""
    limiter = UsageLimiter(pool)
    limit = PLANS["free"].inference_calls_per_hour
    await limiter.claim(workspace_id=workspace_id, units=limit)
    refused = await limiter.claim(workspace_id=workspace_id)

    text = refused.refusal_text
    assert str(limit) in text
    assert "inference calls" in text
    assert "resets at" in text.lower()
    assert refused.resets_at.strftime("%H:%M") in text
    # and it says what still works — a ceiling is not an outage
    assert "IOC checks" in text and "definitions" in text


async def test_the_snapshot_reports_a_meter_that_has_never_been_used(pool, workspace_id):
    """The S16 lesson: a meter that only appears once it has a value cannot be
    told from a meter that is broken. Every meter is always reported."""
    snapshot = await UsageLimiter(pool).snapshot(workspace_id=workspace_id)
    assert snapshot["plan"] == "free"
    assert set(snapshot["meters"]) == {m.value for m in Meter}
    inference = snapshot["meters"][Meter.INFERENCE_CALLS.value]
    assert inference == {
        "used": 0,
        "limit": PLANS["free"].inference_calls_per_hour,
        "remaining": PLANS["free"].inference_calls_per_hour,
    }


# -- housekeeping --------------------------------------------------------------


async def test_closed_windows_are_swept(pool, workspace_id):
    """Without this the table grows one row per workspace per meter per hour,
    forever. Counters bound a window and are evidence for nothing after it."""
    limiter = UsageLimiter(pool)
    old = datetime.now(UTC) - timedelta(hours=5)
    await limiter.claim(workspace_id=workspace_id, now=old)
    await limiter.claim(workspace_id=workspace_id)

    assert await limiter.sweep() >= 1
    rows = await pool.fetchval(
        "SELECT count(*) FROM usage_counters WHERE workspace_id = $1", workspace_id
    )
    assert rows == 1  # the current window survives
