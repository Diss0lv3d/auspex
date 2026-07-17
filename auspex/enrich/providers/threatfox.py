"""ThreatFox — key-gated on ABUSECH_AUTH_KEY (probe §7).

POST JSON {"query": "search_ioc", "search_term": …, "exact_match": true} with
`Auth-Key`. exact_match stays ON: a wildcard search returning relatives of a
benign IOC would fabricate suspicion (D-014 spirit). Happy path live-verified
2026-07-16 (docs/probes/2026-07-16-keyed-providers-live.md): hit =
query_status "ok" + data rows; miss = query_status "no_result" with data as a
STRING — any status that isn't "ok" and doesn't look like a no-result is
failure, and missing/odd data fails soft. Note: ThreatFox stores IP IOCs as
ip:port, so exact bare-IP searches may miss (accepted for v1, see probe).
"""

import httpx

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.providers.base import Provider, parse_json, raise_for_status
from auspex.enrich.types import ProviderInputError, ProviderSignal, VerdictLabel

BASE_URL = "https://threatfox-api.abuse.ch"


def _is_no_result(status: str) -> bool:
    # Docs say "no_result"; exact casing unverified — match the intent, not a string.
    return "no_result" in status.lower()


class ThreatFox(Provider):
    name = "ThreatFox"
    accepts = frozenset(
        {
            ObservableType.IPV4,
            ObservableType.DOMAIN,
            ObservableType.URL,
            ObservableType.MD5,
            ObservableType.SHA256,
        }
    )

    def __init__(self, auth_key: str) -> None:
        self._auth_key = auth_key

    async def lookup(
        self, client: httpx.AsyncClient, observable: Observable
    ) -> ProviderSignal | None:
        resp = await client.post(
            f"{BASE_URL}/api/v1/",
            json={"query": "search_ioc", "search_term": observable.value, "exact_match": True},
            headers={"Auth-Key": self._auth_key},
        )
        raise_for_status(self.name, resp)
        data = parse_json(self.name, resp)

        status = str(data.get("query_status", ""))
        if _is_no_result(status):
            return None
        if status != "ok":
            # Rejected query / contract drift = client-side problem (probe
            # rule) — surfaced in the trailer, never breaker food.
            raise ProviderInputError(f"{self.name}: query_status={status or 'missing'}")
        rows = [r for r in data.get("data") or [] if isinstance(r, dict)]
        if not rows:
            return None

        # Multiple IOC rows can match; report the highest-confidence one.
        top = max(rows, key=lambda r: r.get("confidence_level") or 0)
        confidence_level = top.get("confidence_level")
        confidence_level = confidence_level if isinstance(confidence_level, int) else 50
        malware = top.get("malware_printable") or top.get("malware") or "unnamed malware"
        threat_type = top.get("threat_type") or "unknown threat type"
        summary = (
            f"known IOC: {malware} ({threat_type}), reporter confidence {confidence_level}/100"
        )
        return ProviderSignal(
            provider=self.name,
            label=VerdictLabel.MALICIOUS,
            # ThreatFox is a curated malicious-IOC feed: floor the mapped
            # confidence at 0.5 even when the reporter's own level is low.
            confidence=max(0.5, confidence_level / 100),
            summary=summary,
            evidence={
                "malware": malware,
                "threat_type": threat_type,
                "confidence_level": confidence_level,
                "first_seen": top.get("first_seen"),
                "tags": top.get("tags") or [],
                "matches": len(rows),
            },
        )
