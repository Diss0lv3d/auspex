"""FIRST EPSS API client — probe-pinned (docs/probes/2026-07-17-first-epss.md).

Batch by comma-separated `cve` param. Rows come back in ARBITRARY order and
unknown CVEs are silently dropped (200, no error, no null row) — so results
are keyed by the `cve` field from the RESPONSE, never zipped positionally.
Scores are 9-decimal strings; a missing row means "EPSS holds no score"
(new/rejected CVE) and must render as absence, not 0.0.
"""

from collections.abc import Sequence

import httpx

from auspex import __version__

EPSS_API_URL = "https://api.first.org/data/v1/epss"
EPSS_BATCH_SIZE = 100  # URL-length safety; the API pages at ~this size anyway
CALL_TIMEOUT_SECONDS = 30.0


class EPSSFeed:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": f"Auspex/{__version__}"},
                timeout=CALL_TIMEOUT_SECONDS,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    async def scores(self, cve_ids: Sequence[str]) -> dict[str, dict]:
        """EPSS rows for the known subset of `cve_ids`, keyed by upper CVE id.
        Absent key == EPSS has no score for it."""
        out: dict[str, dict] = {}
        ids = [c.upper() for c in cve_ids]
        client = self._get_client()
        for start in range(0, len(ids), EPSS_BATCH_SIZE):
            batch = ids[start : start + EPSS_BATCH_SIZE]
            resp = await client.get(
                EPSS_API_URL, params={"cve": ",".join(batch), "limit": len(batch)}
            )
            resp.raise_for_status()
            for row in resp.json().get("data", ()):
                out[row["cve"].upper()] = row
        return out
