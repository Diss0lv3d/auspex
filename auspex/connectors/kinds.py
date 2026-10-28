"""The connector job kinds the core enqueues (S33). Their handlers never run in the
app process: an Edge Agent claims them over the edge API (D-062), so the in-app worker
never lists them. `connector.test` is a question asked now, never re-run later."""

from __future__ import annotations

from auspex.jobs.queue import Job, JobKind


async def _never_in_app(pool, job: Job) -> dict:
    raise RuntimeError(f"{job.kind} runs on an Edge Agent, never in the app (D-062)")


# 90 s: above the agent's 60 s subprocess timeout, so a slow test is not reclaimed.
CONNECTOR_TEST = JobKind("connector.test", _never_in_app, lease_seconds=90, max_attempts=1)

EDGE_KINDS = frozenset({CONNECTOR_TEST.name})
