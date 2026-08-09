"""Persistence for enrichment — S5, D-008 workspace-scoped throughout.

`observables` is keyed by (workspace_id, type, value): re-seeing a value
bumps `last_seen` on the same row. `verdicts` is APPEND-ONLY: every enrichment
run writes a new row; the current verdict is the latest by created_at. That
history is the Living Verdicts substrate (D-017) — retro-hunts and
falsification watchers (S7+) need the trail, not just the latest word.

Only enriched observables are persisted: skipped ones (private ranges,
ubiquitous domains, capped bulk-paste tails) were deliberately not looked up,
and a row without an enrichment attempt behind it would imply one happened.
"""

import json

import asyncpg

from auspex.enrich.types import EnrichmentOutcome
from auspex.enrich.verdict import synthesize
from auspex.retrohunt.flips import latest_verdict, record_flip_if_changed


async def persist_enrichment(pool: asyncpg.Pool, workspace_id, outcome: EnrichmentOutcome) -> int:
    """Upsert observables + append verdict rows. Returns verdicts written."""
    written = 0
    # Deterministic (type, value) order: two concurrent turns upserting an
    # overlapping observable set in one transaction each can deadlock if they
    # lock rows in different orders (S5 review finding).
    items = sorted(outcome.enriched, key=lambda i: (i.observable.type.value, i.observable.value))
    async with pool.acquire() as conn, conn.transaction():
        for item in items:
            o = item.observable
            # This upsert is load-bearing beyond the row it returns: DO UPDATE
            # takes a row lock held until commit, so two concurrent enrichments
            # of the SAME observable are serialized from here to the end of the
            # transaction. That is what lets the latest_verdict → INSERT →
            # record_flip_if_changed sequence below run without FOR UPDATE
            # (verified by execution, S15 Step 0). Moving the verdict write out
            # from under this lock would reintroduce the double-flip race.
            observable_row_id = await conn.fetchval(
                """
                INSERT INTO observables (workspace_id, obs_id, type, value)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (workspace_id, type, value)
                DO UPDATE SET last_seen = now()
                RETURNING id
                """,
                workspace_id,
                o.obs_id,
                o.type.value,
                o.value,
            )
            verdict = synthesize(o, item.signals)
            if verdict is None:
                continue
            # S14: the label this observable carried before this run. Read BEFORE
            # the insert below — afterwards "latest" IS the new row.
            previous = await latest_verdict(
                conn, workspace_id=workspace_id, observable_id=observable_row_id
            )
            details = {
                "signals": [
                    {
                        "provider": s.provider,
                        "label": s.label.value,
                        "confidence": s.confidence,
                        "summary": s.summary,
                        "evidence": s.evidence,
                    }
                    for s in item.signals
                ]
            }
            new_verdict_id = await conn.fetchval(
                """
                INSERT INTO verdicts
                    (workspace_id, observable_id, label, confidence_at_write,
                     half_life_days, floor, source, details)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                workspace_id,
                observable_row_id,
                verdict.label.value,
                verdict.confidence_at_write,
                verdict.half_life_days,
                verdict.floor,
                verdict.source,
                json.dumps(details),
            )
            # S14: a changed label becomes its own provenanced row, inside THIS
            # transaction — a flip that outlived a rolled-back verdict would
            # misdescribe the trail. The verdict write is untouched: flips are
            # a record of change, never a substitute for it.
            await record_flip_if_changed(
                conn,
                workspace_id=workspace_id,
                observable_id=observable_row_id,
                previous=previous,
                new_verdict_id=new_verdict_id,
                new_label=verdict.label.value,
            )
            written += 1
    return written
