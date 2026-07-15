# STATE — Auspex

_Last updated: 2026-07-15 (S2 complete against interim endpoint; next is S3)_

## Where we are
- **S2 COMPLETE** (against the D-012 interim endpoint) → **next is S3**
  (Agent loop v1 + chat SSE, see NEXT-SESSION.md).
- **Primary dev LLM (D-013):** local Ollama `http://localhost:11434`,
  model **`qwen3:14b`** (thinking model, native_tools verdict). `llama3.1:8b`
  stays pulled as the "weak endpoint" test case. **Northflank (Llama-4-Scout)
  is now BACKUP/validation only** — values in `.env.bak-northflank`
  (gitignored); Burhan will signal when it's back; its harness run validates,
  no longer gates.
- **S2 shipped, all CI-green (46 tests):**
  - `auspex/llm/client.py` — async httpx OpenAI-compat client coded against
    the 2026-07-15 probe snapshot: non-streaming + streaming, tool-call delta
    accumulation BY INDEX (handles Ollama complete-per-chunk AND vLLM
    fragmented styles), include_usage chunk, `[DONE]`, defensive error parsing
    (Finding 0: bodies may be text/plain), `check_reachable()`.
  - `auspex/llm/capability.py` — connect-time battery (~15 requests) filling
    the typed CapabilityScorecard; endpoint-agnostic (OpenAI surface only).
  - `auspex/llm/scorecard.py` — CapabilityScorecard + decide_agent_mode
    (code picks native_tools/prompted_tools/plan_only) + Postgres save/load
    (`llm_endpoint_scorecards`, per-endpoint fingerprint, D-008 workspace_id).
  - `scripts/llm_harness.py` + `scripts/harness_tasks.py` — 40-task live
    harness; measures valid-call + loop-completion; writes raw run JSON +
    scorecard row.
  - Tests: 11 client fixture tests (offline, from live-captured fixtures in
    `tests/fixtures/llm/ollama/`) + 9 scorecard + schema tests.
- **The S2 numbers (both models, identical 40-task harness, 2026-07-15):**
  | | llama3.1:8b | qwen3:14b |
  |---|---|---|
  | valid-call | 98.7 % | **100 %** |
  | loop-completion | 52.5 % | **87.5 %** |
  | no-tool restraint | 0/4 | 4/4 |
  | fabricated actions | 3 | 0 |
  | mode | prompted_tools | **native_tools** |
  Full taxonomy + comparison in `docs/probes/2026-07-15-ollama-endpoint.md`.
  Scorecard rows in workspace `dev`: `f86da0f3-…` (8B), `37b4b02e-…` (14B;
  earlier `604a72b0-…` superseded — pre-fix battery false-negatives).
  **Thinking-model lessons encoded in code:** harness + battery need
  ≥2000-token budgets; `reasoning` field (separate from content) captured in
  fixtures + parser tests.
- **S3 design inputs from the harness (cite the probe doc):**
  1. Pass observable IDs, not raw 64-char strings, in tool args — fails at
     BOTH model sizes.
  2. Don't offer tools on conversational turns (92/8 fast path) — critical
     for weak endpoints (8B: 0/4 restraint; 14B: 4/4).
  3. Hard-gate writes on ACTUAL tool calls — **ratified as D-014** (8B
     fabricated "ticket created" claims; pinned fixture ships with the S3
     gate code).
  4. Thinking models: stream the `reasoning` field to the UI, budget
     ≥2000 tokens/turn, expect ~10× wall clock (943 s vs 88 s per 40 tasks).
  5. Mode-ladder refinement idea parked in IDEAS.md (syntax vs competence).
- Remote: `origin = git@github-personal:bh3082336888-cell/auspex.git`;
  main promoted through PR #1. **Never use plain `github.com` for this repo**
  (work SSH key). Default branch `main`.

## In-flight
- Nothing mid-code. One standing follow-up (NOT blocking, D-013): when Burhan
  signals Northflank is back, run
  `.venv/bin/python scripts/llm_harness.py` against it (LLM values in
  `.env.bak-northflank`) → Scout scorecard row + probe-doc note. Validation
  of the capability-negotiated runtime on a second real endpoint.

## Blockers / open risks
1. **~~Llama-4-Scout quality unproven~~ RESOLVED BY D-013** — the #1
   existential risk is closed: we build against qwen3:14b (native_tools,
   87.5 % completion, measured). Scout becomes a validation data point.
2. **Northflank endpoint still down** — backup only now. Human step when
   convenient: restart in Northflank UI or fresh `northflank login`.
3. **Embeddings approach unmeasured** — probe in S6 (decided).
4. **TD-001 (OAuth identity keyed on email)** — before any GOOGLE_CLIENT_ID.
5. Compose app can't reach `localhost:11434` (host Ollama) from inside the
   container — needs `host.docker.internal` host-gateway wiring when the APP
   starts calling the LLM (S3, first time the loop runs server-side).

## Host notes (reality snapshot)
- Postgres host port **55432**; app 8000; OpenSearch 9200. Host-run scripts
  and tests pin `DATABASE_URL` to localhost:55432 before importing config.
- Ollama 0.24.0 (snap) on :11434 with `qwen3:14b` (dev model, D-013) +
  `llama3.1:8b` (weak-endpoint test case) + `mistral:latest` (unused).
  GPU: RTX 5070 Ti Laptop 12 GB.
- Host rebooted between sessions — `docker compose up -d` needed at start
  (session-start ritual already covers this).

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
Patterns-to-reuse/avoid live in ROADMAP.md session descriptions. Key refs
(base: `/home/burhan/sara-open/` — the old `sara-open-copy/` is gone; all
paths below re-verified 2026-07-15):
- ReACT loop: /home/burhan/sara-open/sara/core/agent_loop.py:60
- Plan→DAG→Judge loop: main tree lost it — nearest surviving copy is
  /home/burhan/sara-open/.claude/worktrees/1359-chain-surface/sara/core/orchestrator_loop/runner.py:39
  (worktrees get cleaned; re-snapshot the pattern to docs/probes/ before S8)
- Permission hard-rails: /home/burhan/sara-open/sara/core/permissions.py:65-176
- RRF retrieval + ID bypass: /home/burhan/sara-open/sara_retriever.py:538,599
- DEFERRED rail: /home/burhan/sara-open/sara/agents/alert_triage.py:1429
- Capability shape: /home/burhan/sara-open/sara/core/unified_registry.py:37

## Next session should
Run S3 exactly as written in NEXT-SESSION.md (Agent loop v1 + chat SSE),
optionally preceded by the Northflank re-run if the endpoint is back.
