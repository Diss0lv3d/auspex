# STATE — Auspex

_Last updated: 2026-07-14 (S2 — attempted, blocked on dead LLM endpoint; offline half shipped)_

## Where we are
- **Current session: S2 partially done → next session RESUMES S2** (see
  NEXT-SESSION.md). The live-endpoint half is blocked (see Blockers #1).
- S2 shipped (offline, all CI-green):
  - **Typed capability scorecard** (`auspex/llm/scorecard.py`):
    `CapabilityScorecard` (pydantic), `decide_agent_mode()` — code picks
    native_tools / prompted_tools / plan_only from measured rates; thresholds
    are module constants, not prompts. `endpoint_fingerprint()` =
    sha256(base_url|model), never the API key.
  - **Postgres persistence**: `llm_endpoint_scorecards` table in the idempotent
    migration (workspace_id + FK, agent_mode CHECK, jsonb scorecard, probed_at
    history), `save_scorecard`/`load_latest_scorecard`. Schema test enforces the
    CHECK; D-008 test still passes (table carries workspace_id).
  - **Harness task battery** (`scripts/harness_tasks.py`): 40 deterministic
    multi-step SOC tasks (8 single / 10 chain2 / 10 chain3 / 6 parallel /
    4 no-tool restraint / 2 enum stress) + mock tool executors (documentation-
    range IPs only). Runner NOT written yet (gated on client).
  - Tests: 32 total (23 from S1 + 9 scorecard). `scripts/` added to CI lint.
  - Probe doc started: `docs/probes/2026-07-14-llm-endpoint.md` — Finding 0:
    Northflank edge returns **503 text/plain (non-JSON)** when the pod is down;
    client must parse errors defensively.
- NEXT-SESSION.md's stale path (`/home/burhan/new-sara`) fixed → `auspex-new`.

## In-flight (gated, do NOT redo the done parts)
- S2 live half, strictly in this order once the endpoint is up:
  1. `/probe` battery against live endpoint → complete the probe doc + save raw
     responses to `tests/fixtures/llm/` (they become pytest fixtures).
  2. `auspex/llm/client.py` coded against the snapshot (async httpx,
     non-streaming + streaming + tool-call delta accumulation).
  3. Offline client tests from the saved fixtures (pytest stays hermetic).
  4. Harness runner (`scripts/llm_harness.py`) using the client + the 40-task
     battery → valid-call rate + loop-completion rate → `save_scorecard` row
     + results into the probe doc. **These numbers are the S2 deliverable.**

## Blockers / open risks
1. **🔴 Northflank LLM endpoint is DOWN** (2026-07-14 22:24–22:47+, probed
   continuously): istio-envoy 503 "connection refused" on every path — pod not
   listening; NOT a cold start (23 min of polling, would have woken). Can't be
   fixed from this host: personal Northflank CLI context has no projects; all
   three team-context tokens expired (401). **Human step: restart the service
   in the Northflank UI (or `northflank login` fresh), then verify
   `curl -s -o /dev/null -w '%{http_code}' "$LLM_BASE_URL/v1/models"` → 200
   before pasting the next session prompt.**
2. **Llama-4-Scout tool-calling quality still unproven** — the existential
   risk. S2's harness answers it; blocked behind #1.
3. **Embeddings approach unmeasured** — probe in S6 (decided, not a blocker).
4. **Northflank endpoint unauthenticated** (D-006, accepted for testing).
5. **TD-001 (OAuth identity keyed on email)** — must fix before any
   GOOGLE_CLIENT_ID is configured. Not reachable today.
6. **One-time manual step pending**: `gh auth login` for bh3082336888-cell —
   needed before first `/promote` against a remote. No remote yet.

## Host notes (reality snapshot)
- Postgres on host port **55432** (5432 taken); in-network `postgres:5432`.
  App 8000, OpenSearch 9200. Tests run from host against 55432/9200
  (conftest pins these before import).
- Northflank CLI v0.10.12 installed; only `main-context` authenticates (empty).

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
Distilled patterns-to-reuse/avoid live in ROADMAP.md session descriptions.
Key file references if we ever re-check a pattern:
- ReACT loop: sara-open-copy/sara/core/agent_loop.py:60
- Plan→DAG→Judge loop: sara-open-copy/sara/core/orchestrator_loop/runner.py:39
- Permission hard-rails: sara-open-copy/sara/core/permissions.py:65-176
- RRF retrieval + ID bypass: sara-open-copy/sara_retriever.py:538,599
- DEFERRED rail: sara-open-copy/sara/agents/alert_triage.py:1429
- Capability shape: sara-open-copy/sara/core/unified_registry.py:37

## Next session should
Resume S2 exactly as written in NEXT-SESSION.md — but ONLY after the human has
restarted the Northflank service and the readiness curl returns 200.
