# Probe: SARA phishing / header-analysis patterns (S11 reference)

- **Date:** 2026-07-18 (S11)
- **Source:** `/home/burhan/sara-open/sara/agents/phishing.py` (1624 lines),
  `/home/burhan/sara-open/sara/agents/header_analysis.py` (378 lines),
  `/home/burhan/sara-open/sara/core/typosquat.py` (257 lines) — read on disk,
  paths verified this session. Reference for PATTERNS only (CLAUDE.md: we reuse
  SARA's patterns, never its code).

## 1. Header parse (`phishing.parse_email_headers`, lines 48–140)

Regex-per-header extraction over the raw paste (NOT `email.parser` — pastes are
partial/mangled; line-anchored regexes survive that):

- Fields: `From, To, Subject, Return-Path, Reply-To, Date, Message-Id` +
  `Authentication-Results` (multi-line continuation aware).
- Auth results parsed with result-token regexes, tolerant of placement
  (`Authentication-Results` header OR anywhere in the first 3000 chars):
  - `spf=(pass|fail|softfail|neutral|none|temperror|permerror)`
  - `dkim=(pass|fail|neutral|none|temperror|permerror)`
  - `dmarc=(pass|fail|bestguesspass|none)`
- Mismatch flags computed in code: `reply_to_mismatch` (From domain ≠ Reply-To
  domain), `return_path_mismatch` (From domain ≠ Return-Path domain).
- Anomaly checks (EPVME vectors, each appends a NAMED anomaly string):
  multiple `From:` headers (sender-field confusion); RFC-2047 encoded-word in
  From/Subject (decode via `email.header.decode_header`, then re-check);
  control chars in decoded From (header injection); Cyrillic range
  `[Ѐ-ӿ]` in From (homoglyph); invisible Unicode
  (` -‏`, ZWSP/RLO/ZWJ, `﻿`) in From/Subject;
  brand-as-subdomain (`security.microsoft.com.attacker.xyz`);
  domain-within-domain (`paypal.com-verify.xyz` via `[a-z]+\.com[-.]`).

## 2. Typosquat detector (`core/typosquat.py`) — QA Case #415

Born from a real failure: `microsoftonline.org` (TLD swap) emitted BENIGN at
95% confidence by the LLM path. Deterministic pre-check fires BEFORE the LLM.

- `BRAND_ALLOWLIST: dict[sld, set[registrable domains]]` — ~44 brands
  (microsoft, microsoftonline, office365, google, paypal, docusign{.com,.net},
  zoom→zoom.us, banks…). Code-owned constant, no env var.
- Class 1 **TLD swap** (HIGH): SLD exactly matches a brand, registrable domain
  NOT in the brand's allow-list. Distance 0.
- Class 2 **near-miss** (MEDIUM): Damerau-Levenshtein 1–2 between candidate SLD
  and brand SLD (transposition catches `paypla`); `NEAR_MISS_MIN_LEN = 5`
  (skip "ibm"/"aws" — distance-1 space explodes); length-delta ≤ 2 prefilter;
  early-exit cap 3.
- `_registrable_domain` = last two labels (naive; wrong for co.uk — accepted:
  every allow-listed brand uses single-label TLDs, failure mode is a false
  NEGATIVE never a false positive).
- Accepts FQDN, URL, or email (split on last `@`).
- Detector "intentionally errs on the side of flagging" — FP → analyst
  override; FN → credential harvest at 95% BENIGN (the #415 failure).

## 3. Verdict calculation (`phishing.calculate_verdict`, lines 612–695)

Additive score with NAMED signals (same shape as the alert_triage scorer):

| Signal | Points |
|---|---|
| SPF fail | +25 |
| DKIM fail | +25 |
| DMARC fail | +20 |
| Reply-To domain ≠ From | +20 |
| Return-Path ≠ From | +15 |
| Typosquat hit | +30 |
| Each header anomaly | +10 |
| Each deception technique (body) | +15 |
| ≥3 URLs in body | +10 |
| Known-safe sender, no mismatches | −30 |

Bands: `≥70 MALICIOUS (HIGH conf) / ≥40 SUSPICIOUS (MEDIUM) / ≥20 SUSPICIOUS
(LOW) / else CLEAN`. Cap 100.

## 4. What Auspex ports vs. changes (S11 design decisions)

- PORT: regex header parse; result-token auth extraction; mismatch flags in
  code; the brand allow-list + TLD-swap/near-miss classes; Damerau-Levenshtein
  with cap; additive named-signal verdict score; anomaly vocabulary.
- CHANGE: SARA's `CLEAN` ↔ our contract's `BENIGN`; and SARA has no DEFERRED —
  Auspex adds the S10 rail philosophy: **auth-results absence or an unparseable
  paste can never yield BENIGN** (floor = DEFERRED). BENIGN requires positive
  evidence: DMARC pass (or SPF+DKIM pass) AND zero findings.
- CHANGE: the verdict is not handed to the model as prose to weigh — it is a
  **floor pinned in the validator** (S10 pin extended to allowed SETS): the
  model may RAISE severity from body content it reads, never lower it, and an
  un-analyzable message can't be rendered BENIGN. SARA reached the same end
  with orchestrator-side overrides; Auspex does it in the contract validator.
- CHANGE: homograph detection goes beyond a Cyrillic-range check — punycode
  (`xn--`) decode + confusable-fold against the brand list, mixed-script check.
- NOT ported: XSS/MIME/S-MIME anomaly sweeps (body-content analysis beyond
  S11's header scope), body deception techniques, response-plan generator,
  Sigma generation, `-30` safe-sender negative scoring (BENIGN is a gate on
  positive auth evidence, not a score subtraction).
