"""S31 (D-065): the in-app worker, driven tick by tick against live Postgres
(docs/superpowers/specs/2026-10-16-s31-jobs-design.md §2). Kinds are
`t.s31.*`; the app container's worker never claims them."""

import asyncio
from datetime import UTC, datetime

import pytest
from _tenancy import drop_orgs, make_org, make_workspace

from auspex.db import create_pool
from auspex.jobs.queue import ClaimScope, JobKind, claim, enqueue
from auspex.jobs.worker import JobWorker, Schedule

PREFIX = "t-s31-worker"
NOW = datetime(2026, 10, 16, 12, 0, 7, tzinfo=UTC)


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


def _recording_kind(name="t.s31.worker", seen=None, *, raise_when=None, result=None):
    async def handler(pool, job):
        if seen is not None:
            seen.append(job.id)
        if raise_when is not None and job.payload.get(raise_when):
            raise RuntimeError(f"boom on {job.idempotency_key}")
        return result if result is not None else {"ran": job.idempotency_key}
    return JobKind(name, handler)


def _worker(pool, kinds, schedules=(), **kw):
    return JobWorker(pool, kinds, schedules, now=lambda: NOW, **kw)


async def _status(pool, job_id):
    return await pool.fetchrow("SELECT status, result, last_error FROM jobs WHERE id = $1", job_id)


async def test_a_tick_runs_due_schedules_then_the_jobs(pool, ws):
    a = await ws("a")
    seen = []
    kind = _recording_kind(seen=seen)

    async def due(_pool):
        return [a]

    report = await _worker(pool, [kind], [Schedule(kind, 300, due)]).tick()
    assert (report.enqueued, report.ran, report.failed) == (1, 1, 0)
    row = await pool.fetchrow("SELECT status, idempotency_key FROM jobs WHERE workspace_id = $1", a)
    bucket = int(NOW.timestamp()) // 300
    assert (row["status"], row["idempotency_key"]) == ("done", f"t.s31.worker:{bucket}")


async def test_a_bucket_enqueues_once_even_across_two_workers(pool, ws):
    a = await ws("a")
    kind = _recording_kind()

    async def due(_pool):
        return [a]

    first = _worker(pool, [kind], [Schedule(kind, 300, due)])
    assert (await first.tick()).enqueued == 1
    assert (await first.tick()).enqueued == 0  # same bucket: not re-run
    replica = _worker(pool, [kind], [Schedule(kind, 300, due)])
    assert (await replica.tick()).enqueued == 0  # same bucket, another process
    assert await pool.fetchval("SELECT count(*) FROM jobs WHERE workspace_id = $1", a) == 1


async def test_a_raising_handler_is_failed_and_the_tick_goes_on(pool, ws):
    a = await ws("a")
    kind = _recording_kind(raise_when="boom")
    bad, _ = await enqueue(pool, workspace_id=a, kind=kind, idempotency_key="bad",
                           payload={"boom": True})
    good, _ = await enqueue(pool, workspace_id=a, kind=kind, idempotency_key="good")
    report = await _worker(pool, [kind]).tick()
    assert (report.ran, report.failed) == (1, 1)
    failed = await _status(pool, bad.id)
    assert failed["status"] == "queued" and "RuntimeError: boom on bad" in failed["last_error"]
    assert (await _status(pool, good.id))["status"] == "done"


async def test_a_result_json_cannot_carry_fails_the_job_not_the_tick(pool, ws):
    a = await ws("a")
    kind = _recording_kind(result={"at": datetime.now(UTC)})
    job, _ = await enqueue(pool, workspace_id=a, kind=kind, idempotency_key="k")
    report = await _worker(pool, [kind]).tick()
    assert report.failed == 1
    row = await _status(pool, job.id)
    assert row["status"] == "queued" and "TypeError" in row["last_error"]


async def test_a_handler_that_outlived_its_lease_has_its_answer_refused(pool, ws):
    """Review focus 1: the job was re-claimed while the first run went on; the
    first run's answer is refused and logged, and the tick goes on."""
    a = await ws("a")

    async def slow(pool_, job):
        await pool_.execute("UPDATE jobs SET lease_expires_at = now() - interval '1 second'"
                            " WHERE id = $1", job.id)
        again = await claim(pool_, ClaimScope(kinds=frozenset({"t.s31.worker"}),
                                              workspace_ids=frozenset({a})), claimer="other")
        assert again is not None and again.id == job.id
        return {"late": True}

    kind = JobKind("t.s31.worker", slow)
    job, _ = await enqueue(pool, workspace_id=a, kind=kind, idempotency_key="k")
    report = await _worker(pool, [kind], max_per_tick=1).tick()
    assert report.ran == 0 and report.failed == 0
    row = await pool.fetchrow("SELECT status, claimed_by, result FROM jobs WHERE id = $1", job.id)
    assert (row["status"], row["claimed_by"], row["result"]) == ("claimed", "other", None)


async def test_a_worker_claims_only_its_own_kinds(pool, ws):
    a = await ws("a")
    mine, theirs = _recording_kind(), _recording_kind("t.s31.theirs")
    job, _ = await enqueue(pool, workspace_id=a, kind=theirs, idempotency_key="k")
    await _worker(pool, [mine]).tick()
    assert (await _status(pool, job.id))["status"] == "queued"


async def test_a_schedule_that_raises_does_not_stop_the_jobs(pool, ws):
    a = await ws("a")
    kind = _recording_kind()

    async def broken(_pool):
        raise ConnectionError("db away")

    job, _ = await enqueue(pool, workspace_id=a, kind=kind, idempotency_key="k")
    report = await _worker(pool, [kind], [Schedule(kind, 300, broken)]).tick()
    assert report.enqueued == 0 and report.ran == 1
    assert (await _status(pool, job.id))["status"] == "done"


async def test_run_survives_a_failing_tick_and_stops_when_cancelled(pool):
    ticks, sleeps = [], []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    worker = JobWorker(pool, [_recording_kind()], sleep=sleep, poll_seconds=5)

    async def failing_tick():
        ticks.append(1)
        raise RuntimeError("tick blew up")

    worker.tick = failing_tick
    with pytest.raises(asyncio.CancelledError):
        await worker.run()
    assert len(ticks) == 2 and sleeps == [5, 5]


async def test_a_disabled_worker_returns_at_once(pool):
    worker = JobWorker(pool, [_recording_kind()], enabled=False)
    await asyncio.wait_for(worker.run(), timeout=1)


def test_a_worker_refuses_two_kinds_with_one_name_and_an_orphan_schedule():
    with pytest.raises(ValueError, match="share a name"):
        JobWorker(None, [_recording_kind(), _recording_kind()])

    async def due(_pool):
        return []

    with pytest.raises(ValueError, match="does not run"):
        JobWorker(None, [_recording_kind()],
                  [Schedule(_recording_kind("t.s31.elsewhere"), 300, due)])


def test_the_suite_runs_with_the_worker_pinned_off(settings):
    """Hermetic: no background claimer races a test (auspex.devhost)."""
    assert settings.jobs_worker_enabled is False


def test_the_worker_is_on_unless_told_otherwise(monkeypatch):
    from auspex.config import Settings

    monkeypatch.delenv("JOBS_WORKER_ENABLED", raising=False)
    assert Settings(_env_file=None).jobs_worker_enabled is True


def test_the_lifespan_starts_the_worker_and_shutdown_cancels_it(settings):
    from fastapi.testclient import TestClient

    from auspex.app import create_app
    from auspex.config import Settings

    app = create_app(Settings(jobs_worker_enabled=True, secret_key=settings.secret_key))
    with TestClient(app):
        task = app.state.jobs_task
        assert app.state.jobs_worker.enabled is True
        assert not task.done()
    assert task.cancelled()
