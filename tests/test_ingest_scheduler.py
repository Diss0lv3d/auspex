"""S7 ingest scheduler — hermetic: fake feeds, fake KB, in-memory state.
Catalog/CVE shapes come verbatim from the probe fixtures. The scheduler's
testable unit is run_cycle(); the infinite loop body is not spun here."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from auspex.ingest.events import DocChange
from auspex.ingest.kev import KEVCatalog
from auspex.ingest.scheduler import KEV_FEED, NVD_FEED, IngestScheduler
from auspex.ingest.state import FeedState
from auspex.kb.types import KBUnavailable

FIXTURES = Path(__file__).parent / "fixtures"
KEV_RAW = json.loads((FIXTURES / "kev_catalog.json").read_text())
NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=UTC)


def kev_catalog(last_modified: str = "Thu, 16 Jul 2026 17:00:15 GMT") -> KEVCatalog:
    return KEVCatalog(
        catalog_version=KEV_RAW["catalogVersion"],
        date_released=KEV_RAW["dateReleased"],
        last_modified=last_modified,
        entries={v["cveID"].upper(): v for v in KEV_RAW["vulnerabilities"]},
    )


def nvd_cve(cve_id: str, *, status: str = "Analyzed") -> dict:
    return {
        "id": cve_id,
        "vulnStatus": status,
        "descriptions": [{"lang": "en", "value": f"Description of {cve_id}."}],
        "metrics": {},
    }


class FakeState:
    def __init__(self, rows: dict[str, dict] | None = None):
        self.rows: dict[str, dict] = rows or {}
        self.records: list[tuple[str, dict, str]] = []

    async def get(self, feed: str) -> FeedState | None:
        if feed not in self.rows:
            return None
        return FeedState(
            feed=feed,
            cursor=self.rows[feed],
            last_run_at=None,
            last_status="",
            docs_upserted=0,
        )

    async def record(self, feed: str, *, cursor: dict, status: str, docs_delta: int = 0) -> None:
        self.rows[feed] = cursor
        self.records.append((feed, cursor, status))


class FakeNVD:
    def __init__(self, window_cves: list[dict] | None = None, singles: dict | None = None):
        self.window_cves = window_cves or []
        self.singles = singles or {}
        self.window_calls: list[tuple[datetime, datetime]] = []
        self.single_calls: list[str] = []

    async def fetch_window(self, start: datetime, end: datetime) -> list[dict]:
        self.window_calls.append((start, end))
        return self.window_cves

    async def fetch_cve(self, cve_id: str) -> dict | None:
        self.single_calls.append(cve_id)
        return self.singles.get(cve_id)

    async def aclose(self) -> None:
        pass


class FakeKEV:
    """Replays a script of fetch() results (a KEVCatalog, or None for a 304)."""

    def __init__(self, script: list):
        self.script = list(script)
        self.conditional_args: list[str] = []

    async def fetch(self, *, if_modified_since: str = ""):
        self.conditional_args.append(if_modified_since)
        return self.script.pop(0)

    async def aclose(self) -> None:
        pass


class FakeEPSS:
    def __init__(self, scores: dict[str, dict] | None = None):
        self.scores_map = scores or {}
        self.batches: list[list[str]] = []

    async def scores(self, cve_ids) -> dict[str, dict]:
        ids = list(cve_ids)
        self.batches.append(ids)
        return {c: self.scores_map[c] for c in ids if c in self.scores_map}

    async def aclose(self) -> None:
        pass


class FakeKB:
    def __init__(self, *, held_cves: list[str] | None = None, active: bool = True):
        self.active = active
        self.held_cves = held_cves or []
        self.ingested: list[list] = []  # one entry per ingest_docs call
        self.bootstrap_calls = 0
        self.fail_ingest = False

    async def bootstrap(self) -> str:
        self.bootstrap_calls += 1
        return "fake bootstrap ok"

    async def ingest_docs(self, docs) -> int:
        if self.fail_ingest:
            raise KBUnavailable("knowledge base unreachable: simulated")
        self.ingested.append(list(docs))
        return len(docs)  # 1 chunk per doc is fine for tests

    async def list_cve_ids(self, *, max_ids: int = 10_000) -> list[str]:
        return list(self.held_cves)


class RecordingSink:
    def __init__(self):
        self.events: list[DocChange] = []

    async def emit(self, changes) -> None:
        self.events.extend(changes)


async def _no_sleep(_: float) -> None:
    return None


def scheduler(**overrides) -> IngestScheduler:
    defaults = dict(
        kb=FakeKB(),
        state=FakeState(),
        nvd=FakeNVD(),
        kev=FakeKEV([kev_catalog()]),
        epss=FakeEPSS(),
        sink=RecordingSink(),
        now=lambda: NOW,
        sleep=_no_sleep,
    )
    defaults.update(overrides)
    return IngestScheduler(**defaults)


def all_docs(kb: FakeKB) -> dict[str, object]:
    return {d.doc_id: d for batch in kb.ingested for d in batch}


# ── first run ───────────────────────────────────────────────────────────────


async def test_first_run_ingests_backfill_window_skips_rejected_and_enriches():
    kb = FakeKB(held_cves=[])
    nvd = FakeNVD(
        window_cves=[
            nvd_cve("CVE-2024-3400"),  # present in the KEV fixture
            nvd_cve("CVE-2024-9999"),
            nvd_cve("CVE-2024-7038", status="Rejected"),  # must be skipped
        ]
    )
    epss = FakeEPSS(
        {"CVE-2024-3400": {"cve": "CVE-2024-3400", "epss": "0.999990000",
                           "percentile": "1.000000000", "date": "2026-07-16"}}
    )
    state = FakeState()
    sink = RecordingSink()
    sched = scheduler(kb=kb, nvd=nvd, epss=epss, state=state, sink=sink)
    summary = await sched.run_cycle()
    assert "1 window(s)" in summary and "1 rejected skipped" in summary
    docs = all_docs(kb)
    assert set(docs) == {"CVE-2024-3400", "CVE-2024-9999"}
    enriched = docs["CVE-2024-3400"]
    assert enriched.kev_date_added == "2024-04-12"  # verbatim from the KEV fixture
    assert enriched.kev_ransomware is True  # KEV fixture: Known
    assert enriched.epss_score == pytest.approx(0.99999)
    plain = docs["CVE-2024-9999"]
    assert plain.kev_date_added == "" and plain.epss_score is None  # absence stays absent
    # first-run backfill window: exactly [NOW-1d, NOW]
    assert nvd.window_calls == [(NOW - timedelta(days=1), NOW)]
    # watermark advanced to NOW only after ingest
    assert state.rows[NVD_FEED]["last_mod_end"] == NOW.isoformat()
    # KEV first run: horizon set to catalog max, no historical backfill
    assert state.rows[KEV_FEED]["date_added_horizon"] == "2026-07-16"
    assert nvd.single_calls == []  # nothing KEV-fetched (KB held nothing)
    kinds = {(e.feed, e.kind) for e in sink.events}
    assert kinds == {(NVD_FEED, "upserted")}


async def test_first_run_refreshes_kb_held_cves_from_kev():
    # The KB already holds seed CVEs; the first KEV run must re-enrich the ones
    # KEV knows via single-CVE NVD fetches, and mark the refresh done.
    kb = FakeKB(held_cves=["CVE-2021-44228", "CVE-2017-0144"])  # only the first is in KEV fixture
    nvd = FakeNVD(singles={"CVE-2021-44228": nvd_cve("CVE-2021-44228")})
    sink = RecordingSink()
    state = FakeState()
    sched = scheduler(kb=kb, nvd=nvd, state=state, sink=sink)
    await sched.run_cycle()
    assert nvd.single_calls == ["CVE-2021-44228"]  # intersection only
    doc = all_docs(kb)["CVE-2021-44228"]
    assert doc.kev_date_added == "2021-12-10" and doc.kev_ransomware is True
    assert state.rows[KEV_FEED]["kb_refreshed"] is True
    assert (KEV_FEED, "kev-added") in {(e.feed, e.kind) for e in sink.events}


# ── catch-up across gaps (the S7 success criterion) ─────────────────────────


async def test_catchup_chunks_long_gap_and_advances_watermark_per_window():
    since = NOW - timedelta(days=200)
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": since.isoformat()},
            KEV_FEED: {
                "last_modified": "x",
                "date_added_horizon": "2026-07-16",
                "kb_refreshed": True,
            },
        }
    )
    nvd = FakeNVD(window_cves=[nvd_cve("CVE-2024-0001")])
    sched = scheduler(nvd=nvd, state=state)
    await sched.run_cycle()
    assert len(nvd.window_calls) == 2  # 200 days → 120 + 80
    assert nvd.window_calls[0][0] == since
    assert nvd.window_calls[1][1] == NOW
    assert nvd.window_calls[0][1] == nvd.window_calls[1][0]  # contiguous
    # one watermark record per window, in order — a crash mid-catch-up
    # resumes from the last completed window, not the start
    nvd_records = [(c, s) for f, c, s in state.records if f == NVD_FEED]
    assert len(nvd_records) == 2
    assert nvd_records[0][0]["last_mod_end"] == nvd.window_calls[0][1].isoformat()
    assert nvd_records[1][0]["last_mod_end"] == NOW.isoformat()


async def test_failed_ingest_never_advances_the_watermark():
    since = NOW - timedelta(days=3)
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": since.isoformat()},
            KEV_FEED: {
                "last_modified": "x",
                "date_added_horizon": "2026-07-16",
                "kb_refreshed": True,
            },
        }
    )
    kb = FakeKB()
    kb.fail_ingest = True
    sched = scheduler(kb=kb, state=state, nvd=FakeNVD(window_cves=[nvd_cve("CVE-2024-0001")]))
    with pytest.raises(KBUnavailable):
        await sched.run_cycle()
    assert state.rows[NVD_FEED]["last_mod_end"] == since.isoformat()  # unchanged
    assert [f for f, _, _ in state.records if f == NVD_FEED] == []


# ── KEV increments ──────────────────────────────────────────────────────────


async def test_new_kev_entry_is_fetched_enriched_and_horizon_advances():
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": NOW.isoformat()},
            KEV_FEED: {
                "last_modified": "Wed, 15 Jul 2026 17:00:00 GMT",
                "date_added_horizon": "2026-07-15",  # SharePoint (2026-07-16) is new
                "kb_refreshed": True,
            },
        }
    )
    nvd = FakeNVD(singles={"CVE-2026-58644": nvd_cve("CVE-2026-58644")})
    kb = FakeKB()
    sink = RecordingSink()
    sched = scheduler(kb=kb, nvd=nvd, state=state, sink=sink)
    summary = await sched.run_cycle()
    assert nvd.single_calls == ["CVE-2026-58644"]
    doc = all_docs(kb)["CVE-2026-58644"]
    assert doc.kev_date_added == "2026-07-16"
    assert doc.kev_ransomware is False  # fixture: "Unknown" stays absence
    assert state.rows[KEV_FEED]["date_added_horizon"] == "2026-07-16"
    assert DocChange("CVE-2026-58644", KEV_FEED, "kev-added") in sink.events
    assert "1 chunks from 1 docs" in summary


async def test_304_cycle_reuses_cached_catalog_for_enrichment():
    state = FakeState(
        rows={
            KEV_FEED: {
                "last_modified": "Thu, 16 Jul 2026 17:00:15 GMT",
                "date_added_horizon": "2026-07-16",
                "kb_refreshed": True,
            }
        }
    )
    kev = FakeKEV([kev_catalog(), None])  # cycle 1: full body; cycle 2: 304
    nvd = FakeNVD(window_cves=[nvd_cve("CVE-2024-3400")])  # in KEV
    kb = FakeKB()
    sched = scheduler(kb=kb, kev=kev, nvd=nvd, state=state)
    await sched.run_cycle()
    await sched.run_cycle()
    # cycle 1 fetched unconditionally (no cache to back a 304 after a boot)
    assert kev.conditional_args[0] == ""
    assert kev.conditional_args[1] == "Thu, 16 Jul 2026 17:00:15 GMT"
    # cycle 2's NVD doc still got KEV evidence — from the in-memory cache
    assert kb.ingested[-1][0].kev_date_added != ""


async def test_kev_new_id_already_ingested_via_nvd_is_not_refetched():
    # A CVE that is both KEV-new AND in this cycle's NVD window was already
    # enriched from this same catalog — no second NVD fetch; the horizon must
    # still advance past it (or it would re-surface every cycle forever).
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": (NOW - timedelta(days=1)).isoformat()},
            KEV_FEED: {
                "last_modified": "Wed, 15 Jul 2026 17:00:00 GMT",
                "date_added_horizon": "2026-07-15",
                "kb_refreshed": True,
            },
        }
    )
    nvd = FakeNVD(window_cves=[nvd_cve("CVE-2026-58644")])  # KEV-new AND in the window
    sched = scheduler(nvd=nvd, state=state)
    await sched.run_cycle()
    assert nvd.single_calls == []  # no double fetch
    assert state.rows[KEV_FEED]["date_added_horizon"] == "2026-07-16"  # still advances


# ── run() task body ─────────────────────────────────────────────────────────


async def test_run_bootstraps_kb_then_idles_when_ingest_disabled():
    kb = FakeKB()
    sched = scheduler(kb=kb, enabled=False)
    await sched.run()  # must return (not loop) — the task ends after bootstrap
    assert kb.bootstrap_calls == 1
    assert kb.ingested == []  # no cycle ran
