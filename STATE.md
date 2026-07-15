# STATE — Auspex

_Last updated: 2026-07-15 (S2 complete against interim endpoint; next is S3)_

## Where we are
- **S2 COMPLETE** (against the D-012 interim endpoint) → **next is S3**
  (Agent loop v1 + chat SSE, see NEXT-SESSION.md).
- **Interim dev LLM (D-012):** local Ollama `http://localhost:11434`,
  `llama3.1:8b` (131k ctx, tools-capable), keyless, GPU-local (~61 tok/s).
  `.env` switched; Northflank values preserved in `.env.bak-northflank`
  (gitignored). Northflank vLLM still down — Scout numbers still owed.
- **S2 shipped, all CI-green (43 tests):**
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
- **The S2 numbers (llama3.1:8b, full run 2026-07-15):**
  valid-call **98.7 %** (75/76) · loop-completion **52.5 %** (21/40) ·
  per-cat: single 75 / chain2 30 / chain3 70 / parallel 50 / **no-tool 0** /
  enum 100 · **mode → `prompted_tools`**. Failure taxonomy in
  `docs/probes/2026-07-15-ollama-endpoint.md` (long-string truncation in args,
  zero no-tool restraint, fabricated actions, evidence-threading errors;
  verdict robust to grading noise). Scorecard row
  `f86da0f3-…` in workspace `dev`.
- **S3 design inputs from the harness (cite the probe doc):**
  1. Pass observable IDs, not raw 64-char strings, in tool args.
  2. Don't offer tools on conversational turns (92/8 fast path).
  3. Hard-gate writes on ACTUAL tool calls — the model fabricates
     "ticket created" claims (SOAR-critical).
  4. Mode-ladder refinement idea parked in IDEAS.md (syntax vs competence).
- Remote: `origin = git@github-personal:bh3082336888-cell/auspex.git`;
  main promoted through PR #1. **Never use plain `github.com` for this repo**
  (work SSH key). Default branch `main`.

## In-flight
- Nothing mid-code. One standing follow-up: **when Northflank returns**, run
  `.venv/bin/python scripts/llm_harness.py` against it (swap `.env` back from
  `.env.bak-northflank`) → Scout scorecard row + probe-doc update. That is the
  decisive go/no-go data; the 8B numbers are the floor, not the answer.

## Blockers / open risks
1. **Northflank endpoint still down** (2026-07-14 probe). Human step: restart
   in Northflank UI or fresh `northflank login` (host CLI tokens expired).
   Not blocking S3 (interim endpoint works).
2. **Llama-4-Scout tool-calling quality still unproven** — 8B same-family
   data: near-perfect call syntax, weak multi-step competence. S3 builds the
   loop against the scorecard abstraction so the answer slots in.
3. **Embeddings approach unmeasured** — probe in S6 (decided).
4. **TD-001 (OAuth identity keyed on email)** — before any GOOGLE_CLIENT_ID.
5. Compose app can't reach `localhost:11434` (host Ollama) from inside the
   container — needs `host.docker.internal` host-gateway wiring when the APP
   starts calling the LLM (S3, first time the loop runs server-side).

## Host notes (reality snapshot)
- Postgres host port **55432**; app 8000; OpenSearch 9200. Host-run scripts
  and tests pin `DATABASE_URL` to localhost:55432 before importing config.
- Ollama 0.24.0 (snap) on :11434 with `llama3.1:8b` + `mistral:latest`.
  GPU: RTX 5070 Ti Laptop 12 GB.
- Host rebooted between sessions — `docker compose up -d` needed at start
  (session-start ritual already covers this).

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
Patterns-to-reuse/avoid live in ROADMAP.md session descriptions. Key refs:
- ReACT loop: sara-open-copy/sara/core/agent_loop.py:60
- Plan→DAG→Judge loop: sara-open-copy/sara/core/orchestrator_loop/runner.py:39
- Permission hard-rails: sara-open-copy/sara/core/permissions.py:65-176
- RRF retrieval + ID bypass: sara-open-copy/sara_retriever.py:538,599
- DEFERRED rail: sara-open-copy/sara/agents/alert_triage.py:1429
- Capability shape: sara-open-copy/sara/core/unified_registry.py:37

## Next session should
Run S3 exactly as written in NEXT-SESSION.md (Agent loop v1 + chat SSE),
optionally preceded by the Northflank re-run if the endpoint is back.
