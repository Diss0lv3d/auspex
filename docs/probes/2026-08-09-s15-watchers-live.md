# S15 — falsification watchers, live verification (in-container)

_Date: 2026-08-09 · app container rebuilt from the S15 tree (`./ci.sh` green,
676 tests, installed-dist gate passing at 100 modules) · run from `/tmp` inside
the container so the INSTALLED distribution is exercised, not the source tree
(the S14 packaging lesson) · CVE-2026-35273 again, because it is genuinely
KEV-listed in this deployment's KB._

## What was driven

The real writers and the real sinks, in production order — no fakes:

1. `persist_enrichment` settles the CVE as `suspicious` and registers that
   verdict's falsification conditions in the same transaction.
2. The real `DocChange` the KEV feed emits reaches `FanoutSink(RetroHuntSink,
   WatcherSink)` — the exact object `IngestScheduler.from_settings` builds —
   mixed with the `upserted` noise the NVD delta emits ~770×/day.
3. `persist_enrichment` runs again with a disagreeing provider signal.
4. The analyst surface is read over HTTP with a real dev-login token.

## Result

```
1. settle the CVE as suspicious (the history a watcher guards)
   [open       ] provider_escalation  verdict=suspicious
        claim: No connected source rates this worse than suspicious (OTX answered).
   [open       ] record_withdrawn     verdict=suspicious
        claim: This verdict rests on the published record for CVE-2026-35273.
   [open       ] kev_listing          verdict=suspicious
        claim: CVE-2026-35273 is not known to be exploited in the wild — this
               workspace holds it as suspicious.

2. the real KEV DocChange reaches the real sinks
   [satisfied  ] kev_listing          satisfied_by=CVE-2026-35273
   [open       ] record_withdrawn     ← the record was not withdrawn
   [open       ] provider_escalation  ← no provider spoke
        ← only the contradicted claim moves; the upserted change did nothing

3. the verdict trail after the watcher fired
   [{'label': 'suspicious', 'source': 'enrichment:OTX'}]
   flips: 0     ← THE RAIL: a satisfied watcher is not a re-classification

4. the re-open event, upgraded
   trigger_doc=CVE-2026-35273 verdict_at_match=suspicious
   falsifies: CVE-2026-35273 is not known to be exploited in the wild — this
              workspace holds it as suspicious.

5. re-enrichment disagrees → the escalation claim is contradicted too
   [satisfied  ] provider_escalation  satisfied_by=flip:4c0e32cf-…
   [satisfied  ] kev_listing          satisfied_by=CVE-2026-35273
   open claims registered by the NEW verdict:
   [open       ] record_withdrawn     verdict=malicious
        ← the malicious verdict registers NO kev_listing and NO escalation
          watcher: KEV agrees with it, and nothing rates worse than malicious

6. re-emitting the same change is not news twice
   satisfied stamps unchanged: True
```

Step 5 is the part worth reading twice. Both satisfied claims **survive** the
supersession performed in the same transaction that retired the rest — the
platform said in advance what would change its mind, both things happened, and
the record of that is still there after the verdict moved. The new verdict's
registered claims are correctly narrower, without anyone writing a rule saying
"malicious verdicts get fewer watchers": it falls out of the derivation.

## The analyst surface, over HTTP

`GET /api/watchers?status=satisfied` (real token, `default` workspace):

```
count: 2
  provider_escalation  checked_by=enrichment satisfied_by=flip:d9f70da4-…
    claim: No connected source rates this worse than suspicious (OTX answered).
  kev_listing          checked_by=ingest     satisfied_by=CVE-2026-35273
    claim: CVE-2026-35273 is not known to be exploited in the wild — this
           workspace holds it as suspicious.
```

`satisfied_by` is the evidence, not a timestamp: the doc id that contradicted
the claim, or the verdict flip that did. `checked_by` names what actually
evaluates each kind, so "registered" is a promise with the keeper named.

`GET /api/retrohunt/matches` — the S14 event, upgraded rather than duplicated:

```json
{
  "trigger_doc": "CVE-2026-35273",
  "change_kind": "kev-added",
  "verdict_label_at_match": "suspicious",
  "action": "re-examine",
  "falsifies": "CVE-2026-35273 is not known to be exploited in the wild — this workspace holds it as suspicious."
}
```

One fact, one event, one acknowledgement. `GET /api/watchers` unauthenticated →
**401**; `?status=banana` → **422**.

## Residue

The synthetic observable, its verdicts, watchers and matches deleted; the
in-container script removed. `watchers`, `retrohunt_matches` back to 0 rows and
`observables` back to its pre-probe 10.
