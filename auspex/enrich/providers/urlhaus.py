"""URLhaus — key-gated on ABUSECH_AUTH_KEY (probes §6 + keyed follow-up).

POST form-encoded with `Auth-Key`; endpoint by observable type:
/v1/host/ (domain|IPv4), /v1/url/ (url), /v1/payload/ (md5|sha256 — no sha1).
All three happy paths live-verified 2026-07-16
(docs/probes/2026-07-16-keyed-providers-live.md). Quirks that shaped this
parser: heavy payload hashes 504 server-side (~60 s — the 6 s cap turns that
into an honest miss); URLhaus records ANY bytes served from a listed URL, so
an empty payload (file_size 0, e.g. the canonical empty-file hash) is a
failed-download artifact, NOT malware; `url_count` is an int on /host/ but a
string on /payload/. Every parse guards on `query_status` and fails SOFT.
"""

import httpx

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.providers.base import Provider, parse_json, raise_for_status
from auspex.enrich.types import ProviderInputError, ProviderSignal, VerdictLabel

BASE_URL = "https://urlhaus-api.abuse.ch"

_NO_RESULT_STATUSES = {"no_results"}


class URLhaus(Provider):
    name = "URLhaus"
    region = "global"
    accepts = frozenset(
        {
            ObservableType.DOMAIN,
            ObservableType.IPV4,
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
        if observable.type is ObservableType.URL:
            endpoint, form = "/v1/url/", {"url": observable.value}
        elif observable.type is ObservableType.MD5:
            endpoint, form = "/v1/payload/", {"md5_hash": observable.value}
        elif observable.type is ObservableType.SHA256:
            endpoint, form = "/v1/payload/", {"sha256_hash": observable.value}
        else:  # DOMAIN / IPV4
            endpoint, form = "/v1/host/", {"host": observable.value}

        resp = await client.post(
            f"{BASE_URL}{endpoint}", data=form, headers={"Auth-Key": self._auth_key}
        )
        raise_for_status(self.name, resp)  # 401 Unauthorized (live-verified) → breaker
        data = parse_json(self.name, resp)

        status = str(data.get("query_status", ""))
        if status in _NO_RESULT_STATUSES:
            return None
        if status != "ok":
            # invalid_url/invalid_host/… mean OUR request was malformed; anything
            # unrecognized means the contract drifted. Either way it is a
            # client-side problem (probe rule) — surfaced, but never breaker food.
            raise ProviderInputError(f"{self.name}: query_status={status or 'missing'}")

        if endpoint == "/v1/payload/":
            try:
                file_size = int(data.get("file_size") or -1)
            except (TypeError, ValueError):
                file_size = -1  # unparseable size: keep the signal
            if file_size == 0:
                # Empty payload = failed-download artifact URLhaus happened to
                # record, not malware (live probe: the canonical empty-file
                # hash is query_status "ok" here with 2 251 URLs).
                return None
            signature = data.get("signature")
            url_count = data.get("url_count") or 0  # str on this endpoint (probed)
            if signature:
                label, confidence = VerdictLabel.MALICIOUS, 0.9
                summary = f"known malware payload: {signature} (seen at {url_count} URLs)"
            else:
                # Bytes served from listed malware URLs but never classified:
                # suspicious, not an asserted malware family (D-014 spirit).
                label, confidence = VerdictLabel.SUSPICIOUS, 0.65
                summary = f"unclassified payload served from {url_count} listed malware URLs"
            return ProviderSignal(
                provider=self.name,
                label=label,
                confidence=confidence,
                summary=summary,
                evidence={
                    "signature": signature,
                    "file_type": data.get("file_type"),
                    "file_size": data.get("file_size"),
                    "url_count": url_count,
                    "firstseen": data.get("firstseen"),
                },
            )

        if endpoint == "/v1/url/":
            url_status = str(data.get("url_status", ""))
            threat = data.get("threat") or "malware distribution"
            online = url_status == "online"
            return ProviderSignal(
                provider=self.name,
                label=VerdictLabel.MALICIOUS if online else VerdictLabel.SUSPICIOUS,
                confidence=0.9 if online else 0.6,
                summary=f"listed malware URL ({threat}, currently {url_status or 'unknown'})",
                evidence={
                    "url_status": url_status,
                    "threat": threat,
                    "tags": data.get("tags") or [],
                    "date_added": data.get("date_added"),
                },
            )

        # /v1/host/
        urls = data.get("urls") or []
        online_count = sum(
            1 for u in urls if isinstance(u, dict) and u.get("url_status") == "online"
        )
        url_count = data.get("url_count") or len(urls)
        blacklists = data.get("blacklists") or {}
        evidence = {
            "url_count": url_count,
            "online_count": online_count,
            "firstseen": data.get("firstseen"),
            "blacklists": blacklists if isinstance(blacklists, dict) else {},
        }
        if online_count:
            live = f"{online_count} live of {url_count} listed URLs"
            return ProviderSignal(
                provider=self.name,
                label=VerdictLabel.MALICIOUS,
                confidence=0.85,
                summary=f"actively hosting malware ({live})",
                evidence=evidence,
            )
        return ProviderSignal(
            provider=self.name,
            label=VerdictLabel.SUSPICIOUS,
            confidence=0.6,
            summary=f"historically hosted malware ({url_count} listed URLs, none online now)",
            evidence=evidence,
        )
