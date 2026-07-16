---
description: Run the CLAUDE.md session-end ritual (state, next prompt, roadmap, commit, summary)
---

Run the session-end ritual from CLAUDE.md. Never skip steps, even on a bad or
cut-short session:

1. Verify always-demoable: `./ci.sh` green + `docker compose up -d` +
   `/api/health/ready` 200. Red → either fix now or explicitly log the breakage
   in STATE.md Blockers before ending (a red end-state must never be silent).
2. Update `STATE.md`: done / in-flight / blockers / "next session should".
   Standing follow-ups in the outgoing "In-flight" section (event-triggered,
   cross-session — e.g. the D-013 Northflank validation run) MUST be carried
   into the new version unless actually completed; they die by being done,
   not by being forgotten in a rewrite.
3. Rewrite `NEXT-SESSION.md` completely for the next session — a full
   paste-ready prompt with session number, scope-locked goals from ROADMAP.md,
   and constraints. The human must not need to remember or compose anything.
4. Tick completed items in `ROADMAP.md`. Log any shortcut taken this session in
   `TECHNICAL_DEBT.md` (date + risk + path to fix).
5. New env vars introduced? Confirm they exist in `.env.example` AND
   `docs/ENV_VARS.md`.
6. Commit everything on `staging` (one concern per commit if uncommitted work
   is separable). Suggest `/promote` only if the session hit a demoable
   milestone.
7. End with the ≤10-line human summary: shipped / blocked / paste-next.
