"""IngestStateStore round-trip against the live dev Postgres (the suite's
schema tests already depend on it; migrations run via the client fixture).
Rows are cleaned up per test — the persistent dev DB stays as found."""

import asyncpg
import pytest

from auspex.ingest.state import IngestStateStore

TEST_FEED = "test-feed-roundtrip"


@pytest.fixture
async def pool(client, settings):
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    yield pool
    await pool.execute("DELETE FROM ingest_state WHERE feed LIKE 'test-%'")
    await pool.close()


async def test_state_roundtrip_upserts_one_global_row(pool):
    store = IngestStateStore(pool)
    assert await store.get(TEST_FEED) is None  # unknown feed reads as None
    await store.record(
        TEST_FEED,
        cursor={"last_mod_end": "2026-07-16T00:00:00+00:00"},
        status="window done",
        docs_delta=14,
    )
    first = await store.get(TEST_FEED)
    assert first is not None
    assert first.cursor == {"last_mod_end": "2026-07-16T00:00:00+00:00"}
    assert first.last_status == "window done"
    assert first.docs_upserted == 14
    assert first.last_run_at is not None
    # second record UPDATES the same row (partial unique index on global feed)
    # and accumulates the lifetime doc counter
    await store.record(
        TEST_FEED,
        cursor={"last_mod_end": "2026-07-17T00:00:00+00:00"},
        status="next window",
        docs_delta=3,
    )
    second = await store.get(TEST_FEED)
    assert second.cursor["last_mod_end"] == "2026-07-17T00:00:00+00:00"
    assert second.docs_upserted == 17
    count = await pool.fetchval("SELECT count(*) FROM ingest_state WHERE feed = $1", TEST_FEED)
    assert count == 1
