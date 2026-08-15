"""S18 Step 0 — lead 1, part 2: find where the fan-out DOES start to hurt, and
bound the 365-day tail at the size the original S17 defect was measured at.

50 distinct half-lives cost nothing (2.4 ms). That refutes the suspicion at the
scale the prompt named, but it does not bound it: half_life_days is a `real`, and
a per-source decay curve could produce hundreds or thousands of distinct values.
Push to 500 and 2000. Separately: the crossover said the new shape loses past
~180 days, measured at 25k rows — re-measure the tail at 100k, the size where
the original 143 ms defect lived.
"""

import asyncio
import statistics
import time
from datetime import timedelta

import asyncpg

DSN = "postgresql://auspex:auspex@localhost:55432/auspex"

NEW_SQL = open("auspex/timeline/store.py").read().split('_DECAYED_SQL = """')[1].split('"""')[0]
OLD_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (v.observable_id)
           v.observable_id, v.label, v.confidence_at_write, v.floor,
           v.half_life_days, v.created_at
    FROM verdicts v WHERE v.workspace_id = $1
    ORDER BY v.observable_id, v.created_at DESC, v.id DESC
)
SELECT l.observable_id, l.label, l.confidence_at_write, l.floor,
       l.half_life_days, l.created_at, o.obs_id, o.type, o.value
FROM latest l
JOIN observables o ON o.id = l.observable_id AND o.workspace_id = $1
WHERE l.floor < l.confidence_at_write
  AND EXISTS (
      SELECT 1 FROM unnest($4::float8[]) AS e(edge)
      WHERE ($2::timestamptz - l.created_at) >= (e.edge * l.half_life_days) * interval '1 day'
        AND ($3::timestamptz - l.created_at) <  (e.edge * l.half_life_days) * interval '1 day'
  )
ORDER BY EXTRACT(EPOCH FROM ($2::timestamptz - l.created_at)) / (l.half_life_days * 86400) DESC
LIMIT $5
"""


async def seed(pool, name, rows, n_hl):
    ws = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1) ON CONFLICT (name) DO UPDATE "
        "SET name = EXCLUDED.name RETURNING id",
        name,
    )
    await pool.execute("DELETE FROM observables WHERE workspace_id = $1", ws)
    await pool.execute(
        """
        WITH obs AS (
            INSERT INTO observables (workspace_id, obs_id, type, value)
            SELECT $1, 'hlx-' || i, 'domain', 'd' || i || '.' || $3 || '.x.test'
            FROM generate_series(1, $2) AS s(i)
            ON CONFLICT (workspace_id, type, value) DO NOTHING
            RETURNING id, obs_id
        )
        INSERT INTO verdicts (workspace_id, observable_id, label,
            confidence_at_write, half_life_days, floor, source, created_at)
        SELECT $1, obs.id, 'suspicious', 0.6,
               -- $4 distinct values, kept small enough to stay realistic decay
               -- curves (0.5 .. 0.5+$4/2 days) while still being DISTINCT reals
               (0.5 + (substr(obs.obs_id, 5)::int % $4) * 0.5)::real,
               0.0, 'enrichment:seed',
               clock_timestamp() - ((
                   ('x' || substr(md5(obs.obs_id), 1, 8))::bit(32)::int % 730
               ) || ' days')::interval
        FROM obs
        """,
        ws, rows, name, n_hl,
    )
    await pool.execute("VACUUM (ANALYZE) observables")
    await pool.execute("VACUUM (ANALYZE) verdicts")
    got = await pool.fetchval(
        "SELECT count(DISTINCT half_life_days) FROM verdicts WHERE workspace_id = $1", ws
    )
    n = await pool.fetchval("SELECT count(*) FROM verdicts WHERE workspace_id = $1", ws)
    return ws, n, got


async def timed(pool, sql, ws, now, since, edges, limit, runs=3):
    ts = []
    cnt = 0
    for _ in range(runs):
        t0 = time.perf_counter()
        rows = await pool.fetch(sql, ws, now, since, edges, limit)
        ts.append((time.perf_counter() - t0) * 1000)
        cnt = len(rows)
    return statistics.median(ts), cnt


async def main():
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    import sys

    sys.path.insert(0, ".")
    from auspex.timeline.staleness import (
        AGING_AT_HALF_LIVES,
        LAPSED_AT_HALF_LIVES,
        STALE_AT_HALF_LIVES,
    )

    edges = [AGING_AT_HALF_LIVES, STALE_AT_HALF_LIVES, LAPSED_AT_HALF_LIVES]
    made = []
    try:
        print("=== LEAD 1d: pathological half-life counts (25k rows, 7-day window) ===")
        print(f"  {'distinct hl':>11} | {'descents':>8} | {'new ms':>8} | {'old ms':>8} | seq?")
        for n_hl in (50, 200, 500, 2000):
            name = f"probe-hlx-{n_hl}"
            ws, rows, got = await seed(pool, name, 25_000, n_hl)
            made.append(ws)
            now = await pool.fetchval("SELECT clock_timestamp()")
            since = now - timedelta(days=7)
            new_ms, _ = await timed(pool, NEW_SQL, ws, now, since, edges, 50)
            old_ms, _ = await timed(pool, OLD_SQL, ws, now, since, edges, 50)
            plan = "\n".join(
                r[0] for r in await pool.fetch(
                    f"EXPLAIN (ANALYZE) {NEW_SQL}", ws, now, since, edges, 50
                )
            )
            seq = "Seq Scan on verdicts" in plan
            print(f"  {got:>11} | {got * len(edges):>8} | {new_ms:>8.1f} | "
                  f"{old_ms:>8.1f} | {seq}")

        print("\n=== LEAD 1e: the 365-day tail at 100k rows (the size of the S17 defect) ===")
        ws, rows, got = await seed(pool, "probe-hl-tail", 100_000, 12)
        made.append(ws)
        print(f"  seeded {rows} verdicts, {got} distinct half-lives")
        now = await pool.fetchval("SELECT clock_timestamp()")
        print(f"  {'window':>8} | {'new ms':>9} | {'old ms':>9} | {'ratio':>7}")
        for days in (7, 30, 90, 180, 270, 365):
            since = now - timedelta(days=days)
            new_ms, _ = await timed(pool, NEW_SQL, ws, now, since, edges, 50)
            old_ms, _ = await timed(pool, OLD_SQL, ws, now, since, edges, 50)
            print(f"  {days:>8} | {new_ms:>9.1f} | {old_ms:>9.1f} | {new_ms / old_ms:>7.2f}")
    finally:
        for ws in made:
            await pool.execute("DELETE FROM observables WHERE workspace_id = $1", ws)
            await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)
        await pool.execute("VACUUM (ANALYZE) observables")
        await pool.execute("VACUUM (ANALYZE) verdicts")
        print("\n  [cleanup] probe workspaces deleted, tables vacuumed")
        await pool.close()


asyncio.run(main())
