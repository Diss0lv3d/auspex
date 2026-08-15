"""S18 Step 0 — lead 1: what the rewritten _DECAYED_SQL costs when a workspace
has many distinct half-lives, and where the 365-day crossover actually is.

The S17 rewrite was measured on a workspace with exactly THREE half-life
families. bounds = edges x half_lives, so each extra distinct value adds three
more LATERAL descents. Seed 3 / 20 / 50 and measure. Then run the OLD query
(pre-e57ab0c) against the SAME table across window sizes to bound the regression
that S17 recorded but never bounded.

Run from the repo root with .venv/bin/python. Deletes its workspaces at the end
(STATE.md: probe residue made the plan suite take 150s instead of 21s).
"""

import asyncio
import statistics
import sys

import asyncpg

DSN = "postgresql://auspex:auspex@localhost:55432/auspex"
ROWS = 25_000
EDGES = [1.0, 2.0, 4.0]  # read live below; this is only the fallback

NEW_SQL = open("auspex/timeline/store.py").read().split('_DECAYED_SQL = """')[1].split('"""')[0]

OLD_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (v.observable_id)
           v.observable_id, v.label, v.confidence_at_write, v.floor,
           v.half_life_days, v.created_at
    FROM verdicts v
    WHERE v.workspace_id = $1
    ORDER BY v.observable_id, v.created_at DESC, v.id DESC
)
SELECT l.observable_id, l.label, l.confidence_at_write, l.floor,
       l.half_life_days, l.created_at, o.obs_id, o.type, o.value
FROM latest l
JOIN observables o ON o.id = l.observable_id AND o.workspace_id = $1
WHERE l.floor < l.confidence_at_write
  AND EXISTS (
      SELECT 1 FROM unnest($4::float8[]) AS e(edge)
      WHERE ($2::timestamptz - l.created_at)
                >= (e.edge * l.half_life_days) * interval '1 day'
        AND ($3::timestamptz - l.created_at)
                < (e.edge * l.half_life_days) * interval '1 day'
  )
ORDER BY EXTRACT(EPOCH FROM ($2::timestamptz - l.created_at))
         / (l.half_life_days * 86400) DESC
LIMIT $5
"""


async def seed(pool, name, n_halflives):
    ws = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1) ON CONFLICT (name) DO UPDATE "
        "SET name = EXCLUDED.name RETURNING id",
        name,
    )
    await pool.execute("DELETE FROM observables WHERE workspace_id = $1", ws)
    # n_halflives distinct values, spread the way real ones would be: a few short
    # curves, many medium, some long. i % n picks the family so every family gets
    # roughly ROWS/n rows.
    await pool.execute(
        """
        WITH obs AS (
            INSERT INTO observables (workspace_id, obs_id, type, value)
            SELECT $1, 'hlfan-' || i, 'domain', 'd' || i || '.' || $3 || '.fan.test'
            FROM generate_series(1, $2) AS s(i)
            ON CONFLICT (workspace_id, type, value) DO NOTHING
            RETURNING id, obs_id
        )
        INSERT INTO verdicts (workspace_id, observable_id, label,
            confidence_at_write, half_life_days, floor, source, created_at)
        SELECT $1, obs.id, 'suspicious', 0.6,
               -- distinct half-lives: 7, 14, 21, ... capped at $4 families
               (7.0 * (1 + (substr(obs.obs_id, 7)::int % $4)))::real,
               0.0, 'enrichment:seed',
               clock_timestamp() - ((
                   ('x' || substr(md5(obs.obs_id), 1, 8))::bit(32)::int % 730
               ) || ' days')::interval
        FROM obs
        """,
        ws,
        ROWS,
        name,
        n_halflives,
    )
    await pool.execute("VACUUM (ANALYZE) observables")
    await pool.execute("VACUUM (ANALYZE) verdicts")
    got = await pool.fetchval(
        "SELECT count(DISTINCT half_life_days) FROM verdicts WHERE workspace_id = $1", ws
    )
    rows = await pool.fetchval("SELECT count(*) FROM verdicts WHERE workspace_id = $1", ws)
    print(f"  seeded {name}: {rows} verdicts, {got} distinct half-lives")
    return ws


async def timed(pool, sql, ws, now, since, edges, limit, runs=5):
    """Median wall time in ms over `runs`, plus the row count."""
    ts = []
    n = 0
    for _ in range(runs):
        import time

        t0 = time.perf_counter()
        rows = await pool.fetch(sql, ws, now, since, edges, limit)
        ts.append((time.perf_counter() - t0) * 1000)
        n = len(rows)
    return statistics.median(ts), n


async def explain(pool, sql, ws, now, since, edges, limit):
    plan = "\n".join(
        r[0]
        for r in await pool.fetch(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", ws, now, since, edges, limit)
    )
    return plan


async def main():
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    # read the real edges from the code
    src = open("auspex/timeline/store.py").read()
    from datetime import timedelta

    sys.path.insert(0, ".")
    from auspex.timeline.staleness import (
        AGING_AT_HALF_LIVES,
        LAPSED_AT_HALF_LIVES,
        STALE_AT_HALF_LIVES,
    )

    edges = [AGING_AT_HALF_LIVES, STALE_AT_HALF_LIVES, LAPSED_AT_HALF_LIVES]
    print(f"band edges = {edges}  (bounds = {len(edges)} x distinct half-lives)")

    made = []
    try:
        print("\n=== LEAD 1a: cost vs number of distinct half-lives (7-day window) ===")
        for n in (3, 20, 50):
            name = f"probe-hlfan-{n}"
            ws = await seed(pool, name, n)
            made.append(ws)
            now = await pool.fetchval("SELECT clock_timestamp()")
            since = now - timedelta(days=7)
            ms, cnt = await timed(pool, NEW_SQL, ws, now, since, edges, 50)
            plan = await explain(pool, NEW_SQL, ws, now, since, edges, 50)
            seq = "Seq Scan on verdicts" in plan
            idx = "idx_verdicts_ws_hl_created" in plan
            # how many index descents did the bounds LATERAL actually do?
            loops = [
                ln.strip()
                for ln in plan.splitlines()
                if "idx_verdicts_ws_hl_created" in ln or "loops=" in ln and "Recursive" in ln
            ]
            print(f"\n  half-lives={n:>3}  ->  {ms:7.1f} ms, {cnt} rows, "
                  f"seq_scan={seq}, uses_index={idx}")
            for ln in loops[:3]:
                print(f"      {ln[:150]}")
            # the recursive CTE's own cost
            for ln in plan.splitlines():
                if "Recursive Union" in ln or "CTE hl" in ln:
                    print(f"      {ln.strip()[:150]}")

        print("\n=== LEAD 1b: where is the 365-day crossover? (50 half-lives ws) ===")
        ws = made[-1]
        now = await pool.fetchval("SELECT clock_timestamp()")
        print(f"  {'window':>8} | {'new ms':>9} | {'old ms':>9} | {'ratio':>7} | new/old rows")
        for days in (7, 30, 60, 90, 120, 180, 270, 365):
            since = now - timedelta(days=days)
            new_ms, new_n = await timed(pool, NEW_SQL, ws, now, since, edges, 50)
            old_ms, old_n = await timed(pool, OLD_SQL, ws, now, since, edges, 50)
            print(f"  {days:>8} | {new_ms:>9.1f} | {old_ms:>9.1f} | "
                  f"{new_ms / old_ms:>7.2f} | {new_n}/{old_n}")

        print("\n=== LEAD 1c: same crossover on the THREE-half-life shape (S17's) ===")
        ws3 = made[0]
        now = await pool.fetchval("SELECT clock_timestamp()")
        print(f"  {'window':>8} | {'new ms':>9} | {'old ms':>9} | {'ratio':>7} | new/old rows")
        for days in (7, 30, 90, 180, 365):
            since = now - timedelta(days=days)
            new_ms, new_n = await timed(pool, NEW_SQL, ws3, now, since, edges, 50)
            old_ms, old_n = await timed(pool, OLD_SQL, ws3, now, since, edges, 50)
            print(f"  {days:>8} | {new_ms:>9.1f} | {old_ms:>9.1f} | "
                  f"{new_ms / old_ms:>7.2f} | {new_n}/{old_n}")
    finally:
        for ws in made:
            await pool.execute("DELETE FROM observables WHERE workspace_id = $1", ws)
            await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)
        await pool.execute("VACUUM (ANALYZE) observables")
        await pool.execute("VACUUM (ANALYZE) verdicts")
        print("\n  [cleanup] probe workspaces deleted, tables vacuumed")
        await pool.close()


asyncio.run(main())
