"""AbuseIPDB — key-gated on ABUSEIPDB_API_KEY (probe §5).

GET /api/v2/check?ipAddress=…&maxAgeInDays=90, headers `Key` + `Accept`.
Both shapes live-verified 2026-07-16: the 401 `{"errors":[{"detail","status"}]}`
error and the 200 happy path (Tor exit: score 90/106 reports → malicious;
8.8.8.8: isWhitelisted true → benign; `x-ratelimit-limit: 1000` free tier —
docs/probes/2026-07-16-keyed-providers-live.md). 429 → breaker.

Every answer also names the network the address belongs to (isp, domain,
usage type, country, hostnames), whatever the score. That is returned as a
NetworkContext beside the signal, or alone when the score claims nothing
(B-001: it used to be dropped with the low-score None — re-probed live on
34.187.179.218, docs/probes/b1-b001/raw-owner-fields.log).
"""

import httpx

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.providers.base import Provider, parse_json, raise_for_status
from auspex.enrich.types import LookupResult, NetworkContext, ProviderSignal, VerdictLabel

BASE_URL = "https://api.abuseipdb.com"
MAX_AGE_DAYS = 90

_MALICIOUS_SCORE = 75  # AbuseIPDB's own "confident" line
_SUSPICIOUS_SCORE = 25
_MAX_HOSTNAMES = 5  # kept in evidence; the summary names at most three


def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _network(data: dict) -> NetworkContext | None:
    """The network AbuseIPDB named for this address, or None if it named none.
    Only what the response says — a missing field is left out, never guessed."""
    isp, domain = _text(data.get("isp")), _text(data.get("domain"))
    usage, country = _text(data.get("usageType")), _text(data.get("countryCode"))
    raw_hosts = data.get("hostnames")
    hostnames = [h for h in map(_text, raw_hosts if isinstance(raw_hosts, list) else []) if h]
    hostnames = hostnames[:_MAX_HOSTNAMES]
    owner = f"{isp} ({domain})" if isp and domain else (isp or domain)
    summary = ", ".join(part for part in (owner, usage, country) if part)
    if hostnames:
        noun = "hostname" if len(hostnames) == 1 else "hostnames"
        shown = f"{noun} {', '.join(hostnames[:3])}"
        summary = f"{summary} · {shown}" if summary else shown
    if not summary:
        return None
    return NetworkContext(
        provider="AbuseIPDB",
        summary=summary,
        evidence={
            "isp": isp,
            "domain": domain,
            "usage_type": usage,
            "country_code": country,
            "hostnames": hostnames,
        },
    )


def _with(signal: ProviderSignal, network: NetworkContext | None) -> LookupResult:
    return (signal, network) if network is not None else signal


class AbuseIPDB(Provider):
    name = "AbuseIPDB"
    region = "global"
    accepts = frozenset({ObservableType.IPV4, ObservableType.IPV6})

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def lookup(
        self, client: httpx.AsyncClient, observable: Observable
    ) -> LookupResult:
        resp = await client.get(
            f"{BASE_URL}/api/v2/check",
            params={"ipAddress": observable.value, "maxAgeInDays": MAX_AGE_DAYS},
            headers={"Key": self._api_key, "Accept": "application/json"},
        )
        raise_for_status(self.name, resp)
        data = parse_json(self.name, resp).get("data")
        if not isinstance(data, dict):
            return None  # docs-coded path: fail soft on shape drift

        score = data.get("abuseConfidenceScore")
        score = score if isinstance(score, int) else 0
        reports = data.get("totalReports")
        reports = reports if isinstance(reports, int) else 0
        evidence = {
            "abuse_confidence_score": score,
            "total_reports": reports,
            "is_whitelisted": data.get("isWhitelisted"),
            "is_tor": data.get("isTor"),
            "usage_type": data.get("usageType"),
            "isp": data.get("isp"),
            "last_reported_at": data.get("lastReportedAt"),
        }

        network = _network(data)
        if data.get("isWhitelisted") is True:
            return _with(
                ProviderSignal(
                    provider=self.name,
                    label=VerdictLabel.BENIGN,
                    confidence=0.6,
                    summary="whitelisted by AbuseIPDB",
                    evidence=evidence,
                ),
                network,
            )
        if score >= _MALICIOUS_SCORE:
            label, confidence = VerdictLabel.MALICIOUS, score / 100
        elif score >= _SUSPICIOUS_SCORE:
            label, confidence = VerdictLabel.SUSPICIOUS, score / 100
        else:
            # Low score, no whitelist claim: no reputation signal either way.
            # The network it named is still a fact about the address (B-001).
            return network
        window = f"last {MAX_AGE_DAYS} days"
        return _with(
            ProviderSignal(
                provider=self.name,
                label=label,
                confidence=confidence,
                summary=f"abuse confidence {score}/100 ({reports} reports, {window})",
                evidence=evidence,
            ),
            network,
        )
