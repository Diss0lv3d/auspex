"""NVD CVE API 2.0 delta client — probe-pinned (docs/probes/2026-07-17-nvd-delta.md
+ 2026-07-17-nvd-api.md).

Reality bites encoded here:
- 404 means at least three unrelated client errors (bad key, window > 120 days,
  resultsPerPage > 2000) with an EMPTY body — the error text lives in the
  `message` RESPONSE HEADER. A 404 is NEVER "no such CVE"; that is a 200 with
  `totalResults: 0`.
- ~768 modified CVEs in one ordinary day: multi-day gaps must page.
- Rejected CVEs ride the delta stream (empty metrics, boilerplate description).
- NVD bulk etiquette asks for spacing between requests even keyed.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx

from auspex import __version__

NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
MAX_WINDOW_DAYS = 120  # hard API limit (probed: 404 past it)
RESULTS_PER_PAGE = 2000  # hard API cap (probed: 404 above it)
REQUEST_SPACING_SECONDS = 3.0
CALL_TIMEOUT_SECONDS = 60.0


class NVDError(Exception):
    """A non-retryable NVD client error (the `message` header, when present).
    The caller must NOT advance its watermark on this."""


def is_rejected(cve: dict) -> bool:
    return cve.get("vulnStatus") == "Rejected"


def windows(
    since: datetime, until: datetime, *, max_days: int = MAX_WINDOW_DAYS
) -> list[tuple[datetime, datetime]]:
    """Chunk [since, until] into contiguous windows the API will accept."""
    if since >= until:
        return []
    out: list[tuple[datetime, datetime]] = []
    step = timedelta(days=max_days)
    cursor = since
    while cursor < until:
        out.append((cursor, min(cursor + step, until)))
        cursor += step
    return out


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class NVDFeed:
    def __init__(
        self,
        *,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
        spacing_seconds: float = REQUEST_SPACING_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None
        self._spacing = spacing_seconds
        self._sleep = sleep

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"User-Agent": f"Auspex/{__version__}"}
            if self._api_key:
                headers["apiKey"] = self._api_key  # header, not query param (probed)
            self._client = httpx.AsyncClient(headers=headers, timeout=CALL_TIMEOUT_SECONDS)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    async def _get(self, params: dict) -> dict:
        resp = await self._get_client().get(NVD_API_URL, params=params)
        if resp.status_code == 404:
            # Empty body; never json-parse it. Distinct from CVE-not-found.
            raise NVDError(
                resp.headers.get("message", "NVD 404 with no message header (check key/params)")
            )
        resp.raise_for_status()
        return resp.json()

    async def fetch_window(self, start: datetime, end: datetime) -> list[dict]:
        """All CVE objects lastModified inside one ≤120-day window, fully paged.
        Returns raw `vulnerabilities[i].cve` dicts (nvd_to_doc's input shape).
        Page order is not contractual — callers upsert by id."""
        out: list[dict] = []
        start_index = 0
        while True:
            body = await self._get(
                {
                    "lastModStartDate": _iso(start),
                    "lastModEndDate": _iso(end),
                    "resultsPerPage": RESULTS_PER_PAGE,
                    "startIndex": start_index,
                }
            )
            out.extend(v["cve"] for v in body.get("vulnerabilities", ()))
            page = body.get("resultsPerPage", 0)
            start_index += page
            if page == 0 or start_index >= body.get("totalResults", 0):
                return out
            await self._sleep(self._spacing)

    async def fetch_cve(self, cve_id: str) -> dict | None:
        """Single-CVE fetch (the KEV-new-entry path). None = NVD holds no such
        CVE (a 200 with zero results — NOT a 404, which raises)."""
        body = await self._get({"cveId": cve_id})
        vulns = body.get("vulnerabilities", ())
        return vulns[0]["cve"] if vulns else None
