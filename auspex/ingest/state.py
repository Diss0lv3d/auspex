"""ingest_state access — per-feed watermarks in Postgres (S7).

One row per global feed (partial unique index: `feed` WHERE workspace_id IS
NULL). `cursor` is jsonb because watermark shapes differ per feed; callers
advance it ONLY after the corresponding docs are safely in the KB — a crashed
cycle must re-cover its window on the next run (upserts make replays free).
"""

import json
from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True)
class FeedState:
    feed: str
    cursor: dict
    last_run_at: datetime | None
    last_status: str
    docs_upserted: int  # lifetime counter


class IngestStateStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, feed: str) -> FeedState | None:
        row = await self._pool.fetchrow(
            "SELECT feed, cursor, last_run_at, last_status, docs_upserted"
            " FROM ingest_state WHERE feed = $1 AND workspace_id IS NULL",
            feed,
        )
        if row is None:
            return None
        return FeedState(
            feed=row["feed"],
            cursor=json.loads(row["cursor"]),
            last_run_at=row["last_run_at"],
            last_status=row["last_status"],
            docs_upserted=row["docs_upserted"],
        )

    async def record(self, feed: str, *, cursor: dict, status: str, docs_delta: int = 0) -> None:
        await self._pool.execute(
            """
            INSERT INTO ingest_state (feed, cursor, last_run_at, last_status, docs_upserted)
            VALUES ($1, $2::jsonb, now(), $3, $4)
            ON CONFLICT (feed) WHERE workspace_id IS NULL DO UPDATE SET
                cursor = EXCLUDED.cursor,
                last_run_at = now(),
                last_status = EXCLUDED.last_status,
                docs_upserted = ingest_state.docs_upserted + $4,
                updated_at = now()
            """,
            feed,
            json.dumps(cursor),
            status,
            docs_delta,
        )
