# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(No standing follow-ups. S4 is complete on `staging` but NOT yet promoted —
`main` is current only through S3. S4 is a demoable milestone, so running
`/promote` first is reasonable.)_

---

SESSION S5 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S5` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch
→ STOP and tell me. Note: S5 is mostly LLM-free (provider clients + storage);
the LLM matters only for optional live checks of the deep path.

Goal (scope-locked, from ROADMAP.md S5 — Enrichment fan-out + verdict store):

1. **Provider clients** (direct HTTP, no LLM): AbuseIPDB, OTX, GreyNoise
   community, URLhaus, ThreatFox, Shodan InternetDB, CIRCL hashlookup.
   Free/no-key providers first (URLhaus, ThreatFox, InternetDB, hashlookup);
   key-gated ones activate only when their env var exists (every new env var →
   `.env.example` + `docs/ENV_VARS.md` the moment it's born). **Probe each
   provider live first** (`/probe` → docs/probes/) and code against the
   snapshot — reality over memory. Per-provider: which observable types it
   accepts (S4 `ObservableType` is the vocabulary), rate limits, error shapes.
2. **Fan-out orchestration**: submit-all/poll-all parallelism (asyncio.gather
   with per-provider timeout), per-provider circuit breaker (consecutive-
   failure threshold → open, half-open probe after cooldown). Failures degrade
   gracefully — partial results are results (DEFERRED rail, not errors).
3. **Storage**: `observables` table keyed by the S4 normalized value + obs_id;
   `verdicts` table **with decay-curve fields from day one** (first Living
   Verdicts brick — D-entry the field semantics: half_life, floor,
   confidence_at_write, source). D-008 workspace scoping on both tables.
4. **Wire into the S4 ioc_check shortcut**: extract → normalize → enrich →
   verdict echo (replaces the "enrichment deferred" copy when providers are
   configured; keeps the deferred copy when none are). The shortcut path may
   now touch *enrichment* network but still NO LLM — update the S4 tests that
   assert network-free to assert LLM-free + enrichment-mockable instead.

Design inputs / reality already in the repo (cite, don't re-derive):
- S4 classify package: `auspex/classify/` — `Observable.obs_id` (short id),
  `Observable.defanged` (verdict-floor input, parked in IDEAS.md), residual
  gates. The ioc_check handler to extend is `auspex/classify/shortcuts.py`
  (`shortcut_answer` is fallible: returning None falls through to deep).
- SSE protocol: single-key frames; `done` carries `path: shortcut|model`
  (`auspex/routes/chat.py`).
- SARA enrichment pattern notes: docs/probes/2026-07-16-sara-fastpath-pattern.md
  (+ IDEAS.md lines on common-domain skip-lists and private-IP filtering —
  implement both this session: never enrich private/reserved IPs, skip
  ubiquitous domains).
- Proposals/permissions rail exists (`auspex/agent/permissions.py`) — S5
  enrichment is READ-level, no gating needed.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI stays hermetic — provider
  clients tested against saved probe fixtures, never live, in pytest.
- No OpenSearch index creation (KB is S6). No new LLM calls on the shortcut path.
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
- New ideas → IDEAS.md, one line, move on.
- End with `/session-end`; S5 done = demoable enrichment → consider `/promote`.
