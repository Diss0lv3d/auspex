"""S7 feed clients vs scripted HTTP — hermetic (httpx.MockTransport). Response
bodies come from tests/fixtures/*, trimmed verbatim from the live probes
(docs/probes/2026-07-17-{nvd-delta,cisa-kev,first-epss}.md)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from auspex.ingest.enrich import enrich_doc
from auspex.ingest.epss import EPSSFeed
from auspex.ingest.kev import KEVFeed
from auspex.ingest.nvd import NVDError, NVDFeed, is_rejected, windows
from auspex.kb.seed import nvd_to_doc

FIXTURES = Path(__file__).parent / "fixtures"
NVD_PAGE = json.loads((FIXTURES / "nvd_delta_page.json").read_text())
KEV_CATALOG = json.loads((FIXTURES / "kev_catalog.json").read_text())
EPSS_BATCH = json.loads((FIXTURES / "epss_batch.json").read_text())


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


# ── window chunking (the ≤120-day API limit) ────────────────────────────────


def test_windows_chunks_long_gaps_contiguously():
    ws = windows(_dt("2025-09-01T00:00:00"), _dt("2026-07-17T00:00:00"))
    assert len(ws) == 3  # 319 days → 120 + 120 + 79
    assert all((b - a).days <= 120 for a, b in ws)
    assert ws[0][0] == _dt("2025-09-01T00:00:00")
    assert ws[-1][1] == _dt("2026-07-17T00:00:00")
    for (_, end), (start, _) in zip(ws, ws[1:], strict=False):
        assert end == start  # no gaps, no overlap


def test_windows_short_gap_is_one_window_and_empty_gap_is_none():
    assert len(windows(_dt("2026-07-07T00:00:00"), _dt("2026-07-17T00:00:00"))) == 1
    assert windows(_dt("2026-07-17T00:00:00"), _dt("2026-07-17T00:00:00")) == []


# ── NVD delta ───────────────────────────────────────────────────────────────


class NVDRouter:
    """Scripted NVD: fixture page split into per-request pages by startIndex."""

    def __init__(self, cves: list[dict], page_size: int = 2):
        self.cves = cves
        self.page_size = page_size
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(params)
        if "cveId" in params:
            match = [v for v in self.cves if v["cve"]["id"] == params["cveId"]]
            return httpx.Response(
                200, json={"totalResults": len(match), "vulnerabilities": match}
            )
        start = int(params.get("startIndex", 0))
        page = self.cves[start : start + self.page_size]
        return httpx.Response(
            200,
            json={
                "resultsPerPage": len(page),
                "startIndex": start,
                "totalResults": len(self.cves),
                "vulnerabilities": page,
            },
        )


def _nvd_feed(handler, **kwargs) -> NVDFeed:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return NVDFeed(client=client, **kwargs)


async def test_nvd_fetch_window_pages_to_total_with_spacing():
    router = NVDRouter(NVD_PAGE["vulnerabilities"], page_size=2)  # 3 cves → 2 pages
    naps: list[float] = []

    async def fake_sleep(s: float) -> None:
        naps.append(s)

    feed = _nvd_feed(router, sleep=fake_sleep)
    cves = await feed.fetch_window(_dt("2026-07-16T00:00:00"), _dt("2026-07-17T00:00:00"))
    assert [c["id"] for c in cves] == ["CVE-2023-4346", "CVE-2024-8751", "CVE-2024-7038"]
    assert len(router.requests) == 2  # paged, not slurped
    assert router.requests[1]["startIndex"] == "2"
    assert router.requests[0]["lastModStartDate"] == "2026-07-16T00:00:00.000Z"
    assert naps == [3.0]  # polite spacing BETWEEN pages only


async def test_nvd_404_surfaces_the_message_header_never_parses_the_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"message": "Date range cannot exceed 120 days."})

    feed = _nvd_feed(handler)
    with pytest.raises(NVDError, match="120 days"):
        await feed.fetch_window(_dt("2026-01-01T00:00:00"), _dt("2026-07-17T00:00:00"))


async def test_nvd_single_cve_fetch_and_not_found_are_distinct():
    router = NVDRouter(NVD_PAGE["vulnerabilities"])
    feed = _nvd_feed(router)
    cve = await feed.fetch_cve("CVE-2023-4346")
    assert cve is not None and cve["vulnStatus"] == "Analyzed"
    assert await feed.fetch_cve("CVE-1999-0000") is None  # 200-empty ≠ 404


def test_rejected_cves_are_detectable_for_the_skip_policy():
    statuses = {v["cve"]["id"]: is_rejected(v["cve"]) for v in NVD_PAGE["vulnerabilities"]}
    assert statuses == {
        "CVE-2023-4346": False,
        "CVE-2024-8751": False,  # Deferred is NOT rejected — it still indexes
        "CVE-2024-7038": True,
    }


# ── CISA KEV ────────────────────────────────────────────────────────────────


async def test_kev_fetch_parses_catalog_and_keys_by_cve_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "If-Modified-Since" not in request.headers
        return httpx.Response(
            200, json=KEV_CATALOG, headers={"Last-Modified": "Thu, 16 Jul 2026 17:00:15 GMT"}
        )

    catalog = await KEVFeed(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ).fetch()
    assert catalog is not None
    assert catalog.catalog_version == "2026.07.16"
    assert catalog.last_modified == "Thu, 16 Jul 2026 17:00:15 GMT"
    log4 = catalog.entries["CVE-2021-44228"]
    assert log4["dateAdded"] == "2021-12-10"
    assert log4["knownRansomwareCampaignUse"] == "Known"


async def test_kev_conditional_get_returns_none_on_304():
    def handler(request: httpx.Request) -> httpx.Response:
        # If-Modified-Since is the ONLY working conditional (probed; ETag varies
        # by content-encoding at their CDN)
        assert request.headers["If-Modified-Since"] == "Thu, 16 Jul 2026 17:00:15 GMT"
        return httpx.Response(304)

    feed = KEVFeed(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await feed.fetch(if_modified_since="Thu, 16 Jul 2026 17:00:15 GMT") is None


# ── FIRST EPSS ──────────────────────────────────────────────────────────────


async def test_epss_scores_key_by_response_cve_and_drop_unknowns_silently():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=EPSS_BATCH)  # rows in arbitrary order (live)

    feed = EPSSFeed(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    scores = await feed.scores(["CVE-2021-44228", "CVE-2017-0144", "CVE-9999-99999"])
    assert scores["CVE-2021-44228"]["epss"] == "0.999990000"  # keyed, not positional
    assert "CVE-9999-99999" not in scores  # unknown = absent, not 0.0


async def test_epss_batches_at_one_hundred_ids():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(len(request.url.params["cve"].split(",")))
        return httpx.Response(200, json={"data": []})

    feed = EPSSFeed(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await feed.scores([f"CVE-2024-{i:05d}" for i in range(150)])
    assert calls == [100, 50]


# ── enrichment merge (pure) ─────────────────────────────────────────────────


def _doc():
    return nvd_to_doc(NVD_PAGE["vulnerabilities"][0]["cve"])


def test_enrich_doc_merges_kev_and_epss_evidence():
    kev = KEV_CATALOG["vulnerabilities"][2]  # Log4Shell: ransomware Known
    epss = {
        "cve": "CVE-2023-4346",
        "epss": "0.974080000",
        "percentile": "0.998900000",
        "date": "2026-07-16",
    }
    doc = enrich_doc(_doc(), kev, epss)
    assert doc.kev_date_added == "2021-12-10" and doc.kev_ransomware is True
    assert doc.epss_score == pytest.approx(0.97408)  # string → float here, once
    assert doc.epss_percentile == pytest.approx(0.9989)
    assert doc.epss_date == "2026-07-16"
    assert doc.content == _doc().content  # evidence never rewrites the description


def test_enrich_doc_absence_and_unknown_stay_absent():
    assert enrich_doc(_doc(), None, None) == _doc()  # no evidence ⇒ unchanged doc
    sharepoint = KEV_CATALOG["vulnerabilities"][0]  # ransomware "Unknown"
    doc = enrich_doc(_doc(), sharepoint, None)
    assert doc.kev_date_added == "2026-07-16"
    assert doc.kev_ransomware is False  # Unknown is not Known
    assert doc.epss_score is None and doc.epss_date == ""
