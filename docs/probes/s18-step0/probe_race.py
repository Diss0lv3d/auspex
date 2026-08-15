"""S18 — is the exactly-once claim actually being RACED, or just serialised?

`asyncio.gather` over a pool proves nothing on its own: if the pool handed every
task the same connection, the eight UPDATEs would queue on one backend and exactly
one would win for a reason that has nothing to do with the WHERE clause.

This holds eight DISTINCT connections open, releases them into the same UPDATE at
one barrier, and prints the backend pid each ran on. Evidence, not inference.

Run from the repo root with .venv/bin/python.
"""

import asyncio

import asyncpg

DSN = "postgresql://auspex:auspex@localhost:55432/auspex"
RACERS = 8

CLAIM = """
UPDATE proposals
   SET status = 'approved', decided_at = now()
 WHERE id = $1::uuid AND workspace_id = $2::uuid AND status = 'pending_approval'
RETURNING id
"""


async def racer(conn, barrier, proposal_id, ws):
    pid = await conn.fetchval("SELECT pg_backend_pid()")
    await barrier.wait()  # everyone starts together
    row = await conn.fetchrow(CLAIM, str(proposal_id), str(ws))
    return pid, row is not None


async def main():
    setup = await asyncpg.connect(DSN)
    ws = await setup.fetchval(
        "INSERT INTO workspaces (name) VALUES ('probe-race') "
        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
    )
    try:
        for trial in range(1, 6):
            pid_row = await setup.fetchval(
                """
                INSERT INTO proposals
                    (workspace_id, tool_name, tool_level, tool_input, spec_fingerprint)
                VALUES ($1, 'annotate_observable', 'write', '{}'::jsonb, 'probe')
                RETURNING id
                """,
                ws,
            )
            conns = [await asyncpg.connect(DSN) for _ in range(RACERS)]
            try:
                barrier = asyncio.Barrier(RACERS)
                results = await asyncio.gather(
                    *[racer(c, barrier, pid_row, ws) for c in conns]
                )
            finally:
                for c in conns:
                    await c.close()
            pids = {pid for pid, _ in results}
            winners = [pid for pid, won in results if won]
            final = await setup.fetchval("SELECT status FROM proposals WHERE id = $1", pid_row)
            print(
                f"  trial {trial}: {len(pids)} distinct backends, "
                f"{len(winners)} winner(s), final status={final!r}"
            )
            assert len(pids) == RACERS, "the racers shared a backend — not a real race"
            assert len(winners) == 1, f"{len(winners)} winners — exactly-once is broken"
    finally:
        await setup.execute("DELETE FROM proposals WHERE workspace_id = $1", ws)
        await setup.execute("DELETE FROM workspaces WHERE id = $1", ws)
        await setup.close()
        print("  [cleanup] probe workspace deleted")


asyncio.run(main())
