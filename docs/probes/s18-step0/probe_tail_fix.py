"""S18 Step 0 — lead 1, part 3: can the 365-day tail be fixed, or is it a trade?

Measured: at 100k verdicts the new shape costs 161 ms at a 365-day window vs the
old shape's 134 ms — i.e. the MAXIMUM LEGAL window is now slower than the 143 ms
defect S17 rewrote the query to fix. `days` is a user-supplied query parameter
(le=MAX_SINCE_DAYS=365), so any analyst can ask for it.

Why it loses at wide windows: the bounds ranges approach the whole history, so
nearly every verdict becomes a candidate, and EVERY candidate then pays one index
descent for "is this still the current verdict?" — 30k+ probes to return 50 rows.

The ordering key (half-lives elapsed) is computable from the candidate row ALONE.
So sort the candidates first and let the LIMIT stop the current-check early: 50-ish
probes instead of 30k. Test that variant for both SPEED and IDENTICAL OUTPUT.
"""

import asyncio
import statistics
import time
from datetime import timedelta

import asyncpg

DSN = "postgresql://auspex:auspex@localhost:55432/auspex"

CURRENT = open("auspex/timeline/store.py").read().split('_DECAYED_SQL = """')[1].split('"""')[0]

# Same bounds/candidates CTEs; the difference is the last stage. Candidates are
# ordered by decay FIRST (a key each row carries on its own), then the "is it
# still current?" probe runs row by row and the LIMIT stops it early.
VARIANT = """
WITH RECURSIVE hl AS (
    SELECT (SELECT v.half_life_days FROM verdicts v
            WHERE v.workspace_id = $1
            ORDER BY v.half_life_days LIMIT 1) AS half_life_days
  UNION ALL
    SELECT (SELECT v.half_life_days FROM verdicts v
            WHERE v.workspace_id = $1 AND v.half_life_days > hl.half_life_days
            ORDER BY v.half_life_days LIMIT 1)
    FROM hl WHERE hl.half_life_days IS NOT NULL
), bounds AS (
    SELECT hl.half_life_days,
           $3::timestamptz - (e.edge * hl.half_life_days) * interval '1 day' AS lo,
           $2::timestamptz - (e.edge * hl.half_life_days) * interval '1 day' AS hi
    FROM hl, unnest($4::float8[]) AS e(edge)
    WHERE hl.half_life_days IS NOT NULL
), candidates AS (
    SELECT DISTINCT c.id, c.observable_id, c.label, c.confidence_at_write,
           c.floor, c.half_life_days, c.created_at
    FROM bounds b
    JOIN LATERAL (
        SELECT v.id, v.observable_id, v.label, v.confidence_at_write, v.floor,
               v.half_life_days, v.created_at
        FROM verdicts v
        WHERE v.workspace_id = $1
          AND v.half_life_days = b.half_life_days
          AND v.created_at > b.lo
          AND v.created_at <= b.hi
          AND v.floor < v.confidence_at_write
        OFFSET 0
    ) c ON TRUE
), ranked AS (
    SELECT * FROM candidates
    ORDER BY EXTRACT(EPOCH FROM ($2::timestamptz - created_at))
             / (half_life_days * 86400) DESC
)
SELECT c.observable_id, c.label, c.confidence_at_write, c.floor,
       c.half_life_days, c.created_at, o.obs_id, o.type, o.value
FROM ranked c
JOIN observables o ON o.id = c.observable_id AND o.workspace_id = $1
WHERE c.id = (
    SELECT v.id FROM verdicts v
    WHERE v.workspace_id = $1 AND v.observable_id = c.observable_id
    ORDER BY v.created_at DESC, v.id DESC
    LIMIT 1
)
LIMIT $5
"""


async def seed(pool, name, rows, n_hl):
    ws = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1) ON CONFLICT (name) DO UPDATE "
        "SET name = EXCLUDED.name RETURNING id", name,
    )
    await pool.execute("DELETE FROM observables WHERE workspace_id = $1", ws)
    await pool.execute(
        """
        WITH obs AS (
            INSERT INTO observables (workspace_id, obs_id, type, value)
            SELECT $1, 'tf-' || i, 'domain', 'd' || i || '.' || $3 || '.tf.test'
            FROM generate_series(1, $2) AS s(i)
            ON CONFLICT (workspace_id, type, value) DO NOTHING
            RETURNING id, obs_id
        )
        INSERT INTO verdicts (workspace_id, observable_id, label,
            confidence_at_write, half_life_days, floor, source, created_at)
        SELECT $1, obs.id, 'suspicious', 0.6,
               (7.0 * (1 + (substr(obs.obs_id, 4)::int % $4)))::real,
               0.0, 'enrichment:seed',
               clock_timestamp() - ((
                   ('x' || substr(md5(obs.obs_id), 1, 8))::bit(32)::int % 730
               ) || ' days')::interval
        FROM obs
        """,
        ws, rows, name, n_hl,
    )
    # a second, LATER verdict for one observable in ten, so "is it still current?"
    # actually has work to do and the two shapes can disagree if either is wrong
    await pool.execute(
        """
        INSERT INTO verdicts (workspace_id, observable_id, label,
            confidence_at_write, half_life_days, floor, source, created_at)
        SELECT $1, v.observable_id, 'benign', 0.55, v.half_life_days, 0.0,
               'enrichment:superseding', v.created_at + interval '1 day'
        FROM verdicts v
        JOIN observables o ON o.id = v.observable_id
        WHERE v.workspace_id = $1 AND (substr(o.obs_id, 4)::int % 10) = 0
        """,
        ws,
    )
    await pool.execute("VACUUM (ANALYZE) observables")
    await pool.execute("VACUUM (ANALYZE) verdicts")
    n = await pool.fetchval("SELECT count(*) FROM verdicts WHERE workspace_id = $1", ws)
    return ws, n


async def timed(pool, sql, ws, now, since, edges, limit, runs=3):
    ts = []
    rows = []
    for _ in range(runs):
        t0 = time.perf_counter()
        rows = await pool.fetch(sql, ws, now, since, edges, limit)
        ts.append((time.perf_counter() - t0) * 1000)
    return statistics.median(ts), rows


def key(rows):
    return [(str(r["observable_id"]), r["label"], r["created_at"]) for r in rows]


async def main():
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    import sys

    sys.path.insert(0, ".")
    from auspex.timeline.staleness import (
        AGING_AT_HALF_LIVES, LAPSED_AT_HALF_LIVES, STALE_AT_HALF_LIVES,
    )

    edges = [AGING_AT_HALF_LIVES, STALE_AT_HALF_LIVES, LAPSED_AT_HALF_LIVES]
    made = []
    try:
        ws, n = await seed(pool, "probe-tailfix", 100_000, 12)
        made.append(ws)
        print(f"seeded {n} verdicts (10% of observables have a superseding later verdict)\n")
        now = await pool.fetchval("SELECT clock_timestamp()")
        print(f"  {'window':>7} | {'current ms':>11} | {'variant ms':>11} | {'speedup':>8} | identical?")
        all_same = True
        for days in (7, 30, 90, 180, 270, 365):
            since = now - timedelta(days=days)
            cur_ms, cur_rows = await timed(pool, CURRENT, ws, now, since, edges, 50)
            var_ms, var_rows = await timed(pool, VARIANT, ws, now, since, edges, 50)
            same = key(cur_rows) == key(var_rows)
            all_same &= same
            print(f"  {days:>7} | {cur_ms:>11.1f} | {var_ms:>11.1f} | "
                  f"{cur_ms / var_ms:>7.2f}x | {same} ({len(cur_rows)}/{len(var_rows)} rows)")

        # a bigger limit stresses the early-stop claim
        print("\n  limit sweep at 365 days:")
        since = now - timedelta(days=365)
        for lim in (50, 200, 1000):
            cur_ms, cur_rows = await timed(pool, CURRENT, ws, now, since, edges, lim)
            var_ms, var_rows = await timed(pool, VARIANT, ws, now, since, edges, lim)
            same = key(cur_rows) == key(var_rows)
            all_same &= same
            print(f"  limit={lim:>5} | {cur_ms:>9.1f} | {var_ms:>9.1f} | "
                  f"{cur_ms / var_ms:>7.2f}x | identical={same} ({len(cur_rows)} rows)")

        print(f"\n  ALL OUTPUTS IDENTICAL: {all_same}")

        plan = "\n".join(
            r[0] for r in await pool.fetch(
                f"EXPLAIN (ANALYZE) {VARIANT}", ws, now, now - timedelta(days=365), edges, 50
            )
        )
        print("\n  variant plan at 365d (probe counts):")
        for ln in plan.splitlines():
            if "idx_verdicts_ws_obs" in ln or "Limit" in ln or "Sort Method" in ln:
                print(f"    {ln.strip()[:160]}")
    finally:
        for ws in made:
            await pool.execute("DELETE FROM observables WHERE workspace_id = $1", ws)
            await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)
        await pool.execute("VACUUM (ANALYZE) observables")
        await pool.execute("VACUUM (ANALYZE) verdicts")
        print("\n  [cleanup] probe workspace deleted, tables vacuumed")
        await pool.close()


asyncio.run(main())
