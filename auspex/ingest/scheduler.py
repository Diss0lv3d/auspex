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
3. ATT&CK (S8): poll the 31 KB version index; on a new Enterprise version
   (~2×/year) download the STIX bundle and land techniques + tactics as
   plain docs (same ids as the old hand seeds — real content overwrites).
4. Emit one DocChange per upserted doc to the sink (NullSink until S14's
   retro-hunt consumers land) — "kev-added" for docs that entered via KEV,
   "deleted" when NVD rejects a held CVE.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from auspex.checks import FailureCounter
from auspex.config import Settings
from auspex.ingest.attack import ATTACK_SOURCE, ATTACKFeed, bundle_to_docs
from auspex.ingest.enrich import enrich_doc, enrichment_fields
from auspex.ingest.epss import EPSSFeed
from auspex.ingest.events import ChangeSink, DocChange, NullSink
from auspex.ingest.kev import KEVCatalog, KEVFeed
from auspex.ingest.nvd import NVDFeed, has_valid_id, is_rejected, windows
from auspex.ingest.state import IngestStateStore
from auspex.kb.seed import nvd_to_doc
from auspex.kb.types import KBDoc
from auspex.retrohunt import RetroHuntSink
from auspex.watchers import FanoutSink, WatcherSink

logger = logging.getLogger("auspex.ingest")

NVD_FEED = "nvd-delta"
KEV_FEED = "kev"
ATTACK_FEED = "attack-enterprise"


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


class IngestScheduler:
    def __init__(
        self,
        *,
        kb,
        state: IngestStateStore,
        nvd: NVDFeed,
        kev: KEVFeed,
        epss: EPSSFeed,
        attack: ATTACKFeed | None = None,
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
        self._attack = attack
        self._sink = sink or NullSink()
        self.enabled = enabled
        self._interval = interval_seconds
        self._kev_cap = kev_single_fetch_cap
        self._now = now
        self._sleep = sleep
        self._kev_cache: KEVCatalog | None = None  # 304 cycles reuse the last body
        # Counts CYCLES, not dispatches — see run_cycle. Named for what it
        # counts, because it appears on an analyst-facing roster.
        self._cycles = FailureCounter("ingest-cycle")

    @classmethod
    def from_settings(cls, settings: Settings, kb, pool) -> "IngestScheduler":
        # S14: the NullSink seam finally has its consumer. Ingest code is
        # untouched — it emits exactly the DocChanges it emitted at S7; the sink
        # decides which kinds are worth a sweep (TRIGGER_KINDS).
        #
        # S15 adds a second, INDEPENDENT consumer rather than teaching the first
        # one a new job: retro-hunt asks "does this touch anything we saw?" and
        # the watcher check asks "does this contradict a claim a verdict made?".
        # FanoutSink owns the failure isolation between them, so `run_cycle`
        # still holds exactly one sink and neither consumer can sink the other.
        return cls(
            kb=kb,
            state=IngestStateStore(pool),
            nvd=NVDFeed(api_key=settings.nvd_api_key),
            kev=KEVFeed(),
            epss=EPSSFeed(),
            attack=ATTACKFeed(),
            sink=FanoutSink(RetroHuntSink(pool), WatcherSink(pool)),
            enabled=settings.ingest_enabled and kb.active,
        )

    @property
    def checker_health(self) -> tuple:
        """What the change consumers know about their own last few attempts,
        plus whether cycles are running at all.

        The consumers' own entries are empty when the sink does not track itself
        (the NullSink seam, and any test double) — an unknown roster is reported
        as unknown rather than defaulted to healthy, because the S16 digest reads
        this to decide whether "nothing happened" may be shown as reassurance.

        `ingest-cycle` is always present, and it is what keeps a genuinely quiet
        week distinguishable from a dead process (S17 Step 0): the consumers stay
        silent when no feed moves, so without it a quiet week and a crash loop
        produce the same roster."""
        health = getattr(self._sink, "health", None)
        consumers = tuple(health()) if callable(health) else ()
        return (*consumers, self._cycles.status)

    async def aclose(self) -> None:
        feeds = [self._nvd, self._kev, self._epss]
        if self._attack is not None:
            feeds.append(self._attack)
        for feed in feeds:
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
        # Two independent units. ATT&CK has NO data dependency on the CVE
        # feeds, and S8 removed the hand-seeded techniques — so a CVE-feed
        # outage (bad NVD key, CISA down) must not starve technique/tactic
        # content the way it did when both lived in one unwrapped sequence
        # (S9 review: correctness lens). Each holds its own watermarks and
        # retries next interval; neither can mark the other failed.
        failure: BaseException | None = None
        try:
            cve_status = await self._cve_pipeline()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("cve pipeline failed; watermarks hold, retrying next cycle")
            cve_status = "kev/nvd/kev-docs: failed (see log)"
            failure = exc
        try:
            attack_status = await self._attack_phase()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("attack phase failed; retrying next cycle")
            attack_status = "failed (see log)"
            failure = failure or exc
        # S17 Step 0: the only thing that can prove the platform is alive during
        # a QUIET week. A change consumer records success solely when a relevant
        # change arrives, so in a week where no feed moved, every consumer looks
        # exactly like a dead one — and the digest was reading that as
        # trustworthy (auspex/timeline/types.py). A cycle that completed with
        # both phases intact is the missing evidence: it is not proof any claim
        # was checked, it is proof something would have checked one.
        #
        # The early return above deliberately does NOT reach here: a cycle
        # skipped because the KB never came up looked at nothing, and recording
        # it as a success is precisely the laundering this counter exists to
        # stop.
        if failure is None:
            self._cycles.succeeded()
        else:
            self._cycles.failed(failure)
        return f"{cve_status}; attack: {attack_status}"

    async def _cve_pipeline(self) -> str:
        """KEV → NVD delta → KEV-docs, as one isolated unit (they share the
        KEV catalog and NVD-ingested set). A cold-cache KEV failure re-raises
        to the caller so the pipeline holds WITHOUT letting NVD re-ingest and
        erase held KEV evidence; a warm-cache failure degrades to the cached
        catalog."""
        try:
            kev_catalog, kev_new_ids, kev_status = await self._kev_phase()
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._kev_cache is None:
                # No catalog at all: NVD re-ingests would ERASE held KEV
                # evidence (chunk upserts overwrite whole docs). Hold the
                # pipeline; watermarks keep and retry next interval.
                raise
            # Warm cache: a KEV outage must not silence NVD ingestion (S8
            # review) — enrichment uses the last good catalog.
            logger.exception("kev phase failed; continuing with the cached catalog")
            kev_catalog, kev_new_ids, kev_status = (
                self._kev_cache,
                [],
                "failed (cached catalog reused)",
            )
        nvd_status, nvd_ingested_ids = await self._nvd_phase(kev_catalog)
        kev_doc_status = await self._kev_docs_phase(kev_catalog, kev_new_ids, nvd_ingested_ids)
        return f"kev: {kev_status}; nvd: {nvd_status}; kev-docs: {kev_doc_status}"

    async def _attack_phase(self) -> str:
        """ATT&CK rides the hourly cycle but downloads the 53 MB bundle ONLY
        when the 31 KB version index shows a version the cursor hasn't seen
        (~2×/year). Techniques + tactics land as plain (unenriched) docs;
        same doc_ids as the old hand-curated seeds, so real STIX-derived
        content overwrites them and orphan pruning sweeps the tails."""
        if self._attack is None:
            return "disabled"
        latest = await self._attack.latest_version()
        prior = await self._state.get(ATTACK_FEED)
        if prior and (
            prior.cursor.get("version"),
            prior.cursor.get("modified"),
        ) == (latest.version, latest.modified):
            # Version AND modified must match — an in-place re-release of the
            # same version (MITRE hotfix bumps `modified`) is a real change
            # (S9 review, correctness lens: `modified` was stored but never
            # compared, so hotfixes were served stale until the next version).
            return f"current (v{latest.version})"
        prior_version = prior.cursor.get("version") if prior else None
        prior_count = prior.cursor.get("doc_count") if prior else None
        logger.info(
            "attack: v%s (was v%s) — fetching bundle", latest.version, prior_version or "none"
        )
        objects = await self._attack.fetch_objects(latest.url)
        docs = bundle_to_docs(objects)
        if not docs:
            # An empty parse of a claimed-new version means a broken or
            # poisoned bundle — never advance the cursor over it.
            raise RuntimeError(f"ATT&CK bundle v{latest.version} yielded no docs")
        if prior_count and len(docs) < prior_count // 2:
            # A drastic shrink vs the prior version is almost always an upstream
            # shape change that silently dropped most objects (e.g. an
            # external-id format the id rail stopped matching) — refuse to
            # advance the cursor over a 50%+ collapse (S9 review, ops lens).
            raise RuntimeError(
                f"ATT&CK v{latest.version} parsed {len(docs)} docs, under half of "
                f"the prior {prior_count} — refusing to advance (likely upstream shape change)"
            )
        ingested = await self._kb.ingest_docs(docs)
        await self._sink.emit([DocChange(d.doc_id, ATTACK_FEED, "upserted") for d in docs])
        # Retire techniques/tactics revoked or removed in the new version BEFORE
        # recording the cursor — a doc absent from the new bundle would otherwise
        # be served as current forever (S9 review, ops + honesty lenses). A
        # failure here holds the cursor for a clean retry.
        retired = await self._kb.retire_absent(ATTACK_SOURCE, [d.doc_id for d in docs])
        if retired:
            logger.info(
                "attack: retired %d chunks absent from v%s", retired, latest.version
            )
        await self._state.record(
            ATTACK_FEED,
            cursor={
                "version": latest.version,
                "modified": latest.modified,
                "doc_count": len(docs),
            },
            status=f"v{latest.version}: {ingested} chunks from {len(docs)} docs, "
            f"{retired} retired",
            docs_delta=ingested,
        )
        return f"v{latest.version}: {ingested} chunks from {len(docs)} docs, {retired} retired"

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
        total = skipped = removed = 0
        ingested_ids: set[str] = set()
        window_list = windows(since, now)
        for start, end in window_list:
            window_chunks = 0
            # Page-streamed: a 120-day catch-up window is ~92k records — one
            # page (≤2000) in memory at a time, ingested as it arrives.
            async for page in self._nvd.pages(start, end):
                docs = [nvd_to_doc(c) for c in page if not is_rejected(c) and has_valid_id(c)]
                skipped += len(page) - len(docs)
                window_chunks += await self._ingest_enriched(docs, kev_catalog, feed=NVD_FEED)
                ingested_ids.update(d.doc_id for d in docs)
                # A rejection rides the same delta stream — a held doc must
                # not keep rendering its pre-rejection text as current NVD
                # evidence (S8 review). Never-held ids delete as a no-op.
                rejected = [
                    c["id"].upper() for c in page if is_rejected(c) and has_valid_id(c)
                ]
                if rejected:
                    removed += await self._kb.delete_docs(rejected)
                    await self._sink.emit(
                        [DocChange(r, NVD_FEED, "deleted") for r in rejected]
                    )
            total += window_chunks
            # Watermark advances per WINDOW, only after its docs are in the KB.
            await self._state.record(
                NVD_FEED,
                cursor={"last_mod_end": end.isoformat()},
                status=f"window {start.date()}→{end.date()}: {window_chunks} chunks",
                docs_delta=window_chunks,
            )
        status = (
            f"{len(window_list)} window(s) since {since.date()}, "
            f"{total} chunks, {skipped} skipped (rejected/invalid), "
            f"{removed} rejected chunks removed"
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
        refreshed_chunks = 0
        if not kev_new_ids and not cursor.get("kb_refreshed"):
            # First-run refresh: docs the KB ALREADY holds get their evidence
            # fields set in one update_by_query — no NVD re-fetch, no
            # re-embed. The S7 singles loop here was uncapped (~1,647 paced
            # fetches against a grown KB) and all-or-nothing (S8 review).
            held = await self._kb.list_cve_ids()
            refresh_ids = [
                c for c in held if c in kev_catalog.entries and c not in covered_this_cycle
            ]
            refresh_ran = True
            if refresh_ids:
                scores = await self._epss.scores(refresh_ids)
                updates = {
                    c: enrichment_fields(kev_catalog.entries.get(c), scores.get(c))
                    for c in refresh_ids
                }
                refreshed_chunks = await self._kb.apply_enrichment(
                    {c: u for c, u in updates.items() if u}
                )
                await self._sink.emit(
                    [DocChange(c, KEV_FEED, "kev-added") for c in refresh_ids]
                )
        target_ids = [c for c in kev_new_ids if c not in covered_this_cycle]
        if not target_ids and not kev_new_ids and not refresh_ran:
            return "nothing to do"
        docs: list[KBDoc] = []
        for i, cve_id in enumerate(target_ids):
            if i:  # NVD quota is a rolling 30 s — spacing is the feed's (key-aware)
                await self._sleep(self._nvd.spacing_seconds)
            cve = await self._nvd.fetch_cve(cve_id)
            if cve is not None and not is_rejected(cve) and has_valid_id(cve):
                docs.append(nvd_to_doc(cve))
            elif cve is not None and is_rejected(cve):
                await self._kb.delete_docs([cve_id])
                await self._sink.emit([DocChange(cve_id, KEV_FEED, "deleted")])
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
        status = f"{len(docs)} docs via new entries"
        if refresh_ran:
            status += f"; first-run refresh updated {refreshed_chunks} held chunks"
        await self._state.record(
            KEV_FEED,
            cursor=cursor,
            status=status,
            docs_delta=ingested,
        )
        summary = f"{ingested} chunks from {len(docs)} docs"
        if refresh_ran:
            summary += f"; refreshed {refreshed_chunks} held chunks"
        return summary

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
