# STATE — Auspex

_Last updated: 2026-07-14 (S1 — Scaffold, complete)_

## Where we are
- **Current session: S1 complete → next is S2** (see NEXT-SESSION.md).
- The application scaffold exists, runs under docker-compose, and is CI-green.
  `docker compose up` serves `/api/health` (liveness) and `/api/health/ready`
  (checks Postgres AND our own OpenSearch container). Verified end-to-end.
- FastAPI app factory (`auspex/app.py`, `server.py`), async throughout; state on
  `app.state`, pool + idempotent migration run in the lifespan.
- Config: env-driven (`auspex/config.py`); every var in `.env.example` +
  `docs/ENV_VARS.md`. `.env` gitignored, SECRET_KEY generated locally.
- Postgres schema v0 (idempotent startup migration, advisory-locked):
  workspaces, users, api_keys, chat_sessions, messages — `workspace_id` on every
  table (D-008), enforced by a schema test. `workspaces.name` is UNIQUE.
- Auth: single `resolve_user` chokepoint (JWT or `X-API-Key`); JWT issuance via
  Google OAuth callback (config-stubbed → 503 until a client ID exists) and a
  dev-login endpoint (dev-only). API keys stored as SHA-256 hash + prefix; raw
  key shown once. Key creation requires a JWT session (a key can't mint keys).
- Tooling: pytest (23 tests: health incl. degraded-503, auth, schema), ruff
  (E/F/W/I/UP/B/ASYNC/S), `./ci.sh` = lint + tests + real container liveness
  build; `make check`.
- **S1 adversarial review done** (4 dimensions × 2 skeptics, 38 agents): 17
  confirmed findings. 12 fixed this session (see git); 2 deferred with records
  (IDEAS.md: API-key mgmt endpoints; TECHNICAL_DEBT.md TD-001: OAuth sub-binding,
  hard-gated before any GOOGLE_CLIENT_ID). Remaining were duplicates of these.

## In-flight
- Nothing. Clean end-state.

## Blockers / open risks
1. **Llama-4-Scout tool-calling quality unproven** — the existential risk.
   S2's harness answers it. Until then, don't build anything that assumes
   reliable multi-step native tool calls.
2. **Embeddings approach unmeasured** — own OpenSearch container (D-009) makes
   server-side ML possible but heavy for a dev box; probe in S6, fallback
   in-process MiniLM (decided, not a blocker).
3. **Northflank endpoint unauthenticated** (D-006, accepted for testing).
4. **TD-001 (OAuth identity keyed on email)** — must be fixed before any
   `GOOGLE_CLIENT_ID` is configured. Not reachable today (OAuth 503-stubbed).
5. **One-time manual step pending**: `gh auth login` for the personal account
   (bh3082336888-cell, SSH + ~/.ssh/personal_git) — needed before the first
   `gh pr create` / `/promote` against a remote. There is no remote yet.

## Host notes (reality snapshot)
- Host port 5432 is taken by other stacks, so compose maps Postgres to **55432**
  on the host (`postgresql://auspex:auspex@localhost:55432/auspex`); inside the
  compose network it's `postgres:5432`. App 8000, OpenSearch 9200.
- Tests run from the host against 55432 / 9200 (conftest pins these before import,
  because `.env` uses compose-internal hostnames that don't resolve from the host).

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
Run S2 exactly as written in NEXT-SESSION.md (LLM provider layer + capability
probe — de-risks the #1 blocker).
