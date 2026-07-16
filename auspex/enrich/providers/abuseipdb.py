"""AbuseIPDB — key-gated on ABUSEIPDB_API_KEY (probe §5).

GET /api/v2/check?ipAddress=…&maxAgeInDays=90, headers `Key` + `Accept`.
Both shapes live-verified 2026-07-16: the 401 `{"errors":[{"detail","status"}]}`
error and the 200 happy path (Tor exit: score 90/106 reports → malicious;
8.8.8.8: isWhitelisted true → benign; `x-ratelimit-limit: 1000` free tier —
docs/probes/2026-07-16-keyed-providers-live.md). 429 → breaker.
"""

import httpx

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.providers.base import Provider, parse_json, raise_for_status
from auspex.enrich.types import ProviderSignal, VerdictLabel

BASE_URL = "https://api.abuseipdb.com"
MAX_AGE_DAYS = 90

_MALICIOUS_SCORE = 75  # AbuseIPDB's own "confident" line
_SUSPICIOUS_SCORE = 25


class AbuseIPDB(Provider):
    name = "AbuseIPDB"
    accepts = frozenset({ObservableType.IPV4, ObservableType.IPV6})

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def lookup(
        self, client: httpx.AsyncClient, observable: Observable
    ) -> ProviderSignal | None:
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

        if data.get("isWhitelisted") is True:
            return ProviderSignal(
                provider=self.name,
                label=VerdictLabel.BENIGN,
                confidence=0.6,
                summary="whitelisted by AbuseIPDB",
                evidence=evidence,
            )
        if score >= _MALICIOUS_SCORE:
            label, confidence = VerdictLabel.MALICIOUS, score / 100
        elif score >= _SUSPICIOUS_SCORE:
            label, confidence = VerdictLabel.SUSPICIOUS, score / 100
        else:
            return None  # low score, no whitelist claim — no signal either way
        window = f"last {MAX_AGE_DAYS} days"
        return ProviderSignal(
            provider=self.name,
            label=label,
            confidence=confidence,
            summary=f"abuse confidence {score}/100 ({reports} reports, {window})",
            evidence=evidence,
        )
