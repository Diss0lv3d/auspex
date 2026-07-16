# Probe: key-gated providers live (TD-004 follow-up — keys registered)

- **Date:** 2026-07-16, evening (post-S5-session; Burhan registered both keys)
- **Target:** URLhaus + ThreatFox (ABUSECH_AUTH_KEY) and AbuseIPDB
  (ABUSEIPDB_API_KEY), authenticated happy paths — the three parsers that were
  docs-coded and marked UNVERIFIED-LIVE in
  docs/probes/2026-07-16-enrichment-providers.md (§5–§7, TD-004).
- **Result: docs-coded shapes were correct** with two payload-endpoint
  surprises (below). One parser fix shipped from this probe.

## ThreatFox — VERIFIED, no parser change

- `get_iocs days=1` → 1 377 rows; `search_ioc` + `exact_match:true` on a
  listed domain → `query_status:"ok"`, one row with exactly the consumed
  fields (live sample: `uvzbxwuc.gamehazarat.com`, ClearFake,
  payload_delivery, confidence_level 100, tags).
- Miss → `{"query_status": "no_result", "data": "Your search did not yield
  any results"}` — **exact casing and string-data confirmed**; the fixture
  guess was right.

## URLhaus — VERIFIED with two payload surprises

- `/v1/host/` hit (live Mozi C2 112.248.255.71): `query_status:"ok"`,
  `url_count` **int** 2, `urls[]` with url_status/threat/tags,
  `blacklists {spamhaus_dbl, surbl}`. Miss (google.com) →
  `{"query_status": "no_results"}` exact.
- `/v1/url/` hit: `url_status:"online"`, `threat`, `tags`, `payloads[]`
  (field `response_sha256`).
- **Surprise 1 — heavy payloads 504:** `/v1/payload/` on a Mozi sha256
  (thousands of URLs) → HTTP **504 after ~60 s, twice**. Same pathology as
  OTX heavy indicators; our 6 s cap + ProviderError path covers it. Light
  payload lookups answer in ~1 s.
- **Surprise 2 — the empty-file trap:** `/v1/payload/` on the canonical
  empty-file MD5 (`d41d8…`) is **`query_status:"ok"`**, not `no_results`:
  `file_size:"0"`, `signature:null`, `file_type:"unknown"`,
  `url_count:"2251"` (string here, int on /host/ — type inconsistency),
  `urls[]` capped at 1000. URLhaus records ANY bytes served from a listed
  malware URL, including empty failed downloads — the S5 parser would have
  called the empty-file hash "malicious 0.9".
  **Fix shipped:** `file_size == 0` ⇒ no signal; `signature:null` with real
  size ⇒ SUSPICIOUS 0.65 ("unclassified payload"), signature present ⇒
  MALICIOUS 0.9 as before. Pinned fixture `URLHAUS_PAYLOAD_EMPTY`.

## AbuseIPDB — VERIFIED, no parser change

- Tor exit 185.220.101.34: `abuseConfidenceScore` 90, `totalReports` 106,
  `numDistinctUsers` 68, `isTor:true`, `isWhitelisted:false` → parser maps
  MALICIOUS 0.9. 8.8.8.8: score 0, **`isWhitelisted:true`** → BENIGN branch
  confirmed live.
- Rate-limit headers live: `x-ratelimit-limit: 1000` (free tier/day),
  `x-ratelimit-remaining` counts down per call. ~1 s.

## What changed in code because of this probe

- `urlhaus.py` payload branch: empty-file guard + signature-null downgrade
  (above). Everything else stands as shipped in S5.
- Test fixtures for all three providers replaced/annotated with live bodies;
  "docs-coded / unverified" markers removed.
- TD-004 resolved (TECHNICAL_DEBT.md updated).
