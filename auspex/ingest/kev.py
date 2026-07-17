"""CISA KEV catalog client — probe-pinned (docs/probes/2026-07-17-cisa-kev.md).

One static JSON file, business-daily updates. Conditional GET works via
If-Modified-Since ONLY — the ETag varies by content-encoding at their CDN
(probed: replaying the exact etag returned 200 + full body). gzip cuts the
1.5 MB body to ~178 KB; httpx negotiates that by default.
"""

from dataclasses import dataclass

import httpx

from auspex import __version__

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
CALL_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class KEVCatalog:
    catalog_version: str  # e.g. "2026.07.16"
    date_released: str
    last_modified: str  # HTTP Last-Modified header — the conditional-GET cursor
    entries: dict[str, dict]  # cveID (upper) -> raw KEV entry


class KEVFeed:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": f"Auspex/{__version__}"},
                timeout=CALL_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    async def fetch(self, *, if_modified_since: str = "") -> KEVCatalog | None:
        """The full catalog, or None when unchanged since the given
        Last-Modified value (304)."""
        headers = {"If-Modified-Since": if_modified_since} if if_modified_since else {}
        resp = await self._get_client().get(KEV_URL, headers=headers)
        if resp.status_code == 304:
            return None
        resp.raise_for_status()
        body = resp.json()
        return KEVCatalog(
            catalog_version=body.get("catalogVersion", ""),
            date_released=body.get("dateReleased", ""),
            last_modified=resp.headers.get("last-modified", ""),
            entries={v["cveID"].upper(): v for v in body.get("vulnerabilities", ())},
        )
