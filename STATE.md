# STATE — Auspex

_Last updated: 2026-07-18 (S10 COMPLETE — S9 review + promote #11, then the S10
alert normalizer + additive scorer + DEFERRED rail, live-verified on Scout; S10
work on `staging` awaits an S11 Step-0 review + promote #12)_

## Where we are
- **S10 COMPLETE.** Two halves:
  - **Step 0 — the outstanding S9 adversarial review → promote #11 (DONE).**
    5-lens review over cae88e9..HEAD (the S9 modes + TD-009 fence). Findings
    verified by execution before fixing; 4 fix commits (below), then
    **promoted #11** (PR #11 squash-merged, back-merged, main==staging verified).
  - **S10 feature — Alert normalizer + risk score (DONE, on staging, NOT yet
    promoted).** Multi-SIEM parse → typed envelope → additive itemized 0–100
    score → DEFERRED rail; live-verified against Scout. Awaits S11 Step-0
    review → **promote #12** (deliberately NOT promoting unreviewed — #9 lesson).
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
- **S10 feature shipped (staging):**
  - `auspex/alerts/` — `normalize()` detects CEF/LEEF/syslog/JSON → typed
    closed-vocab `AlertEnvelope` (severity off 5 scales, src/dst, signals, IOCs,
    MITRE ids, timestamps; errors + UNKNOWN → parsed=False). `score_alert()` =
    additive 0–100 with itemized NAMED contributions (ports SARA assess_risk,
    docs/probes/2026-07-18-sara-alert-triage-scorer.md); artifact count NOT
    scored; bands CRITICAL≥85/HIGH≥70/MEDIUM≥40/LOW.
  - **DEFERRED rail, both SARA conditions:** (a) signal-poor (incl.
    INFORMATIONAL-only + unparseable) → DEFERRED/score nulled/needs_deep_triage;
    (b) severity-known-but-IOCs-un-enriched → DEFERRED naming the IOC counts.
    "No data ≠ low risk" is CODE (the scorer emits it), not a prompt.
  - Wired into `chat.py` ALERT_TRIAGE path: `render.py` compiles the code
    verdict into an AUTHORITATIVE directive — the model renders ## Risk with the
    code's level, not its own. Also MITIGATES TD-013 for alerts (model scores
    the code verdict, not the raw untrusted paste).
  - **Live-verified on Scout** (docs/probes/2026-07-18-s10-alert-triage-live.md):
    rich CEF → CRITICAL(90), signal-poor CEF → DEFERRED — both rendered by Scout
    with the code Risk level, done frame `contract_valid:true`, re-validated ok.
- **Deferred cleanly:** the ioc_check→KB-CVE-context stretch (parked 5×,
  IDEAS.md sketch) — this is the enrichment that would set `has_enrichment=True`
  on the score path (until then, every non-LOW score carries the pending-
  enrichment tail); TD-012 (contract validation post-hoc, no re-ask loop);
  TD-013 phishing-path portion (phishing_analysis has no normalizer yet);
  TD-014 (unbounded history fetch).
- **Primary dev LLM (D-015):** Llama-4-Scout via Northflank; secondary/offline
  Ollama `qwen3:14b` (D-013). S10 parse+score is ZERO-LLM (hermetic fixtures);
  only the alert_triage WIRING touches the LLM — live-verified against Scout.
  TD-005 battery NOT re-triggered (S10 adds no doc_type, no model change).
- **CI-green: 478 tests** (was 447 at S9 end: +11 S9-review regressions,
  +18 alerts, +2 alert_triage wiring). `./ci.sh` green; container rebuilt with
  the `auspex.alerts` package; `/api/health/ready` 200.

## S9 shipped (promote #11, on `main` 2026-07-18)
- `auspex/modes/` — code-owned `resolve_mode` (format beats keywords, ADR 0006),
  `ModeContract` compiling to system directive AND validator (ADR 0007), 6-mode
  catalog with the `alert_triage` DEFERRED rail from day one. Wired into
  chat.py's DEEP path; `done` frame reports `{mode, contract_valid}`.
- **TD-009 CLOSED:** `_history` fences prior assistant turns as `⟦DATA⟧` blocks
  + system fence directive; embedded markers neutralized; user turns unfenced.
- Hardened by the S10 Step-0 review (4 fixes above): resolver common-domain
  exemption, validator header/enum/empty robustness, contract-drift log, honest
  docs. Live-verified on Scout (brief + alert_triage DEFERRED).

## In-flight / standing follow-ups (carry forward until DONE)
1. **Run the S10 adversarial review, then `/promote` (#12)** — the S10 feature
   work (`auspex/alerts/` normalizer+scorer+DEFERRED-rail+render, chat.py
   alert_triage wiring, the 20 new tests) is on `staging`, CI-green,
   live-verified, but UNREVIEWED. This is the S11 Step 0. Same 5-lens drill
   (correctness, honesty/copy, security, test-hygiene, ops); verify findings by
   execution before fixing. Review scope = what landed AFTER promote #11
   (5f00f25): commits 40af4b9..HEAD on staging. Security lens should hammer the
   normalizer parsers (CEF/LEEF escaping, syslog PRI, JSON flatten) on malformed/
   adversarial input, and confirm the alert-path TD-013 mitigation actually holds
   (can a crafted paste move the code Risk level?). DO NOT promote unreviewed
   (the #9 mistake).
2. **TD-005 re-battery trigger (standing):** corpus > 30k chunks, ANY new
   doc_type, or embedding-model change → re-run the labeled battery
   (script pattern in the probe doc). Sigma/abuse.ch ingestion (parked in
   IDEAS) trips this trigger by definition. (S10 added no doc_type — not tripped.)

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat; S9 modes shape the DEEP prompt + validate output, and S10
   alert_triage now feeds a CODE-computed Risk verdict, but neither EXECUTES
   tools/proposals. TD-012 tracks contract validation being post-hoc (no
   re-ask/repair loop). TD-009 CLOSED; TD-013 alert-path MITIGATED in S10
   (phishing-path portion still open); TD-014 (unbounded history) open.
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
- Ollama 0.24.0 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- `gh` flips to SIRP-Burhan between sessions AND mid-session (D-011) —
  re-check before EVERY `gh` call. At S10 start it was on the PERSONAL account
  (bh3082336888-cell) and stayed there through promote #11.
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
- Capability shape: /home/burhan/sara-open/sara/core/unified_registry.py:37

## Next session should
Review the S10 feature work (multi-lens, verify by execution before fixing) →
`/promote` (#12) → then S11 exactly as written in NEXT-SESSION.md (Phishing/
header agent — deterministic SPF/DKIM/DMARC/typosquat/homograph checks injected
as AUTHORITATIVE, LLM narrative on top, victim-domain IOC filtering). S11 is the
phishing analogue of S10: the same "code decides, model renders" pattern applied
to phishing_analysis — and it closes the still-open phishing portion of TD-013.
