"""S7 ingest scheduler — hermetic: fake feeds, fake KB, in-memory state.
Catalog/CVE shapes come verbatim from the probe fixtures. The scheduler's
testable unit is run_cycle(); the infinite loop body is not spun here."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from auspex.checks import DEGRADED_AFTER
from auspex.ingest.events import DocChange
from auspex.ingest.kev import KEVCatalog
from auspex.ingest.scheduler import ATTACK_FEED, KEV_FEED, NVD_FEED, IngestScheduler
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
    def __init__(
        self,
        window_cves: list[dict] | None = None,
        singles: dict | None = None,
        window_pages: list[list[dict]] | None = None,
        fail_pages: bool = False,
    ):
        self.window_cves = window_cves or []
        self.window_pages = window_pages  # explicit multi-page script, if set
        self.singles = singles or {}
        self.fail_pages = fail_pages  # simulate NVDError (bad key / outage)
        self.spacing_seconds = 3.0  # the real feed derives this from key presence
        self.window_calls: list[tuple[datetime, datetime]] = []
        self.single_calls: list[str] = []

    async def pages(self, start: datetime, end: datetime):
        self.window_calls.append((start, end))
        if self.fail_pages:
            raise RuntimeError("NVD 403: invalid API key")
        for page in self.window_pages if self.window_pages is not None else [self.window_cves]:
            yield page

    async def fetch_cve(self, cve_id: str) -> dict | None:
        self.single_calls.append(cve_id)
        return self.singles.get(cve_id)

    async def aclose(self) -> None:
        pass


class FakeKEV:
    """Replays a script of fetch() results (a KEVCatalog, None for a 304, or
    an Exception instance to raise)."""

    def __init__(self, script: list):
        self.script = list(script)
        self.conditional_args: list[str] = []

    async def fetch(self, *, if_modified_since: str = ""):
        self.conditional_args.append(if_modified_since)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

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
        self.deleted: list[list[str]] = []  # one entry per delete_docs call
        self.retired: list[tuple[str, list[str]]] = []  # one per retire_absent call
        self.retire_count = 0  # what retire_absent returns
        self.enriched_in_place: list[dict] = []  # one entry per apply_enrichment call
        self.bootstrap_calls = 0
        self.fail_ingest = False
        self.bootstrapped = True  # set False to simulate a failed boot bootstrap
        self.bootstrap_heals = True  # whether a retry succeeds

    async def bootstrap(self) -> str:
        self.bootstrap_calls += 1
        if self.bootstrap_heals:
            self.bootstrapped = True
        return "fake bootstrap ok" if self.bootstrapped else "fake bootstrap failed"

    async def ingest_docs(self, docs) -> int:
        if self.fail_ingest:
            raise KBUnavailable("knowledge base unreachable: simulated")
        self.ingested.append(list(docs))
        return len(docs)  # 1 chunk per doc is fine for tests

    async def delete_docs(self, doc_ids) -> int:
        self.deleted.append(list(doc_ids))
        return len(doc_ids)

    async def retire_absent(self, source: str, keep_doc_ids) -> int:
        self.retired.append((source, list(keep_doc_ids)))
        return self.retire_count

    async def apply_enrichment(self, updates: dict) -> int:
        self.enriched_in_place.append(dict(updates))
        return len(updates)  # 1 chunk per doc is fine for tests

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
    assert "1 window(s)" in summary and "1 skipped (rejected/invalid)" in summary
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
    # KEV first run: horizon = last FULLY-covered date; the newest date's ids
    # sit in done_ids so a same-day follow-up release is still picked up
    assert state.rows[KEV_FEED]["date_added_horizon"] == "2024-04-12"
    assert state.rows[KEV_FEED]["done_ids"] == ["CVE-2026-58644"]
    assert nvd.single_calls == []  # nothing KEV-fetched (KB held nothing)
    kinds = {(e.feed, e.kind) for e in sink.events}
    # the rejected CVE emits a delete (held-chunk cleanup is a no-op here)
    assert kinds == {(NVD_FEED, "upserted"), (NVD_FEED, "deleted")}


async def test_first_run_refreshes_kb_held_cves_in_place_without_nvd_fetches():
    # The KB already holds seed CVEs; the first KEV run re-enriches the ones
    # KEV knows via ONE update_by_query — no NVD singles (S8 review: the
    # singles loop was uncapped and all-or-nothing against a grown KB).
    kb = FakeKB(held_cves=["CVE-2021-44228", "CVE-2017-0144"])  # only the first is in KEV fixture
    nvd = FakeNVD()
    epss = FakeEPSS(
        {"CVE-2021-44228": {"cve": "CVE-2021-44228", "epss": "0.999990000",
                            "percentile": "1.000000000", "date": "2026-07-16"}}
    )
    sink = RecordingSink()
    state = FakeState()
    sched = scheduler(kb=kb, nvd=nvd, epss=epss, state=state, sink=sink)
    summary = await sched.run_cycle()
    assert nvd.single_calls == []  # held docs are never re-fetched
    assert epss.batches == [["CVE-2021-44228"]]  # intersection only
    assert len(kb.enriched_in_place) == 1
    fields = kb.enriched_in_place[0]["CVE-2021-44228"]
    assert fields["kev_listed"] is True
    assert fields["kev_date_added"] == "2021-12-10" and fields["kev_ransomware"] is True
    assert fields["epss_score"] == pytest.approx(0.99999)
    assert state.rows[KEV_FEED]["kb_refreshed"] is True
    assert (KEV_FEED, "kev-added") in {(e.feed, e.kind) for e in sink.events}
    assert "refreshed 1 held chunks" in summary


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


async def test_window_pages_ingest_as_they_arrive_watermark_after_last_page():
    # S8 review: the whole window used to be materialized before one ingest —
    # a 120-day catch-up (~92k records) OOMed. Pages must ingest one at a
    # time; the watermark still records once, per window, after the last page.
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
    nvd = FakeNVD(
        window_pages=[[nvd_cve("CVE-2024-0001")], [nvd_cve("CVE-2024-0002")]]
    )
    sched = scheduler(kb=kb, nvd=nvd, state=state)
    await sched.run_cycle()
    assert len(kb.ingested) == 2  # one ingest call PER PAGE
    assert [d.doc_id for batch in kb.ingested for d in batch] == [
        "CVE-2024-0001",
        "CVE-2024-0002",
    ]
    nvd_records = [(c, s) for f, c, s in state.records if f == NVD_FEED]
    assert len(nvd_records) == 1  # but one watermark record per WINDOW
    assert nvd_records[0][0]["last_mod_end"] == NOW.isoformat()
    assert "2 chunks" in nvd_records[0][1]


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
    # A KB outage holds the CVE pipeline without advancing the watermark. The
    # hold is now local (S9 review): run_cycle reports the failure instead of
    # re-raising, so ATT&CK still gets its turn — but the watermark-hold
    # invariant (the point of this test) is unchanged.
    summary = await sched.run_cycle()
    assert "kev/nvd/kev-docs: failed" in summary
    assert state.rows[NVD_FEED]["last_mod_end"] == since.isoformat()  # unchanged
    assert [f for f, _, _ in state.records if f == NVD_FEED] == []


# ── KEV increments ──────────────────────────────────────────────────────────


async def test_new_kev_entry_is_fetched_enriched_and_marked_done():
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
    # 2026-07-16 is the catalog's NEWEST date — it never becomes the horizon
    # (CISA appends same-day follow-ups); the processed id waits in done_ids.
    assert state.rows[KEV_FEED]["date_added_horizon"] == "2026-07-15"
    assert state.rows[KEV_FEED]["done_ids"] == ["CVE-2026-58644"]
    assert DocChange("CVE-2026-58644", KEV_FEED, "kev-added") in sink.events
    assert "1 chunks from 1 docs" in summary


async def test_304_cycle_reuses_cached_catalog_for_enrichment():
    # S8 test-hygiene: the old version gave cycle 2 no work (windows(NOW, NOW)
    # is empty), so its headline assert checked CYCLE 1's batch — a mutant
    # with cache reuse deleted passed. The clock now advances so cycle 2
    # genuinely ingests, and its batch must carry KEV evidence from the CACHE.
    clock = {"now": NOW}
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": (NOW - timedelta(hours=1)).isoformat()},
            KEV_FEED: {
                "last_modified": "Thu, 16 Jul 2026 17:00:15 GMT",
                "date_added_horizon": "2026-07-16",
                "kb_refreshed": True,
            },
        }
    )
    kev = FakeKEV([kev_catalog(), None])  # cycle 1: full body; cycle 2: 304
    nvd = FakeNVD(window_cves=[nvd_cve("CVE-2024-3400")])  # in KEV
    kb = FakeKB()
    sched = scheduler(kb=kb, kev=kev, nvd=nvd, state=state, now=lambda: clock["now"])
    await sched.run_cycle()
    clock["now"] = NOW + timedelta(hours=1)  # cycle 2 has a fresh window to cover
    await sched.run_cycle()
    # cycle 1 fetched unconditionally (no cache to back a 304 after a boot)
    assert kev.conditional_args[0] == ""
    assert kev.conditional_args[1] == "Thu, 16 Jul 2026 17:00:15 GMT"
    # cycle 2 DID ingest, and its doc got KEV evidence — from the in-memory cache
    assert len(kb.ingested) == 2
    assert kb.ingested[-1][0].kev_date_added == "2024-04-12"


async def test_kev_new_id_already_ingested_via_nvd_is_not_refetched():
    # A CVE that is both KEV-new AND in this cycle's NVD window was already
    # enriched from this same catalog — no second NVD fetch; it must still be
    # marked done (or it would re-surface every cycle forever).
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
    sched = scheduler(nvd=nvd, state=state, kev=FakeKEV([kev_catalog(), None]))
    await sched.run_cycle()
    assert nvd.single_calls == []  # no double fetch
    assert state.rows[KEV_FEED]["done_ids"] == ["CVE-2026-58644"]
    # the invariant itself: a later 304 cycle must not re-surface the id
    await sched.run_cycle()
    assert nvd.single_calls == []


# ── KEV cursor boundary math (S8 review: the cap lost same-date entries) ────


def make_catalog(
    dated_ids: dict[str, str], *, last_modified: str = "LM-1", version: str = "v1"
) -> KEVCatalog:
    return KEVCatalog(
        catalog_version=version,
        date_released="",
        last_modified=last_modified,
        entries={
            cve: {"cveID": cve, "dateAdded": date, "knownRansomwareCampaignUse": "Unknown"}
            for cve, date in dated_ids.items()
        },
    )


def kev_cursor(**overrides) -> dict:
    base = {"last_modified": "LM-0", "date_added_horizon": "2026-07-10", "kb_refreshed": True}
    base.update(overrides)
    return base


async def test_kev_cap_same_date_batch_processes_remainder_across_304_cycles():
    # S8 review regression: 6 same-date entries, cap 4 — the old horizon (max
    # of processed dateAdded + strict >) lost the last 2 FOREVER. They must be
    # fetched on the next cycle, even though that cycle sees a 304.
    ids = {f"CVE-2026-1000{i}": "2026-07-16" for i in range(6)}
    catalog = make_catalog(ids)
    nvd = FakeNVD(singles={c: nvd_cve(c) for c in ids})
    state = FakeState(
        rows={NVD_FEED: {"last_mod_end": NOW.isoformat()}, KEV_FEED: kev_cursor()}
    )
    sched = scheduler(
        nvd=nvd, state=state, kev=FakeKEV([catalog, None]), kev_single_fetch_cap=4
    )
    await sched.run_cycle()
    assert len(nvd.single_calls) == 4
    assert state.rows[KEV_FEED]["done_ids"] == sorted(ids)[:4]
    await sched.run_cycle()  # 304 — the cached catalog must still be scanned
    assert len(nvd.single_calls) == 6
    assert sorted(nvd.single_calls) == sorted(ids)
    assert state.rows[KEV_FEED]["done_ids"] == sorted(ids)
    # same-date == newest date: the horizon must NOT advance into it
    assert state.rows[KEV_FEED]["date_added_horizon"] == "2026-07-10"


async def test_second_same_day_kev_release_is_picked_up():
    # CISA sometimes ships twice in one day with the same dateAdded. The
    # follow-up entry must be selected even though the first release's ids
    # were already processed.
    first = make_catalog({"CVE-2026-20001": "2026-07-16"}, last_modified="LM-1")
    second = make_catalog(
        {"CVE-2026-20001": "2026-07-16", "CVE-2026-20002": "2026-07-16"},
        last_modified="LM-2",
    )
    nvd = FakeNVD(
        singles={"CVE-2026-20001": nvd_cve("CVE-2026-20001"),
                 "CVE-2026-20002": nvd_cve("CVE-2026-20002")}
    )
    state = FakeState(
        rows={NVD_FEED: {"last_mod_end": NOW.isoformat()}, KEV_FEED: kev_cursor()}
    )
    sched = scheduler(nvd=nvd, state=state, kev=FakeKEV([first, second]))
    await sched.run_cycle()
    assert nvd.single_calls == ["CVE-2026-20001"]
    await sched.run_cycle()
    assert nvd.single_calls == ["CVE-2026-20001", "CVE-2026-20002"]


async def test_horizon_advances_only_past_fully_covered_dates():
    catalog = make_catalog(
        {"CVE-2026-30001": "2026-07-12", "CVE-2026-30002": "2026-07-12",
         "CVE-2026-30003": "2026-07-16"}
    )
    nvd = FakeNVD(singles={f"CVE-2026-3000{i}": nvd_cve(f"CVE-2026-3000{i}") for i in (1, 2, 3)})
    state = FakeState(
        rows={NVD_FEED: {"last_mod_end": NOW.isoformat()}, KEV_FEED: kev_cursor()}
    )
    sched = scheduler(
        nvd=nvd, state=state, kev=FakeKEV([catalog, None, None]), kev_single_fetch_cap=1
    )
    await sched.run_cycle()  # processes 30001 — 07-12 incomplete, horizon holds
    assert state.rows[KEV_FEED]["date_added_horizon"] == "2026-07-10"
    assert state.rows[KEV_FEED]["done_ids"] == ["CVE-2026-30001"]
    await sched.run_cycle()  # processes 30002 — 07-12 complete → horizon advances, done pruned
    assert state.rows[KEV_FEED]["date_added_horizon"] == "2026-07-12"
    assert state.rows[KEV_FEED]["done_ids"] == []
    await sched.run_cycle()  # processes 30003 — newest date never becomes the horizon
    assert state.rows[KEV_FEED]["date_added_horizon"] == "2026-07-12"
    assert state.rows[KEV_FEED]["done_ids"] == ["CVE-2026-30003"]


async def test_kev_freshness_persisted_even_when_nothing_to_ingest():
    # A 200 whose entries are all covered (dueDate/notes-only re-release) must
    # still persist Last-Modified — else every later fetch is a full-body 200
    # until CISA next adds an entry.
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": NOW.isoformat()},
            KEV_FEED: {
                "last_modified": "STALE",
                "date_added_horizon": "2026-07-16",
                "kb_refreshed": True,
            },
        }
    )
    sched = scheduler(state=state)  # default FakeKEV serves one fresh catalog
    summary = await sched.run_cycle()
    assert "nothing to do" in summary
    assert state.rows[KEV_FEED]["last_modified"] == "Thu, 16 Jul 2026 17:00:15 GMT"


async def test_kb_refreshed_only_recorded_when_refresh_ran():
    # Cycle 1 has new KEV ids, so the first-run refresh branch is skipped —
    # kb_refreshed must NOT be recorded (the old code stamped it anyway,
    # permanently losing the refresh). Cycle 2 has no new ids → refresh runs.
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": NOW.isoformat()},
            KEV_FEED: {"last_modified": "LM-0", "date_added_horizon": "2026-07-15"},
        }
    )
    kb = FakeKB(held_cves=["CVE-2021-44228"])
    nvd = FakeNVD(singles={"CVE-2026-58644": nvd_cve("CVE-2026-58644")})
    sched = scheduler(kb=kb, nvd=nvd, state=state, kev=FakeKEV([kev_catalog(), None]))
    await sched.run_cycle()
    assert nvd.single_calls == ["CVE-2026-58644"]
    assert "kb_refreshed" not in state.rows[KEV_FEED]
    assert kb.enriched_in_place == []  # refresh did NOT run
    await sched.run_cycle()
    assert "CVE-2021-44228" in kb.enriched_in_place[0]  # now it did, in place
    assert state.rows[KEV_FEED]["kb_refreshed"] is True


# ── rejected CVEs delete held chunks (S8 review: withdrawn ≠ current) ────────


async def test_rejected_cve_in_delta_deletes_held_chunks():
    # The rejection rides the same delta stream; a doc ingested before its
    # rejection must not keep rendering pre-rejection text as current NVD
    # evidence. (Never-held ids delete as a free no-op.)
    since = NOW - timedelta(days=1)
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": since.isoformat()},
            KEV_FEED: kev_cursor(date_added_horizon="2026-07-16"),
        }
    )
    kb = FakeKB()
    sink = RecordingSink()
    nvd = FakeNVD(
        window_cves=[nvd_cve("CVE-2024-0001"), nvd_cve("CVE-2020-9999", status="Rejected")]
    )
    sched = scheduler(kb=kb, nvd=nvd, state=state, sink=sink)
    summary = await sched.run_cycle()
    assert kb.deleted == [["CVE-2020-9999"]]
    assert DocChange("CVE-2020-9999", NVD_FEED, "deleted") in sink.events
    assert "1 rejected chunks removed" in summary
    assert "CVE-2020-9999" not in all_docs(kb)  # and it was never ingested


async def test_rejected_kev_single_deletes_instead_of_ingesting():
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": NOW.isoformat()},
            KEV_FEED: kev_cursor(date_added_horizon="2026-07-15"),
        }
    )
    kb = FakeKB()
    sink = RecordingSink()
    # the KEV-new SharePoint CVE comes back from NVD as Rejected
    nvd = FakeNVD(singles={"CVE-2026-58644": nvd_cve("CVE-2026-58644", status="Rejected")})
    sched = scheduler(kb=kb, nvd=nvd, state=state, sink=sink)
    await sched.run_cycle()
    assert kb.deleted == [["CVE-2026-58644"]]
    assert DocChange("CVE-2026-58644", KEV_FEED, "deleted") in sink.events
    assert all_docs(kb) == {}
    # still marked done — a rejected KEV entry must not re-surface hourly
    assert state.rows[KEV_FEED]["done_ids"] == ["CVE-2026-58644"]


# ── KEV failure isolation (S8 review: one bad feed silenced the other) ──────


async def test_kev_outage_with_warm_cache_does_not_silence_nvd():
    since = NOW - timedelta(days=1)
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": since.isoformat()},
            KEV_FEED: kev_cursor(date_added_horizon="2026-07-16"),
        }
    )
    kb = FakeKB()
    nvd = FakeNVD(window_cves=[nvd_cve("CVE-2024-3400")])  # in the KEV fixture
    kev = FakeKEV([kev_catalog(), RuntimeError("CISA is down")])
    sched = scheduler(kb=kb, nvd=nvd, kev=kev, state=state)
    await sched.run_cycle()  # warms the cache
    state.rows[NVD_FEED] = {"last_mod_end": since.isoformat()}  # rewind for cycle 2
    summary = await sched.run_cycle()  # KEV raises — NVD must still ingest
    assert "failed (cached catalog reused)" in summary
    assert len(kb.ingested) == 2
    # enrichment still applied, from the cached catalog
    assert kb.ingested[-1][0].kev_date_added == "2024-04-12"


async def test_kev_outage_with_cold_cache_holds_the_cve_pipeline():
    # Without any catalog, NVD re-ingests would ERASE held KEV evidence
    # (chunk upserts overwrite whole docs) — the CVE pipeline must hold. But
    # the hold is now LOCAL to the CVE pipeline (S9 review): run_cycle no
    # longer raises, so the independent ATT&CK phase still runs. The core
    # invariant — no NVD ingest without a catalog — is preserved.
    state = FakeState(rows={NVD_FEED: {"last_mod_end": NOW.isoformat()}})
    kev = FakeKEV([RuntimeError("CISA is down")])
    kb = FakeKB()
    sched = scheduler(kb=kb, kev=kev, state=state)
    summary = await sched.run_cycle()  # holds the CVE pipeline, does NOT raise
    assert "kev/nvd/kev-docs: failed" in summary
    assert kb.ingested == []  # evidence never erased — the invariant that matters
    assert NVD_FEED in state.rows and state.rows[NVD_FEED]["last_mod_end"] == NOW.isoformat()


# ── ATT&CK phase (S8): index-as-cursor, bundle only on version change ───────


class FakeATTACK:
    def __init__(self, version="19.1", objects=None, fail_index=False):
        from auspex.ingest.attack import ATTACKVersion

        self.latest = ATTACKVersion(
            version=version,
            modified="2026-05-12T14:00:00.188Z",
            url="https://raw.githubusercontent.com/mitre-attack/attack-stix-data/x.json",
        )
        self.objects = objects if objects is not None else ATTACK_BUNDLE["objects"]
        self.fail_index = fail_index
        self.index_polls = 0
        self.bundle_fetches = 0

    async def latest_version(self):
        self.index_polls += 1
        if self.fail_index:
            raise RuntimeError("github is down")
        return self.latest

    async def fetch_objects(self, url):
        self.bundle_fetches += 1
        return self.objects

    async def aclose(self) -> None:
        pass


ATTACK_BUNDLE = json.loads((FIXTURES / "attack_bundle.json").read_text())


def idle_cursors() -> FakeState:
    return FakeState(
        rows={
            NVD_FEED: {"last_mod_end": NOW.isoformat()},
            KEV_FEED: {
                "last_modified": "Thu, 16 Jul 2026 17:00:15 GMT",
                "date_added_horizon": "2026-07-16",
                "kb_refreshed": True,
            },
        }
    )


async def test_attack_new_version_ingests_and_records_cursor():
    kb, state, sink = FakeKB(), idle_cursors(), RecordingSink()
    attack = FakeATTACK()
    sched = scheduler(kb=kb, state=state, sink=sink, attack=attack)
    summary = await sched.run_cycle()
    assert attack.bundle_fetches == 1
    assert "attack: v19.1: 3 chunks from 3 docs" in summary
    assert {d.doc_id for batch in kb.ingested for d in batch} == {"T1059", "T1059.001", "TA0006"}
    assert state.rows[ATTACK_FEED] == {
        "version": "19.1",
        "modified": "2026-05-12T14:00:00.188Z",
        "doc_count": 3,  # stored so a later drastic shrink can be refused
    }
    # first ingest of a fresh source retires nothing (keep-set == the new docs)
    assert len(kb.retired) == 1
    source, keep = kb.retired[0]
    assert source == "mitre-attack-stix"
    assert set(keep) == {"T1059", "T1059.001", "TA0006"}
    assert DocChange("T1059", ATTACK_FEED, "upserted") in sink.events


async def test_attack_current_version_never_downloads_the_bundle():
    state = idle_cursors()
    # version AND modified match the feed → current, no download
    state.rows[ATTACK_FEED] = {"version": "19.1", "modified": "2026-05-12T14:00:00.188Z"}
    attack = FakeATTACK()
    sched = scheduler(state=state, attack=attack)
    summary = await sched.run_cycle()
    assert "attack: current (v19.1)" in summary
    assert attack.index_polls == 1  # the 31 KB index IS polled each cycle
    assert attack.bundle_fetches == 0  # the 53 MB bundle is NOT


async def test_attack_in_place_rerelease_same_version_new_modified_reingests():
    # S9 review (correctness lens): MITRE hotfixes a version in place — the
    # index bumps `modified` but keeps the version number. Serving stale
    # content until the next version ships would be a silent freshness bug.
    state = idle_cursors()
    state.rows[ATTACK_FEED] = {"version": "19.1", "modified": "OLD", "doc_count": 3}
    attack = FakeATTACK()  # feed reports modified="2026-05-12T14:00:00.188Z"
    sched = scheduler(state=state, attack=attack)
    summary = await sched.run_cycle()
    assert attack.bundle_fetches == 1  # re-downloaded despite same version
    assert "attack: v19.1" in summary


async def test_attack_retires_docs_absent_from_the_new_version():
    # A technique present in v19 but revoked/removed in v20 must be deleted,
    # not served forever (S9 review, ops + honesty lenses).
    state = idle_cursors()
    state.rows[ATTACK_FEED] = {"version": "18.0", "modified": "OLD", "doc_count": 3}
    kb = FakeKB()
    kb.retire_count = 7  # pretend 7 chunks of withdrawn techniques were swept
    attack = FakeATTACK(version="19.1")
    sched = scheduler(kb=kb, state=state, attack=attack)
    summary = await sched.run_cycle()
    assert len(kb.retired) == 1
    source, keep = kb.retired[0]
    assert source == "mitre-attack-stix"
    assert set(keep) == {"T1059", "T1059.001", "TA0006"}
    assert "7 retired" in summary


async def test_attack_refuses_to_advance_over_a_drastic_shrink():
    # If an upstream shape change drops most objects, the parse is non-empty
    # but tiny — advancing would (with retirement) delete the real corpus.
    # Refuse and hold the cursor (S9 review, ops lens).
    state = idle_cursors()
    state.rows[ATTACK_FEED] = {"version": "18.0", "modified": "OLD", "doc_count": 700}
    kb = FakeKB()
    # a bundle that parses to only the 3 fixture docs, vs a prior 700
    attack = FakeATTACK(version="19.1")
    sched = scheduler(kb=kb, state=state, attack=attack)
    summary = await sched.run_cycle()
    assert "attack: failed" in summary
    assert kb.ingested == []  # nothing ingested
    assert kb.retired == []  # nothing retired
    assert state.rows[ATTACK_FEED] == {"version": "18.0", "modified": "OLD", "doc_count": 700}


async def test_attack_empty_parse_never_advances_the_cursor():
    # a claimed-new version whose bundle parses to zero docs is broken or
    # poisoned — cursor must hold so the next cycle retries
    attack = FakeATTACK(objects=[])
    state = idle_cursors()
    sched = scheduler(state=state, attack=attack)
    summary = await sched.run_cycle()
    assert "attack: failed" in summary
    assert ATTACK_FEED not in state.rows


async def test_attack_failure_is_isolated_from_the_cve_phases():
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": (NOW - timedelta(days=1)).isoformat()},
            KEV_FEED: {
                "last_modified": "Thu, 16 Jul 2026 17:00:15 GMT",
                "date_added_horizon": "2026-07-16",
                "kb_refreshed": True,
            },
        }
    )
    kb = FakeKB()
    sched = scheduler(
        kb=kb,
        state=state,
        nvd=FakeNVD(window_cves=[nvd_cve("CVE-2024-0001")]),
        attack=FakeATTACK(fail_index=True),
    )
    summary = await sched.run_cycle()  # must NOT raise
    assert "attack: failed" in summary
    assert state.rows[NVD_FEED]["last_mod_end"] == NOW.isoformat()  # NVD advanced
    assert len(kb.ingested) == 1


async def test_no_attack_feed_reports_disabled():
    summary = await scheduler(state=idle_cursors()).run_cycle()
    assert "attack: disabled" in summary


async def test_cve_pipeline_failure_does_not_starve_the_attack_phase():
    # S9 review (correctness lens): the reverse of the attack-isolation test.
    # S8 removed the hand-seeded techniques, so the ATT&CK feed is the ONLY
    # path to technique/tactic content. When NVD errors every cycle (bad API
    # key, multi-day NVD outage), ATT&CK ingestion must STILL run — otherwise
    # a fresh deploy answers every "what is <technique>" with the miss copy
    # for as long as NVD is down.
    state = FakeState(
        rows={
            NVD_FEED: {"last_mod_end": (NOW - timedelta(days=1)).isoformat()},
            KEV_FEED: {
                "last_modified": "Thu, 16 Jul 2026 17:00:15 GMT",
                "date_added_horizon": "2026-07-16",
                "kb_refreshed": True,
            },
        }
    )
    kb, sink, attack = FakeKB(), RecordingSink(), FakeATTACK()
    sched = scheduler(
        kb=kb, state=state, sink=sink, nvd=FakeNVD(fail_pages=True), attack=attack
    )
    summary = await sched.run_cycle()  # must NOT raise
    assert "kev/nvd/kev-docs: failed" in summary
    # ATT&CK ran and ingested despite the CVE pipeline failing
    assert attack.bundle_fetches == 1
    assert {d.doc_id for batch in kb.ingested for d in batch} == {
        "T1059",
        "T1059.001",
        "TA0006",
    }
    assert "attack: v19.1" in summary


# ── run() task body ─────────────────────────────────────────────────────────


async def test_run_bootstraps_kb_then_idles_when_ingest_disabled():
    kb = FakeKB()
    sched = scheduler(kb=kb, enabled=False)
    await sched.run()  # must return (not loop) — the task ends after bootstrap
    assert kb.bootstrap_calls == 1
    assert kb.ingested == []  # no cycle ran


async def test_run_survives_a_cycle_failure_and_keeps_cycling():
    # S8 test-hygiene: 'the loop never dies from a cycle failure' was a
    # headline claim with no pin. Cycle 1 fails at ingest; the loop must log,
    # sleep, and let cycle 2 succeed over the SAME window (watermark held).
    import asyncio

    since = NOW - timedelta(days=1)
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
    naps = {"n": 0}

    async def interval_sleep(_: float) -> None:
        naps["n"] += 1
        if naps["n"] == 1:
            kb.fail_ingest = False  # "OpenSearch recovered" before cycle 2
            return
        raise asyncio.CancelledError  # end the otherwise-infinite loop

    sched = scheduler(
        kb=kb,
        nvd=FakeNVD(window_cves=[nvd_cve("CVE-2024-0001")]),
        kev=FakeKEV([kev_catalog(), None]),
        state=state,
        sleep=interval_sleep,
    )
    with pytest.raises(asyncio.CancelledError):
        await sched.run()
    assert len(kb.ingested) == 1  # cycle 2 ingested the window cycle 1 failed
    assert state.rows[NVD_FEED]["last_mod_end"] == NOW.isoformat()


async def test_cycle_skips_feeds_until_bootstrap_succeeds():
    # S8 review: a failed boot-time bootstrap left _model_id unset forever —
    # every cycle burned full feed quota then died at embed; worse, a _bulk
    # before _ensure_index would auto-create a poisoned dynamic-mapping index.
    kb = FakeKB()
    kb.bootstrapped = False
    kb.bootstrap_heals = False
    kev = FakeKEV([kev_catalog()])
    sched = scheduler(kb=kb, kev=kev)
    summary = await sched.run_cycle()
    assert "cycle skipped" in summary
    assert kev.conditional_args == []  # no feed was touched
    assert kb.bootstrap_calls == 1  # but a bootstrap retry happened


async def test_cycle_proceeds_after_bootstrap_heals():
    kb = FakeKB()
    kb.bootstrapped = False  # boot-time bootstrap failed…
    kb.bootstrap_heals = True  # …but OpenSearch has recovered since
    kev = FakeKEV([kev_catalog()])
    sched = scheduler(kb=kb, kev=kev)
    summary = await sched.run_cycle()
    assert "cycle skipped" not in summary
    assert kb.bootstrap_calls == 1
    assert len(kev.conditional_args) == 1  # the same cycle continued into the feeds


# ── cycle liveness (S17 Step 0) ─────────────────────────────────────────────


async def test_a_completed_cycle_is_recorded_even_when_no_feed_moved():
    """The evidence a quiet week needs. Every change consumer records success
    only when a relevant change actually arrives, so a week where no feed moved
    leaves them looking exactly like dead ones — and the S16 digest read that as
    trustworthy (auspex/timeline/types.py). A cycle that completed is not proof
    a claim was checked; it is proof something would have checked one."""
    kb, state, sink = FakeKB(), idle_cursors(), RecordingSink()
    sched = scheduler(kb=kb, state=state, sink=sink, kev=FakeKEV([kev_catalog()]))
    await sched.run_cycle()
    cycles = {c.name: c for c in sched.checker_health}["ingest-cycle"]
    assert cycles.ever_succeeded
    assert cycles.consecutive_failures == 0 and not cycles.degraded


async def test_a_failed_phase_counts_against_the_cycle():
    """A cycle whose CVE pipeline died looked at nothing, and must not be able to
    vouch for a quiet digest."""
    kev = FakeKEV([RuntimeError("CISA down")])
    sched = scheduler(kev=kev)
    for _ in range(DEGRADED_AFTER):
        await sched.run_cycle()
    cycles = {c.name: c for c in sched.checker_health}["ingest-cycle"]
    assert cycles.consecutive_failures == DEGRADED_AFTER
    assert cycles.degraded and not cycles.ever_succeeded


async def test_a_cycle_skipped_for_a_dead_kb_is_not_a_success():
    """The laundering this counter exists to stop: ingest that never came up has
    not earned the right to say the quiet is real."""
    kb = FakeKB()
    kb.bootstrapped = False
    kb.bootstrap_heals = False
    sched = scheduler(kb=kb, kev=FakeKEV([kev_catalog()]))
    assert "cycle skipped" in await sched.run_cycle()
    cycles = {c.name: c for c in sched.checker_health}["ingest-cycle"]
    assert not cycles.ever_succeeded
    assert cycles.consecutive_failures == 0  # not a failure either — nothing ran


async def test_the_cycle_counter_is_on_the_roster_even_without_a_tracking_sink():
    """`checker_health` is what the digest reads. A NullSink seam contributes no
    consumer entries, and the cycle counter must still be there — otherwise an
    empty roster is the only signal and 'ingest is off' and 'ingest is wedged'
    stay indistinguishable."""
    sched = scheduler(sink=None)
    assert [c.name for c in sched.checker_health] == ["ingest-cycle"]
