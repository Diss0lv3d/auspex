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
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx

from auspex import __version__

NVD_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
MAX_WINDOW_DAYS = 120  # hard API limit (probed: 404 past it)
RESULTS_PER_PAGE = 2000  # hard API cap (probed: 404 above it)
# A real 120-day window is ~46 pages at the probed ~768 modified CVEs/day.
# The pager trusts server-supplied totalResults for termination, so a
# poisoned/broken response must hit a hard ceiling, not page forever.
MAX_PAGES_PER_WINDOW = 100
REQUEST_SPACING_SECONDS = 3.0  # keyed quota: 50 req/rolling-30 s (probed)
# Keyless quota is 5 req/rolling-30 s (probe 2026-07-17-nvd-api.md) — 3 s
# spacing is 10/30 s and wedges any keyless catch-up needing >5 pages at the
# same 403 every hour forever (S8 review). 6.5 s keeps margin under 5/30.
KEYLESS_SPACING_SECONDS = 6.5
CALL_TIMEOUT_SECONDS = 60.0


class NVDError(Exception):
    """A non-retryable NVD client error (the `message` header, when present).
    The caller must NOT advance its watermark on this."""


def is_rejected(cve: dict) -> bool:
    return cve.get("vulnStatus") == "Rejected"


_CVE_ID_RE = re.compile(r"CVE-\d{4}-\d{4,12}", re.IGNORECASE)


def has_valid_id(cve: dict) -> bool:
    """Feed records are untrusted — an id that isn't CVE-shaped (or is huge)
    would become an OpenSearch _id and can poison or wedge ingest (the bulk
    _id limit is 512 bytes; a failed batch holds the watermark forever)."""
    return bool(_CVE_ID_RE.fullmatch(str(cve.get("id", ""))))


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
        spacing_seconds: float | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None
        if spacing_seconds is None:
            spacing_seconds = REQUEST_SPACING_SECONDS if api_key else KEYLESS_SPACING_SECONDS
        self._spacing = spacing_seconds
        self._sleep = sleep

    @property
    def spacing_seconds(self) -> float:
        """Quota-aware request spacing — callers doing their own pacing (the
        KEV singles loop) must use this, not a constant of their own."""
        return self._spacing

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
        if resp.status_code in (403, 429):
            # Quota exceeded. NVDError holds the watermark; the cycle retries
            # next interval with quota-aware spacing.
            raise NVDError(
                f"NVD rate limited (HTTP {resp.status_code}) — quota is "
                f"{'50' if self._api_key else '5 (keyless)'} req/30 s; "
                "watermark held, retrying next cycle"
            )
        resp.raise_for_status()
        return resp.json()

    async def pages(self, start: datetime, end: datetime):
        """Yield raw `vulnerabilities[i].cve` dicts one PAGE at a time so a
        120-day catch-up window (~92k records at the probed rate) is never
        materialized in memory at once — callers ingest per page and keep
        their watermark per window (S8 review). Page order is not
        contractual — callers upsert by id."""
        start_index = 0
        page_count = 0
        while True:
            body = await self._get(
                {
                    "lastModStartDate": _iso(start),
                    "lastModEndDate": _iso(end),
                    "resultsPerPage": RESULTS_PER_PAGE,
                    "startIndex": start_index,
                }
            )
            page_count += 1
            cves = [v["cve"] for v in body.get("vulnerabilities", ())]
            if cves:
                yield cves
            page = body.get("resultsPerPage", 0)
            start_index += page
            if page == 0 or start_index >= body.get("totalResults", 0):
                return
            if page_count >= MAX_PAGES_PER_WINDOW:
                raise NVDError(
                    f"window still paging after {MAX_PAGES_PER_WINDOW} pages "
                    "(poisoned totalResults or a rate far past the probed one); "
                    "watermark held"
                )
            await self._sleep(self._spacing)

    async def fetch_window(self, start: datetime, end: datetime) -> list[dict]:
        """All of one window's CVEs in a single list — convenience over
        pages() for small windows and tests."""
        out: list[dict] = []
        async for page in self.pages(start, end):
            out.extend(page)
        return out

    async def fetch_cve(self, cve_id: str) -> dict | None:
        """Single-CVE fetch (the KEV-new-entry path). None = NVD holds no such
        CVE (a 200 with zero results — NOT a 404, which raises)."""
        body = await self._get({"cveId": cve_id})
        vulns = body.get("vulnerabilities", ())
        return vulns[0]["cve"] if vulns else None
