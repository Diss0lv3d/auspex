"""A compiled connector action's roles run as jobs on the integration's Edge Agent (S34,
design decisions 3, 6 and 9). `dispatcher(pool, integration)` is the `Dispatch` that
`compile_action` closes over: it enqueues `connector.action.<step>` for the integration
and waits, within the step's bound, for the answer the edge API already checked
against the manifest (`auspex_sdk.validate`, by job kind).

Job keys. execute and undo are keyed by the operation's own idempotency key, so asking
again finds the same job: its answer if it has one, its failure if it has none, never a
second run. dry_run and observe are questions about now, keyed afresh each time.

A wait that runs out raises. A job still queued then is failed on the spot, so it is
never claimed after the core stopped listening; one already claimed is left to its
lease (one attempt, `kinds.ACTION_KINDS`).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict
from typing import Any

import asyncpg

from auspex.connectors.compile import Dispatch
from auspex.connectors.jobs import ConnectorJobPayload
from auspex.connectors.kinds import ACTION_KINDS
from auspex.integrations.store import Integration
from auspex.jobs.queue import enqueue

# Seconds the core waits for each step's answer (design decisions 3 and 6).
WAITS = {"dry_run": 30.0, "execute": 60.0, "undo": 60.0, "observe": 30.0}
POLL_SECONDS = 0.25
_KEYED = frozenset({"execute", "undo"})
MAX_RETRIES = 20  # fresh jobs after failed ones, per operation key


class DispatchFailed(RuntimeError):
    """The Edge Agent did not answer in time, or answered with an error. In words.
    `model_feedback` is the part the agent loop may hand the model: the platform's own
    sentence, never the agent's or the connector's text (D-045's rule).

    `may_have_run`: an agent claimed the job and no answer came (the wait ran out, or
    its lease did). The command may have run, or may still be running, so the settlement
    records its effects as unknown instead of asking observe now (fresh review of S34,
    #2): a look while execute still runs could say 0 and mark a change that landed
    `failed`, which cannot be undone."""

    def __init__(self, message: str, model_feedback: str, *,
                 may_have_run: bool = False) -> None:
        super().__init__(message)
        self.model_feedback = model_feedback
        self.may_have_run = may_have_run


def _step(kind: str) -> str:
    step = kind.rsplit(".", 1)[1]
    if step not in ACTION_KINDS:
        raise ValueError(f"{kind} is not an action job kind")
    return step


def _payload(job: ConnectorJobPayload, integration: Integration) -> dict:
    out = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in asdict(job).items()}
    out["config"] = integration.config  # the agent resolves its secret: names (D-063)
    return out


def _what(step: str) -> str:
    return "the preview" if step == "dry_run" else step


def dispatcher(pool: asyncpg.Pool, integration: Integration, *,
               waits: dict[str, float] = WAITS, poll: float = POLL_SECONDS) -> Dispatch:
    async def dispatch(kind: str, job: ConnectorJobPayload) -> Any:
        step = _step(kind)
        base = (f"connector.{step}:{job.idempotency_key}"
                if step in _KEYED and job.idempotency_key
                else f"connector.{step}:{uuid.uuid4()}")
        # A job under this key that FAILED did not run, or ran and said it failed: a
        # retry gets a fresh job (PR #53 review #1), the handler keeping the operation
        # key so the vendor side still drops a repeat. One that is done, or dead (it may
        # have run), keeps answering for the key: never a second run.
        for attempt in range(MAX_RETRIES + 1):
            key = base if attempt == 0 else f"{base}#retry{attempt}"
            queued, _ = await enqueue(pool, workspace_id=integration.workspace_id,
                                      kind=ACTION_KINDS[step], idempotency_key=key,
                                      integration_id=integration.id,
                                      payload=_payload(job, integration))
            if queued.status != "failed":
                break
        else:
            raise DispatchFailed(
                f"{_what(step)} has failed or been cancelled {MAX_RETRIES + 1} times; read the"
                " integration's jobs for why (a connector error, or edits cancelling them)",
                f"not proposed: {_what(step)} failed too many times")
        return await _answer(pool, queued.id, step, waits[step], poll)

    return dispatch


async def _answer(pool: asyncpg.Pool, job_id: uuid.UUID, step: str, bound: float,
                  poll: float) -> Any:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + bound
    while True:
        row = await pool.fetchrow("SELECT status, result, last_error FROM jobs WHERE id = $1",
                                  job_id)
        if row["status"] == "done":
            result = row["result"]
            return json.loads(result) if isinstance(result, str) else result
        if row["status"] in ("failed", "dead"):
            # dead: claimed, then the lease ran out unanswered (one attempt).
            raise DispatchFailed(f"the Edge Agent could not run {_what(step)}:"
                                 f" {row['last_error'] or 'no reason given'}",
                                 f"not proposed: the Edge Agent could not run {_what(step)}",
                                 may_have_run=row["status"] == "dead")
        if loop.time() >= deadline:
            cancelled = await pool.fetchval(
                "UPDATE jobs SET status = 'failed', finished_at = now(), last_error ="
                " 'the core stopped waiting before an Edge Agent claimed it'"
                " WHERE id = $1 AND status = 'queued' RETURNING id", job_id)
            said = f"the Edge Agent did not answer {_what(step)} within {bound:g} s"
            raise DispatchFailed(said, f"not proposed: {said}", may_have_run=cancelled is None)
        await asyncio.sleep(min(poll, max(0.0, deadline - loop.time())))


__all__ = ["WAITS", "DispatchFailed", "dispatcher"]
