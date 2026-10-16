"""S31 (D-065): the jobs queue against live Postgres
(docs/superpowers/specs/2026-10-16-s31-jobs-design.md §1).

Test kinds are named `t.s31.*`. The app container's worker holds only its own
kinds, so it never claims a job made here."""

import asyncio
import uuid

import pytest
from _tenancy import drop_orgs, make_org, make_workspace

from auspex.db import create_pool
from auspex.jobs.queue import ClaimScope, JobKind, JobLost, claim, complete, enqueue, fail

PREFIX = "t-s31-jobs"


async def _noop(pool, job) -> dict:
    return {}


KIND = JobKind("t.s31.queue", _noop)


@pytest.fixture
async def pool(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    await drop_orgs(pool, PREFIX)
    try:
        yield pool
    finally:
        await drop_orgs(pool, PREFIX)
        await pool.close()


@pytest.fixture
def ws(pool):
    async def make(name: str):
        org = await make_org(pool, f"{PREFIX}-{name}", "direct")
        return await make_workspace(pool, f"{PREFIX}-{name}", org)
    return make


async def test_a_job_carries_its_kinds_lease_and_attempts(pool, ws):
    a = await ws("a")
    kind = JobKind("t.s31.queue", _noop, lease_seconds=90, max_attempts=3)
    job, created = await enqueue(pool, workspace_id=a, kind=kind, idempotency_key="k1",
                                 payload={"x": 1})
    assert created is True
    assert (job.workspace_id, job.kind, job.status, job.attempts) == (a, "t.s31.queue", "queued", 0)
    assert (job.lease_seconds, job.max_attempts, job.payload) == (90, 3, {"x": 1})
    assert job.claim_token is None and job.integration_id is None


async def test_the_same_key_twice_is_one_job(pool, ws):
    a = await ws("a")
    first, created = await enqueue(pool, workspace_id=a, kind=KIND, idempotency_key="once",
                                   payload={"n": 1})
    second, again = await enqueue(pool, workspace_id=a, kind=KIND, idempotency_key="once",
                                  payload={"n": 2})
    assert (created, again) == (True, False)
    assert second.id == first.id and second.payload == {"n": 1}
    assert await pool.fetchval(
        "SELECT count(*) FROM jobs WHERE workspace_id = $1 AND idempotency_key = 'once'", a) == 1


async def test_the_same_key_in_two_workspaces_is_two_jobs(pool, ws):
    a, b = await ws("a"), await ws("b")
    ja, _ = await enqueue(pool, workspace_id=a, kind=KIND, idempotency_key="shared")
    jb, created = await enqueue(pool, workspace_id=b, kind=KIND, idempotency_key="shared")
    assert created is True and ja.id != jb.id


@pytest.mark.parametrize("bad", [
    {"name": "  "}, {"lease_seconds": 0}, {"max_attempts": 0},
])
def test_a_kind_needs_a_name_a_lease_and_an_attempt(bad):
    with pytest.raises(ValueError):
        JobKind(**{"name": "t.s31.queue", "handler": _noop, **bad})


async def test_a_job_needs_a_key(pool, ws):
    a = await ws("a")
    with pytest.raises(ValueError, match="idempotency key"):
        await enqueue(pool, workspace_id=a, kind=KIND, idempotency_key="  ")


CLAIM = JobKind("t.s31.claim", _noop)


def _scope(*workspaces, kinds=("t.s31.claim",), integrations=None) -> ClaimScope:
    return ClaimScope(kinds=frozenset(kinds), workspace_ids=frozenset(workspaces),
                      integration_ids=integrations)


async def _expire_lease(pool, job_id) -> None:
    await pool.execute(
        "UPDATE jobs SET lease_expires_at = now() - interval '1 second' WHERE id = $1", job_id)


async def _claimed_by(pool, job_id):
    return await pool.fetchval("SELECT claimed_by FROM jobs WHERE id = $1", job_id)


async def _make_due(pool, job_id) -> None:
    await pool.execute("UPDATE jobs SET run_after = now() WHERE id = $1", job_id)


async def test_a_claim_takes_a_queued_job_and_stamps_a_token_and_lease(pool, ws):
    a = await ws("a")
    queued, _ = await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="k")
    job = await claim(pool, _scope(a), claimer="tester")
    assert job is not None and job.id == queued.id
    assert (job.status, job.attempts, job.claimed_by) == ("claimed", 1, "tester")
    assert job.claim_token is not None
    lease = await pool.fetchval(
        "SELECT EXTRACT(EPOCH FROM lease_expires_at - now()) FROM jobs WHERE id = $1", job.id)
    assert 55 <= lease <= 61
    assert await claim(pool, _scope(a), claimer="tester") is None  # held, not re-claimable


async def test_two_claimers_racing_one_job_get_exactly_one_claim(pool, ws):
    a = await ws("a")
    for n in range(10):
        await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key=f"race-{n}")
        got = await asyncio.gather(claim(pool, _scope(a), claimer="one"),
                                   claim(pool, _scope(a), claimer="two"))
        assert sum(j is not None for j in got) == 1, got


async def test_twenty_jobs_four_claimers_each_job_claimed_once(pool, ws):
    a = await ws("a")
    ids = {(await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key=f"j{n}"))[0].id
           for n in range(20)}

    async def drain(name):
        mine = []
        while (job := await claim(pool, _scope(a), claimer=name)) is not None:
            mine.append(job.id)
        return mine

    claimed = [i for batch in await asyncio.gather(*(drain(f"c{n}") for n in range(4)))
               for i in batch]
    assert sorted(claimed) == sorted(ids) and len(claimed) == len(set(claimed))


async def test_a_job_not_yet_due_is_not_claimed(pool, ws):
    a = await ws("a")
    await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="later")
    await pool.execute("UPDATE jobs SET run_after = now() + interval '1 hour'"
                       " WHERE workspace_id = $1", a)
    assert await claim(pool, _scope(a), claimer="t") is None


async def test_complete_needs_the_claims_token(pool, ws):
    a = await ws("a")
    await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="k")
    job = await claim(pool, _scope(a), claimer="t")
    with pytest.raises(JobLost):
        await complete(pool, job.id, uuid.uuid4(), {"ok": True})
    await complete(pool, job.id, job.claim_token, {"ok": True})
    row = await pool.fetchrow("SELECT status, result, claim_token, claimed_by, finished_at"
                              " FROM jobs WHERE id = $1", job.id)
    assert row["status"] == "done" and row["claim_token"] is None
    assert row["claimed_by"] is None
    assert row["finished_at"] is not None and '"ok": true' in row["result"]
    with pytest.raises(JobLost):  # a second answer for a finished job
        await complete(pool, job.id, job.claim_token, {"ok": True})


async def test_an_expired_lease_is_reclaimed_and_the_old_token_is_refused(pool, ws):
    a = await ws("a")
    await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="k")
    first = await claim(pool, _scope(a), claimer="slow")
    await _expire_lease(pool, first.id)
    second = await claim(pool, _scope(a), claimer="fast")
    assert second.id == first.id and second.claim_token != first.claim_token
    assert second.attempts == 2
    with pytest.raises(JobLost):
        await complete(pool, first.id, first.claim_token, {})
    with pytest.raises(JobLost):
        await fail(pool, first.id, first.claim_token, "late")


async def test_an_answer_after_the_lease_but_before_a_reclaim_is_accepted(pool, ws):
    """Spec §1: the token still holds the row until someone re-claims it."""
    a = await ws("a")
    await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="k")
    job = await claim(pool, _scope(a), claimer="slow")
    await _expire_lease(pool, job.id)
    await complete(pool, job.id, job.claim_token, {"late": True})
    assert await pool.fetchval("SELECT status FROM jobs WHERE id = $1", job.id) == "done"


async def test_an_expired_lease_with_no_attempts_left_goes_dead(pool, ws):
    a = await ws("a")
    once = JobKind("t.s31.claim", _noop, max_attempts=1)
    await enqueue(pool, workspace_id=a, kind=once, idempotency_key="k")
    job = await claim(pool, _scope(a), claimer="t")
    await _expire_lease(pool, job.id)
    assert await claim(pool, _scope(a), claimer="t") is None
    row = await pool.fetchrow("SELECT status, last_error, claim_token, claimed_by FROM jobs"
                              " WHERE id = $1", job.id)
    assert (row["status"], row["last_error"], row["claim_token"]) == ("dead", "lease expired", None)
    assert row["claimed_by"] is None


async def test_a_failure_backs_off_doubling_to_a_cap_then_dies(pool, ws):
    a = await ws("a")
    seven = JobKind("t.s31.claim", _noop, max_attempts=7)
    await enqueue(pool, workspace_id=a, kind=seven, idempotency_key="k")
    for expected in (30, 60, 120, 240, 480, 900):  # 30·2^5 = 960, capped at 900
        job = await claim(pool, _scope(a), claimer="t")
        assert await fail(pool, job.id, job.claim_token, "boom") == "queued"
        assert await _claimed_by(pool, job.id) is None
        wait = await pool.fetchval(
            "SELECT EXTRACT(EPOCH FROM run_after - now()) FROM jobs WHERE id = $1", job.id)
        assert expected - 3 <= wait <= expected + 1, (job.attempts, wait)
        await _make_due(pool, job.id)
    job = await claim(pool, _scope(a), claimer="t")
    assert job.attempts == 7
    assert await fail(pool, job.id, job.claim_token, "boom") == "dead"
    assert await _claimed_by(pool, job.id) is None
    assert await claim(pool, _scope(a), claimer="t") is None


async def test_a_permanent_failure_is_failed_and_never_retried(pool, ws):
    a = await ws("a")
    await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="k")
    job = await claim(pool, _scope(a), claimer="t")
    assert await fail(pool, job.id, job.claim_token, "bad payload", permanent=True) == "failed"
    assert await _claimed_by(pool, job.id) is None
    await _make_due(pool, job.id)
    assert await claim(pool, _scope(a), claimer="t") is None


async def test_an_enormous_error_is_stored_capped(pool, ws):
    a = await ws("a")
    await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="k")
    job = await claim(pool, _scope(a), claimer="t")
    await fail(pool, job.id, job.claim_token, "x" * 100_000)
    assert await pool.fetchval("SELECT length(last_error) FROM jobs WHERE id = $1",
                               job.id) == 2000


async def test_a_scope_claims_only_its_kinds(pool, ws):
    a = await ws("a")
    other = JobKind("t.s31.other", _noop)
    await enqueue(pool, workspace_id=a, kind=other, idempotency_key="k")
    assert await claim(pool, _scope(a), claimer="t") is None
    assert (await claim(pool, _scope(a, kinds=("t.s31.other",)), claimer="t")) is not None


async def test_a_scope_claims_only_its_workspaces(pool, ws):
    a, b = await ws("a"), await ws("b")
    await enqueue(pool, workspace_id=b, kind=CLAIM, idempotency_key="k")
    assert await claim(pool, _scope(a), claimer="t") is None
    got = await claim(pool, _scope(b), claimer="t")
    assert got is not None and got.workspace_id == b


async def test_a_scope_claims_an_integrations_job_only_by_naming_it(pool, ws):
    a = await ws("a")
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="k", integration_id=mine)
    assert await claim(pool, _scope(a), claimer="t") is None  # None means: no integration
    assert await claim(pool, _scope(a, integrations=frozenset({theirs})), claimer="t") is None
    got = await claim(pool, _scope(a, integrations=frozenset({mine})), claimer="t")
    assert got is not None and got.integration_id == mine


async def test_an_integration_scope_never_claims_an_in_app_job(pool, ws):
    a = await ws("a")
    await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="k")
    assert await claim(pool, _scope(a, integrations=frozenset({uuid.uuid4()})),
                       claimer="t") is None


def test_a_scope_must_name_a_kind():
    with pytest.raises(ValueError, match="kinds"):
        ClaimScope(kinds=frozenset())


async def test_a_claim_skips_a_row_another_claimer_holds_locked(pool, ws):
    """SKIP LOCKED itself: with the first job's row locked, a claim moves on to the
    second at once instead of waiting on the lock."""
    a = await ws("a")
    first, _ = await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="first")
    second, _ = await enqueue(pool, workspace_id=a, kind=CLAIM, idempotency_key="second")
    await pool.execute("UPDATE jobs SET run_after = now() - interval '1 hour' WHERE id = $1",
                       first.id)
    async with pool.acquire() as holder, holder.transaction():
        await holder.execute("SELECT 1 FROM jobs WHERE id = $1 FOR UPDATE", first.id)
        got = await asyncio.wait_for(claim(pool, _scope(a), claimer="t"), timeout=5)
    assert got is not None and got.id == second.id


FAIR = JobKind("t.s31.fair", _noop)


async def test_one_busy_client_cannot_starve_another(pool, ws):
    """A bulk-enqueued 50 jobs first; B's one job, enqueued after, is served
    within the first two claims, not after A's fifty."""
    a, b = await ws("busy"), await ws("quiet")
    for n in range(50):
        await enqueue(pool, workspace_id=a, kind=FAIR, idempotency_key=f"a{n}")
    await enqueue(pool, workspace_id=b, kind=FAIR, idempotency_key="b0")
    scope = _scope(a, b, kinds=("t.s31.fair",))
    served = [(await claim(pool, scope, claimer="t")).workspace_id for _ in range(2)]
    assert b in served


async def test_claims_alternate_between_workspaces_while_both_have_work(pool, ws):
    a, b = await ws("first"), await ws("second")
    for n in range(6):
        await enqueue(pool, workspace_id=a, kind=FAIR, idempotency_key=f"a{n}")
    for n in range(6):
        await enqueue(pool, workspace_id=b, kind=FAIR, idempotency_key=f"b{n}")
    scope = _scope(a, b, kinds=("t.s31.fair",))
    served = [(await claim(pool, scope, claimer="t")).workspace_id for _ in range(12)]
    assert served == [a, b] * 6
