# Live verify: S7 ingestion — catch-up, enrichment, and what the scale probe caught

- **Date:** 2026-07-17 (S7, evening)
- **Setup:** rebuilt app container on the real compose stack; NVD keyed via
  `.env`; INGEST_ENABLED default-on in-container.

## Cycle 1 (first run ever, old volume)

```
kb bootstrap: model … already deployed; index auspex-knowledge exists;
              mapping upgraded (+5 fields); seeded 14 chunks
ingest cycle: kev: first run (1647 entries);
              nvd: 1 window(s) since 2026-07-16, 643 chunks, 3 rejected skipped;
              kev-docs: 8 chunks from 8 docs
```

- `_ensure_mapping_fields` upgraded the live S6-era strict mapping in place.
- Seed re-ingested because the fingerprint definition changed (payload grew
  the 5 KEV/EPSS fields) — by design.
- KEV first run: horizon → 2026-07-16, NO 1 647-entry backfill; 8 KB-held
  CVEs re-enriched instead.
- Live Rejected CVEs skipped (3 in one real day).

## Cycle 2 — simulated 2-day gap (the S7 catch-up criterion)

NVD cursor rewound to `2026-07-15T12:00Z` in ingest_state, app restarted:

```
kb bootstrap: … mapping current; seed present (14 chunks, fingerprint match)
ingest cycle: kev: 0/0 new entries;
              nvd: 1 window(s) since 2026-07-15, 1844 chunks, 30 rejected skipped;
              kev-docs: nothing to do
```

Watermark advanced to now only after ingest; warm bootstrap fully no-ops.
Cycle wall-clock ≈ 2.5 min for ~1 800 live docs (fetch + embed + bulk).

## The demo turn (fresh post-seed CVE, zero LLM, path=shortcut)

```
- CVE-2026-58644 — CRITICAL (CVSS 9.8)
  Deserialization of untrusted data in Microsoft Office SharePoint allows …
  Known exploited — in CISA KEV since 2026-07-16.
  EPSS 0.01 — 70.7th percentile (as of 2026-07-17).
  Source: NVD · https://nvd.nist.gov/vuln/detail/CVE-2026-58644
```

KEV ransomware "Unknown" renders as silence (no claim either way); the low
EPSS beside a KEV listing is honest tension the analyst SHOULD see.

## What the TD-005 spot-check caught at ~2 500 chunks (2 real bugs, fixed)

Corpus grew 14 → ~2 486 chunks, so the mandated floor spot-check ran — and
failed loudly, in two distinct ways (both mechanically confirmed against the
live index before fixing):

1. **HNSW recall collapse, not a floor problem:** unfiltered lucene kNN at
   k=10 for "what is lateral movement" returned ten mid-0.5s CVE chunks —
   the true best match (CONCEPT-LATERAL-MOVEMENT, cosine **0.840**, same as
   S6) was absent from the top-10 entirely. The S6 demo query silently
   became a miss.
2. **Floor erosion by corpus growth:** "what is quantum entanglement" put
   TWO CVE chunks over the 0.6 absolute floor (0.610, 0.602) — max-of-N
   cosine grows with N; at N=14 the max noise was 0.498. Fabrication
   returned at scale. ("what is credential dumping" likewise answered with a
   random CVE record.)

**Fix (probed before coding):** the same neural query with
`filter: {terms: {doc_type: [concept, technique]}}` returns 0.840 top-1
(lucene kNN goes exact over small filtered subsets — the filter restores
RECALL, it doesn't just trim) and drops the off-corpus top to 0.586 < floor.
`search()` now takes `doc_types` applied to BOTH legs; the definition
shortcut pins `("concept", "technique")`. Post-fix full turn matrix re-run
live: lateral movement answers, quantum entanglement misses honestly, both
CVE turns render KEV/EPSS — all `path=shortcut`.

**Open (→ TD-005, S8):** the UNFILTERED floor remains uncalibrated for
CVE-scale free-text search; k/ef sizing for the neural leg needs the labeled
query set. Definition path is structurally safe regardless of corpus size.
