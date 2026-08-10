"""Timeline reads — S16. Nothing here writes anything.

Every query is workspace-scoped in its own WHERE clause (D-008). The sweep that
FINDS things is global (ingest is platform-global); every read of what it found
is not, and that has been true since S14 — this module does not get to be the
exception because it is "just a view".
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

import asyncpg

from auspex.retrohunt.store import list_flips, list_matches
from auspex.timeline.staleness import (
    AGING_AT_HALF_LIVES,
    LAPSED_AT_HALF_LIVES,
    STALE_AT_HALF_LIVES,
    Staleness,
    band_for,
    confidence_now,
    half_lives_elapsed,
    standing_for,
)
from auspex.timeline.types import (
    Decayed,
    DecayedVerdict,
    Digest,
    StandingClaim,
    VerdictTimeline,
)
from auspex.watchers.store import list_watchers

logger = logging.getLogger("auspex.timeline")

# A verdict's trail is append-only and one observable can be re-enriched many
# times, so the history is bounded like every other collection on these surfaces
# (the S12 top-20 discipline). Newest first, so the bound drops the oldest rows —
# the ones whose decay has already taken them out of the conversation.
MAX_TRAIL = 200

# The band edges again, as data, for the SQL that finds verdicts which crossed
# one. Imported from staleness.py rather than retyped: a digest that used
# different edges from the badge on the verdict would be a second opinion about
# aging, which is exactly what that module exists to prevent.
_BAND_EDGES = (AGING_AT_HALF_LIVES, STALE_AT_HALF_LIVES, LAPSED_AT_HALF_LIVES)

_TRAIL_SQL = """
SELECT id, label, confidence_at_write, floor, half_life_days, source, created_at
FROM verdicts
WHERE workspace_id = $1 AND observable_id = $2
ORDER BY created_at DESC, id DESC
LIMIT $3
"""

# The latest verdict per observable that crossed a band between `since` and
# `now`. "Went stale while you were away" is a vanishingly small slice of a
# workspace's history, and the read is built so its cost is that slice rather
# than the archive.
#
# For a band edge e (in half-lives), a verdict crossed it in the window iff
#     age(now) >= e * half_life   AND   age(since) < e * half_life
# — the row was on one side of the edge when the analyst left and the other side
# when they came back. Edges arrive as a parameter, so this SQL knows the SHAPE
# of a crossing and staleness.py stays the only place that knows the numbers.
#
# S17 Step 0 rearranged that same predicate rather than changing it. Moving
# created_at to one side,
#     since - e*half_life  <  created_at  <=  now - e*half_life
# — so for each (edge, half-life) pair the crossing set is a created_at RANGE
# exactly as wide as the window itself, whatever the half-life. Ranges use an
# index; an expression over half_life_days cannot, and the original spelling
# therefore read every verdict the workspace had ever written and sorted the
# survivors on disk (143 ms and an external merge at 109k verdicts, measured in
# docs/probes/2026-08-11-s17-step0-review.md — TD-021's uncosted read, now
# costed at 4.6 ms).
#
# The distinct half-lives come from the DATA, via the recursive loose-index-scan
# term below (3 values in 14 buffers here), not from a parameter carrying
# HALF_LIFE_DAYS. A parameter would have been shorter and would have made a
# writer with a new half-life silently absent from the digest — the exact class
# of failure S16 Step 0 spent itself on, and this surface's whole subject is
# absence claims.
#
# The two LATERALs are load-bearing, not style. Each makes the scan under it
# PARAMETERISED by the row above, which is what turns a range into an index
# descent; written as plain joins, the planner flattens both and hash-joins the
# whole table instead (measured: 68 ms of the 71 ms, same rows).
_DECAYED_SQL = """
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
    -- DISTINCT because a short-half-life verdict can cross two edges inside one
    -- window and would otherwise be reported twice. `was`/`now` in Python then
    -- name the outermost transition, which is the honest reading of it.
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
        -- OFFSET 0 is an optimisation fence, not a leftover: without it Postgres
        -- pulls this subquery up, loses b.lo/b.hi as scan parameters and
        -- seq-scans the workspace instead of descending idx_verdicts_ws_hl_created.
        OFFSET 0
    ) c ON TRUE
)
SELECT c.observable_id, c.label, c.confidence_at_write, c.floor,
       c.half_life_days, c.created_at, o.obs_id, o.type, o.value
FROM candidates c
-- "is this still the current verdict?", asked as one index descent per candidate
-- instead of by materialising every observable's latest row. Same tiebreak the
-- trail uses (created_at, then id), so the two surfaces cannot disagree about
-- which verdict is current — S15 Step 0 found what happens when they do.
JOIN LATERAL (
    SELECT v.id
    FROM verdicts v
    WHERE v.workspace_id = $1 AND v.observable_id = c.observable_id
    ORDER BY v.created_at DESC, v.id DESC
    LIMIT 1
) latest ON latest.id = c.id
JOIN observables o ON o.id = c.observable_id AND o.workspace_id = $1
ORDER BY EXTRACT(EPOCH FROM ($2::timestamptz - c.created_at))
         / (c.half_life_days * 86400) DESC
LIMIT $5
"""


async def reader_now(pool: asyncpg.Pool) -> datetime:
    """The instant staleness is measured against — read from the DATABASE.

    Every `created_at` on this path is `clock_timestamp()` in Postgres, and
    until S17 Step 0 every `now` defaulted to `datetime.now(UTC)` in the app
    process. Two clocks decided one band, and nothing checked that they agreed:
    on a skewed app container a verdict Postgres stamped one second ago reports
    an age of whatever the skew is, and the digest's window slides by the same
    amount. Measured on this host the skew is 0.001 s and no band moves (a
    two-day skew moves a 365-day verdict by 0.005 half-lives), so this is not a
    bug being fixed — it is a question being removed. The clock that stamps a
    row is the clock that ages it.

    Callers that pass an explicit `now` (every test, and the digest passing its
    own window's end) still decide for themselves.
    """
    return await pool.fetchval("SELECT clock_timestamp()")


def _decayed_verdict(row, *, now: datetime, current: bool) -> DecayedVerdict:
    kw = {
        "confidence_at_write": row["confidence_at_write"],
        "floor": row["floor"],
        "half_life_days": row["half_life_days"],
        "created_at": row["created_at"],
        "now": now,
    }
    return DecayedVerdict(
        id=row["id"],
        label=row["label"],
        confidence_at_write=row["confidence_at_write"],
        confidence_now=round(confidence_now(**kw), 4),
        floor=row["floor"],
        half_life_days=row["half_life_days"],
        half_lives_elapsed=round(
            half_lives_elapsed(
                created_at=row["created_at"],
                now=now,
                half_life_days=row["half_life_days"],
            ),
            3,
        ),
        staleness=band_for(**kw),
        source=row["source"],
        created_at=row["created_at"],
        current=current,
    )


async def timeline_for(
    pool: asyncpg.Pool,
    *,
    workspace_id: UUID,
    obs_id: str,
    now: datetime | None = None,
) -> VerdictTimeline | None:
    """One observable's whole life, or None when this workspace has never seen
    it. `obs_id` is the short id analysts already use in chat ("cve-1a2b3c4d"),
    not a UUID — the timeline is reachable from what is on screen."""
    now = now or await reader_now(pool)
    obs = await pool.fetchrow(
        "SELECT id, obs_id, type, value FROM observables"
        " WHERE workspace_id = $1 AND obs_id = $2",
        workspace_id,
        obs_id,
    )
    if obs is None:
        # Same answer whether it belongs to another workspace or to nobody
        # (D-008) — the route turns this into a 404 that leaks nothing.
        return None

    observable_id = obs["id"]
    trail_rows = await pool.fetch(_TRAIL_SQL, workspace_id, observable_id, MAX_TRAIL)
    trail = tuple(
        _decayed_verdict(r, now=now, current=(i == 0)) for i, r in enumerate(trail_rows)
    )

    flips = await list_flips(
        pool, workspace_id=workspace_id, limit=MAX_TRAIL, observable_id=observable_id
    )
    matches = await list_matches(
        pool, workspace_id=workspace_id, limit=MAX_TRAIL, observable_id=observable_id
    )
    watchers = await list_watchers(
        pool, workspace_id=workspace_id, limit=MAX_TRAIL, observable_id=observable_id
    )

    # A claim's standing follows the verdict that MADE it, not the current one:
    # asking how much weight a superseded verdict's claim carries is answered by
    # its status, and asking it of an open claim is answered by that claim's own
    # verdict having decayed. Both are looked up from the trail we just read.
    by_verdict = {v.id: v for v in trail}
    claims = tuple(
        StandingClaim(
            watcher=w,
            standing=(
                standing_for(by_verdict[w.verdict_id].staleness)
                if w.status == "open" and w.verdict_id in by_verdict
                else None
            ),
        )
        for w in watchers
    )
    return VerdictTimeline(
        workspace_id=workspace_id,
        observable_id=observable_id,
        obs_id=obs["obs_id"],
        type=obs["type"],
        value=obs["value"],
        trail=trail,
        flips=tuple(flips),
        matches=tuple(matches),
        claims=claims,
    )


async def decayed_since(
    pool: asyncpg.Pool,
    *,
    workspace_id: UUID,
    since: datetime,
    now: datetime,
    limit: int = 50,
) -> list[Decayed]:
    """Verdicts that crossed a staleness band in the window. The only part of
    the digest nobody recorded, because nothing happened: time passed."""
    rows = await pool.fetch(
        _DECAYED_SQL, workspace_id, now, since, list(_BAND_EDGES), limit
    )
    out: list[Decayed] = []
    for r in rows:
        common = {
            "confidence_at_write": r["confidence_at_write"],
            "floor": r["floor"],
            "half_life_days": r["half_life_days"],
            "created_at": r["created_at"],
        }
        out.append(
            Decayed(
                observable_id=r["observable_id"],
                obs_id=r["obs_id"],
                type=r["type"],
                value=r["value"],
                label=r["label"],
                was=band_for(**common, now=since),
                now=band_for(**common, now=now),
                confidence_at_write=r["confidence_at_write"],
                confidence_now=round(confidence_now(**common, now=now), 4),
                half_lives_elapsed=round(
                    half_lives_elapsed(
                        created_at=r["created_at"],
                        now=now,
                        half_life_days=r["half_life_days"],
                    ),
                    3,
                ),
                created_at=r["created_at"],
            )
        )
    # The SQL bounds the window; this drops anything whose two bands came out
    # equal anyway. That can only happen when `since` is in the future or the
    # clocks disagree, and reporting "fresh → fresh" as news would be worse than
    # reporting nothing.
    return [d for d in out if d.was != d.now]


async def digest(
    pool: asyncpg.Pool,
    *,
    workspace_id: UUID,
    since: datetime,
    now: datetime | None = None,
    limit: int = 50,
    checkers: tuple = (),
) -> Digest:
    """"Your past got re-scored" — the view an analyst opens after a week away.

    Four things can have happened to a settled question while nobody watched,
    and each is read from the surface that already owns it rather than from a
    new one (D-020, D-021): new intel re-opened it (`retrohunt_matches`), the
    label actually changed (`verdict_flips`), a claim the verdict made stopped
    being true (`watchers`), or nothing happened and it decayed anyway.

    `checkers` is not decoration. Every field above is an ABSENCE claim when it
    comes back empty, and S16 Step 0 executed what absence currently looks like:
    fifty consecutive failed watcher checks are indistinguishable from fifty
    quiet ones at every surface. A digest that says "nothing contradicted your
    verdicts" while the thing that would have noticed has been dead since Tuesday
    is not quiet, it is wrong — so the health of the checkers travels with the
    claim, and `Digest.trustworthy` is what a client asks before rendering the
    reassuring version."""
    now = now or await reader_now(pool)
    # Every list is asked for one row more than the caller wants. A digest is
    # read as "here is what happened", and S17 Step 0 measured what it does when
    # there is more than fits: with two re-open events and limit=1 it returned
    # one and said nothing about the other — and a 365-day window found 32,930
    # decayed verdicts and showed 50. That is the same failure as an unexplained
    # empty list, which this surface already refuses to make: a bounded answer
    # presented as a complete one. The extra row is the cheapest honest signal —
    # no COUNT(*) over the archive, and never a total the page cannot back up.
    probe = limit + 1
    over: list[str] = []

    def cut(rows: list, field: str) -> tuple:
        if len(rows) > limit:
            over.append(field)
        return tuple(rows[:limit])

    matches = cut(
        await list_matches(
            pool, workspace_id=workspace_id, status="open", limit=probe, since=since
        ),
        "matches",
    )
    flips = cut(
        await list_flips(pool, workspace_id=workspace_id, limit=probe, since=since),
        "flips",
    )
    contradicted = cut(
        await list_watchers(
            pool,
            workspace_id=workspace_id,
            status="satisfied",
            limit=probe,
            satisfied_since=since,
        ),
        "contradicted",
    )
    decayed = cut(
        await decayed_since(
            pool, workspace_id=workspace_id, since=since, now=now, limit=probe
        ),
        "decayed",
    )
    return Digest(
        since=since,
        now=now,
        matches=matches,
        flips=flips,
        contradicted=contradicted,
        decayed=decayed,
        checkers=tuple(checkers),
        limit=limit,
        truncated=tuple(over),
    )


__all__ = [
    "MAX_TRAIL",
    "Staleness",
    "decayed_since",
    "digest",
    "timeline_for",
]
