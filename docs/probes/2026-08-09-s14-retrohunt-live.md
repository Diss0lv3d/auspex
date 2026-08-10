# S14 — retro-hunt live verification (in-container, real ingest path)

_Date: 2026-08-09 · app container rebuilt from the S14 tree (`./ci.sh` green) ·
CVE-2026-35273 chosen because it is **genuinely KEV-listed in this deployment's
KB** (`kev_listed: true`, `kev_date_added: 2026-06-12`,
`knownRansomwareCampaignUse: Known`) — one of 132 real KEV-listed CVEs the S7/S8
ingest has landed. Run from `/tmp` inside the container so the INSTALLED
distribution is exercised, not the source tree._

## What was driven

The real writers and the real sink, in the order they occur in production:

1. `persist_enrichment` (the only code that writes verdicts) settles the CVE as
   `suspicious` for the `default` workspace — the "history" a retro-hunt exists
   to revisit.
2. `RetroHuntSink.emit` receives the exact `DocChange` the KEV feed emits, mixed
   with the `upserted` noise the NVD delta feed emits ~770×/day.
3. The analyst surface is read over HTTP with a real dev-login token.
4. `persist_enrichment` runs again with a disagreeing provider signal.

## Result

```
workspace(default) = cce51a41-a95b-4696-94b4-d04fad511c95

1. historical verdict: {'obs_id': 'cve-fe609221', 'label': 'suspicious',
   'confidence_at_write': 0.55, 'half_life_days': 365.0, 'source': 'enrichment:OTX'}
   sink type: RetroHuntSink

2. re-open events: 1
   { "obs_id": "cve-fe609221", "trigger_doc": "CVE-2026-35273", "feed": "kev",
     "change_kind": "kev-added", "verdict_label_at_match": "suspicious",
     "status": "open" }
   ← the kev-added change swept; the upserted change in the same batch did not

3. verdict trail after the sweep: [{'label': 'suspicious', 'source': 'enrichment:OTX'}]
   flips after the sweep: 0          ← the rail: a match is not a re-classification

4. flips after re-enrichment: 1
   { "from_label": "suspicious", "to_label": "malicious",
     "trigger": "retrohunt:CVE-2026-35273", "match_id_linked": true }
   match status after the flip: ['open']    ← never closed on the analyst's behalf
   match_id == flip.match_id: True

5. events after re-emitting the same change: 1    ← idempotent, not news twice
```

Half-life 365 d is the D-017 default for CVEs, so the decay fields came from the
real table too.

## The analyst surface, over HTTP

`GET /api/retrohunt/matches` (real token, `default` workspace):

```json
{
  "status_filter": "open", "count": 1, "limit": 50,
  "matches": [{
    "match_id": "97ddeb47-9b7a-4431-b7da-db24d87419b5",
    "observable": {"obs_id": "cve-fe609221", "type": "cve", "value": "CVE-2026-35273"},
    "trigger_doc": "CVE-2026-35273", "feed": "kev", "change_kind": "kev-added",
    "verdict_label_at_match": "suspicious", "settled": true, "status": "open",
    "action": "re-examine",
    "note": "New intel touches an observable this workspace already saw. This is a
             reason to re-examine, not a re-classification: no verdict has been changed."
  }],
  "sweeps_on": ["deleted", "kev-added"]
}
```

`GET /api/retrohunt/flips` returned the flip with
`trigger: "retrohunt:CVE-2026-35273"` and `match_id` pointing at that match, so
the causal chain intel → re-open → re-look → flip is readable end to end.

Then: `POST /matches/{id}/ack` → `{"status": "reviewed"}`; the open list drops to
0; a second ack → **404** (an honest refusal, not a silent success); no token →
**401** on every route.

Residue removed afterwards — the synthetic observable, its verdicts, the match
and the flip are all gone from the dev workspace
(`retrohunt_matches` 0, `verdict_flips` 0).

## Two things this probe caught that nothing else did

**1. `auspex.retrohunt` and `auspex.modes` were never in the installed
distribution.** The first run died on
`ModuleNotFoundError: No module named 'auspex.retrohunt'`, from an installed
`auspex/enrich/store.py` that imports `auspex.retrohunt.flips`.
`[tool.setuptools] packages` in pyproject.toml is a hand-maintained list and both
were missing — `auspex.modes` since S9. Tests never saw it (they run from the
source tree) and `./ci.sh` was green.

**2. Every `__init__.py` in the installed distribution was 0 bytes** — all 13
packages, since the day the Dockerfile was written. The deps-only layer runs
`pip install .` against a `touch`ed skeleton to cache dependencies; that leaves
`build/lib/auspex/**/__init__.py` at 0 bytes, and setuptools reuses `build/lib`,
skipping files whose timestamps look current. So the app layer's wheel shipped
real modules beside empty package inits.

Both hid behind the same accident: `uvicorn server:app` runs with
`WORKDIR=/srv/auspex` on `sys.path`, so the COPY'd source shadows site-packages.
The container served every request correctly on top of a broken install, and
liveness could never have noticed.

Fixed: both packages declared; both layers `rm -rf build auspex.egg-info`;
`build/` added to `.dockerignore`. After a `--no-cache` rebuild the installed
tree byte-matches the source (10,533 bytes of `__init__.py` across 14 files;
`auspex/routes/__init__.py` is legitimately empty in source too).

Guarded so it cannot recur: `tests/test_packaging.py` (5 tests — declared
packages vs the actual tree in both directions, the Dockerfile skeleton covers
every declared package, both layers clean build artifacts, `.dockerignore`
excludes them) and a new `./ci.sh` step that imports the app from `/tmp` in the
container and asserts the installed tree byte-matches the source (94 modules).
**Liveness is not evidence that an image is sound.**

## Known limitation of this probe

The sweep ran in a `docker compose exec` process, not inside the long-lived
scheduler task, so its `retro-hunt: feed=… hits=…` line does not appear in
`docker compose logs app`. What that leaves unproven is only the scheduler's
timing — that it calls `emit` on a real cycle. The wiring itself is pinned by
`test_the_scheduler_is_wired_to_the_retrohunt_sink`
(`IngestScheduler.from_settings(...)._sink` is a `RetroHuntSink`, not the S7
`NullSink`), and the emit call sites are S7 code that this session did not touch.
A cycle-driven observation needs CISA to publish a KEV entry for a CVE this
workspace has already enriched, which is not something a session can schedule.
