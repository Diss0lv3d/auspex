"""Per-workspace spend limits and the plan seam — S19 (Phase 4, Hardening).

TD-018 has been on the roadmap since S14: **nothing bounds the NUMBER of
inference calls a workspace can cause.** A deep turn is two endpoint calls
(D-016's two-pass fallback), an agent loop is one per step, and every one of
them is a request the customer's endpoint serves. A loop that fans out is a
bill, and until this module existed the only thing standing between a workspace
and an unbounded one was that nobody had tried.

Three deliberate choices:

1. **The ceiling is enforced in the same statement that reads the counter.**
   A conditional UPSERT (`... DO UPDATE SET used = used + 1 WHERE used < limit
   RETURNING used`) either claims a unit of spend or matches zero rows. This is
   the S18 settlement device applied to metering: "read the count, decide, then
   increment" is a window that two concurrent turns fit through, and the failure
   mode is silently serving free inference.

2. **The plan is data; the limits are code.** A workspace row carries a plan
   name. What each plan may spend lives here, next to `EXECUTABLE_SYSTEMS` in
   spirit — a limits table would make "unbounded inference" reachable by a bad
   UPDATE, and D-006 says safety-critical behaviour is code.

3. **Refusal is honest and specific.** A workspace at its ceiling is told which
   meter it hit, what the ceiling is, and when the window resets. Never a silent
   truncation, never a generic 500 — the S16/S17 lesson about surfaces that
   cannot tell absence from failure, applied to spend.

This is the gating SKELETON the roadmap asks for, not billing: it counts what is
spent and refuses over the line. Nothing here prices anything, and no plan is
sold — `PLANS` is the seam a commercial tier list will replace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

import asyncpg

logger = logging.getLogger("auspex.limits")


class Meter(StrEnum):
    """What gets counted. One value per thing a workspace can exhaust.

    `INFERENCE_CALLS` is TD-018's: it counts CALLS, not turns and not tokens,
    because the call is what the endpoint actually serves and what a runaway
    loop multiplies. Tokens are the natural second meter and are deliberately
    not here yet — counting them honestly needs usage back from every endpoint,
    and an endpoint that omits `usage` would silently meter zero.
    """

    INFERENCE_CALLS = "inference_calls"


# The window every meter is counted over. One hour is short enough that a
# workspace which trips a limit is not locked out for the day, and long enough
# that the counter is not a rounding error against a burst.
WINDOW = timedelta(hours=1)


@dataclass(frozen=True)
class Plan:
    """What one tier may spend per window. A limit of None means unmetered."""

    name: str
    inference_calls_per_hour: int | None

    def limit_for(self, meter: Meter) -> int | None:
        return {Meter.INFERENCE_CALLS: self.inference_calls_per_hour}[meter]


# The tier list. Numbers are a starting point chosen against measured turn cost
# (a deep turn is 1-2 calls, D-016 two-pass), not a commercial decision:
# `free` allows a working day of steady analysis, `pro` a busy team, and
# `enterprise` is unmetered because those deployments bring their own endpoint
# and their own capacity (D-005 — we never pay for inference either way).
PLANS: dict[str, Plan] = {
    "free": Plan("free", inference_calls_per_hour=100),
    "pro": Plan("pro", inference_calls_per_hour=2_000),
    "enterprise": Plan("enterprise", inference_calls_per_hour=None),
}

DEFAULT_PLAN = "free"


def plan_for(name: str | None) -> Plan:
    """Resolve a plan name to its limits.

    An unknown name resolves to the MOST restrictive plan, never to unmetered.
    A typo in a plan column must not be a way to buy unlimited inference, and a
    plan this build does not know about is a plan whose limits it cannot honour.
    """
    if name and name in PLANS:
        return PLANS[name]
    if name:
        logger.warning("unknown plan %r — falling back to %r", name, DEFAULT_PLAN)
    return PLANS[DEFAULT_PLAN]


def window_start(now: datetime | None = None) -> datetime:
    """The start of the window `now` falls in. Truncation, so every replica
    agrees on the boundary without coordinating."""
    moment = now or datetime.now(UTC)
    return moment.replace(minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class Allowance:
    """The answer to "may this workspace spend one more unit?"."""

    allowed: bool
    meter: Meter
    used: int
    limit: int | None
    resets_at: datetime

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(0, self.limit - self.used)

    @property
    def refusal_text(self) -> str:
        """What the analyst reads. Names the meter, the ceiling and the reset —
        an analyst who hits this needs to know whether to wait or to ask for a
        bigger plan, and a message that says neither is a dead end."""
        return (
            f"This workspace has reached its limit of {self.limit} "
            f"{self.meter.value.replace('_', ' ')} per hour "
            f"({self.used} used). It resets at "
            f"{self.resets_at.strftime('%H:%M UTC')}. Analysis that does not need "
            "the reasoning engine — IOC checks, CVE lookups and definitions — "
            "keeps working."
        )


class UsageLimiter:
    """Counts and caps what a workspace spends. Postgres holds the truth."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _plan(self, workspace_id: UUID | str) -> Plan:
        name = await self._pool.fetchval(
            "SELECT plan FROM workspaces WHERE id = $1::uuid", str(workspace_id)
        )
        return plan_for(name)

    async def claim(
        self,
        *,
        workspace_id: UUID | str,
        meter: Meter = Meter.INFERENCE_CALLS,
        units: int = 1,
        now: datetime | None = None,
    ) -> Allowance:
        """Claim `units` of spend, or refuse. Atomic.

        The UPSERT increments and enforces in one statement, so two concurrent
        turns cannot both read "99 used" and both proceed. A refusal costs one
        extra read to report the current count — after the fact, so it cannot
        widen the window that matters (the same shape as S18's `settle`).
        """
        plan = await self._plan(workspace_id)
        limit = plan.limit_for(meter)
        start = window_start(now)
        resets_at = start + WINDOW

        if limit is None:  # unmetered plan — still counted, never refused
            used = await self._pool.fetchval(
                """
                INSERT INTO usage_counters (workspace_id, meter, window_start, used)
                VALUES ($1::uuid, $2, $3, $4)
                ON CONFLICT (workspace_id, meter, window_start) DO UPDATE
                    SET used = usage_counters.used + $4, updated_at = clock_timestamp()
                RETURNING used
                """,
                str(workspace_id),
                meter.value,
                start,
                units,
            )
            return Allowance(True, meter, used, None, resets_at)

        used = await self._pool.fetchval(
            """
            INSERT INTO usage_counters (workspace_id, meter, window_start, used)
            VALUES ($1::uuid, $2, $3, $4)
            ON CONFLICT (workspace_id, meter, window_start) DO UPDATE
                SET used = usage_counters.used + $4, updated_at = clock_timestamp()
             WHERE usage_counters.used + $4 <= $5
            RETURNING used
            """,
            str(workspace_id),
            meter.value,
            start,
            units,
            limit,
        )
        if used is not None:
            return Allowance(True, meter, used, limit, resets_at)

        # Refused. Report the real count rather than the limit — they differ
        # when a multi-unit claim is rejected with room left under the ceiling.
        current = await self.usage(workspace_id=workspace_id, meter=meter, now=now)
        return Allowance(False, meter, current, limit, resets_at)

    async def usage(
        self,
        *,
        workspace_id: UUID | str,
        meter: Meter = Meter.INFERENCE_CALLS,
        now: datetime | None = None,
    ) -> int:
        """What this workspace has spent in the current window."""
        return (
            await self._pool.fetchval(
                """
                SELECT used FROM usage_counters
                 WHERE workspace_id = $1::uuid AND meter = $2 AND window_start = $3
                """,
                str(workspace_id),
                meter.value,
                window_start(now),
            )
            or 0
        )

    async def snapshot(
        self, *, workspace_id: UUID | str, now: datetime | None = None
    ) -> dict:
        """Everything a surface needs to show a workspace where it stands.

        Reported whether or not anything has been spent — a meter that only
        appears once it has a value cannot be told from a meter that is broken.
        """
        plan = await self._plan(workspace_id)
        start = window_start(now)
        meters = {}
        for meter in Meter:
            used = await self.usage(workspace_id=workspace_id, meter=meter, now=now)
            limit = plan.limit_for(meter)
            meters[meter.value] = {
                "used": used,
                "limit": limit,
                "remaining": None if limit is None else max(0, limit - used),
            }
        return {
            "plan": plan.name,
            "window_start": start.isoformat(),
            "resets_at": (start + WINDOW).isoformat(),
            "meters": meters,
        }

    async def sweep(self, *, before: datetime | None = None) -> int:
        """Delete closed windows. Counters are evidence for the window they
        bound and nothing after it; without this the table grows one row per
        workspace per meter per hour forever."""
        cutoff = before or (window_start() - WINDOW)
        result = await self._pool.execute(
            "DELETE FROM usage_counters WHERE window_start < $1", cutoff
        )
        return int(result.split()[-1]) if result.startswith("DELETE") else 0


__all__ = [
    "DEFAULT_PLAN",
    "PLANS",
    "WINDOW",
    "Allowance",
    "Meter",
    "Plan",
    "UsageLimiter",
    "plan_for",
    "window_start",
]
