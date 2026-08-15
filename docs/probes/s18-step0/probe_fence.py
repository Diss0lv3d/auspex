"""S18 Step 0 — lead 2: is the OFFSET 0 optimisation fence actually PROTECTED?

The comment says deleting it costs 15x. The plan test asserts the index is used.
Nobody checked that the test FAILS when the fence is removed — if it passes, the
fence is unprotected and the test is decoration.

The test's only input is the SQL string, so EXPLAIN the fence-less string and
re-run the test's four assertions verbatim. No file edit, same answer.
"""

import asyncio
import statistics
import sys
import time

import asyncpg

sys.path.insert(0, ".")
DSN = "postgresql://auspex:auspex@localhost:55432/auspex"

WITH_FENCE = open("auspex/timeline/store.py").read().split('_DECAYED_SQL = """')[1].split('"""')[0]
assert "OFFSET 0" in WITH_FENCE
# exactly what a future reader deleting "dead syntax" would leave behind:
# the OFFSET 0 line and the comment above it that explains why it is there
NO_FENCE = "\n".join(
    ln
    for ln in WITH_FENCE.splitlines()
    if ln.strip() != "OFFSET 0" and not ln.strip().startswith("--")
)
assert "OFFSET 0" not in NO_FENCE, "the fence line survived the strip"

PLAN_SEED_ROWS = 25_000  # the size the plan suite seeds


async def seed(pool, ws):
    await pool.execute(
        """
        WITH obs AS (
            INSERT INTO observables (workspace_id, obs_id, type, value)
            SELECT $1, 'cve-fence-' || i,
                   (ARRAY['ipv4','domain','cve'])[1 + (i % 3)],
                   CASE (i % 3)
                       WHEN 0 THEN '10.' || (i/65536)%256 || '.' || (i/256)%256 || '.' || i%256
                       WHEN 1 THEN 'f' || i || '.fence.test'
                       ELSE 'CVE-2016-' || lpad(i::text, 6, '0')
                   END
            FROM generate_series(1, $2) AS s(i)
            ON CONFLICT (workspace_id, type, value) DO NOTHING
            RETURNING id, type, obs_id
        )
        INSERT INTO verdicts (workspace_id, observable_id, label,
            confidence_at_write, half_life_days, floor, source, created_at)
        SELECT $1, obs.id, 'suspicious', 0.6,
               CASE obs.type WHEN 'ipv4' THEN 14.0 WHEN 'domain' THEN 30.0 ELSE 365.0 END,
               0.0, 'enrichment:seed',
               clock_timestamp() - ((
                   ('x' || substr(md5(obs.obs_id), 1, 8))::bit(32)::int % 730
               ) || ' days')::interval
        FROM obs
        """,
        ws, PLAN_SEED_ROWS,
    )
    await pool.execute("VACUUM (ANALYZE) observables")
    await pool.execute("VACUUM (ANALYZE) verdicts")


def assertions(plan):
    """The four assertions of test_the_decay_read_probes_date_ranges_not_the_whole_history."""
    return {
        "idx_verdicts_ws_hl_created in plan": "idx_verdicts_ws_hl_created" in plan,
        "no Seq Scan on verdicts": "Seq Scan on verdicts" not in plan,
        "idx_verdicts_ws_obs in plan": "idx_verdicts_ws_obs" in plan,
        "no Seq Scan on observables": "Seq Scan on observables" not in plan,
    }


async def main():
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    from datetime import timedelta

    from auspex.timeline.staleness import (
        AGING_AT_HALF_LIVES, LAPSED_AT_HALF_LIVES, STALE_AT_HALF_LIVES,
    )

    edges = [AGING_AT_HALF_LIVES, STALE_AT_HALF_LIVES, LAPSED_AT_HALF_LIVES]
    ws = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ('probe-fence') ON CONFLICT (name) "
        "DO UPDATE SET name = EXCLUDED.name RETURNING id"
    )
    try:
        await pool.execute("DELETE FROM observables WHERE workspace_id = $1", ws)
        await seed(pool, ws)
        now = await pool.fetchval("SELECT clock_timestamp()")
        since = now - timedelta(days=7)

        for label, sql in (("WITH the fence", WITH_FENCE), ("WITHOUT the fence", NO_FENCE)):
            plan = "\n".join(
                r[0] for r in await pool.fetch(
                    f"EXPLAIN (ANALYZE) {sql}", ws, now, since, edges, 50
                )
            )
            ts = []
            for _ in range(5):
                t0 = time.perf_counter()
                rows = await pool.fetch(sql, ws, now, since, edges, 50)
                ts.append((time.perf_counter() - t0) * 1000)
            checks = assertions(plan)
            print(f"\n=== {label} ===")
            print(f"  {statistics.median(ts):.1f} ms, {len(rows)} rows")
            for name, passed in checks.items():
                print(f"    {'PASS' if passed else 'FAIL'}  {name}")
            print(f"  => the plan test would {'PASS' if all(checks.values()) else 'FAIL'}")
            for ln in plan.splitlines():
                if "Seq Scan" in ln or "Materialize" in ln or "Hash Join" in ln:
                    print(f"     plan: {ln.strip()[:130]}")
    finally:
        await pool.execute("DELETE FROM observables WHERE workspace_id = $1", ws)
        await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)
        await pool.execute("VACUUM (ANALYZE) observables")
        await pool.execute("VACUUM (ANALYZE) verdicts")
        print("\n  [cleanup] probe workspace deleted, tables vacuumed")
        await pool.close()


asyncio.run(main())
