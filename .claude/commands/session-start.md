---
description: Run the CLAUDE.md session-start ritual for one track (wrong-window guard + reality check)
argument-hint: "[be|fe|bugs] [session id, e.g. F1] — no track: asks which"
---

Run the session-start ritual from CLAUDE.md, strictly. Arguments: `$ARGUMENTS`

0. **Pick the track (D-051).** Sessions run in three tracks, each with its own
   prompt file and its own session numbers:

   | Track | Words accepted | Prompt file | Session ids |
   |---|---|---|---|
   | backend | `be`, `backend` | `NEXT-SESSION-BE.md` | `S<n>` |
   | front end | `fe`, `frontend`, `front-end` | `NEXT-SESSION-FE.md` | `F<n>` |
   | bugs | `bugs`, `bug` | `NEXT-SESSION-BUGS.md` | `B<n>` |

   - The first argument names the track. A bare session id names it by its
     prefix (`S29` → backend, `F1` → front end, `B1` → bugs).
   - **No track and no id → do NOT pick one.** Read the header line of each
     prompt file and the Tracks table in STATE.md, show the three next sessions
     (marking the one STATE.md calls the focus and any that are paused), and
     ask the human which to start. Wait for the answer.
   - An unknown word, or a track word that disagrees with the id's prefix
     (`fe S29`) → STOP and ask. Never guess a track.

1. Verify `pwd` is the Auspex repo (this repo). Wrong dir → STOP: "wrong window".
2. Read `STATE.md`, `SESSION-RULES.md` and the track's prompt file. If the human
   supplied a session id, it must match the id in that file's header line,
   `# NEXT-SESSION-<TRACK> — track: <track> · session: <id>`. Mismatch → STOP
   and say "wrong window / wrong session, expected <id> on the <track> track".
   Do not improvise a session.
2b. STATE.md's Tracks table must name the same next id for this track.
   Divergence → fix STATE.md first and say so. If the table marks the track
   paused, or another track as the focus, say that in one line and carry on;
   the human picked it.
3. Verify we're on `staging` (D-010). On main or detached → switch to staging
   and say so.
3b. Identity guard (D-011, D-059 — personal identities only): the repo-local
   `git config user.email` must be an email on SESSION-RULES.md's "Who works
   here" table, and if `gh` will be used this session, `gh auth status` must
   show as ACTIVE the GitHub account on the same row — otherwise run
   `gh auth switch --hostname github.com --user <that account>` (if it isn't
   logged in yet, tell the human to run `gh auth login` once, choosing SSH and
   their personal key; Burhan's is `~/.ssh/personal_git`).
   - Email not on the table → ask the human who they are. A collaborator Burhan
     added to the repo adds their own row (personal account + its noreply
     email) in its own commit, then carry on. Anyone else → STOP.
   - Never set one person's identity for another, and never let a work
     identity (an employer email such as `@sirp.io`, an account such as
     SIRP-Burhan) author commits or API calls in this repo.
4. Reality check: `git log --oneline -5`, `git status`, and (once compose
   exists) `docker compose up -d && docker compose ps` + `/api/health/ready`
   (readiness — checks Postgres AND OpenSearch, stricter than liveness).
   Divergence from STATE.md → fix STATE.md first, report the divergence.
4b. Dev-LLM gate (D-013 — the endpoint is load-bearing from S3 on):
   `curl -s localhost:11434/api/version` must answer, and
   `curl -s localhost:11434/api/tags` must list the dev model that STATE.md
   declares (currently `qwen3:14b`; read it from STATE.md, don't trust this
   file). Down or model missing → STOP and tell the human (Ollama service /
   `ollama pull`) unless the track's prompt says the session needs no LLM.
5. First line of the restatement: **"Track: <track> · Session: <id>"**. Then
   the session goal from the track's prompt in 2–3 lines, and the scope-lock
   rule (new ideas → `/idea`, bugs found → `/bug`), then begin the session's
   work.
