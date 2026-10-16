"""S31 (D-065): the jobs queue against live Postgres
(docs/superpowers/specs/2026-10-16-s31-jobs-design.md §1).

Test kinds are named `t.s31.*`. The app container's worker holds only its own
kinds, so it never claims a job made here."""

import pytest
from _tenancy import drop_orgs, make_org, make_workspace

from auspex.db import create_pool
from auspex.jobs.queue import JobKind, enqueue

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
