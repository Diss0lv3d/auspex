---
description: Run the CLAUDE.md session-start ritual (wrong-window guard + reality check)
argument-hint: [expected session number, e.g. S4]
---

Run the session-start ritual from CLAUDE.md, strictly:

1. Verify `pwd` is the Auspex repo (this repo). Wrong dir → STOP: "wrong window".
2. Read `STATE.md` and `NEXT-SESSION.md`. If the human supplied a session number
   ($ARGUMENTS), it must match NEXT-SESSION.md's — mismatch → STOP and say
   "wrong window / wrong session, expected S<N>". Do not improvise a session.
3. Verify we're on `staging` (D-010). On main or detached → switch to staging
   and say so.
3b. Identity guard (D-011 — personal project): `git config user.email` must be
   `bh3082336888-cell@users.noreply.github.com` (fix with the local git config
   if not), and if `gh` will be used this session, `gh auth status` must show
   the ACTIVE account as `bh3082336888-cell` — otherwise run
   `gh auth switch --user bh3082336888-cell` (if that account isn't logged in
   yet, tell the human to run `gh auth login` once, choosing SSH +
   `~/.ssh/personal_git`). Never let work identity (SIRP-Burhan / burhan@sirp.io)
   author commits or API calls in this repo.
4. Reality check: `git log --oneline -5`, `git status`, and (once compose
   exists) `docker compose up -d && docker compose ps` + `/api/health/ready`
   (readiness — checks Postgres AND OpenSearch, stricter than liveness).
   Divergence from STATE.md → fix STATE.md first, report the divergence.
4b. Dev-LLM gate (D-013 — the endpoint is load-bearing from S3 on):
   `curl -s localhost:11434/api/version` must answer, and
   `curl -s localhost:11434/api/tags` must list the dev model that STATE.md
   declares (currently `qwen3:14b`; read it from STATE.md, don't trust this
   file). Down or model missing → STOP and tell the human (Ollama service /
   `ollama pull`) unless NEXT-SESSION.md says the session needs no LLM.
5. Restate the session goal from NEXT-SESSION.md in 2–3 lines and the
   scope-lock rule (new ideas → IDEAS.md), then begin the session's work.
