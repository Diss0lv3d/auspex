"""Submit-all/poll-all fan-out — S5.

One asyncio task per (provider, observable) pair, gathered concurrently with a
per-CALL timeout. Failures degrade gracefully: a provider that times out or
errors contributes a `provider_failures` entry (DEFERRED rail copy), never an
exception — partial results are results.

The circuit breaker is consulted per provider before its calls launch and fed
after each call settles. Breaker state lives in the service (persists across
turns); this module only reads/records. Two exceptions to the feed:
ProviderInputError (the provider rejected OUR query — a client/contract
problem, probe rule "client bug, not provider-down") and per-observable
answered-tracking, which exists so the echo can distinguish "this source said
it knows nothing" from "this source never answered" (D-014: never claim a
lookup result that didn't happen).
"""

import asyncio
import logging

import httpx

from auspex.classify.observables import Observable
from auspex.enrich.breaker import CircuitBreaker
from auspex.enrich.providers.base import Provider
from auspex.enrich.types import ProviderError, ProviderInputError, ProviderSignal

logger = logging.getLogger("auspex.enrich")

BREAKER_OPEN_REASON = "temporarily disabled after repeated failures"
INPUT_REJECTED_REASON = "could not process one of the queries"


async def fan_out(
    client: httpx.AsyncClient,
    providers: list[Provider],
    observables: list[Observable],
    breakers: dict[str, CircuitBreaker],
    *,
    call_timeout: float,
) -> tuple[dict[str, list[ProviderSignal]], dict[str, str], dict[str, int]]:
    """Returns (signals by obs_id, provider failures by name, completed-lookup
    counts by obs_id)."""
    signals: dict[str, list[ProviderSignal]] = {o.obs_id: [] for o in observables}
    answered: dict[str, int] = {o.obs_id: 0 for o in observables}
    failures: dict[str, str] = {}

    async def run_one(provider: Provider, observable: Observable) -> None:
        breaker = breakers[provider.name]
        try:
            async with asyncio.timeout(call_timeout):
                signal = await provider.lookup(client, observable)
        except TimeoutError:
            breaker.record_failure()
            failures.setdefault(provider.name, f"timed out after {call_timeout:g}s")
            return
        except ProviderInputError as err:
            # Our query was rejected — visible in the trailer, NOT breaker food.
            failures.setdefault(provider.name, INPUT_REJECTED_REASON)
            logger.warning("enrichment provider rejected our query: %s", err)
            return
        except (ProviderError, httpx.HTTPError) as err:
            breaker.record_failure()
            failures.setdefault(provider.name, "unreachable or returned an error")
            logger.warning("enrichment provider failed: %s", err)
            return
        except Exception:
            # A parser bug must not sink the other providers' results.
            breaker.record_failure()
            failures.setdefault(provider.name, "unexpected error")
            logger.exception("enrichment provider crashed: %s", provider.name)
            return
        breaker.record_success()
        answered[observable.obs_id] += 1
        if signal is not None:
            signals[observable.obs_id].append(signal)

    tasks = []
    for provider in providers:
        wanted = [o for o in observables if o.type in provider.accepts]
        if not wanted:
            continue  # nothing this provider could answer — don't report on it
        if not breakers[provider.name].allow():
            failures[provider.name] = BREAKER_OPEN_REASON
            continue
        tasks.extend(run_one(provider, o) for o in wanted)
    if tasks:
        await asyncio.gather(*tasks)

    # Deterministic echo/persist order regardless of completion order.
    for obs_signals in signals.values():
        obs_signals.sort(key=lambda s: s.provider)
    return signals, failures, answered
