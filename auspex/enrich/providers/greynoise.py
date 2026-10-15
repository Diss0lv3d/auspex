"""GreyNoise community — key-gated on GREYNOISE_API_KEY (probe §4).

GET https://api.greynoise.io/v3/community/{ip}, header `key`. Keyless works but
is budget-useless (25 lookups/WEEK — probe mismatch #3), so this provider only
activates when a key exists. The 404 is SEMANTIC: "IP not observed scanning the
internet" — data, not failure. IPv4 only (community scope).
"""

import httpx

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.providers.base import Provider, parse_json, raise_for_status
from auspex.enrich.types import ProviderSignal, VerdictLabel

BASE_URL = "https://api.greynoise.io"


class GreyNoise(Provider):
    name = "GreyNoise"
    region = "global"
    accepts = frozenset({ObservableType.IPV4})

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def lookup(
        self, client: httpx.AsyncClient, observable: Observable
    ) -> ProviderSignal | None:
        resp = await client.get(
            f"{BASE_URL}/v3/community/{observable.value}", headers={"key": self._api_key}
        )
        if resp.status_code == 404:
            return None  # "IP not observed scanning the internet" — no signal
        raise_for_status(self.name, resp)  # 401 bad key / 429 budget → breaker
        data = parse_json(self.name, resp)

        classification = str(data.get("classification", "unknown"))
        noise = bool(data.get("noise"))
        riot = bool(data.get("riot"))
        actor = str(data.get("name", "")) or "unknown actor"
        evidence = {
            "classification": classification,
            "noise": noise,
            "riot": riot,
            "name": actor,
            "last_seen": data.get("last_seen"),
        }

        if classification == "malicious":
            return ProviderSignal(
                provider=self.name,
                label=VerdictLabel.MALICIOUS,
                confidence=0.8,
                summary=f"classified malicious — {actor}, observed scanning the internet",
                evidence=evidence,
            )
        if classification == "benign" or riot:
            what = "common business service" if riot else f"known benign scanner ({actor})"
            return ProviderSignal(
                provider=self.name,
                label=VerdictLabel.BENIGN,
                confidence=0.7,
                summary=what,
                evidence=evidence,
            )
        if noise:
            return ProviderSignal(
                provider=self.name,
                label=VerdictLabel.SUSPICIOUS,
                confidence=0.35,
                summary="observed scanning the internet (unclassified)",
                evidence=evidence,
            )
        return None
