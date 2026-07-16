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
- [ ] **S5 — Enrichment fan-out + verdict store.** Direct provider clients
  (AbuseIPDB, OTX, GreyNoise community, URLhaus, ThreatFox, Shodan InternetDB,
  CIRCL hashlookup), submit-all/poll-all parallelism, per-provider circuit
  breaker, `verdicts` table **with decay curve fields from day one**
  (first Living Verdicts brick), observables table keyed by normalized IOC.
- [ ] **S6 — KB/RAG on OpenSearch.** `auspex-knowledge` index design (mapping
  probe first), chunking, embeddings (probe own-container ML-plugin server-side; fallback
  in-process MiniLM), BM25 + kNN + client-side RRF, CVE/MITRE ID-query neural
  bypass, regime-aware score floors.
- [ ] **S7 — Ingestion 1.** NVD delta + CISA KEV + FIRST EPSS merged into one
  enriched doc per CVE; `ingest_state` table + startup catch-up scheduler.
- [ ] **S8 — Ingestion 2.** MITRE ATT&CK (lazy + cached), Sigma rules, abuse.ch
  quartet; auto-promotion to KB on miss.
- [ ] **S9 — Response modes.** 6 modes only (definition, ioc_enrichment,
  threat_intel, alert_triage, phishing_analysis, brief), code-owned priority
  resolver (format beats keywords), typed output contracts that compile to
  prompts + validators.

## Phase 2 — Analysis

- [ ] **S10 — Alert normalizer + risk score.** Multi-SIEM format detection →
  closed-vocab envelope; additive 0–100 score with itemized contributions;
  **DEFERRED rail** (no data ≠ low risk).
- [ ] **S11 — Phishing/header agent.** Deterministic SPF/DKIM/DMARC/typosquat/
  homograph checks injected as AUTHORITATIVE; LLM narrative on top; victim-domain
  IOC filtering.
- [ ] **S12 — Hypothesis engine v1 (ACH).** Competing hypotheses per
  investigation, per-evidence scoring against each hypothesis, next-lookup
  chosen by expected information gain.
- [ ] **S13 — Evidence graph + cited output.** Typed evidence objects; every
  generated claim carries a citation; output guard rejects uncited claims.

## Phase 3 — Living Verdicts (flagship)

- [ ] **S14 — Retro-hunt.** On-ingest sweep of historical observables (indexed
  join, never scan), re-open notifications, verdict flip events.
- [ ] **S15 — Falsification watchers.** Verdicts register "what would flip me";
  watchers monitor feeds/enrichment for exactly that.
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
