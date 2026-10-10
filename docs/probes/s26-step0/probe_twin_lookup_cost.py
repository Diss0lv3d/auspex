"""S26 review finding 8: the cost of `identical_pending` at queue scale.

The approvals stream runs `ProposalSettlement.pending(limit=MAX_PAGE)` every
second per subscriber, and the twin lookup is a correlated subquery per
returned row. The reviewer measured 886 ms at 20k distinct pending rows on a
throwaway PG16. This re-measures on the dev DB, in a scratch workspace that is
deleted afterwards: 20k distinct pending rows, `pending(limit=200)` timed 5
times, median reported.

Run:  .venv/bin/python docs/probes/s26-step0/probe_twin_lookup_cost.py
"""

import asyncio
import statistics
import sys
import time

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

from auspex.actions import ProposalSettlement  # noqa: E402
from auspex.config import Settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402

ROWS = 20_000


async def main() -> None:
    pool = await create_pool(Settings().database_url)
    ws = await pool.fetchval("INSERT INTO workspaces (name) VALUES ('t-twin-cost') RETURNING id")
    try:
        await pool.execute(
            """
            INSERT INTO proposals (workspace_id, tool_name, tool_level, tool_input,
                                   spec_fingerprint, status)
            SELECT $1, 'annotate_observable', 'write',
                   jsonb_build_object('observable_id', 'domain-x', 'note', 'note ' || g),
                   'fp', 'pending_approval'
              FROM generate_series(1, $2) g
            """, ws, ROWS)
        await pool.execute("ANALYZE proposals")
        settlement = ProposalSettlement(pool)
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            rows = await settlement.pending(workspace_id=ws, limit=200)
            times.append((time.perf_counter() - t0) * 1000)
        print(f"{ROWS} distinct pending rows, pending(limit=200): "
              f"median {statistics.median(times):.1f} ms (runs: {[round(t) for t in times]}),"
              f" rows={len(rows)}")
    finally:
        await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
