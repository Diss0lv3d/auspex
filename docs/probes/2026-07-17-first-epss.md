# Probe: FIRST EPSS API (S7 ingestion)

- **Date:** 2026-07-17
- **Target:** `https://api.first.org/data/v1/epss` (public, keyless) +
  bulk CSV `https://epss.empiricalsecurity.com/epss_scores-current.csv.gz`
- **Why:** EPSS score + percentile enrich S7's CVE docs and the cve_lookup
  echo ("EPSS 0.97"). Scores refresh daily — enrichment must be re-runnable.

## Measured — API

Single: `?cve=CVE-2021-44228` → 200:

```
{ status: "OK", "status-code": 200, version: "1.0", access: "public",
  total: 1, offset: 0, limit: 100,
  data: [ { cve: "CVE-2021-44228",
            epss: "0.999990000",          ← STRING, 9 decimal places
            percentile: "1.000000000",    ← STRING
            date: "2026-07-16" } ] }      ← scoring day (yesterday: daily model)
```

- **Batch:** `?cve=CVE-A,CVE-B,...` (comma list) → one row per KNOWN CVE.
  5-CVE batch → total 5; **rows come back in arbitrary order, NOT request
  order** — key the result dict by `cve`, never zip with the request list.
- **Unknown CVE is silently dropped**: `?cve=CVE-2021-44228,CVE-9999-99999`
  → 200, total 1, no error, no null row. Missing row == "EPSS has no score"
  (new/rejected CVEs) — render as absence, not 0.0.
- `limit` accepted beyond the default-100 (probe: `epss-gt=0.95&limit=1000`
  → 200, all 517 rows in one page, `limit: 1000` echoed). Envelope always
  carries total/offset/limit for paging.
- Latency ~0.3–0.8 s; no auth, no rate-limit headers observed on this
  volume (keep batches ≤ ~100 ids per GET to stay under URL-length limits).

## Measured — bulk CSV

- `epss_scores-current.csv.gz` → **302** to the dated file
  (`epss_scores-2026-07-16.csv.gz`) → 200, **2 469 577 bytes**,
  `last-modified: Thu, 16 Jul 2026 13:31:28 GMT`, etag present.
  Redirect target filename == scoring date (useful as a version stamp).

## What our code must therefore do

- Enrich by **API batch** (comma list, ≤100 per request), keyed by `cve`
  from the response — never positional. Missing row ⇒ no EPSS fields on the
  doc ⇒ echo renders no EPSS claim (honest absence).
- Parse `epss`/`percentile` as Decimal-ish floats from strings; format for
  the echo as 2-decimal (score) / whole-percent (percentile) — render from
  stored numbers, don't re-quote strings.
- Store the row `date` on the doc (EPSS is a daily moving score — the echo
  can say "EPSS 0.97 (as of 2026-07-16)"; staleness is visible, not hidden).
- Bulk CSV is the right path IF we ever score the whole corpus (2.5 MB gz
  vs thousands of API pages); for S7's per-CVE enrichment the batch API is
  simpler — CSV path parked in IDEAS.md.
