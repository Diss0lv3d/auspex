# STATE — Auspex

_Last updated: 2026-07-16 (S5 complete — enrichment fan-out + verdict store, live-verified)_

## Where we are
- **S5 COMPLETE** (all 4 steps + 2 live-caught fixes, tests shipping with each)
  → **next is S6** (KB/RAG on OpenSearch — see NEXT-SESSION.md).
- **Promoted:** promote #4 (S4) is on `main`. **S5 is on `staging` only — NOT
  yet promoted.** S5 is a demoable milestone, but hold `/promote` until the
  multi-agent adversarial review re-runs (see In-flight; it was quota-blocked
  this session — an inline single-reviewer pass found nothing blocking).
- **Primary dev LLM (D-015):** Llama-4-Scout via Northflank; secondary/offline
  Ollama `qwen3:14b` (D-013). S5 touched no LLM paths (enrichment is LLM-free
  by design, test-enforced).
- **CI-green: 237 tests** (was 177 at S4 end; +60 this session). `./ci.sh`
  passes end-to-end: ruff, pytest, container build + health + ready.

## S5 shipped (all committed on staging, 2026-07-16)
- **Probes first (rule 4):** docs/probes/2026-07-16-enrichment-providers.md —
  all 7 providers hit live. Headline reality-vs-plan mismatches: **abuse.ch
  (URLhaus+ThreatFox) is Auth-Key-gated now** (keyless = 401; one free
  auth.abuse.ch key covers both); **OTX works keyless** (key optional);
  GreyNoise keyless = 25 req/WEEK (useless → key-gated); OTX `pulse_info.count`
  is poisoned for famous domains (whitelist `validation[]` must veto);
  hashlookup is a known-GOOD-file DB (hit = weak benign, miss = nothing).
- **`auspex/enrich/` package:** 7 probe-pinned provider clients (always-on
  keyless: InternetDB ipv4/ipv6, CIRCL hashlookup md5/sha1/sha256, OTX
  ipv4/ipv6/domain/url/hashes; key-gated: URLhaus, ThreatFox, AbuseIPDB,
  GreyNoise). Per-(provider,observable) asyncio fan-out, 6 s per-call timeout,
  per-provider circuit breaker (3 strikes → open, half-open probe after 60 s,
  state persists across turns on app.state). Failures degrade to an honest
  trailer (DEFERRED rail); "partial" marker when a provider failed one lookup
  but answered another. Skip filters: private/reserved IPs (`is_global`) and
  ubiquitous domains (even defanged) never enriched; per-turn cap 8
  observables, capped tail echoed, never silent.
- **Storage (D-008 scoped):** `observables` upsert-keyed (workspace, type,
  value) + obs_id index; `verdicts` APPEND-ONLY with decay fields from day one
  — **D-017 ratifies the semantics** (formula executable + test-pinned in
  `auspex/enrich/verdict.py::effective_confidence`; half-lives IP 14 d /
  domain 30 d / hash 365 d; decay never flips labels; v1 combining =
  worst-label-wins).
- **Chat wiring:** ioc_check shortcut now runs extract → skip-filter → fan-out
  → verdict echo → persist, still ZERO LLM (test: enrichment runs, fake LLM
  never called). No providers/disabled ⇒ the honest S4 "deferred" copy stands.
  Host pytest pins `ENRICHMENT_ENABLED=false` (hermetic; enrichment mockable
  at `app.state.enrichment`); container default is on.
- **Live-verified in-container** (docs/probes/2026-07-16-s5-enrichment-live.md):
  defanged Tor exit → real InternetDB context; WannaCry SHA-256 → "suspicious
  0.70 — 50 threat pulses · linked adversary: Lazarus Group"; private IP
  skipped honestly; verdict rows in Postgres with correct decay fields.
- **Two real bugs caught BY the live verify, fixed + pinned as regressions:**
  (1) OTX `validation[source=tor_exits]` would have whitelisted a Tor exit —
  benign veto now restricted to whitelist/false_positive/majestic/akamai
  (fixture `OTX_TOR_EXIT`); (2) trailer said "OTX unavailable" beside an OTX
  signal (per-call fan-out) → "partial — timed out" marker.
- **Measured quirk:** OTX takes 14–16.6 s on pulse-heavy indicators (limit
  param ignored). Kept the 6 s cap: fast path must not stall; misses are
  reported honestly; keyed curated feeds cover exactly those cases (TD-004).

## In-flight / standing follow-ups (carry forward until DONE)
1. **Re-run the S5 multi-agent adversarial review, then `/promote`.** The
   5-lens review workflow died at launch — ALL agents hit the account session
   limit (reset 8:20 pm Asia/Karachi, 2026-07-16). An inline single-reviewer
   pass over the full diff (correctness/security/contract/tests/honesty)
   found nothing blocking, but the S4 precedent is review-then-promote, so
   S5 promote waits for the real pass. Script is reusable:
   `.claude/.../workflows/scripts/s5-adversarial-review-wf_f4b4c4e5-0b2.js`
   (or just re-ask for a fresh 5-lens review of `git diff 67c4a76..HEAD`).
2. **TD-004 — register free API keys, then re-probe:** auth.abuse.ch key
   (unlocks URLhaus + ThreatFox — their happy-path parsers are docs-coded,
   unverified live) and abuseipdb.com key. Human step; after keys exist,
   `/probe` the happy paths and pin real fixtures.

## Blockers / open risks
1. **Embeddings approach unmeasured** — probe in S6 (decided).
2. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
3. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat; history replay unbounded; shortcut answers replayed into
   deep-turn history. Parked in IDEAS.md; modes land S9.
4. **Keyless verdicts cap at "suspicious"** — asserting MALICIOUS needs the
   curated feeds (ThreatFox/URLhaus), which need keys (TD-004). Honest but
   weaker demo until then.

## Host notes (reality snapshot)
- Postgres host port **55432**; app 8000; OpenSearch 9200. Host runs pin via
  `auspex.devhost` (DB/OpenSearch/APP_ENV + **ENRICHMENT_ENABLED=false** new
  in S5 — override in shell for host-run live enrichment checks).
- Ollama 0.24.0 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- Host reboots between sessions — `docker compose up -d --wait` at start.
- Claude-side note: the account session usage limit can kill subagent fan-outs
  mid-session (it did today at ~19:20 PKT); the main loop keeps working.

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
Base: `/home/burhan/sara-open/` (paths re-verified 2026-07-15):
- ReACT loop: /home/burhan/sara-open/sara/core/agent_loop.py:60
- Plan→DAG→Judge loop: /home/burhan/sara-open/.claude/worktrees/1359-chain-surface/sara/core/orchestrator_loop/runner.py:39
  (worktrees get cleaned; re-snapshot to docs/probes/ before S8)
- Permission hard-rails: /home/burhan/sara-open/sara/core/permissions.py:65-176
- Fast classifier / 92-8: docs/probes/2026-07-16-sara-fastpath-pattern.md
- Enrichment/fan-out pattern: reused in S5 (probe doc above supersedes the
  SARA notes for provider truth)
- RRF retrieval + ID bypass: /home/burhan/sara-open/sara_retriever.py:538,599
  (S6 pattern source — snapshot before use, rule 4)
- DEFERRED rail: /home/burhan/sara-open/sara/agents/alert_triage.py:1429
- Capability shape: /home/burhan/sara-open/sara/core/unified_registry.py:37

## Next session should
Start with the carried follow-up: re-run the adversarial review of the S5
diff, fix anything confirmed, then `/promote` S5. Then run S6 exactly as
written in NEXT-SESSION.md (KB/RAG on OpenSearch).
