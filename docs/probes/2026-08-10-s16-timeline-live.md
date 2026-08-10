# S16 — verdict timeline, live verification (in-container)

_Date: 2026-08-10 · app container rebuilt from the S16 tree (`./ci.sh` green,
installed-dist gate passing at **106 modules**) · run from `/tmp` inside the
container so the INSTALLED distribution is exercised, not the source tree (the
S14 packaging lesson) · CVE-2026-35273 again, because it is genuinely KEV-listed
in this deployment's KB._

## What was driven

The real writers, the real sinks and the real HTTP surface — no fakes:

1. `persist_enrichment` settles two CVEs. One is then moved 549 days into the
   past (1.504 CVE half-lives) so its decay is real rather than simulated: the
   row is genuinely old, and every number below is computed from it.
2. The real `DocChange` the KEV feed emits reaches
   `FanoutSink(RetroHuntSink, WatcherSink)` — the exact object
   `IngestScheduler.from_settings` builds — mixed with the `upserted` noise the
   NVD delta emits ~770×/day.
3. The digest is read twice: once with a healthy checker roster, once with a
   checker that has failed three cycles running.
4. The analyst surface is read over HTTP with a real dev-login token.

## Result

```
1. two verdicts written, one aged just past the stale edge (549d = 1.504 half-lives)
   CVE-2026-77777: asserted 0.80 → still stands 0.28 after 1.504 half-lives  [stale]
   its 3 open claims, TD-020 answered: ['lapsed']  (status still ['open'])

2. the real KEV DocChange through the real sinks
   CVE-2026-35273: re-open events=1 falsifies='CVE-2026-35273 is not known to be
                   exploited in the wild — '…
   verdict trail untouched: ['suspicious']  flips=0
   checker health: [('retrohunt', False), ('watchers', False), ('fanout', False)]

3. the digest, with a HEALTHY checker roster
   quiet=False trustworthy=True reopened=1 contradicted=1 decayed=0

4. the same digest with a DEAD checker (S16 Step 0's finding)
   quiet=False trustworthy=False
   checkers=[('fanout', True, 'RuntimeError')]
   → same rows either way; only `trustworthy` tells you whether to believe them

5. over HTTP with a real token
   GET /api/timeline/cve-b0437294
     suspicious · 0.8 → 0.282 · stale · needs_attention=True
     claims: [('provider_escalation','open','lapsed'),
              ('record_withdrawn','open','lapsed'),
              ('kev_listing','open','lapsed')]
   GET /api/timeline/digest?days=7 → quiet=False trustworthy=True
     checkers: retrohunt / watchers / fanout — all healthy, ever_succeeded=True
     decayed:  [('CVE-2026-77777', 'aging', 'stale')]
     reopened: [('CVE-2026-35273', True)]

   residue deleted
```

## The three lines worth reading twice

**`asserted 0.80 → still stands 0.28`.** `effective_confidence` has been
executable and pinned by a test since S5 and rendered by nothing for eleven
sessions. Every surface has been showing an eighteen-month-old belief at the
strength it had the day it was written. That gap is now the primary visual on
the timeline page: the written claim is the track, what still stands is the fill.

**`TD-020 answered: ['lapsed'] (status still ['open'])`.** The claim is still
watched and will still fire — the platform committed to it, and quietly ceasing
to check is the failure the whole feature exists to prevent. What changed is that
it no longer reads as though it carries the weight of a claim made yesterday.
`status` answers "was this contradicted?"; `standing` answers "does the belief
behind it still stand?". Letting decay write to `status` would have been the
easy version and would have destroyed the distinction between *never
contradicted* and *contradicted*.

**`decayed: [('CVE-2026-77777', 'aging', 'stale')]`.** The only item in the
digest nobody recorded, because nothing happened — time passed. It appears only
because the verdict crossed a band INSIDE the window: at the 7-day cutoff its age
was 542 days (`aging`), today 549 (`stale`). Step 3's tiny window correctly
reports `decayed=0` for the same row — a verdict that was already stale when you
left is not news about this week.

## The honesty half

Step 4 is the S16 Step-0 finding closed. The rows returned are identical with a
healthy checker and with one that has failed every cycle since Tuesday; what
differs is `trustworthy`, and the UI renders the reassuring banner only when it
is true. A digest that says "nothing contradicted your verdicts" while the thing
that would have noticed is dead is not quiet, it is wrong.

Note `ever_succeeded=True` on the live roster: the container's scheduler has
completed real check cycles. It is reported but deliberately NOT required for
`trustworthy` — a checker only records success when a check actually ran, so
demanding one would mark a healthy platform untrustworthy for exactly as long as
it had nothing to do, which is the same conflation of dead and idle pointed the
other way.

## Reproducing

Script: this probe's step list is `scratchpad/s16_live.py` in the session; the
demo turn in STATE.md carries the short version. Every observable it creates is
deleted at the end (`residue deleted`) — the dev DB is left as it was found.
