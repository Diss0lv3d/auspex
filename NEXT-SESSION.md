# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/new-sara

---

SESSION S2 of Auspex. Working dir must be /home/burhan/new-sara — run the
CLAUDE.md session-start ritual first (`/session-start S2`): read STATE.md, verify
this is S2, confirm branch is `staging`, confirm git identity is
bh3082336888-cell, run the reality check (`git log`, `docker compose up -d &&
docker compose ps`, `/api/health/ready` 200). Any mismatch → STOP and tell me.

⚠ This session de-risks the #1 project blocker (Llama-4-Scout tool-calling quality
is unproven). The go/no-go data you produce decides how hard the agent loop leans
on native ReACT vs prompted tools vs plan-only. Treat the numbers as the deliverable.

Goal (scope-locked, from ROADMAP.md S2 — LLM provider layer + capability probe):
1. OpenAI-compatible client (`auspex/llm/`): configured from LLM_BASE_URL + LLM_MODEL
   + LLM_API_KEY (already in config.py / .env). Support non-streaming and streaming
   `/v1/chat/completions`, including streaming tool-call deltas. Async (httpx).
2. **Probe FIRST, code against the snapshot (CLAUDE.md rule 4).** Use `/probe` to
   hit the live Northflank endpoint before writing client assumptions; save the raw
   reality snapshot to `docs/probes/YYYY-MM-DD-llm-endpoint.md`. No coding against a
   remembered API shape.
3. Capability probe battery against the live endpoint: native tool-calling? parallel
   tool calls? JSON mode / response_format? schema adherence? usable context window?
   tok/s? Produce a typed capability scorecard.
4. Persist the scorecard per endpoint in Postgres (new table, `workspace_id` on it —
   D-008; add to the idempotent migration). Save the raw harness run + summary to
   `docs/probes/`.
5. Harness: 30–50 scripted multi-step tool tasks against the Northflank endpoint;
   measure valid-call rate + loop-completion rate. Record results in the probe file.
6. Tests ship with the feature (CLAUDE.md rule 8): unit-test the client's
   request/response + streaming-delta parsing against SAVED fixtures from the probe
   (do NOT hit the network in pytest — CI must stay hermetic and offline). At least
   one migration/schema test for the new scorecard table.
7. End with the session-end ritual (`/session-end`): update STATE.md, rewrite
   NEXT-SESSION.md for S3 (Agent loop v1 + chat SSE — see ROADMAP.md), tick
   ROADMAP.md, log any shortcut in TECHNICAL_DEBT.md, commit on `staging`.

Constraints:
- Live LLM calls happen in the probe/harness ONLY; pytest stays offline (fixtures).
- Northflank endpoint is currently unauthenticated (D-006) — fine for testing; do
  not add secrets to code; keep placeholders in examples.
- No OpenSearch index creation this session (still S6).
- Brand: no model/provider name leaks into any user-visible string (CLAUDE.md).
- Reality over memory: every claim about the endpoint's behavior cites the probe file.
