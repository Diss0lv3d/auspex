"""Provider contract — S5.

Every provider is a small direct-HTTP client (no LLM anywhere in this package)
coded against docs/probes/2026-07-16-enrichment-providers.md. The contract:

- `accepts` declares which S4 ObservableTypes the provider can look up.
- `lookup()` returns a ProviderSignal (the provider said something), None (the
  provider knows nothing — NOT an error), or raises ProviderError (the call
  failed — breaker + DEFERRED rail territory).
- Network errors (httpx transport exceptions) and timeouts are handled by the
  fan-out, not here; providers only translate HTTP responses.
"""

from abc import ABC, abstractmethod

import httpx

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.types import ProviderError, ProviderSignal


class Provider(ABC):
    name: str  # display name used in echoes and verdict sources
    accepts: frozenset[ObservableType]

    @abstractmethod
    async def lookup(
        self, client: httpx.AsyncClient, observable: Observable
    ) -> ProviderSignal | None: ...


def raise_for_status(provider: str, resp: httpx.Response) -> None:
    """Translate a non-2xx response into ProviderError (except statuses the
    caller already handled as data, e.g. semantic 404s)."""
    if resp.status_code >= 400:
        raise ProviderError(f"{provider}: HTTP {resp.status_code}")


def parse_json(provider: str, resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError as err:
        raise ProviderError(f"{provider}: non-JSON response") from err
    if not isinstance(data, dict):
        raise ProviderError(f"{provider}: unexpected response shape")
    return data
