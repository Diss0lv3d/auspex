---
description: Run the CLAUDE.md session-end ritual for the track this session ran on (state, next prompt, roadmap, commit, summary)
---

Run the session-end ritual from CLAUDE.md. Never skip steps, even on a bad or
cut-short session. The track is the one `/session-start` named ("Track: … ·
Session: …"). If no start ritual ran in this window, ask which track before
writing anything.

1. Verify always-demoable: `./ci.sh` green + `docker compose up -d` +
   `/api/health/ready` 200. Red → either fix now or explicitly log the breakage
   in STATE.md Blockers before ending (a red end-state must never be silent).
2. Update `STATE.md`: done / in-flight / blockers / "next session should".
   - Update **this track's row** of the Tracks table (last closed, next id),
     and the shared facts every track reads: test count, module count, the
     promote slate. Those numbers live in STATE.md only.
   - Standing follow-ups in the outgoing "In-flight" section (event-triggered,
     cross-session — e.g. the D-013 Northflank validation run) MUST be carried
     into the new version unless actually completed; they die by being done,
     not by being forgotten in a rewrite.
3. Rewrite **this track's** prompt file completely for its next session (D-051):
   - `NEXT-SESSION-BE.md`, `NEXT-SESSION-FE.md` or `NEXT-SESSION-BUGS.md`, with
     its header line `# NEXT-SESSION-<TRACK> — track: <track> · session: <id>`
     and the id incremented (`S29` → `S30`, `F1` → `F2`, `B1` → `B2`).
   - A full paste-ready prompt: `/session-start <track> <id>`, Step 0,
     scope-locked goals, candidates, and only the constraints that are about
     this track's next session. The human must not need to remember or compose
     anything.
   - **Standing rules belong in `SESSION-RULES.md`, once.** A rule this session
     changed or learned → edit it there, not into a prompt. Never copy a
     moving number (tests, modules, promote #) into a prompt; point at STATE.md.
3b. **Read the other two prompt files.** Anything this session made untrue
   there (a promote done, a bug fixed, a rule changed, code a goal names
   moved) → fix it there now, in its own commit. Do not re-scope another
   track's goals; flag that to Burhan instead.
4. Tick completed items in `ROADMAP.md`, in this track's section. Bugs fixed →
   `fixed <commit> (<id>)` in BUGS.md. Log any shortcut taken this session in
   `TECHNICAL_DEBT.md` (date + risk + path to fix).
5. New env vars introduced? Confirm they exist in `.env.example` AND
   `docs/ENV_VARS.md`.
6. Commit everything on `staging` (one concern per commit if uncommitted work
   is separable). Suggest `/promote` only if the session hit a demoable
   milestone.
7. End with the ≤10-line human summary: shipped / blocked / paste-next. The
   paste-next names the track file and its `/session-start <track> <id>`. If
   another track is the focus in STATE.md, name that one too.
8. **After the ritual, the window is still live.** If Burhan changes scope,
   focus or priorities before it closes, write it into STATE.md and the
   affected prompt file(s) and commit it at once. On 2026-10-10 a pivot said
   after the ritual died with the window (D-051).
