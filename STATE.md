# STATE — Auspex

_Last updated: 2026-07-18 (S9 COMPLETE — S8 review + promote #10, then the S9
response-modes feature + TD-009 fence, live-verified on Scout; S9 work on
`staging` awaits an S10 Step-0 review + promote #11)_

## Where we are
- **S9 COMPLETE.** Two halves:
  - **Step 0 — the outstanding S8 adversarial review → promote #10 (DONE).**
    promote #9 had shipped S8's feature work to `main` UNREVIEWED (an unrecorded
    session merged it). This session ran the 5-lens review over da42735..144b247,
    fixed 8 real findings with regression tests, and **promoted #10** (PR #10
    squash-merged, back-merged, main==staging tree verified).
  - **S9 feature — Response modes + TD-009 (DONE, on staging, NOT yet promoted).**
    6-mode code-owned resolver, typed contracts, TD-009 fence; live-verified
    against Scout. Awaits S10 Step-0 review → **promote #11** (deliberately
    NOT promoting unreviewed — that was the #9 mistake).
- **S8 review fixes (promote #10, on `main`):** (1) phase isolation — a bad NVD
  key no longer starves all technique content; (2) bundle parse skip-and-count;
  (3) assembled-content cap (closed the `extras` fan-out bypass) + name/version
  bound + re.ASCII ids; (4) version-bump retirement + `modified` compare +
  shrink floor; (5) MITRE ToU notice; (6) markdown/HTML stripped at ingest;
  (7) NEURAL_FLOORS pinned verbatim + per-doc_type coverage; (8) ENV egress
  docs + TD-010 scope + fixture trim 103,694→330. TD-010 (unbounded feed body)
  stays deferred (shared bounded_json helper across all 4 feeds).
- **S9 feature shipped (staging):**
  - `auspex/modes/` — `resolve_mode` (format beats keywords, ADR 0006) +
    `ModeContract` (compiles to system directive AND validator, ADR 0007) +
    6-mode catalog. `alert_triage` carries the DEFERRED rail ("no data ≠ low
    risk") from day one (SARA snapshot).
  - Wired into `chat.py` DEEP path: mode directive appended, output validated
    post-hoc, `done` frame reports `{mode, contract_valid}`.
  - **TD-009 CLOSED:** `_history` fences prior assistant turns as `⟦DATA⟧`
    blocks + a system fence directive; embedded markers neutralized; user turns
    unfenced. Regression tests incl. an instruction-bearing payload + break-out.
  - **Live-verified on Scout** (docs/probes/2026-07-18-s9-modes-live.md):
    `brief` produced all contract sections + re-validated ok; a signal-poor CEF
    alert returned Risk **DEFERRED** (not LOW). done frame carries mode+valid.
- **Deferred cleanly:** the ioc_check→KB-CVE-context stretch (parked 4×,
  IDEAS.md sketch); TD-012 (contract validation is post-hoc/observability-only —
  no re-ask/repair loop yet); stored ATT&CK markdown self-heals on next
  re-ingest (ingest-time fix; render-time MITRE notice already live).
- **Primary dev LLM (D-015):** Llama-4-Scout via Northflank; secondary/offline
  Ollama `qwen3:14b` (D-013). S9 modes are the FIRST LLM-path change since S3 —
  live-verified against Scout, hermetic tests use fake clients (no live LLM in
  pytest). TD-005 battery NOT re-triggered (no new doc_type, no model change).
- **CI-green: 447 tests** (was 412 at S8 end). `./ci.sh` green; container
  rebuilt with S9 code; `/api/health/ready` 200.

## S8 shipped (all committed on staging, 2026-07-18)
- **Step 0 first — adversarial review of S7** (5 parallel lenses:
  correctness, honesty/copy, security, test-hygiene, ops; 18 verified
  findings, nothing refuted; every finding verified against code before
  fixing). 13 fix commits, highlights:
  - KEV cursor DATA LOSS (2 lenses independently): cap + strict `>` horizon
    permanently dropped same-date entries; now horizon = newest FULLY-covered
    date + done_ids, 304 cycles scan the cached catalog, freshness persists,
    kb_refreshed only when the refresh ran.
  - Ingest brick: one failed boot bootstrap left embed() dead forever (and
    _bulk could auto-create a poisoned dynamic index); cycles now gate on
    `kb.bootstrapped`, embed() lazy-resolves like the neural leg.
  - NVD page-streaming (120-day window ≈ 92k dicts was one in-memory
    all-or-nothing) + hard page ceiling + refresh-once-per-ingest + keyless
    6.5 s spacing (5/30s quota) + 403/429→NVDError.
  - Feed poisoning: NaN/Infinity EPSS wedged the watermark forever →
    isfinite + allow_nan=False + CVE-id shape rail + 20k description cap.
  - Honesty: rejected CVEs now DELETE held chunks ("deleted" DocChange);
    re-ingest prunes orphaned chunks; EPSS copy never crosses boundaries it
    doesn't hold (<0.01 / >0.99 / >99.9th); kev_listed presence field;
    lookup_ids re-queries truncated ids (BM25-idf false miss); definition
    miss copy says "no curated definition", not KB-wide absence.
  - First-run KEV refresh = ONE update_by_query (was ≤1,647 paced NVD
    singles, uncapped, all-or-nothing).
  - Deferred with paths: TD-009 (prompt-injection fence → S9 modes work),
    TD-010 (feed byte ceilings), TD-011 (index rollover trigger).
  - Then **promote #8** (PR #8, checks green, squash + back-merge verified).
- **ATT&CK STIX feed** (probe: docs/probes/2026-07-18-attack-stix.md):
  31 KB version index is the cursor (`attack-enterprise` row,
  {version, modified}); 53 MB bundle only on version change (~2×/yr).
  bundle_to_docs filters revoked(149)/deprecated(12), shape-validates ids,
  scrubs (Citation:…), honest provenance "MITRE ATT&CK (STIX-derived) ·
  …attack.mitre.org… (ATT&CK v19.1)". 712 docs (697 techniques + 15
  tactics) INGESTED LIVE in ~26 s → 1,398 chunks. Hand-curated technique
  seeds REMOVED (same doc_ids → STIX overwrites; concepts stay). Definition
  filter grew to (concept, technique, tactic). Live-verified: "what is
  T1059" (real STIX text + sub-technique Related entries via prefix rail),
  "what is T1055.011" (never hand-seeded), "what is credential access"
  (TA0006). Bundle URLs pinned to the mitre-attack repo prefix; phase
  failures isolated from CVE phases.
- **TD-005 RESOLVED** (probe: docs/probes/2026-07-18-td005-calibration.md):
  14-query labeled battery on the live 3,417-chunk corpus. It re-caught the
  fabrication LIVE: ATT&CK's 1,398 curated chunks pushed filtered noise
  over the flat 0.6 floor — "what is quantum entanglement" answered
  T1090.002 (0.617) until the fix, same day. Per-doc_type floors from
  measured separation: curated 0.65 (noise 0.618 / weakest relevant 0.691),
  cve 0.70 (0.624 / 0.766), default 0.6. Regression-pinned: every boundary
  row is a parametrized test naming the live query that breaks. Battery
  also caught a labeling trap — "kubernetes ingress controller
  configuration" was a planned hard negative but the corpus HELD
  CVE-2026-55723 (real ingress CVE, 0.793): the corpus decides relevance.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Run the S9 adversarial review, then `/promote` (#11)** — the S9 feature
   work (auspex/modes/ resolver+contracts+catalog, chat.py mode wiring +
   TD-009 fence, the 35 new tests) is on `staging`, CI-green, live-verified,
   but UNREVIEWED. This is the S10 Step 0. Same 5-lens drill (correctness,
   honesty/copy, security, test-hygiene, ops); verify findings before fixing.
   Review scope = what landed AFTER promote #10 (306b9c7): commits
   cae88e9..HEAD on staging. DO NOT promote unreviewed (the #9 mistake).
2. **TD-005 re-battery trigger (standing):** corpus > 30k chunks, ANY new
   doc_type, or embedding-model change → re-run the labeled battery
   (script pattern in the probe doc). Sigma/abuse.ch ingestion (parked in
   IDEAS) trips this trigger by definition.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat; S9 modes shape the DEEP prompt + validate output but do NOT yet
   execute tools/proposals. TD-012 tracks contract validation being post-hoc
   (no re-ask/repair loop). TD-009 (feed-text fence) is now CLOSED.
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
  re-check before EVERY `gh` call. It flipped again at S8 start.
- S8 demo turns (zero-LLM shortcuts, still valid): `what is T1059` /
  `what is T1055.011` / `what is credential access` (STIX-derived);
  `what is quantum entanglement` → honest miss; `check CVE-2026-58644`.
- **S9 demo turns (DEEP path, live Scout):** `give me a brief on the Log4Shell
  vulnerability` → BRIEF mode, `## Bottom line/Details/Watch items`, done frame
  `{mode:brief, contract_valid:true}`;
  `CEF:0|Vendor|Product|1.0|100|generic activity observed|0|` → ALERT_TRIAGE,
  Risk **DEFERRED** (not LOW). NOTE: `what is T1059` still shows markdown links
  in stored content until the next ATT&CK re-ingest (render-time MITRE notice
  already appears; markdown-strip is ingest-time).

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
- Capability shape: /home/burhan/sara-open/sara/core/unified_registry.py:37

## Next session should
Review the S9 feature work (multi-lens, verify before fixing) → `/promote`
(#11) → then S10 exactly as written in NEXT-SESSION.md (Alert normalizer +
risk score — multi-SIEM format detection feeding the alert_triage mode). The
S9 modes give S10 its consumer: the normalizer's structured envelope is what
alert_triage's DEFERRED "no data ≠ low risk" rail scores.
