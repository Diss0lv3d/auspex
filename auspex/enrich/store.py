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


async def persist_enrichment(pool: asyncpg.Pool, workspace_id, outcome: EnrichmentOutcome) -> int:
    """Upsert observables + append verdict rows. Returns verdicts written."""
    written = 0
    async with pool.acquire() as conn, conn.transaction():
        for item in outcome.enriched:
            o = item.observable
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
            await conn.execute(
                """
                INSERT INTO verdicts
                    (workspace_id, observable_id, label, confidence_at_write,
                     half_life_days, floor, source, details)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
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
            written += 1
    return written
