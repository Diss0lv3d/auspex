# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(The D-013 Northflank validation run is DONE — 2026-07-16, Scout scored
native_tools; see STATE.md. No standing follow-ups remain.)_

---

SESSION S3 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S3` first (it does the full ritual, including the dev-LLM
gate: local Ollama + `qwen3:14b` per D-013). Any mismatch → STOP and tell me.

Goal (scope-locked, from ROADMAP.md S3 — Agent loop v1 + chat SSE).
**Must-ship core: steps 0–3 with their tests. Stretch: steps 4–5** (the
prompted-tools fallback inside step 1 may also be a stub if time is short).
Tests ship WITH each step, not as a trailing phase (CLAUDE.md rule 8).

0. **Unblock server→LLM networking FIRST** (known blocker, STATE.md #5):
   `host.docker.internal` host-gateway wiring in docker-compose.yml, then
   prove the app container can reach the host Ollama before building
   anything (one curl from inside the container).
1. **ReACT agent loop v1** (`auspex/agent/`): drive `LLMClient` in a tool-use
   loop. `load_latest_scorecard` already returns `(scorecard, mode)` — use
   that persisted mode, do NOT re-derive it via `decide_agent_mode` (thresholds
   may drift from what was ratified at probe time). Native tools primary;
   prompted `<tool_call>` fallback behind the same interface (stub OK).
   Ships with: loop unit tests against a FAKE client (no live LLM in pytest).
2. **Tool registry** with read/write/destructive levels — reuse the envelope
   builder `tool_spec()` (auspex/llm/client.py) for specs; SARA pattern
   reference: /home/burhan/sara-open/sara/core/permissions.py:65-176 (reuse
   the pattern, not the code). Ships with: registry level tests.
3. **Permission gate skeleton (D-014)**: write-actions create proposal records
   instead of executing; an action is "done" ONLY when its tool call actually
   executed — model-asserted completion text is never treated as execution.
   Ships with: proposals schema test + the D-014 pinned regression fixture
   (the exact fabricated "ticket created" answer from
   docs/probes/harness-run-llama3-1-8b.json, task C206).
4. _(stretch)_ **SSE chat endpoint** (`/api/chat`): single-key JSON event
   protocol with a `reasoning` event type (thinking models emit a separate
   `reasoning` field in stream deltas — see probe doc + client fixtures);
   auth via existing `resolve_user`; persist to chat_sessions/messages.
   Ships with: SSE endpoint test.
5. _(stretch)_ **Minimal UI shell** (dark-first, CLAUDE.md palette; the engine
   is never named in user-visible strings).
6. `/session-end` (it carries STATE.md standing follow-ups forward).

S2 design inputs (canonical: STATE.md "S3 design inputs" + the probe doc
docs/probes/2026-07-15-ollama-endpoint.md — the list below is a reminder,
not the source):
- Tool args carry observable IDs, never raw 64-char strings (all three
  models tested mangled long hashes — 8B, 14B, and Scout).
- Conversational turns get no tools; the loop API takes `tools=None` cleanly.
- Thinking models: budget ≥2000 tokens/turn (import PROBE_MAX_TOKENS), expect
  ~10× wall clock; content stays clean, reasoning rides its own field.
- Loop step cap: harness used `Task.max_steps = 8` (scripts/harness_tasks.py);
  pick the loop's cap consciously, not by copying.

Constraints:
- Dev endpoint is local Ollama + qwen3:14b (D-013); live LLM calls outside
  pytest only — CI stays hermetic on the saved fixtures.
- No OpenSearch index creation (S6). No enrichment providers (S5).
- Reality over memory: any new endpoint behavior → probe file first.
- New ideas → IDEAS.md, one line, move on.
