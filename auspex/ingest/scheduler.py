"""Startup catch-up + hourly ingest cycle (S7).

Built for the reality that this host reboots between sessions: watermarks live
in ingest_state, gaps of any length chunk into ≤120-day NVD windows, and a
cursor only advances after its window's docs are safely in the KB — so a crash
mid-catch-up re-covers the same window next boot (chunk-id upserts make the
replay free). The whole thing runs as ONE background task that also owns the
KB bootstrap (TD-008: lifespan no longer blocks serving on a slow bootstrap).

Per cycle:
1. KEV: conditional fetch (If-Modified-Since; in-memory catalog cache between
   cycles — a 304 cycle still scans the cached catalog, so capped remainders
   don't wait for CISA's next release). Entries above the stored dateAdded
   horizon and not yet in `done_ids` are fetched from NVD individually
   (capped per cycle, oldest first). dateAdded is day-granular and CISA adds
   same-day batches, so the horizon only advances through FULLY-covered
   dates and never into the catalog's newest date — processed ids wait in
   `done_ids` until a newer date appears (a same-day follow-up release still
   gets picked up). First run ever skips the historical backfill
   (1 647 entries) and instead enriches the CVE docs already in the KB.
2. NVD delta: windows from the stored watermark (first run: a short default
   backfill) — parse via nvd_to_doc (Rejected CVEs skipped, counted), enrich
   from the KEV catalog + an EPSS batch, ingest, advance the watermark
   per-window.
3. Emit one DocChange per upserted doc to the sink (NullSink until S14's
   retro-hunt consumers land) — "kev-added" for docs that entered via KEV.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from auspex.config import Settings
from auspex.ingest.enrich import enrich_doc
from auspex.ingest.epss import EPSSFeed
from auspex.ingest.events import ChangeSink, DocChange, NullSink
from auspex.ingest.kev import KEVCatalog, KEVFeed
from auspex.ingest.nvd import NVDFeed, is_rejected, windows
from auspex.ingest.state import IngestStateStore
from auspex.kb.seed import nvd_to_doc
from auspex.kb.types import KBDoc

logger = logging.getLogger("auspex.ingest")

NVD_FEED = "nvd-delta"
KEV_FEED = "kev"


def _advance_kev_cursor(cursor: dict, catalog, processed: list[str]) -> dict:
    """Fold `processed` into done_ids, then advance date_added_horizon through
    dates whose entries are ALL done. dateAdded is day-granular and CISA both
    ships same-day batches larger than the per-cycle cap and appends same-day
    follow-up releases — so the newest catalog date never becomes the horizon;
    its processed ids wait in done_ids until a newer date appears. Pure so the
    boundary math is testable without a scheduler."""
    horizon = cursor.get("date_added_horizon", "")
    done = set(cursor.get("done_ids", ())) | set(processed)
    by_date: dict[str, set[str]] = {}
    for cve, entry in catalog.entries.items():
        if entry["dateAdded"] > horizon:
            by_date.setdefault(entry["dateAdded"], set()).add(cve)
    if by_date:
        newest = max(by_date)
        for date in sorted(by_date):
            if date == newest or not by_date[date] <= done:
                break
            horizon = date
    # Keep only ids still above the horizon and still in the catalog.
    done = {
        c for c in done if catalog.entries.get(c, {}).get("dateAdded", "") > horizon
    }
    out = dict(cursor)
    out["date_added_horizon"] = horizon
    out["done_ids"] = sorted(done)
    return out
CYCLE_INTERVAL_SECONDS = 3600.0
FIRST_RUN_BACKFILL_DAYS = 1  # ~768 modified CVEs/day (probed) — keep first boot sane
KEV_SINGLE_FETCH_CAP = 50  # new-KEV NVD fetches per cycle; remainder next cycle
SINGLE_FETCH_SPACING_SECONDS = 3.0  # NVD etiquette between single-CVE fetches


class IngestScheduler:
    def __init__(
        self,
        *,
        kb,
        state: IngestStateStore,
        nvd: NVDFeed,
        kev: KEVFeed,
        epss: EPSSFeed,
        sink: ChangeSink | None = None,
        enabled: bool = True,
        interval_seconds: float = CYCLE_INTERVAL_SECONDS,
        kev_single_fetch_cap: int = KEV_SINGLE_FETCH_CAP,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._kb = kb
        self._state = state
        self._nvd = nvd
        self._kev = kev
        self._epss = epss
        self._sink = sink or NullSink()
        self.enabled = enabled
        self._interval = interval_seconds
        self._kev_cap = kev_single_fetch_cap
        self._now = now
        self._sleep = sleep
        self._kev_cache: KEVCatalog | None = None  # 304 cycles reuse the last body

    @classmethod
    def from_settings(cls, settings: Settings, kb, pool) -> "IngestScheduler":
        return cls(
            kb=kb,
            state=IngestStateStore(pool),
            nvd=NVDFeed(api_key=settings.nvd_api_key),
            kev=KEVFeed(),
            epss=EPSSFeed(),
            enabled=settings.ingest_enabled and kb.active,
        )

    async def aclose(self) -> None:
        for feed in (self._nvd, self._kev, self._epss):
            await feed.aclose()

    # ── the background task body ──────────────────────────────────────────

    async def run(self) -> None:
        """Owns KB bootstrap (TD-008: off the lifespan critical path), then
        catch-up + cycle forever. Never dies from a cycle failure."""
        if self._kb.active:
            logger.info("kb bootstrap: %s", await self._kb.bootstrap())
        if not self.enabled:
            logger.info("ingest disabled; scheduler idle")
            return
        while True:
            try:
                logger.info("ingest cycle: %s", await self.run_cycle())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — the loop must survive anything
                logger.exception("ingest cycle failed; retrying next interval")
            await self._sleep(self._interval)

    # ── one cycle (the testable unit) ─────────────────────────────────────

    async def run_cycle(self) -> str:
        if self._kb.active and not self._kb.bootstrapped:
            # A failed boot-time bootstrap must not brick ingest until app
            # restart — and ingesting through _bulk before _ensure_index ran
            # would auto-create a poisoned dynamic-mapping index (S8 review).
            logger.info("kb bootstrap retry: %s", await self._kb.bootstrap())
            if not self._kb.bootstrapped:
                return "kb not ready; cycle skipped (bootstrap retries next interval)"
        kev_catalog, kev_new_ids, kev_status = await self._kev_phase()
        nvd_status, nvd_ingested_ids = await self._nvd_phase(kev_catalog)
        kev_doc_status = await self._kev_docs_phase(kev_catalog, kev_new_ids, nvd_ingested_ids)
        return f"kev: {kev_status}; nvd: {nvd_status}; kev-docs: {kev_doc_status}"

    async def _kev_phase(self) -> tuple[KEVCatalog | None, list[str], str]:
        """Fetch/refresh the catalog; decide which entries are NEW (above the
        stored horizon, not yet processed). Returns (catalog, new-ids
        oldest-first, status). A 304 cycle scans the CACHED catalog — capped
        remainders and failed batches retry next cycle, not at CISA's next
        release."""
        prior = await self._state.get(KEV_FEED)
        cursor = prior.cursor if prior else {}
        # Conditional GET only when the in-memory cache can back a 304 — after
        # a reboot the cache is empty and a 304 would leave the cycle blind.
        conditional = cursor.get("last_modified", "") if self._kev_cache else ""
        fetched = await self._kev.fetch(if_modified_since=conditional)
        catalog = fetched if fetched is not None else self._kev_cache
        if catalog is None:  # 304 answered an unconditional request — no data
            return None, [], "no catalog (304 with empty cache)"
        if fetched is not None:
            self._kev_cache = fetched
        if "date_added_horizon" not in cursor:
            # First run: no historical backfill (1 647 singles would take
            # hours) — enrichment applies to KB-held docs (below) and to
            # everything flowing through the NVD delta from here on. The
            # horizon starts at the last FULLY-covered date: the newest date's
            # ids go to done_ids so a same-day follow-up release is still seen.
            dates = sorted({e["dateAdded"] for e in catalog.entries.values()})
            newest = dates[-1] if dates else ""
            horizon = dates[-2] if len(dates) > 1 else ""
            done = sorted(c for c, e in catalog.entries.items() if e["dateAdded"] == newest)
            await self._state.record(
                KEV_FEED,
                cursor={
                    "last_modified": catalog.last_modified,
                    "catalog_version": catalog.catalog_version,
                    "date_added_horizon": horizon,
                    "done_ids": done,
                },
                status=f"first run: horizon {horizon or 'epoch'}, {len(done)} newest-day ids "
                f"done; backfill skipped ({len(catalog.entries)} historical entries "
                "enrich prospectively)",
            )
            return catalog, [], f"first run ({len(catalog.entries)} entries)"
        if fetched is not None and cursor.get("last_modified") != catalog.last_modified:
            # Persist freshness even when nothing needs ingesting — a stale
            # Last-Modified downgrades every later fetch from 304 to a full
            # 1.5 MB 200 until CISA next adds an entry.
            cursor = {
                **cursor,
                "last_modified": catalog.last_modified,
                "catalog_version": catalog.catalog_version,
            }
            await self._state.record(KEV_FEED, cursor=cursor, status="catalog refreshed")
        done_ids = set(cursor.get("done_ids", ()))
        horizon = cursor["date_added_horizon"]
        new = sorted(
            (
                cve
                for cve, e in catalog.entries.items()
                if e["dateAdded"] > horizon and cve not in done_ids
            ),
            key=lambda cve: (catalog.entries[cve]["dateAdded"], cve),
        )
        capped = new[: self._kev_cap]
        if len(new) > len(capped):
            logger.info(
                "kev: %d new entries, processing %d this cycle (cap %d) — rest next cycle",
                len(new),
                len(capped),
                self._kev_cap,
            )
        return catalog, capped, f"{len(capped)}/{len(new)} new entries"

    async def _nvd_phase(self, kev_catalog: KEVCatalog | None) -> tuple[str, set[str]]:
        prior = await self._state.get(NVD_FEED)
        now = self._now()
        if prior and prior.cursor.get("last_mod_end"):
            since = datetime.fromisoformat(prior.cursor["last_mod_end"])
        else:
            since = now - timedelta(days=FIRST_RUN_BACKFILL_DAYS)
        total = skipped = 0
        ingested_ids: set[str] = set()
        window_list = windows(since, now)
        for start, end in window_list:
            cves = await self._nvd.fetch_window(start, end)
            docs = [nvd_to_doc(c) for c in cves if not is_rejected(c)]
            skipped += len(cves) - len(docs)
            ingested = await self._ingest_enriched(docs, kev_catalog, feed=NVD_FEED)
            total += ingested
            ingested_ids.update(d.doc_id for d in docs)
            # Watermark advances per WINDOW, only after its docs are in the KB.
            await self._state.record(
                NVD_FEED,
                cursor={"last_mod_end": end.isoformat()},
                status=f"window {start.date()}→{end.date()}: {ingested} chunks",
                docs_delta=ingested,
            )
        status = (
            f"{len(window_list)} window(s) since {since.date()}, "
            f"{total} chunks, {skipped} rejected skipped"
        )
        return status, ingested_ids

    async def _kev_docs_phase(
        self,
        kev_catalog: KEVCatalog | None,
        kev_new_ids: list[str],
        covered_this_cycle: set[str],
    ) -> str:
        """Docs entering via KEV: new entries since the horizon (NVD single
        fetches, oldest first), or — on the first run — CVE docs already in
        the KB re-enriched with KEV/EPSS evidence. Ids the NVD delta already
        ingested THIS cycle are excluded (they were enriched from this same
        catalog); their dateAdded still advances the horizon below."""
        if kev_catalog is None:
            return "no catalog this cycle"
        prior = await self._state.get(KEV_FEED)
        cursor = dict(prior.cursor) if prior else {}
        refresh_ran = False
        first_run_refresh: list[str] = []
        if not kev_new_ids and not cursor.get("kb_refreshed"):
            held = await self._kb.list_cve_ids()
            first_run_refresh = [
                c for c in held if c in kev_catalog.entries and c not in covered_this_cycle
            ]
            refresh_ran = True
        target_ids = [c for c in (kev_new_ids or first_run_refresh) if c not in covered_this_cycle]
        if not target_ids and not kev_new_ids and not refresh_ran:
            return "nothing to do"
        docs: list[KBDoc] = []
        for i, cve_id in enumerate(target_ids):
            if i:  # NVD etiquette: space single fetches, quota is a rolling 30 s
                await self._sleep(SINGLE_FETCH_SPACING_SECONDS)
            cve = await self._nvd.fetch_cve(cve_id)
            if cve is not None and not is_rejected(cve):
                docs.append(nvd_to_doc(cve))
        ingested = await self._ingest_enriched(
            docs, kev_catalog, feed=KEV_FEED, kind="kev-added"
        )
        # Every capped new id counts as processed — fetched here, covered by
        # this cycle's NVD delta, absent from NVD, or rejected (deliberate
        # skips). A raise above leaves the cursor untouched for a clean retry.
        cursor = _advance_kev_cursor(cursor, kev_catalog, kev_new_ids)
        cursor["last_modified"] = kev_catalog.last_modified
        cursor["catalog_version"] = kev_catalog.catalog_version
        if refresh_ran:
            # Only when the refresh branch actually executed — recording it on
            # other cycles would permanently lose a refresh that never ran.
            cursor["kb_refreshed"] = True
        await self._state.record(
            KEV_FEED,
            cursor=cursor,
            status=f"{len(docs)} docs via {'new entries' if kev_new_ids else 'first-run refresh'}",
            docs_delta=ingested,
        )
        return f"{ingested} chunks from {len(docs)} docs"

    async def _ingest_enriched(
        self,
        docs: list[KBDoc],
        kev_catalog: KEVCatalog | None,
        *,
        feed: str,
        kind: str = "upserted",
    ) -> int:
        if not docs:
            return 0
        scores = await self._epss.scores([d.doc_id for d in docs])
        kev_entries = kev_catalog.entries if kev_catalog else {}
        enriched = [
            enrich_doc(d, kev_entries.get(d.doc_id), scores.get(d.doc_id)) for d in docs
        ]
        ingested = await self._kb.ingest_docs(enriched)
        await self._sink.emit([DocChange(d.doc_id, feed, kind) for d in enriched])
        return ingested
