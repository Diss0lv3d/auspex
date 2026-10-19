"""The first job kind (S31 design §2): proposals nobody decided within the TTL
become `expired`.

Not the guarantee: approve and reject already refuse an overdue proposal in the
UPDATE that would settle it (`ProposalSettlement.settle`). This makes the status
visible, so the approvals list and a reopened chat say what happened.
"""

from uuid import UUID

import asyncpg

from auspex.actions.settlement import PROPOSAL_TTL_SECONDS, ProposalSettlement
from auspex.jobs.queue import Job, JobKind
from auspex.jobs.worker import Schedule

SWEEP_EVERY_SECONDS = 300


async def _expire(pool: asyncpg.Pool, job: Job) -> dict:
    return {"expired": await ProposalSettlement(pool).expire_overdue(
        workspace_id=job.workspace_id)}


async def overdue_workspaces(pool: asyncpg.Pool) -> list[UUID]:
    """The workspaces holding a proposal nobody decided in time. The one read
    across workspaces here is system code choosing whom to enqueue for, like
    retro-hunt's sinks; it reads ids only, and each job then touches its own
    workspace."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT workspace_id FROM proposals
         WHERE status = 'pending_approval'
           AND created_at <= now() - make_interval(secs => $1::double precision)
        """,
        float(PROPOSAL_TTL_SECONDS),
    )
    return [r["workspace_id"] for r in rows]


EXPIRE = JobKind("proposals.expire", _expire)
EXPIRE_SCHEDULE = Schedule(EXPIRE, SWEEP_EVERY_SECONDS, overdue_workspaces)
