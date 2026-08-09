# Auspex Roadmap — sessions & deliverables

One session = one focused working window. A session is DONE only when the
CLAUDE.md session-end ritual is complete. Order may flex; scope of a session
may not grow mid-session (IDEAS.md exists for that).

## Phase 0 — Foundations & de-risk

- [x] **S1 — Scaffold.** FastAPI app factory, config module (env-driven,
  `.env.example` + `docs/ENV_VARS.md`), docker-compose (app + Postgres),
  Postgres schema v0 (workspaces, users, api_keys, chat_sessions, messages —
  `workspace_id` on EVERY table from day one), Google OAuth + JWT + hashed API
  keys, pytest + ruff CI script, health endpoints. `docker compose up` serves
  `/api/health`.
- [x] **S2 — LLM provider layer + capability probe.** ⚠ De-risks the #1 blocker.
  _Done 2026-07-15 against interim local endpoint (D-012): 98.7 % valid calls,
  52.5 % loop completion, mode → prompted_tools. Scout numbers still owed when
  the Northflank endpoint returns (one command: `scripts/llm_harness.py`)._
  OpenAI-compat client (base_url + model + api_key, streaming, streaming
  tool-call deltas). Probe battery: native tools? parallel calls? JSON mode?
  schema adherence? usable context? tok/s? Persisted capability scorecard per
  endpoint. Harness: 30–50 scripted multi-step tool tasks against the Northflank
  endpoint; measure valid-call rate + loop completion. Save results to
  docs/probes/. **Go/no-go data decides how hard we lean on ReACT vs plan-only.**
- [x] **S3 — Agent loop v1 + chat SSE.** ReACT loop (native tools primary,
  prompted `<tool_call>` fallback chosen by scorecard), tool registry with
  read/write/destructive levels, permission gate skeleton, SSE chat endpoint
  (single-key JSON event protocol), minimal functional UI shell.
  _(Done 2026-07-16: `auspex/agent/{registry,permissions,loop}.py`,
  `auspex/routes/{chat,ui}.py`; D-014 gate + proposals; 79 tests;
  live-verified vs qwen3:14b. Step 0 networking fully closed — containerized
  app streams real /api/chat over host.docker.internal.)_

## Phase 1 — Intelligence core

- [x] **S4 — Fast classifier (92/8 split).** IOC regex patterns (defang-aware),
  query classifier, shortcut handlers (greeting/identity/ioc_check/cve_lookup/
  definition), deep path stub. No LLM on the shortcut path.
  _(Done 2026-07-16: `auspex/classify/{observables,classifier,shortcuts}.py`;
  stretch step 4 shipped too — /api/chat classifies before the model, done
  frame carries `path: shortcut|model`; 8-angle adversarial review applied;
  177 tests; shortcut path verified LLM-free + network-free in-container.)_
- [x] **S5 — Enrichment fan-out + verdict store.** Direct provider clients
  (AbuseIPDB, OTX, GreyNoise community, URLhaus, ThreatFox, Shodan InternetDB,
  CIRCL hashlookup), submit-all/poll-all parallelism, per-provider circuit
  breaker, `verdicts` table **with decay curve fields from day one**
  (first Living Verdicts brick), observables table keyed by normalized IOC.
- [x] **S6 — KB/RAG on OpenSearch.** `auspex-knowledge` index design (mapping
  probe first), chunking, embeddings (probe own-container ML-plugin server-side; fallback
  in-process MiniLM), BM25 + kNN + client-side RRF, CVE/MITRE ID-query neural
  bypass, regime-aware score floors.
  _(Shipped 2026-07-17: server-side embeddings ratified D-018 — ONNX pinned,
  TORCH_SCRIPT broken on 2.19.4; idempotent bootstrap incl. 14-chunk seed
  corpus (5 live-fetched NVD CVEs + ATT&CK/concept seed summaries);
  cve_lookup + definition shortcuts consult the KB with zero LLM; live verify
  caught 2 fabrication bugs — absolute neural floor 0.6 + neural-as-relevance-
  gate now regression-pinned; 320 tests, CI green.)_
- [x] **S7 — Ingestion 1.** NVD delta + CISA KEV + FIRST EPSS merged into one
  enriched doc per CVE; `ingest_state` table + startup catch-up scheduler.
  _(Done 2026-07-17: `auspex/ingest/` package, probe-pinned feed clients,
  watermarks advance per-window after ingest, KB bootstrap moved into the
  scheduler task (TD-008 resolved), DocChange→NullSink hook for S14. Also:
  S6 review verified inline (10 fixes) + promote #7. Live: simulated 2-day
  gap → 1 844 chunks; fresh CVE answers with KEV+EPSS, zero LLM. The TD-005
  spot-check caught HNSW-recall + floor-erosion at ~2.5k chunks — fixed via
  doc_types-filtered retrieval; full calibration is an S8 gate. 357 tests.)_
- [x] **S8 — Ingestion 2 (core).** MITRE ATT&CK (lazy + cached), Sigma rules, abuse.ch
  quartet; auto-promotion to KB on miss.
  _(Done 2026-07-18: S7 adversarial review — 18 verified findings across 5
  lenses, 13 fix commits (KEV cursor data loss, bootstrap-brick, page
  streaming, NaN wedge, rejected-CVE deletion, orphan pruning, boundary-
  honest EPSS copy, lookup-truncation false miss, UBQ first-run refresh) —
  then promote #8. ATT&CK STIX feed: index-as-cursor, 712 live docs
  (697 techniques + 15 tactics) replace the hand seeds; T1059 + never-seeded
  sub-techniques + tactic definitions answer live with STIX provenance.
  TD-005 RESOLVED: 14-query labeled battery on the 3,417-chunk corpus
  re-caught fabrication live (quantum→T1090.002 at 0.617 after ATT&CK grew
  the pool) → per-doc_type floors (curated 0.65 / cve 0.70) regression-
  pinned. 412 tests. Sigma + abuse.ch + auto-promotion-on-miss → IDEAS,
  not reached — fold into a later ingestion slot.)_
- [x] **S9 — Response modes.** 6 modes only (definition, ioc_enrichment,
  threat_intel, alert_triage, phishing_analysis, brief), code-owned priority
  resolver (format beats keywords), typed output contracts that compile to
  prompts + validators. _(Reviewed (S10 Step 0: 4 fix commits — resolver
  common-domain exemption, validator header/enum/empty robustness, drift log,
  honest docs) → **promote #11**. Live-verified against Scout.)_

## Phase 2 — Analysis

- [x] **S10 — Alert normalizer + risk score.** Multi-SIEM format detection
  (CEF/LEEF/syslog/JSON) → typed closed-vocab envelope; additive 0–100 score
  with itemized, named contributions; **DEFERRED rail** (no data ≠ low risk,
  both SARA conditions). Code-owned parse+score (no LLM); feeds the S9
  alert_triage mode with the AUTHORITATIVE verdict. _(Reviewed at S11 Step 0
  — 8 findings fixed with regressions — and promoted #12 to main.)_
- [x] **S11 — Phishing/header agent.** Deterministic SPF/DKIM/DMARC/typosquat/
  homograph checks injected as AUTHORITATIVE; LLM narrative on top; victim-domain
  IOC filtering. _(`auspex.phishing`: regex header parse → typed EmailEnvelope →
  named auth/spoof/lookalike findings → additive Verdict FLOOR; BENIGN gated on
  positive auth evidence, absence/unparseable → DEFERRED; victim-domain + internal
  IPs withheld from indicators; validator pin extended to an ALLOWED SET so the
  model may raise above the floor, never launder below it. Format-beats-keywords
  email→DEEP gate added to the classifier. Live-verified on Scout (MALICIOUS floor
  + BENIGN gate). MITIGATES the phishing portion of TD-013. Reviewed at S12
  Step 0 — 9 findings (A–I) verified by execution and fixed with regressions,
  incl. body-prose BENIGN manufacture, BEC sender victim-filtering, ccTLD brand
  false positives, ARC relay passes — and promoted #13 to main.)_
- [x] **S12 — Hypothesis engine v1 (ACH).** Competing hypotheses per
  investigation, per-evidence scoring against each hypothesis, next-lookup
  chosen by expected information gain. _(`auspex/ach` + `/api/investigations`,
  D-019: closed 4-hypothesis catalog per subject kind; evidence adapters over
  the S5/S10/S11 typed shapes with curated cell-vector doctrine tables; Heuer
  least-inconsistency matrix with hard-contradiction rejection + honesty
  rails; expected-information-gain lookup ranking with curated P(outcome|H)
  rows, executed live through the S5 fan-out. Zero LLM end-to-end — model
  rendering deferred to S13 by design. Hardened by a same-session 4-lens
  verification workflow: 16 findings, all verified by execution, all fixed.
  Live-verified in-container; the live gain figure matched the hand-computed
  fixture to 6 decimals. On staging, awaiting S13 Step-0 review + promote #14.)_
- [x] **S13 — Evidence graph + cited output.** Typed evidence objects; every
  generated claim carries a citation; output guard rejects uncited claims.
  _(Step 0 first: fresh-eyes review of the S12 diff — 7 findings, every one
  verified by execution, all fixed with regressions; promote #14 PR opened
  (merge pending, human-gated). Then: ach_evidence row uuids became the
  stable citation identity (E-<hex8> labels, collision-extending);
  `POST /api/investigations/{id}/summary` renders the first LLM output on
  the surface through an investigation_summary contract — code compiles the
  authoritative directive (matrix, per-hypothesis bearing evidence,
  flattened statements, top lookup), the leading hypothesis is PINNED, and
  the post-hoc citation guard names fabricated ids and uncited claim lines
  (TD-012: detected, not prevented). Live-verified against Scout twice: run
  1 caught a guard bug (grouped [E-a, E-b] citations refused) and a
  directive gap (rejected rows had nothing to cite) — both fixed with
  regressions; run 2 clean: 19 valid citations, 0 fabricated, 0 uncited.
  KB-doc citability deliberately NOT picked up — the parked ioc_check→KB
  idea stays parked. 597 tests green.)_

## Phase 3 — Living Verdicts (flagship)

- [x] **S14 — Retro-hunt.** On-ingest sweep of historical observables (indexed
  join, never scan), re-open notifications, verdict flip events.
  _(Done 2026-08-09: Step 0 — independent adversarial review of the S13 cited-
  summary commits, 4 findings all verified by execution before fixing (citation-
  shaped tokens in attacker text poisoning the guard; the uncited check tuned to
  one model's markdown, failing 3 of 4 faithful renderings; the pin broken by
  bold on hyphenated tokens; a 200-row directive costing ~13.5k prompt tokens),
  1 named angle confirmed sound. Then S14: the S7 NullSink seam got its consumer
  — `auspex/retrohunt/` sweeps CVE observables for kev-added/deleted changes
  through ONE indexed join per 50-id chunk, chunk size chosen from a MEASURED
  plan crossover (EXPLAIN caught the first spelling as
  `Seq Scan … Rows Removed by Filter: 19760`); re-open events are typed rows
  that never touch a verdict (D-020 rail, held in code); verdict label changes
  become provenanced `verdict_flips` rows naming the doc that prompted the
  re-look. 3 zero-LLM routes with explicit analyst ack. Live-verified
  in-container against a genuinely KEV-listed CVE, which also exposed two
  long-standing packaging defects — `auspex.modes`/`auspex.retrohunt` absent from
  the installed distribution and EVERY `__init__.py` installed at 0 bytes since
  the Dockerfile was written, both masked by uvicorn's cwd shadowing
  site-packages. 643 tests; zero new env vars.)_
- [x] **S15 — Falsification watchers.** Verdicts register "what would flip me";
  watchers monitor feeds/enrichment for exactly that.
  _(D-021. Every verdict registers typed falsification conditions AT WRITE TIME
  in the same transaction — a closed enum of three kinds, derived in code from
  the observable/label/signals, never prose and never model-proposed. Each kind
  is owned by a checker and the partition is asserted, so a watcher nobody
  evaluates cannot be added. Ingest checks them through an indexed join per
  bounded chunk on a PARTIAL index (closed watchers accumulate forever and are
  never joined against — measured flat at 75k rows, 50k closed); enrichment
  checks escalation by SEVERITY, not inequality. A satisfied watcher never
  writes a verdict: it upgrades the S14 re-open event with the claim that
  stopped being true. Live-verified in-container end to end. Also fixed a
  circular import that resolved only by lucky import order. 676 tests; zero new
  env vars.)_
- [ ] **S16 — Verdict timeline UI.** Decay/staleness surfaces, flip history,
  "your past got re-scored" view.

## Phase 4 — Platform

- [ ] **S17 — Actions SDK contract.** `@action` decorator (semantics/scope/risk),
  **undo required for destructive**, dry_run required, registration API,
  planner manifest integration.
- [ ] **S18 — Approval flow.** Approval cards over SSE, atomic claim-first
  settlement, permission re-check at execute time.
- [ ] **S19 — Hardening.** Input guard (injection patterns + security-content
  carve-outs), rate limits, usage-based plan gating skeleton.
- [ ] **S20 — Beta.** Deploy pipeline, docs pass, demo script.

## Later / explicitly deferred
Herd Immunity federation (needs k≥3 workspaces + privacy review) · billing ·
i18n · admin console · Python SDK public packaging · KSA residency routing.
