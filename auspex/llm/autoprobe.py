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
"""

import asyncio
import logging

import asyncpg

from auspex.config import Settings
from auspex.llm.capability import BASIC_CHAT_FAILED, probe_capabilities
from auspex.llm.client import LLMClient
from auspex.llm.scorecard import (
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
) -> str:
    """One attempt. Returns what happened: 'unconfigured', 'known', 'busy'
    (another worker holds the probe), 'unreachable', 'unusable', or 'probed'.

    Several workers start at once, and the battery is the customer's inference,
    so the probe runs under an advisory lock and re-checks for a scorecard once
    it holds it."""
    if not settings.llm_base_url or not settings.llm_model:
        return "unconfigured"
    base, model = settings.llm_base_url, settings.llm_model
    if await load_deployment_scorecard(pool, base, model):
        return "known"
    key = _lock_key(base, model)
    async with pool.acquire() as conn:
        if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", key):
            return "busy"
        try:
            if await load_deployment_scorecard(pool, base, model):
                return "known"
            client = client_factory(settings)
            try:
                sc = await probe(client)
            finally:
                await client.aclose()
            if not sc.reachable:
                return "unreachable"
            if BASIC_CHAT_FAILED in sc.notes:
                return "unusable"
            await save_deployment_scorecard(pool, sc)
            return "probed"
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
