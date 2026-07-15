# STATE — Auspex

_Last updated: 2026-07-16 (S3 complete — agent runtime v1 + chat SSE + UI shell)_

## Where we are
- **S3 COMPLETE** (all steps 0–5 shipped with tests) → **next is S4**
  (Fast classifier / 92-8 split — see NEXT-SESSION.md).
- **Primary dev LLM (D-013):** local Ollama `http://localhost:11434`,
  model **`qwen3:14b`** (thinking model, native_tools). `llama3.1:8b` stays
  pulled as the "weak endpoint" case. Northflank (Llama-4-Scout) is
  backup/validation only.
- **CI-green: 79 tests** (was 47 at S2 end; +32 this session). `./ci.sh`
  passes: ruff clean, pytest, real container build + liveness.

## S3 shipped (all committed on staging, 2026-07-16)
- **Step 0 — server→LLM networking (repo half DONE):** docker-compose app
  service got `extra_hosts: host.docker.internal:host-gateway`; container uses
  `LLM_BASE_URL=http://host.docker.internal:11434`, host runs pin localhost via
  `auspex.devhost`. Probe `docs/probes/2026-07-16-server-to-ollama-networking.md`.
  **DONE end-to-end (2026-07-16):** host Ollama rebound to `*:11434`; the
  containerized app streams real `/api/chat` responses (Blocker #1 closed).
- **Step 2 — tool registry** (`auspex/agent/registry.py`): `ToolLevel`
  (read/write/destructive, StrEnum), `Tool` (builds its OpenAI envelope via the
  shared `tool_spec()`), `ToolRegistry`. 8 tests.
- **Step 3 — permission gate + proposals (D-014)** (`auspex/agent/permissions.py`
  + migration): `gate()` → READ auto-executes, WRITE/DESTRUCTIVE become
  `pending_approval` proposals, never executions (fail-safe on unknown level).
  `proposals` table (D-008 workspace_id; tool_level/status CHECKs). `ProposalStore`
  Protocol + `PgProposalStore`. Proposals schema CHECK tests + live-DB store
  round-trip + gate unit tests.
- **Step 1 — ReACT loop v1** (`auspex/agent/loop.py`): drives `LLMClient` in the
  **persisted scorecard mode** (caller passes mode; loop never re-derives it).
  Mode → `ToolChannel` (native / prompted `<tool_call>` / plan_only; unknown
  fails safe to plan_only). One step loop + gate + proposal path behind all
  three. Step cap (8, chosen consciously) → one tool-free synthesis pass.
  **D-014 enforced structurally**: action records come ONLY from real tool
  calls; fabricated "done" text mints nothing. 12 tests vs a FAKE client incl.
  the pinned C206 regression (verbatim llama3.1:8b fabricated-ticket output).
- **Step 4 (stretch) — SSE `/api/chat`** (`auspex/routes/chat.py`): single-key
  JSON event protocol (`session`/`reasoning`/`content`/`done`/`error`) over
  text/event-stream; auth via `resolve_user`; session workspace+user scoped;
  persists to chat_sessions/messages (reasoning ephemeral). Required a client
  change: `ChatResult.reasoning` now captured from message + stream deltas
  (fixture-backed). v1 conversational (tools=None). 4 hermetic tests.
- **Step 5 (stretch) — UI shell** (`auspex/routes/ui.py` + `auspex/static/
  index.html`): dark-first Auspex palette, dev sign-in, streaming chat parsing
  the SSE frames, reasoning in a dimmed "Thinking" pane. Engine never named
  (test-enforced). 2 smoke tests.
- **Build:** `auspex.agent` added to setuptools packages + `static/*.html`
  package-data; Dockerfile deps-layer skeleton extended. Container verified:
  `auspex.agent`/chat/ui import, `GET /` → 200, proposals table migrated.

**Live-verified (host-run, real qwen3:14b, not pytest):**
`docs/probes/2026-07-16-agent-loop-live-verification.md` — the loop drives
real native tool calls; read executes; **write is PROPOSED, not executed**
(`performed()==False`) — D-014 holds against a real model. SSE endpoint streams
`reasoning`→`content`→`done` correctly.

## In-flight / standing follow-ups (carry forward until DONE)
- Nothing. The Ollama host-bind follow-up is DONE (2026-07-16): Burhan restarted
  Ollama bound to `*:11434`; the container now reaches host Ollama and a real
  `/api/chat` streamed end-to-end through the containerized app (Blocker #1
  closed below).

## Blockers / open risks
1. **~~Container→Ollama host command~~ RESOLVED (2026-07-16).** Ollama now binds
   `*:11434`; `docker compose exec app` reaches `http://host.docker.internal:11434/v1/models`
   → 200 (all three models), and a real `POST /api/chat` against the
   *containerized* app streamed `session→reasoning(1597 chars)→content→done`
   from qwen3:14b. Step 0 goal fully met. Verification appended to
   `docs/probes/2026-07-16-server-to-ollama-networking.md`.
2. **Embeddings approach unmeasured** — probe in S6 (decided).
3. **TD-001 (OAuth identity keyed on email)** — before any GOOGLE_CLIENT_ID.
4. **SSE /api/chat is conversational-only (v1)** — the AgentLoop (tools) is NOT
   wired into it yet; and history replay is unbounded. Both parked in IDEAS.md.

## Host notes (reality snapshot)
- Postgres host port **55432**; app 8000; OpenSearch 9200. Host-run scripts
  and tests pin `DATABASE_URL`/`OPENSEARCH_URL`/`LLM_BASE_URL` to localhost
  before importing config (`auspex.devhost`).
- Ollama 0.24.0 (snap) on :11434 with `qwen3:14b` (dev), `llama3.1:8b`
  (weak-endpoint case), `mistral:latest` (unused). Binds 127.0.0.1 (Blocker #1).
  GPU: RTX 5070 Ti Laptop 12 GB.
- Host rebooted between sessions — `docker compose up -d` needed at start
  (session-start ritual covers this). The app image must be rebuilt on source
  changes (`docker compose up -d --build`) — `./ci.sh` does this.

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
Base: `/home/burhan/sara-open/` (paths re-verified 2026-07-15):
- ReACT loop: /home/burhan/sara-open/sara/core/agent_loop.py:60
  (reused as the S3 loop pattern; Auspex loop is `auspex/agent/loop.py`)
- Plan→DAG→Judge loop: nearest surviving copy is
  /home/burhan/sara-open/.claude/worktrees/1359-chain-surface/sara/core/orchestrator_loop/runner.py:39
  (worktrees get cleaned; re-snapshot to docs/probes/ before S8)
- Permission hard-rails: /home/burhan/sara-open/sara/core/permissions.py:65-176
  (reused as the S3 gate pattern; Auspex gate is `auspex/agent/permissions.py`)
- RRF retrieval + ID bypass: /home/burhan/sara-open/sara_retriever.py:538,599
- DEFERRED rail: /home/burhan/sara-open/sara/agents/alert_triage.py:1429
- Capability shape: /home/burhan/sara-open/sara/core/unified_registry.py:37

## Next session should
Run S4 exactly as written in NEXT-SESSION.md (Fast classifier / 92-8 split).
(The S3 Ollama-networking follow-up is closed — no standing carry-over.)
