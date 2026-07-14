# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

⚠ **BEFORE PASTING — one-time human step (Blocker #1 in STATE.md):**
The Northflank LLM service was DOWN on 2026-07-14 (pod not listening; CLI
tokens on this host are expired). Restart it in the Northflank UI (or
`northflank login` fresh, then start the service), wait for vLLM to finish
loading, and confirm:

```bash
source <(grep -E '^LLM_' /home/burhan/auspex-new/.env | sed 's/^/export /')
curl -s -o /dev/null -w '%{http_code}\n' "$LLM_BASE_URL/v1/models"   # must print 200
```

If it prints 503, the model is still loading (or the service is still down) —
wait and retry before starting the session.

---

SESSION S2 (RESUME) of Auspex. Working dir must be /home/burhan/auspex-new —
run the CLAUDE.md session-start ritual first (`/session-start S2`): read
STATE.md, verify this is the S2 resume, confirm branch `staging`, git identity
bh3082336888-cell, reality check (`git log`, `docker compose up -d && docker
compose ps`, `/api/health/ready` 200). **Extra gate for this session:**
`curl "$LLM_BASE_URL/v1/models"` must return 200 — if it doesn't, STOP and
tell me to restart the Northflank service; do not start coding.

⚠ This session finishes de-risking the #1 project blocker (Llama-4-Scout
tool-calling quality). The go/no-go numbers are the deliverable.

Already DONE last session (S2 first half — do NOT redo; see STATE.md):
- `auspex/llm/scorecard.py`: typed CapabilityScorecard + decide_agent_mode
  (code-picks-the-mode) + save/load; `llm_endpoint_scorecards` table in the
  idempotent migration (workspace_id, agent_mode CHECK, jsonb, history).
- `scripts/harness_tasks.py`: 40-task deterministic battery + mock tools.
- Tests: 32 green (incl. 9 scorecard + schema CHECK test). CI lints scripts/.
- `docs/probes/2026-07-14-llm-endpoint.md`: Finding 0 — edge 503s are
  text/plain, NOT JSON; client must parse errors defensively.

Goal (scope-locked, ROADMAP S2 second half — strictly in this order):
1. **Probe FIRST (CLAUDE.md rule 4).** `/probe` the live endpoint: /v1/models,
   non-streaming + streaming chat, native tools, parallel tools, streaming
   tool-call deltas, tool-role round-trip, tool_choice named/required,
   response_format json_object + json_schema, error shapes (bad model,
   context overflow → reveals max context, missing fields), tok/s. Save raw
   responses verbatim to `tests/fixtures/llm/` AND complete the probe doc.
   A probe script draft exists from last session at the scratchpad path in
   git history — rewrite it fresh if gone (it crashed on non-JSON 503; keep
   the defensive parsing fix).
2. `auspex/llm/client.py` — async httpx OpenAI-compatible client coded against
   the snapshot: non-streaming + streaming `/v1/chat/completions`, streaming
   tool-call delta accumulation, defensive error parsing (Finding 0), bounded
   connect-time reachability retry. Config from LLM_BASE_URL/LLM_MODEL/
   LLM_API_KEY (already in config.py).
3. Capability battery (`auspex/llm/capability.py`): probe → fill
   CapabilityScorecard (native tools, parallel, tool_choice, streaming deltas,
   json modes, schema adherence, max context, tok/s).
4. Harness runner (`scripts/llm_harness.py`): run the 40-task battery through
   the client against the live endpoint; measure valid-call rate +
   loop-completion rate (per category too); write results into the probe doc,
   `save_scorecard` a row (workspace: get-or-create by name, e.g. 'dev'),
   and print the go/no-go verdict from decide_agent_mode.
5. Tests ship with the feature (rule 8): client request/response + streaming
   delta parsing unit tests against the SAVED fixtures — pytest stays offline.
6. Session-end ritual (`/session-end`): STATE.md, NEXT-SESSION.md → S3 (Agent
   loop v1 + chat SSE, per ROADMAP), tick ROADMAP S2, TECHNICAL_DEBT.md,
   commit on `staging`.

Constraints:
- Live LLM calls in probe/battery/harness ONLY; pytest hermetic (fixtures).
- Endpoint is keyless (D-006) — no secrets in code; placeholders in examples.
- No OpenSearch index creation (still S6).
- Brand: no model/provider name in any user-visible string (CLAUDE.md).
- Every claim about endpoint behavior cites the probe file.
- If the endpoint dies mid-session: save whatever fixtures were captured,
  update the probe doc status log, and fall back to fixture-driven work.
