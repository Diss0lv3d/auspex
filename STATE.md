# STATE — Auspex

_Last updated: 2026-08-08 (S12 IN PROGRESS — Step 0 DONE: S11 adversarial
review, 9 findings all verified by execution, fixed, live-verified, **promoted
#13** (main==staging). Now in S12 proper: ACH hypothesis engine — recon done,
design next)_

## Where we are
- **S12 Step 0 COMPLETE (2026-08-08).** Adversarial 5-lens review of the S11
  phishing work (136992f..dd46410). **9 findings (A–I), every one verified by
  execution before fixing**; 7 fix commits + TD-015 correction + live probe.
  Then **promoted #13** (PR #13 squash-merged by the human after a permission
  block on `gh pr merge`; back-merged `5d3d2dc`, main==staging, ready 200).
  - **(A, security)** `_auth` scanned `text[:3000]` — attacker body prose
    (`spf=pass dkim=pass dmarc=pass` in a footer) MANUFACTURED a BENIGN floor.
    Auth now reads ONLY gateway-stamped headers (Authentication-Results, X-,
    Received-SPF, Received).
  - **(B, security)** the victim filter withheld the SENDER on a BEC self-spoof
    (From: ceo@acme.com → finance@acme.com) — the docstring promised the
    opposite. Sender-side artifacts (From/Reply-To/Return-Path, addr+domain)
    now exempt in code.
  - **(C, security)** indicator values skipped `flatten` — a 50 KB address made
    a 51,758-char directive (measured), crowding out instructions. Now
    flatten(cap=120) per value; regression pins block <4000 chars.
  - **(D, correctness)** naive registrable domain: `amazon.co.uk` → `co.uk`, so
    EVERY ccTLD brand mail false-positived to SUSPICIOUS (score 35, measured).
    Fixed: curated `_MULTI_LABEL_SUFFIXES` + `is_brand_host` (TD-015 item 3).
  - **(E, correctness)** same root cause hid cross-domain Reply-To mismatches
    under compound TLDs (→ BENIGN) and let a compound-TLD victim swallow
    attacker infra in victims.py.
  - **(F, test-hygiene)** the sender-not-filtered test asserted only that a
    DIFFERENT host survived — vacuous while the named invariant was broken.
    Now asserts the sender is kept AND the victim withheld.
  - **(G, honesty)** 4 places claimed the pin means "can NEVER launder below
    the floor" — validation is post-hoc (TD-012); the laundered answer streams
    and persists, `contract_valid:false` is a RECORD not a block. Copy now
    follows the S9 containment-vs-inertness standard; launder test asserts the
    streamed text carries the laundered value.
  - **(H, security)** ARC-Authentication-Results (relay-stamped, attacker-
    routable) could reach BENIGN alone. Now asymmetric: relay failures believed
    (raise-only), relay passes discarded; gateway wins when both present.
  - **(I, honesty/live-only)** with B fixed, the directive still said "never
    naming the recipient's own domain" — which in a self-spoof DESCRIBES THE
    SENDER; Scout dropped ceo@acme.com from ## Indicators live. Directive now
    calls out the self-spoof explicitly; re-verified live (Scout renders it,
    still withholds the victim mailbox).
  - Probe: docs/probes/2026-08-08-s12-phishing-review-live.md (before/after per
    finding, all 3 turns contract_valid:true + independent re-validation).
  - TD-015 CORRECTED: its "only under-detect, never a false alarm" claim was
    falsified by D/E — registrable-domain item moved to FIXED; brand-list and
    confusable-set gaps remain (those really are FN-biased).
- **S12 feature (IN PROGRESS): Hypothesis engine v1 / ACH** — competing
  hypotheses per investigation, per-evidence scoring in CODE (the ACH matrix),
  next-lookup by expected information gain. NOT the S9–S11 "code decides, model
  renders" mold — a reasoning structure; design-first (recon workflow run over
  SARA analogues + evidence seams + storage + chat wiring before any code).
- **S11 shipped (promote #13, on `main` 2026-08-08).** Two halves:
  - **Step 0 — the outstanding S10 adversarial review → promote #12 (DONE).**
    5-lens review over 40af4b9..HEAD (the S10 alert normalizer+scorer+rail+wiring).
    8 findings, all verified by execution before fixing; 5 fix commits (below),
    then **promoted #12** (PR #12 squash-merged, back-merged, main==staging).
  - **S11 feature — Phishing/header agent.**
    `auspex.phishing`: regex header parse → typed EmailEnvelope → named auth/
    spoof/lookalike findings → additive Verdict FLOOR; victim-domain IOC filter;
    validator pin extended to an ALLOWED SET (raise-yes, launder-no). Closes the
    phishing portion of TD-013 (MITIGATED — see the G-corrected copy). Live-
    verified against Scout, then hardened by the 9 S12 Step-0 fixes above.

## S10 review fixes (promote #12, on `main` 2026-07-18)
- **(A)** `auspex/modes/contract.py`: the validator did enum-MEMBERSHIP only — a
  steered model could swap one valid Risk level for another with
  `contract_valid=true`. `validate(pinned=…)` now pins a field to the code
  verdict (exact for a str, membership for a set); chat.py pins Risk to the
  scorer level. This is the mechanism S11 reused for the phishing floor.
- **(C)** `scorer.py`: an `parsed=False` envelope whose raw text carried
  `-enc`/`powershell` still scored a confident LOW/MEDIUM — new rail (0):
  unparsed always DEFERS (signals stay listed, never sum to a score).
- **(D)** the pending-enrichment tail fired on IOC-less alerts (nothing to
  enrich) — now gated on `has_iocs`.
- **(E)** signal-poor DEFERRED reason said "no severity" for INFORMATIONAL —
  now names "informational-only severity".
- **(F/G/H)** `normalizer.py`: JSON-wrapped raw CEF mis-detected (JSON-first
  detection); syslog-framed CEF/LEEF lost fields (parse from the marker offset);
  fraction confidence `0.9` read as 0% (fraction-scale handling); + never-raise
  guard extended over the uniform detectors.
- **(B)** `render.py`: untrusted envelope free-text (name/src/dst) embedded in a
  SYSTEM directive with newlines intact — now flattened via the shared
  `auspex.untrusted.flatten` (also used by the S11 phishing directive).

## S11 feature shipped (staging)
- `auspex/phishing/` — `parse_email()` (regex header parse over the raw paste,
  never `email.parser`; recovers From display+addr with a fallback for the
  display-name-spoof case that defeats stdlib `parseaddr`, Reply-To, Return-Path,
  recipients, SPF/DKIM/DMARC result tokens, named header anomalies; <2 headers →
  `parsed=False`). `decide_verdict()` = additive named-signal score (SARA
  weights) → Verdict FLOOR + the S10 rail philosophy: BENIGN needs POSITIVE auth
  evidence (DMARC pass, or SPF+DKIM pass) and zero findings; absence/unparseable/
  lone-weak-signal → DEFERRED, never a rounded-down BENIGN.
- `lookalike.py` + `brands.py` — TLD-swap (HIGH), Damerau-Levenshtein near-miss
  (MEDIUM), IDN homograph (punycode decode + confusable-fold, HIGH), brand-
  subdomain bait (MEDIUM); each a NAMED finding + confidence. Brand list is a
  CODE constant (~44 brands, ported from SARA) — no env var.
- `victims.py` — recipient-domain artifacts + internal/reserved IPs withheld
  from indicators (a phishing email names its victim; the victim is not an IOC).
  The SENDER is never filtered, even when it spoofs the victim's own domain.
- `render.py` — compiles the envelope+verdict into an AUTHORITATIVE directive
  (S10 pattern); the validator pin (`pinned={"Verdict": allowed}`) enforces the
  floor: the model may RAISE severity on body content, never launder below.
- **Classifier fix (prerequisite):** the 92/8 gate fast-tracked only ALERT
  pastes to DEEP; a short email paste was intercepted as IOC_CHECK and never
  reached PHISHING_ANALYSIS (and the victim's addresses would have been
  enriched). `_is_email_paste` (≥2 RFC-5322 headers) now routes to DEEP —
  format beats keywords — defined once in the classifier, imported by the
  resolver.
- **Live-verified on Scout** (docs/probes/2026-07-18-s11-phishing-live.md):
  spoof+auth-fail+typosquat → MALICIOUS (floor-locked, model rendered MALICIOUS,
  re-validated ok, recipient domain NOT surfaced); all-auth-pass → BENIGN
  (positive-evidence gate). Both `contract_valid:true`.
- **S9 review fixes (promote #11, on `main`):** (1) resolver reused the naive
  `any(non-CVE)` → prose mentioning microsoft.com/github.com hijacked into
  IOC_ENRICHMENT; now delegates to the classifier's `_ioc_shaped`
  (common-domain exemption). (2) validator: header-inline/emphasis enum
  tolerance (`## Risk: HIGH`, `## **Risk**`) the docstring promised but didn't
  implement; compound-value reject (`LOW/MEDIUM`); empty-required flagged;
  `##`-only headers so single-# code comments don't forge sections. (3) chat.py:
  server-side contract-drift log (mode+reason, never content); honest
  containment-vs-inertness fence comment; done-frame tri-state documented.
  (4) TD-013 (untrusted paste in triage modes) + TD-014 (unbounded history).
- **S10 shipped (promote #12, on `main`):** `auspex/alerts/` — `normalize()`
  detects CEF/LEEF/syslog/JSON → typed closed-vocab `AlertEnvelope`;
  `score_alert()` = additive 0–100 itemized NAMED contributions; DEFERRED rail
  (both SARA conditions + unparsed-always-defers from the S11 review); wired into
  chat.py ALERT_TRIAGE with the AUTHORITATIVE code verdict (Risk PINNED at
  validation). Live-verified on Scout (docs/probes/2026-07-18-s10-alert-triage-live.md).
  Hardened by the 8 S11 Step-0 fixes above.
- **S9 shipped (promote #11, on `main`):** `auspex/modes/` — code-owned
  `resolve_mode` (format beats keywords), `ModeContract` compiling to directive
  AND validator, 6-mode catalog with the `alert_triage` DEFERRED rail. TD-009
  CLOSED (`_history` fences prior assistant turns).
- **Deferred cleanly:** the ioc_check→KB-CVE-context stretch (parked 5×,
  IDEAS.md sketch) — the enrichment that would set `has_enrichment=True` on the
  alert score path; TD-012 (contract validation post-hoc, no re-ask loop);
  TD-014 (unbounded history fetch); TD-015 (S11 phishing heuristic coverage —
  brand list, confusable set, naive registrable domain; false-negative biased).
- **Primary dev LLM (D-015):** Llama-4-Scout via Northflank; secondary/offline
  Ollama `qwen3:14b` (D-013). S11 parse/score/verdict is ZERO-LLM (hermetic
  fixtures); only the phishing_analysis WIRING touches the LLM — live-verified.
  TD-005 battery NOT re-triggered (S11 adds no doc_type, no model change).
- **CI-green: 516 tests** (measured at S12 start; S11's session-end note said
  515 — a write-time miscount, not a lost test) (was 478 at S10 end: +12 S10-review regressions,
  +21 phishing, +3 phishing SSE wiring, +1 email-paste routing). `./ci.sh` green;
  container rebuilt with the `auspex.phishing` package; `/api/health/ready` 200.

## In-flight / standing follow-ups (carry forward until DONE)
1. **S12 feature work** — ACH hypothesis engine (see "Where we are"). The S12
   feature commits will land on `staging` and need their own Step-0 review in
   S13 before promote #14 (the standing drill).
2. **TD-005 re-battery trigger (standing):** corpus > 30k chunks, ANY new
   doc_type, or embedding-model change → re-run the labeled battery
   (script pattern in the probe doc). Sigma/abuse.ch ingestion (parked in
   IDEAS) trips this trigger by definition. (S11 added no doc_type — not tripped.)

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat; S9 modes shape the DEEP prompt + validate output, and S10
   alert_triage now feeds a CODE-computed Risk verdict, but neither EXECUTES
   tools/proposals. TD-012 tracks contract validation being post-hoc (no
   re-ask/repair loop). TD-009 CLOSED; TD-013 MITIGATED for BOTH triage
   (S10) and phishing (S11) paths — the code verdict is pinned, only free-prose
   narration remains manipulable; TD-014 (unbounded history) open.
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly
   (watermarks hold, catch-up on recovery; ATT&CK/KEV phase failures are
   isolated from NVD).
4. **Corpus ~3.4k chunks, grows ~770 docs/day** while the container runs.
   OpenSearch 1 GiB heap fine; TD-011 tracks the rollover trigger
   (>150k chunks / RSS >70% / p95 >500 ms).

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`
  (ENRICHMENT_ENABLED=false, KB_ENABLED=false, INGEST_ENABLED=false —
  override in shell for host-run live ingest).
- `ingest_state` rows: `nvd-delta` (window-end cursor), `kev` (last_modified
  + date_added_horizon + done_ids + kb_refreshed), **`attack-enterprise`
  ({version: "19.1", modified}) — new in S8**. Gap-catch-up demo: rewind
  `nvd-delta.cursor.last_mod_end`, restart app.
- auspex-knowledge: ~3,417 chunks (seed 8 + live NVD/KEV/EPSS + 1,398
  ATT&CK). Index _meta carries the seed fingerprint; mapping now includes
  kev_listed (+1 additive upgrade, live-verified).
- Ollama **0.32.5** on :11434 (was 0.24.0 at S11 — host upgraded between
  sessions, verified S12 start); models qwen3:14b / llama3.1:8b / mistral:latest.
- `gh` flips to SIRP-Burhan between sessions AND mid-session (D-011) —
  re-check before EVERY `gh` call. At S11 start the ACTIVE account was already
  PERSONAL (bh3082336888-cell) and stayed there through promote #12. **At S12
  start it had flipped BACK to SIRP-Burhan** — caught by the ritual, switched
  with `gh auth switch --user bh3082336888-cell`. The flip is the norm, not the
  exception: re-check before every `gh` call this session too.
- S8 demo turns (zero-LLM shortcuts, still valid): `what is T1059` /
  `what is T1055.011` / `what is credential access` (STIX-derived);
  `what is quantum entanglement` → honest miss; `check CVE-2026-58644`.
- **S9 demo turns (DEEP path, live Scout):** `give me a brief on the Log4Shell
  vulnerability` → BRIEF mode, `## Bottom line/Details/Watch items`, done frame
  `{mode:brief, contract_valid:true}`.
- **S10 demo turns (ALERT_TRIAGE, code-scored, live Scout):**
  rich CEF `CEF:0|Trellix|ENS|10.7|1201|Malware detected|9|src=10.1.2.3 cs1=powershell -enc SQBFAFgA externalId=T1059.001 confidence=90`
  → **CRITICAL (90)** (itemized: sev+40/conf+15/enc+20/proc+10/mitre+5);
  signal-poor `CEF:0|Vendor|Product|1.0|100|generic activity observed|0|`
  → **DEFERRED** (score nulled) — both rendered by Scout with the CODE Risk
  level, `contract_valid:true`. NOTE: `what is T1059` still shows markdown
  links in stored content until the next ATT&CK re-ingest (render-time MITRE
  notice already appears; markdown-strip is ingest-time).
- **S11 demo turns (PHISHING_ANALYSIS, code-decided Verdict, live Scout):**
  a spoofed auth-failing email (`From: "PayPal Support" <security@paypa1.com>`,
  `Reply-To: recover@account-verify.ru`, spf/dkim/dmarc=fail, link paypa1.com)
  → **MALICIOUS** (floor-locked; findings: 3 auth fails + reply-to mismatch +
  display-name spoof + paypa1~paypal typosquat); an all-auth-pass email from
  a normal sender → **BENIGN** (positive-evidence gate). Both `contract_valid:
  true`; the recipient's own domain (acme.com) was NOT surfaced as an IOC.
  A laundering attempt (body claims legitimacy) can't pull MALICIOUS→BENIGN
  (the floor pin fails it, pinned hermetically).

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
Base: `/home/burhan/sara-open/` (paths re-verified 2026-07-15):
- ReACT loop: /home/burhan/sara-open/sara/core/agent_loop.py:60
- Plan→DAG→Judge loop: /home/burhan/sara-open/.claude/worktrees/1359-chain-surface/sara/core/orchestrator_loop/runner.py:39
  (worktrees get cleaned; re-snapshot to docs/probes/ before S9 modes work)
- Permission hard-rails: /home/burhan/sara-open/sara/core/permissions.py:65-176
- Fast classifier / 92-8: docs/probes/2026-07-16-sara-fastpath-pattern.md
- Enrichment/fan-out: probe docs 2026-07-16
- RRF retrieval + ID bypass: docs/probes/2026-07-17-sara-rrf-retriever-pattern.md
- DEFERRED rail: /home/burhan/sara-open/sara/agents/alert_triage.py:1429
  (re-snapshotted S9 → docs/probes/2026-07-18-sara-orchestrator-deferred.md)
- Alert additive scorer: /home/burhan/sara-open/sara/agents/alert_triage.py:1276-1590
  (re-snapshotted S10 → docs/probes/2026-07-18-sara-alert-triage-scorer.md;
  live source still present but may be cleaned)
- Phishing / header / typosquat: /home/burhan/sara-open/sara/agents/phishing.py,
  header_analysis.py, sara/core/typosquat.py (re-snapshotted S11 →
  docs/probes/2026-07-18-sara-phishing-header-patterns.md)
- Capability shape: /home/burhan/sara-open/sara/core/unified_registry.py:37

## Next session should
Review the S11 feature work (multi-lens, verify by execution before fixing) →
`/promote` (#13) → then S12 exactly as written in NEXT-SESSION.md (Hypothesis
engine v1 / ACH — competing hypotheses per investigation, per-evidence scoring
against each, next-lookup by expected information gain). S12 is a different shape
from S9–S11 (not a "code decides, model renders" mode — a reasoning structure);
scope it carefully at session start against ROADMAP.md.
