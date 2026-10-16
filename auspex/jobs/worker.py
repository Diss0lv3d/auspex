"""The in-app jobs worker (D-065; docs/superpowers/specs/2026-10-16-s31-jobs-design.md §2).

The ingest scheduler's shape (`auspex/ingest/scheduler.py`): `tick()` is the
testable unit, `run()` loops forever, re-raises CancelledError, logs and
survives anything else. Each tick runs the due schedules, then claims and runs
jobs until none is ready (at most MAX_JOBS_PER_TICK). The worker's claim scope
names only the kinds it holds, so it never claims a job it cannot run.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import asyncpg

from auspex.jobs.queue import (
    MAX_ERROR_CHARS,
    ClaimScope,
    JobKind,
    JobLost,
    claim,
    complete,
    enqueue,
    fail,
)

logger = logging.getLogger(__name__)

POLL_SECONDS = 5
# Bounded so one tick returns to its schedules and its sleep even under a
# backlog; the next tick carries on where this one stopped.
MAX_JOBS_PER_TICK = 50


@dataclass(frozen=True)
class Schedule:
    """A kind enqueued for each workspace `due_workspaces` names, once per
    `every_seconds` bucket of the wall clock. The bucket is in the job's
    idempotency key, so two ticks, or two app replicas, enqueue it once."""

    kind: JobKind
    every_seconds: int
    due_workspaces: Callable[[asyncpg.Pool], Awaitable[list[UUID]]]


@dataclass(frozen=True)
class TickReport:
    enqueued: int
    ran: int
    failed: int


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]


class JobWorker:
    def __init__(
        self,
        pool: asyncpg.Pool,
        kinds: Sequence[JobKind],
        schedules: Sequence[Schedule] = (),
        *,
        name: str = "app-worker",
        enabled: bool = True,
        poll_seconds: float = POLL_SECONDS,
        max_per_tick: int = MAX_JOBS_PER_TICK,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._kinds = {k.name: k for k in kinds}
        if len(self._kinds) != len(kinds):
            raise ValueError("two job kinds share a name")
        for schedule in schedules:
            if schedule.kind.name not in self._kinds:
                raise ValueError(f"a schedule for {schedule.kind.name!r}, a kind this worker"
                                 " does not run")
        self._scope = ClaimScope(kinds=frozenset(self._kinds))
        self._pool = pool
        self._schedules = tuple(schedules)
        self._name = name
        self.enabled = enabled
        self._poll = poll_seconds
        self._max = max_per_tick
        self._now = now
        self._sleep = sleep
        self._last_bucket: dict[str, int] = {}

    async def run(self) -> None:
        if not self.enabled:
            logger.info("jobs worker disabled (JOBS_WORKER_ENABLED=false)")
            return
        while True:
            try:
                report = await self.tick()
                if report.enqueued or report.ran or report.failed:
                    logger.info("jobs tick: %s", report)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — the loop must survive anything
                logger.exception("jobs tick failed; retrying next interval")
            await self._sleep(self._poll)

    async def tick(self) -> TickReport:
        enqueued = await self._run_schedules()
        ran = failed = 0
        for _ in range(self._max):
            job = await claim(self._pool, self._scope, claimer=self._name)
            if job is None:
                break
            try:
                result = await self._kinds[job.kind].handler(self._pool, job)
                await complete(self._pool, job.id, job.claim_token, result or {})
            except asyncio.CancelledError:
                raise
            except JobLost:
                # Its lease was re-claimed while it ran (or it went dead): the
                # answer belongs to whoever holds it now. Logged, never raised.
                logger.warning("job %s (%s) finished after losing its claim", job.id, job.kind)
                continue
            except Exception as exc:  # noqa: BLE001 — a failing job must not stop the tick
                failed += 1
                try:
                    await fail(self._pool, job.id, job.claim_token, _error_text(exc))
                except JobLost:
                    logger.warning("job %s (%s) failed after losing its claim", job.id, job.kind)
                logger.warning("job %s (%s) failed: %s", job.id, job.kind, _error_text(exc))
                continue
            ran += 1
        return TickReport(enqueued=enqueued, ran=ran, failed=failed)

    async def _run_schedules(self) -> int:
        enqueued = 0
        stamp = int(self._now().timestamp())
        for schedule in self._schedules:
            bucket = stamp // schedule.every_seconds
            if self._last_bucket.get(schedule.kind.name) == bucket:
                continue
            try:
                workspaces = await schedule.due_workspaces(self._pool)
                for workspace_id in workspaces:
                    _, created = await enqueue(
                        self._pool, workspace_id=workspace_id, kind=schedule.kind,
                        idempotency_key=f"{schedule.kind.name}:{bucket}",
                    )
                    enqueued += int(created)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — a broken schedule must not stop the jobs
                logger.exception("schedule %s failed; it retries next tick", schedule.kind.name)
                continue
            self._last_bucket[schedule.kind.name] = bucket
        return enqueued
