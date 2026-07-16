# Probe: enrichment providers (S5 design source)

- **Date:** 2026-07-16 (S5)
- **Method:** live curl from dev host against each provider's public API; official
  docs fetched same-day for the three providers that cannot be probed
  authenticated (no keys in `.env` yet). Timings are single-sample, KHI-region.
- **Why:** S5 builds direct-HTTP provider clients; per CLAUDE.md rule 4 every
  client codes against THIS snapshot, and pytest fixtures are derived from the
  bodies below — never from memory.

## Headline reality-vs-assumption mismatches

1. **abuse.ch now requires an Auth-Key for BOTH URLhaus and ThreatFox.**
   The session plan listed them as "free/no-key" — wrong. Keyless POST →
   `401 {"error": "Unauthorized"}` (live-verified, both APIs). One key from
   auth.abuse.ch covers both (`ABUSECH_AUTH_KEY`). They move to the key-gated
   set; their happy-path parsing is coded against official docs and is
   **unverified-live** (TECHNICAL_DEBT: re-probe when the key exists).
2. **OTX works keyless.** `X-Remote-User-Name: Anonymous`, full response bodies
   on IPv4/IPv6/domain/url/file endpoints (live-verified). Key optional
   (`OTX_API_KEY` → `X-OTX-API-KEY` header). No rate-limit headers observed;
   treat 429/403 as provider-down (breaker handles it).
3. **GreyNoise community works keyless but is budget-useless:**
   `x-ratelimit-limit: 25` with a reset ~1 week out (epoch 1784814716).
   25 lookups/week ≈ two bulk pastes → activate ONLY when `GREYNOISE_API_KEY`
   exists.
4. **OTX `pulse_info.count` is NOT a malice signal by itself:** benign
   `example.com` sits in 50 pulses (phishing collections reference the
   legitimate domain). The `validation[]` array (whitelist / false-positive
   markers) must veto pulse-derived suspicion. `www.example.com` and
   `http://example.com/test` both return count 0 — count is real data, just
   poisoned by list-style pulses for famous domains.
5. **hashlookup is a known-GOOD file database** (NSRL and friends): a hit means
   "known distributed file" (`hashlookup:trust` 0–100), a 404 means "no
   information" — a miss is NOT malice, a hit is (weak) benign evidence.

## Per-provider contract (what our code consumes)

### 1. Shodan InternetDB — keyless, always-on
- `GET https://internetdb.shodan.io/{ip}` (IPv4 AND IPv6 live-verified).
- 200: `{"cpes":[], "hostnames":["dns.google"], "ip":"8.8.8.8", "ports":[53,443], "tags":[], "vulns":[]}`
  (IPv6 sample carried `tags:["cdn"]`, `cpes:["cpe:/a:cloudflare:cloudflare"]`).
- 404 `{"detail":"No information available"}` for BOTH unknown-IP and garbage
  input — 404 is "no data", never an error.
- No auth, no rate-limit headers; Cloudflare-cached `max-age=432000` (5 days).
  0.15–0.8 s. Signal: exposure/context (open ports, `vulns[]` CVE ids), not a
  verdict — `vulns` non-empty ⇒ suspicious-leaning context only.

### 2. CIRCL hashlookup — keyless, always-on
- `GET https://hashlookup.circl.lu/lookup/{md5|sha1|sha256}/{hash}`.
- 200: NSRL-style record: `FileName`, `ProductCode.ProductName`, `db`,
  `hashlookup:trust` (int, 100 = high), `parents[]` (**huge — never store
  raw; keep FileName/ProductName/trust only**).
- 404 `{"message": "Non existing SHA-256", "query": "<hash>"}` = unknown file.
- 400 `{"message": "...value incorrect, expecting a SHA-256..."}` on bad hex.
- Case-insensitive input (probed lowercase, matched). ~0.5–0.8 s.
  Signal: hit ⇒ known-distributed file (benign evidence, trust-weighted);
  miss ⇒ no signal (unknown ≠ bad).

### 3. AlienVault OTX — keyless (key optional), always-on
- `GET https://otx.alienvault.com/api/v1/indicators/{IPv4|IPv6|domain|url|file}/{value}/general`
  — all five live-verified keyless. URL values must be percent-encoded.
  Subdomains are fine on the `domain` endpoint (no separate hostname call
  needed). Compressed IPv6 accepted (response echoes expanded form).
- 200 fields we consume: `pulse_info.count`, `pulse_info.pulses[]` (trim to
  name/tags/adversary/malware_families of the first few), `validation[]`
  (whitelist/false-positive veto — see mismatch #4), `reputation`, `asn`.
- Optional `OTX_API_KEY` → `X-OTX-API-KEY` header (higher limits, same shape).
- Responses can exceed 100 KB (50 embedded pulses) — parse-and-trim, never
  persist raw. ~1–1.5 s.

### 4. GreyNoise community — key-gated (`GREYNOISE_API_KEY`)
- `GET https://api.greynoise.io/v3/community/{ip}`, header `key: <key>`.
- 200: `{"ip", "noise": bool, "riot": bool, "classification": "benign|malicious|unknown", "name", "link", "last_seen", "message"}`
  (live sample: Shodan scanner 71.6.135.131 → noise=true, classification=benign).
- 404 is SEMANTIC: `{"ip", "noise": false, "riot": false, "message": "IP not observed scanning the internet."}`
  — "not seen" data, not an error.
- Rate-limit headers on every response incl. 404s: `x-ratelimit-limit: 25`
  keyless/week (mismatch #3). IPv4 only (community scope). ~0.8–1 s.

### 5. AbuseIPDB — key-gated (`ABUSEIPDB_API_KEY`)
- `GET https://api.abuseipdb.com/api/v2/check?ipAddress=<ip>&maxAgeInDays=90`,
  headers `Key: <key>`, `Accept: application/json`. IPv4+IPv6 (v6 URL-encoded).
- 401 (live-verified, identical keyless and bogus-key):
  `{"errors":[{"detail":"Authentication failed...","status":401}]}` — the
  `errors[]` array is the error shape for all 4xx.
- 200 (docs, unverified-live): `data.abuseConfidenceScore` (0–100),
  `isWhitelisted`, `isTor`, `totalReports`, `numDistinctUsers`,
  `lastReportedAt`, `usageType`, `isp`, `countryCode`.
- Free tier 1 000 req/day; 429 carries `Retry-After` + `X-RateLimit-*`.

### 6. URLhaus — key-gated (`ABUSECH_AUTH_KEY`) — happy path unverified-live
- POST form-encoded, header `Auth-Key`. Three endpoints:
  `/v1/host/` (`host=` domain|IPv4), `/v1/url/` (`url=`),
  `/v1/payload/` (`md5_hash=` | `sha256_hash=`).
- Keyless: `401 {"error": "Unauthorized"}` (live-verified).
- Docs shape: `query_status`: `ok | no_results | invalid_url | invalid_host |
  invalid_md5 | invalid_sha256 | http_post_expected`. Host 200-ok:
  `url_count`, `firstseen`, `blacklists{surbl, spamhaus_dbl}`, `urls[]`
  (`url`, `url_status` online|offline, `threat`, `tags`). Payload 200-ok:
  `signature`, `file_type`, `url_count`, `firstseen`/`lastseen`.
- `query_status` != "ok"/"no_results" is a client bug, not provider-down.

### 7. ThreatFox — key-gated (`ABUSECH_AUTH_KEY`) — happy path unverified-live
- `POST https://threatfox-api.abuse.ch/api/v1/` JSON body, header `Auth-Key`.
- Request: `{"query": "search_ioc", "search_term": "<value>", "exact_match": true}`
  (exact_match on — wildcard search would hallucinate relatives of a benign IOC).
- Keyless: `401 {"error": "Unauthorized"}` (live-verified).
- Docs shape 200-ok: `query_status: "ok"`, `data[]`:
  `ioc`, `threat_type` (e.g. botnet_cc), `malware_printable`,
  `confidence_level` (0–100), `first_seen`/`last_seen`, `tags[]`.
  No-result: `query_status: "no_result"` (docs; exact casing unverified —
  client must treat any non-"ok" status without data as no-data, not error).
- IP IOCs are stored as `ip:port` — search by bare IP may need wildcard; keep
  exact_match for v1 and accept misses (re-probe with key, see TD entry).

## What our code must therefore do

- **Env vars born this session:** `ABUSECH_AUTH_KEY`, `ABUSEIPDB_API_KEY`,
  `OTX_API_KEY` (optional-key), `GREYNOISE_API_KEY` (+ docs/ENV_VARS.md rows).
- Always-on set (probed keyless): InternetDB (ipv4/ipv6),
  hashlookup (md5/sha1/sha256), OTX (ipv4/ipv6/domain/url/sha256/sha1/md5).
  Key-gated set: URLhaus, ThreatFox, AbuseIPDB, GreyNoise (ipv4 only).
- 404 is DATA for InternetDB ("no exposure info"), hashlookup ("unknown file"),
  GreyNoise ("not observed") — only network errors / 5xx / 429 / auth failures
  count as provider failure for the circuit breaker.
- Trim every stored/echoed response to the consumed fields above; OTX and
  hashlookup bodies are unboundedly large.
- OTX verdict mapping MUST check `validation[]` before treating pulse presence
  as suspicious (mismatch #4).
- abuse.ch parsers guard on `query_status` and fail soft (DEFERRED rail) on
  unrecognized statuses — they are coded from docs, not live responses.
