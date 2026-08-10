"""The watcher ChangeSink — S15.

S14 attached one consumer to the S7 seam; this is the second, and it is a
PARALLEL sink rather than an extension of the retro-hunt one (the S15 prompt
allows either). Two reasons, both about not coupling things that answer
different questions:

* The retro-hunt sweep asks "does this doc touch anything we have seen?" —
  observable-keyed and verdict-agnostic. A watcher asks "does this doc
  contradict a claim a specific verdict made?" Folding the second into the
  first would make falsification coverage a silent function of `TRIGGER_KINDS`,
  so renaming a retro-hunt trigger would quietly stop checking claims.
* A failure in one must not cost the other. Both already swallow their own
  exceptions so ingest survives them (the scheduler's posture); as separate
  sinks, a broken watcher check cannot take the sweep down with it.

The cost of independence is a second indexed join over the same doc ids —
measured at 32 chunk queries for a 1,600-id KEV first run, which the S15 Step-0
timings put well inside the cycle's noise.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

import asyncpg

from auspex.checks import CheckerStatus, FailureCounter
from auspex.watchers.store import check_documents, satisfy_documents
from auspex.watchers.types import SATISFIED_BY_CHANGE

if TYPE_CHECKING:
    # Type-only for the same reason as the retro-hunt sink: importing
    # auspex.ingest.events at runtime pulls in the scheduler, which imports
    # this module. The class satisfies ChangeSink structurally (Protocol).
    from auspex.ingest.events import DocChange

logger = logging.getLogger("auspex.watchers")


class WatcherSink:
    """Checks registered falsification conditions against newly-changed docs."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        # S16: the swallow below is correct and stays, but it used to be the
        # whole story. See auspex/checks.py — a checker that fails every cycle
        # and one with nothing to do are indistinguishable at every analyst
        # surface, and this surface's whole job is claims about absence.
        self._health = FailureCounter("watchers")

    @property
    def health(self) -> CheckerStatus:
        return self._health.status

    async def emit(self, changes: Sequence[DocChange]) -> None:
        grouped: dict[str, list[str]] = {}
        for c in changes:
            if c.kind in SATISFIED_BY_CHANGE:
                grouped.setdefault(c.kind, []).append(c.doc_id)
        failed = False
        for change_kind, doc_ids in grouped.items():
            kind = SATISFIED_BY_CHANGE[change_kind]
            try:
                hits = await check_documents(self._pool, doc_ids=doc_ids, kind=kind)
                moved = await satisfy_documents(
                    self._pool, hits, change_kind=change_kind
                )
            except Exception as exc:  # noqa: BLE001 — ingest outlives watcher failures
                failed = True
                self._health.failed(exc)
                logger.exception(
                    "watcher check failed: change=%s kind=%s docs=%d",
                    change_kind,
                    kind.value,
                    len(doc_ids),
                )
                continue
            if hits:
                # Counts only — never observable values (org data-handling rule).
                logger.info(
                    "watchers: change=%s kind=%s docs=%d hits=%d satisfied=%d",
                    change_kind,
                    kind.value,
                    len(doc_ids),
                    len(hits),
                    moved,
                )
        # Success is recorded only when a check actually RAN. A cycle carrying
        # no relevant changes is not evidence the checker works, and resetting
        # on it would let a broken checker look healthy in the quiet weeks —
        # which are exactly the weeks an analyst would be trusting the digest.
        if grouped and not failed:
            self._health.succeeded()


class FanoutSink:
    """Emits one batch of DocChanges to several sinks, isolating failures.

    The scheduler holds exactly one sink (S7's seam), and S15 needs two
    consumers. A list comprehension in the scheduler would have done it, but
    then the scheduler owns the failure policy for each consumer — this keeps
    "ingest survives its consumers" in one place, and makes a third consumer a
    constructor argument rather than an edit to `run_cycle`."""

    def __init__(self, *sinks) -> None:
        self._sinks = sinks
        # For a sink that raises OUT of emit rather than swallowing internally.
        # The two real consumers never do — which is why each carries its own
        # counter — but a consumer that dies loudly must not be the one failure
        # mode nothing counts.
        self._health = FailureCounter("fanout")

    def health(self) -> tuple[CheckerStatus, ...]:
        """Each consumer's own status, plus this fanout's. Sinks that do not
        track themselves are simply absent — the digest reports what is known,
        never a default that reads as healthy."""
        own = tuple(
            s
            for s in (getattr(sink, "health", None) for sink in self._sinks)
            if isinstance(s, CheckerStatus)
        )
        return (*own, self._health.status)

    async def emit(self, changes: Sequence[DocChange]) -> None:
        failed = False
        for sink in self._sinks:
            try:
                await sink.emit(changes)
            except Exception as exc:  # noqa: BLE001 — one consumer must not sink another
                failed = True
                self._health.failed(exc)
                logger.exception("change sink failed: %s", type(sink).__name__)
        if not failed:
            self._health.succeeded()
