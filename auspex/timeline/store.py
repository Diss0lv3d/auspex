"""Timeline reads — S16. Nothing here writes anything.

Every query is workspace-scoped in its own WHERE clause (D-008). The sweep that
FINDS things is global (ingest is platform-global); every read of what it found
is not, and that has been true since S14 — this module does not get to be the
exception because it is "just a view".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
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
# `now`. Crossing is expressed in the WHERE clause rather than computed for
# every verdict in Python, because "went stale while you were away" is a
# vanishingly small slice of a workspace's history and materialising the rest to
# filter it would make the digest's cost the size of the archive.
#
# For a band edge e (in half-lives), a verdict crossed it in the window iff
#     age(now) >= e * half_life   AND   age(since) < e * half_life
# — the row was on one side of the edge when the analyst left and the other side
# when they came back. Edges arrive as a parameter, so this SQL knows the SHAPE
# of a crossing and staleness.py stays the only place that knows the numbers.
_DECAYED_SQL = """
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
    now = now or datetime.now(UTC)
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
    now = now or datetime.now(UTC)
    return Digest(
        since=since,
        now=now,
        matches=tuple(
            await list_matches(
                pool, workspace_id=workspace_id, status="open", limit=limit, since=since
            )
        ),
        flips=tuple(
            await list_flips(pool, workspace_id=workspace_id, limit=limit, since=since)
        ),
        contradicted=tuple(
            await list_watchers(
                pool,
                workspace_id=workspace_id,
                status="satisfied",
                limit=limit,
                satisfied_since=since,
            )
        ),
        decayed=tuple(
            await decayed_since(
                pool, workspace_id=workspace_id, since=since, now=now, limit=limit
            )
        ),
        checkers=tuple(checkers),
    )


__all__ = [
    "MAX_TRAIL",
    "Staleness",
    "decayed_since",
    "digest",
    "timeline_for",
]
