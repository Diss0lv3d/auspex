"""The connector job kinds the core enqueues (S33, S34). Their handlers never run in the
app process: an Edge Agent claims them over the edge API (D-062), so the in-app worker
never lists them. `connector.test` is a question asked now, never re-run later.

An action's jobs (S34) are tried once: a lease that runs out marks the job dead, never
re-runs it. An execute whose answer was lost may have run; asking it again would run
it twice (design decision 9). Settlement's failure path asks observe instead (TD-028b).
"""

from __future__ import annotations

from auspex.jobs.queue import Job, JobKind


async def _never_in_app(pool, job: Job) -> dict:
    raise RuntimeError(f"{job.kind} runs on an Edge Agent, never in the app (D-062)")


# 90 s: above the agent's 60 s subprocess timeout, so a slow test is not reclaimed.
CONNECTOR_TEST = JobKind("connector.test", _never_in_app, lease_seconds=90, max_attempts=1)

# One per step of an action (`connector.action.<step>`), same lease, one attempt.
ACTION_KINDS = {
    step: JobKind(f"connector.action.{step}", _never_in_app, lease_seconds=90, max_attempts=1)
    for step in ("dry_run", "execute", "undo", "observe")
}

EDGE_KINDS = frozenset({CONNECTOR_TEST.name, *(k.name for k in ACTION_KINDS.values())})
