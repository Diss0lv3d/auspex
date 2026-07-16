# Probe: S5 enrichment live verification (in-container, real providers)

- **Date:** 2026-07-16 (S5, post-implementation)
- **Target:** rebuilt `auspex-app-1` container on localhost:8000, keyless
  provider set (InternetDB, CIRCL hashlookup, OTX), real dev-login + SSE.
- **Why:** the always-demoable invariant — prove the shortcut path enriches
  live with zero LLM calls before ending the session.

## Turn 1 — defanged Tor exit + known MD5 + private IP (one message)

`check 185.220.101[.]34 and d41d8cd98f00b204e9800998ecf8427e and 10.0.0.1`

- `185.220.101.34` — refanged, `· received defanged` marker, InternetDB
  context LIVE: `open ports 10134 · hostnames tor-exit-34.for-privacy.net`.
  OTX timed out (6 s cap vs measured 14–16 s for this pulse-heavy indicator —
  see the main enrichment probe, finding #7) and was reported in the trailer.
- `d41d8cd98f00b204e9800998ecf8427e` — `verdict: benign (confidence 0.60)`:
  hashlookup trust 100/100 + OTX "community-validated as benign (Empty hash,
  Whitelisted hash)".
- `10.0.0.1` — `private/reserved address — not routable, never enriched`.
- `done.path == "shortcut"`, no `reasoning` frames — LLM untouched.

This turn also surfaced the two bugs fixed same-session:
- trailer said "OTX unavailable" while an OTX signal sat above it → now
  "OTX (partial — timed out after 6s)";
- the Tor exit's `validation[source=tor_exits]` would have been treated as a
  benign whitelist veto → benign veto now restricted to
  whitelist/false_positive/majestic/akamai (pinned fixture `OTX_TOR_EXIT`).

## Turn 2 — WannaCry SHA-256 (after both fixes, rebuilt container)

`seen ed01ebfbc9eb5bbea545af4d01bf5f1071661840480439c6e5babe8e080e41aa anywhere?`

```
verdict: suspicious (confidence 0.70) — CIRCL hashlookup: known distributed
file: unnamed known file (trust 30/100); OTX: referenced in 50 threat pulses
— e.g. WannaCry linked Lazarus indicators · linked adversary: Lazarus Group
```

- Max-severity combining picked SUSPICIOUS over hashlookup's weak benign —
  and hashlookup knowing WannaCry at trust 30 is live proof that known-file
  hits must stay weak evidence (the 0.5 cap is earning its keep).
- "Suspicious, not malicious" is honest for the keyless set: OTX pulses cap
  at 0.7; asserting MALICIOUS needs the curated feeds (ThreatFox/URLhaus —
  key-gated, TD-004).

## Postgres rows (after turn 2)

```
 sha256-bf7826a0 | sha256 | suspicious | 0.7 | 365 | 0 | enrichment:CIRCL hashlookup,OTX
 md5-83031bfa    | md5    | benign     | 0.6 | 365 | 0 | enrichment:CIRCL hashlookup,OTX
```

Decay fields per D-017 (hash half-life 365 d, floor 0). Turn-1 IP rows were
purged by the chat-test cleanup during ci.sh — expected, not a bug.
