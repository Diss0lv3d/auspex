# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/new-sara

---

SESSION S1 of Auspex. Working dir must be /home/burhan/new-sara — run the
CLAUDE.md session-start ritual first (read STATE.md, verify this is S1, check
git log). If anything mismatches, STOP and tell me.

Goal (scope-locked, from ROADMAP.md S1 — Scaffold):
1. FastAPI app factory (`auspex/app.py`, `server.py`), async throughout.
2. Config module: env-driven, every var in `.env.example` AND `docs/ENV_VARS.md`.
   Real values already exist in `.env` (gitignored) — own-container OpenSearch + dev LLM endpoint.
3. docker-compose: `app` + `postgres` + `opensearch` (opensearchproject/
   opensearch:2.19.4, single-node, 1g heap) services. `docker compose up` must
   serve `GET /api/health` (liveness) and `/api/health/ready` (checks Postgres
   AND our OpenSearch container) before the session ends. (D-009: never SARA's
   cluster.)
4. Postgres schema v0 via idempotent startup migration: workspaces, users,
   api_keys, chat_sessions, messages. `workspace_id` on EVERY table (D-008).
5. Auth: Google OAuth endpoint (config-stubbed is fine if no client ID yet),
   JWT session issuance, API keys stored as SHA-256 hash + prefix, single
   `resolve_user(request)` chokepoint.
6. Tooling: pytest (with at least health + auth + schema tests), ruff config,
   a `make check` or `./ci.sh` that runs lint + tests like CI will.
7. End with the CLAUDE.md session-end ritual: update STATE.md, rewrite
   NEXT-SESSION.md for S2 (LLM capability probe — see ROADMAP.md), tick
   ROADMAP.md, commit.

Constraints: no LLM calls this session; no OpenSearch index creation beyond the
ready-check ping; brand strings/palette from CLAUDE.md; no secrets in code.
