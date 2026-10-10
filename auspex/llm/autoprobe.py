"""The deployment probes its own endpoint (D-038, TD-037).

The deployment scorecard (D-035) chooses native vs two-pass reasoning (D-016)
and whether deep turns take the agent path (D-037). Until S26 its only writer
was a developer running `scripts/llm_harness.py`, so every other deployment
read "unknown": a two-pass on every deep turn and no agent path at all.

So the app measures its configured endpoint itself: once per fingerprint (base
URL + model, never the key), in the background, at startup. ~15 requests of the
customer's inference, once per endpoint (D-005); LLM_AUTOPROBE_ENABLED turns it
off. A probe that measured nothing about the endpoint (asleep, wrong key) is not
recorded, so it cannot pin a fingerprint to plan_only — and it is retried on a
schedule, because a scale-to-zero endpoint asleep at startup is normal.

**And again once the measurement is old** (TD-041, D-042). A provider can
change what a model does under the same name — a silent update, thinking
toggled server-side, tool calling degraded — and the fingerprint cannot see
that. So the running app looks at the scorecard's age every
REPROBE_CHECK_SECONDS and measures again once it passes
SCORECARD_MAX_AGE_SECONDS. A re-probe that measures nothing leaves the old
scorecard standing: an old measurement is still better than "unknown". A
re-probe that finds the endpoint changed says so in the log, because the rail's
thinking floor (D-040) is calibrated per model and no probe re-calibrates it.
"""

import asyncio
import logging

import asyncpg

from auspex.config import Settings
from auspex.llm.capability import BASIC_CHAT_FAILED, probe_capabilities
from auspex.llm.client import LLMClient
from auspex.llm.scorecard import (
    CapabilityScorecard,
    decide_agent_mode,
    deployment_scorecard_age,
    endpoint_fingerprint,
    load_deployment_scorecard,
    save_deployment_scorecard,
)

logger = logging.getLogger("auspex.llm.autoprobe")

# How long to wait before re-trying a probe that measured nothing. Code, not
# configuration (D-026): one GET /models per attempt while the endpoint sleeps.
AUTOPROBE_RETRY_DELAYS = (60.0, 300.0, 900.0, 3600.0)

# Outcomes worth another attempt: the endpoint, or another worker, may be done.
_RETRY = frozenset({"unreachable", "unusable", "busy"})

# TD-041 (D-042): how old a measurement may get before the running app takes
# another, and how often it looks. Code, not configuration (D-026). A week is
# ~15 requests of the customer's inference per week; the look is one DB read.
SCORECARD_MAX_AGE_SECONDS = 7 * 24 * 3600.0
REPROBE_CHECK_SECONDS = 6 * 3600.0

# What a re-probe compares, because each of these changes what a deep turn does:
# the reasoning path (D-016/D-036), the agent path (D-037), and the structured
# pass (D-043).
_WATCHED = ("native_reasoning", "native_tool_calling", "streaming_tool_deltas",
            "json_object_mode", "json_schema_mode")


def _changes(before: CapabilityScorecard, after: CapabilityScorecard) -> list[str]:
    out = [
        f"{name}: {getattr(before, name)} -> {getattr(after, name)}"
        for name in _WATCHED
        if getattr(before, name) != getattr(after, name)
    ]
    if decide_agent_mode(before) != decide_agent_mode(after):
        out.insert(0, f"agent_mode: {decide_agent_mode(before)} -> {decide_agent_mode(after)}")
    return out


def _lock_key(base_url: str, model: str) -> int:
    """A Postgres advisory-lock key for this endpoint: 60 bits of its
    fingerprint, so it fits a signed bigint."""
    return int(endpoint_fingerprint(base_url, model)[:15], 16)


async def ensure_deployment_scorecard(
    pool: asyncpg.Pool,
    settings: Settings,
    *,
    probe=probe_capabilities,
    client_factory=LLMClient.from_settings,
    max_age: float = SCORECARD_MAX_AGE_SECONDS,
) -> str:
    """One attempt. Returns what happened: 'unconfigured', 'known', 'busy'
    (another worker holds the probe), 'unreachable', 'unusable', 'probed' (the
    first measurement), or 'reprobed' (a newer one replaced an old one).

    Several workers start at once, and the battery is the customer's inference,
    so the probe runs under an advisory lock and re-checks the scorecard's age
    once it holds it."""
    if not settings.llm_base_url or not settings.llm_model:
        return "unconfigured"
    base, model = settings.llm_base_url, settings.llm_model

    async def fresh() -> bool:
        age = await deployment_scorecard_age(pool, base, model)
        return age is not None and age < max_age

    if await fresh():
        return "known"
    key = _lock_key(base, model)
    async with pool.acquire() as conn:
        if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", key):
            return "busy"
        try:
            if await fresh():
                return "known"
            previous = await load_deployment_scorecard(pool, base, model)
            client = client_factory(settings)
            try:
                sc = await probe(client)
            finally:
                await client.aclose()
            # Measured nothing: an old scorecard, if there is one, stands.
            if not sc.reachable:
                return "unreachable"
            if BASIC_CHAT_FAILED in sc.notes:
                return "unusable"
            await save_deployment_scorecard(pool, sc)
            if previous is None:
                return "probed"
            changed = _changes(previous[0], sc)
            if changed:
                # Field names and booleans only — no endpoint output in the log.
                logger.warning(
                    "endpoint re-probe: the endpoint changed under the same name (%s);"
                    " re-measure the rail's thinking floor (D-040)",
                    "; ".join(changed),
                )
            return "reprobed"
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", key)


async def autoprobe(
    pool: asyncpg.Pool,
    settings: Settings,
    *,
    attempt=ensure_deployment_scorecard,
    sleep=asyncio.sleep,
    delays: tuple[float, ...] = AUTOPROBE_RETRY_DELAYS,
) -> str:
    """The startup task: attempt, and retry on the schedule while the attempt
    measured nothing. Never raises — a probe that fails must not take the app
    down; the deployment just stays "unknown", which is the safe default."""
    try:
        outcome = await attempt(pool, settings)
        for delay in delays:
            if outcome not in _RETRY:
                break
            await sleep(delay)
            outcome = await attempt(pool, settings)
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001 — the app outlives its probe
        logger.warning("endpoint autoprobe failed: %s", type(err).__name__)
        return "error"
    logger.info("endpoint autoprobe: %s", outcome)
    return outcome


async def keep_scorecard_fresh(
    pool: asyncpg.Pool,
    settings: Settings,
    *,
    cycle=autoprobe,
    sleep=asyncio.sleep,
    every: float = REPROBE_CHECK_SECONDS,
) -> None:
    """The app's background task (TD-041): the startup cycle, then a look at
    the scorecard's age every `every` seconds for as long as the app runs. Each
    look is `autoprobe`, so it never raises and costs one DB read until the
    measurement is old. Ends only when the app cancels it."""
    while True:
        await cycle(pool, settings)
        await sleep(every)
