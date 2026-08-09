"""The retro-hunt ChangeSink — S14, the consumer S7 built the seam for.

`auspex/ingest/events.py` has emitted one DocChange per upserted doc since S7
into an explicit NullSink, "so S14 can attach a retro-hunt sink without touching
ingest". This is that sink: ingest keeps emitting exactly as it did, and this
class decides what is worth a sweep.

Failure posture matches the scheduler's: a retro-hunt failure must never take
down an ingest cycle. Intel landing in the KB is the more important of the two
jobs, and a swept batch we missed will be re-swept when the doc changes again —
so this logs and returns rather than raising into `run_cycle`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

import asyncpg

from auspex.retrohunt.store import record_matches, sweep
from auspex.retrohunt.types import TRIGGER_KINDS

if TYPE_CHECKING:
    # Type-only: importing auspex.ingest.events at runtime would run
    # auspex/ingest/__init__.py, which imports the scheduler, which imports this
    # module — a cycle. The sink satisfies ChangeSink structurally (Protocol), so
    # it needs the name for the annotation and nothing else.
    from auspex.ingest.events import DocChange

logger = logging.getLogger("auspex.retrohunt")


class RetroHuntSink:
    """Sweeps historical observables when material intel lands.

    One sweep per (feed, kind) group rather than one per change: the whole point
    of the indexed join is that 500 changed docs cost one query, not 500."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def emit(self, changes: Sequence[DocChange]) -> None:
        material = [c for c in changes if c.kind in TRIGGER_KINDS]
        if not material:
            return
        grouped: dict[tuple[str, str], list[str]] = {}
        for c in material:
            grouped.setdefault((c.feed, c.kind), []).append(c.doc_id)
        for (feed, kind), doc_ids in grouped.items():
            try:
                hits = await sweep(
                    self._pool, doc_ids=doc_ids, feed=feed, change_kind=kind
                )
                written = await record_matches(self._pool, hits)
            except Exception:  # noqa: BLE001 — ingest outlives retro-hunt failures
                logger.exception(
                    "retro-hunt sweep failed: feed=%s kind=%s docs=%d",
                    feed,
                    kind,
                    len(doc_ids),
                )
                continue
            if hits:
                # Counts only — never observable values (org data-handling rule).
                logger.info(
                    "retro-hunt: feed=%s kind=%s docs=%d hits=%d new_matches=%d",
                    feed,
                    kind,
                    len(doc_ids),
                    len(hits),
                    written,
                )
