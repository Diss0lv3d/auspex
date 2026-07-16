"""AlienVault OTX — keyless (key optional), always-on (probe §3).

GET /api/v1/indicators/{IPv4|IPv6|domain|url|file}/{value}/general — all five
live-verified keyless (`X-Remote-User-Name: Anonymous`). `OTX_API_KEY` adds the
`X-OTX-API-KEY` header (higher limits, same shape).

The probe's headline trap (mismatch #4): `pulse_info.count` alone is NOT a
malice signal — benign example.com sits in 50 pulses because list-style pulses
reference famous legitimate domains. The `validation[]` whitelist/false-positive
markers VETO pulse-derived suspicion and flip the signal to benign.
"""

from urllib.parse import quote

import httpx

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.providers.base import Provider, parse_json, raise_for_status
from auspex.enrich.types import ProviderSignal, VerdictLabel

BASE_URL = "https://otx.alienvault.com"

_PATH_BY_TYPE = {
    ObservableType.IPV4: "IPv4",
    ObservableType.IPV6: "IPv6",
    ObservableType.DOMAIN: "domain",  # subdomains fine on this endpoint (probed)
    ObservableType.URL: "url",
    ObservableType.MD5: "file",
    ObservableType.SHA1: "file",
    ObservableType.SHA256: "file",
}

# validation[] sources that genuinely assert "benign" (all seen live in probes):
# whitelist / false_positive / majestic / akamai. Everything else (e.g.
# tor_exits) is context and must NOT veto suspicion.
_BENIGN_VALIDATION_SOURCES = frozenset({"whitelist", "false_positive", "majestic", "akamai"})


class OTX(Provider):
    name = "OTX"
    accepts = frozenset(_PATH_BY_TYPE)

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    async def lookup(
        self, client: httpx.AsyncClient, observable: Observable
    ) -> ProviderSignal | None:
        section = _PATH_BY_TYPE[observable.type]
        value = quote(observable.value, safe="")  # URLs must be percent-encoded
        headers = {"X-OTX-API-KEY": self._api_key} if self._api_key else {}
        resp = await client.get(
            f"{BASE_URL}/api/v1/indicators/{section}/{value}/general", headers=headers
        )
        if resp.status_code == 404:
            return None  # defensive: unknown indicators usually 200-empty (probed)
        raise_for_status(self.name, resp)
        data = parse_json(self.name, resp)

        pulse_info = data.get("pulse_info") or {}
        count = pulse_info.get("count")
        count = count if isinstance(count, int) else 0
        pulses = pulse_info.get("pulses") or []
        validation = [v for v in data.get("validation", []) if isinstance(v, dict)]
        # Only genuinely-benign validation sources veto suspicion. OTX also uses
        # validation[] for CONTEXT markers — a live Tor exit carries
        # {"source": "tor_exits", "message": "IP Associated with Tor Exit
        # Nodes"} (probed 2026-07-16), and treating that as a whitelist would
        # label a Tor exit benign.
        benign_markers = sorted(
            {
                str(v.get("name", ""))
                for v in validation
                if v.get("source") in _BENIGN_VALIDATION_SOURCES
            }
        )
        context_markers = sorted(
            {
                str(v.get("message") or v.get("name", ""))
                for v in validation
                if v.get("source") not in _BENIGN_VALIDATION_SOURCES
            }
        )
        top_pulses = [str(p.get("name", "")) for p in pulses[:3] if isinstance(p, dict)]
        adversaries = sorted(
            {str(p["adversary"]) for p in pulses[:10] if isinstance(p, dict) and p.get("adversary")}
        )
        evidence = {
            "pulse_count": count,
            "top_pulses": top_pulses,
            "adversaries": adversaries[:3],
            "benign_validation": benign_markers,
            "context_validation": context_markers,
        }

        if benign_markers:
            # Whitelist/false-positive markers veto pulse-derived suspicion.
            validated_by = ", ".join(benign_markers[:3])
            return ProviderSignal(
                provider=self.name,
                label=VerdictLabel.BENIGN,
                confidence=0.6,
                summary=f"community-validated as benign ({validated_by})",
                evidence=evidence,
            )
        if count > 0:
            summary = f"referenced in {count} threat pulse{'s' if count != 1 else ''}"
            if top_pulses:
                summary += f" — e.g. {top_pulses[0]}"
            if adversaries:
                summary += f" · linked adversary: {adversaries[0]}"
            if context_markers:
                summary += f" · flagged: {context_markers[0]}"
            return ProviderSignal(
                provider=self.name,
                label=VerdictLabel.SUSPICIOUS,
                confidence=round(min(0.3 + 0.02 * count, 0.7), 3),
                summary=summary,
                evidence=evidence,
            )
        if context_markers:
            # e.g. Tor-exit membership with zero pulses: context, not a verdict.
            return ProviderSignal(
                provider=self.name,
                label=VerdictLabel.UNKNOWN,
                confidence=0.0,
                summary=f"flagged: {', '.join(context_markers[:2])}",
                evidence=evidence,
            )
        return None  # no pulses, no validation — OTX has nothing to say
