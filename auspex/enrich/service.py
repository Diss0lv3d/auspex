"""EnrichmentService — the one object the app holds (app.state.enrichment).

Owns the provider list, one circuit breaker per provider (state persists
across turns — that is the point of a breaker), and a single shared
httpx.AsyncClient created lazily on first use and closed by the lifespan.

The per-turn cap bounds fan-out cost: a 30-hash bulk paste must not fire
30 × N provider calls on one chat turn (free-tier quotas die that way).
Capped observables are echoed as skipped, never silently dropped.
"""

import httpx

from auspex import __version__
from auspex.classify.observables import Observable, ObservableType
from auspex.config import Settings
from auspex.enrich.breaker import CircuitBreaker
from auspex.enrich.fanout import fan_out
from auspex.enrich.filters import skip_reason
from auspex.enrich.providers import Provider, build_providers
from auspex.enrich.types import EnrichmentOutcome, ObservableEnrichment

CALL_TIMEOUT_SECONDS = 6.0
ENRICH_MAX_OBSERVABLES = 8
CAP_SKIP = "beyond this turn's enrichment cap — parsed and recorded as text only"


class EnrichmentService:
    def __init__(
        self,
        providers: list[Provider],
        *,
        call_timeout: float = CALL_TIMEOUT_SECONDS,
        cap: int = ENRICH_MAX_OBSERVABLES,
        client: httpx.AsyncClient | None = None,
        breakers: dict[str, CircuitBreaker] | None = None,
    ) -> None:
        self._providers = list(providers)
        self._call_timeout = call_timeout
        self._cap = cap
        self._client = client
        self._owns_client = client is None
        self._breakers = breakers or {p.name: CircuitBreaker() for p in self._providers}

    @classmethod
    def from_settings(cls, settings: Settings) -> "EnrichmentService":
        if not settings.enrichment_enabled:
            return cls([])
        return cls(build_providers(settings))

    @property
    def active(self) -> bool:
        return bool(self._providers)

    @property
    def coverage(self) -> dict[ObservableType, int]:
        """How many active providers accept each observable type."""
        counts: dict[ObservableType, int] = {}
        for provider in self._providers:
            for type_ in provider.accepts:
                counts[type_] = counts.get(type_, 0) + 1
        return counts

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._call_timeout,
                headers={"User-Agent": f"Auspex/{__version__}"},
            )
        return self._client

    async def enrich(self, observables: tuple[Observable, ...]) -> EnrichmentOutcome:
        skips: dict[str, str] = {}
        eligible: list[Observable] = []
        for o in observables:
            reason = skip_reason(o)
            if reason is not None:
                skips[o.obs_id] = reason
            elif len(eligible) >= self._cap:
                skips[o.obs_id] = CAP_SKIP
            else:
                eligible.append(o)

        signals: dict[str, list] = {}
        failures: dict[str, str] = {}
        if eligible and self._providers:
            signals, failures = await fan_out(
                self._get_client(),
                self._providers,
                eligible,
                self._breakers,
                call_timeout=self._call_timeout,
            )

        items = tuple(
            ObservableEnrichment(
                observable=o,
                signals=tuple(signals.get(o.obs_id, ())),
                skip_reason=skips.get(o.obs_id),
            )
            for o in observables
        )
        return EnrichmentOutcome(items=items, provider_failures=failures)

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None
