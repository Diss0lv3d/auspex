# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_Optional pre-step (any time the Northflank service is restarted): swap `.env`
LLM values back from `.env.bak-northflank`, verify `curl "$LLM_BASE_URL/v1/models"`
→ 200, run `.venv/bin/python scripts/llm_harness.py`, and paste the summary into
docs/probes/ — that's the owed Scout go/no-go data. Then swap `.env` back to
Ollama if the session continues locally._

---

SESSION S3 of Auspex. Working dir must be /home/burhan/auspex-new — run the
CLAUDE.md session-start ritual first (`/session-start S3`): read STATE.md,
verify this is S3, confirm branch `staging`, git identity bh3082336888-cell,
reality check (`git log`, `docker compose up -d && docker compose ps`,
`/api/health/ready` 200, and `curl -s localhost:11434/api/version` — local
Ollama is the dev LLM per D-012; model is **qwen3:14b**, a THINKING model:
native_tools verdict, 87.5 % loop completion, ~33 tok/s). Any mismatch →
STOP and tell me.

Goal (scope-locked, from ROADMAP.md S3 — Agent loop v1 + chat SSE):
1. **ReACT agent loop v1** (`auspex/agent/`): drive `LLMClient` in a
   tool-use loop. Native tools primary; the mode comes from the persisted
   scorecard (`load_latest_scorecard` → decide_agent_mode), NEVER hardcoded.
   Prompted `<tool_call>` fallback can be a stub this session if time is short
   (scorecard abstraction must allow it).
2. **Tool registry** with read/write/destructive levels (SARA pattern,
   permissions.py:65-176 as reference — reuse the *pattern*, not the code).
   Destructive always gates; write requires approval-pending records.
3. **Permission gate skeleton**: proposals table (approve/deny later),
   write-actions create proposals instead of executing (S2 harness finding 3:
   the model FABRICATES "ticket created" claims — never trust model text,
   gate on actual tool-call execution results).
4. **SSE chat endpoint** (`/api/chat`): single-key JSON event protocol,
   stream agent progress (content deltas, tool events) to the client.
   Auth via existing resolve_user chokepoint; session + messages persisted
   (tables exist since S1).
5. **Minimal functional UI shell** (dark-first, brand palette from CLAUDE.md,
   no provider/model names anywhere user-visible).
6. Tests ship with the feature: loop unit tests against a FAKE client
   (fixtures/replay — no live LLM in pytest), registry level tests,
   SSE endpoint test, proposals schema test.
7. Session-end ritual (`/session-end`).

S2 findings that MUST shape this session (docs/probes/2026-07-15-ollama-endpoint.md):
- Tool args: pass observable IDs, never raw 64-char strings (fails at BOTH
  model sizes tested).
- Conversational turns get NO tools (92/8 split is S4, but the loop API should
  accept tools=None cleanly now). Weak endpoints have zero restraint.
- Writes gate on ACTUAL tool execution, never model claims (8B fabricated
  "ticket created" — SOAR-critical).
- Thinking models: `reasoning` arrives as a separate field in stream deltas —
  design the SSE event protocol with a reasoning event type; budget ≥2000
  tokens/turn; expect ~10× wall clock vs non-thinking.
- Loop cap + step budget (harness used max 8; pick from scorecard data).
- Compose app → host Ollama needs `host.docker.internal` host-gateway wiring
  in docker-compose.yml (STATE.md blocker 5) — first session where the SERVER
  calls the LLM.

Constraints:
- Live LLM calls: dev endpoint is local Ollama (D-012). pytest stays offline.
- No OpenSearch index creation (S6). No enrichment providers (S5).
- Brand: engine is unnamed in user-visible strings (CLAUDE.md).
- Reality over memory: any new endpoint behavior → probe file first.
- New ideas → IDEAS.md, one line, move on.
