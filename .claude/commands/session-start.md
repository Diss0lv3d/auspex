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
4. Reality check: `git log --oneline -5`, `git status`, and (once compose
   exists) `docker compose up -d && docker compose ps` + `/api/health`.
   Divergence from STATE.md → fix STATE.md first, report the divergence.
5. Restate the session goal from NEXT-SESSION.md in 2–3 lines and the
   scope-lock rule (new ideas → IDEAS.md), then begin the session's work.
