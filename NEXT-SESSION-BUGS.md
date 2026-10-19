# NEXT-SESSION-BUGS — track: bugs · session: B4

_Paste everything below the line into a fresh Claude Code window opened in the
Auspex repo. **B4 is not scoped yet: which bugs it takes is Burhan's call.**
B3 closed 2026-10-19 (Hunaiza, D-059): B-010 and B-024 fixed, B-027 and B-028
logged. Run B4 only when STATE.md's Tracks table makes bugs the focus or
Burhan says so; the order table in `NEXT-SESSION-BE.md` runs the backend
first._

---

SESSION B4 of Auspex, **bugs track** (D-051). The working dir is the Auspex
repo. Run `/session-start bugs B4` first (the full ritual). It reads
`SESSION-RULES.md` (standing rules for every track) and STATE.md.

**Who decides.** Burhan, unless STATE.md says B4 was handed to a collaborator
(D-059); then the calls inside its scope are theirs, and re-scoping stays
Burhan's.

Step 0 (do BEFORE new scope):

1. **Start from GitHub.** `git checkout staging && git pull --ff-only origin
   staging`. One session at a time holds across machines (D-051, D-059): if
   `origin/staging` moves while B4 runs and you did not move it, stop.
2. **If STATE.md says the promote slate is not empty, `/promote` it** (unless
   the handoff says otherwise). Read the diff, not the list.
3. **Ask Burhan which bugs B4 takes, and in what order.** Do not pick. The
   open entries in BUGS.md:
   - **B-027** (B3): `extract()` checks every match against every earlier
     span, so thousands of observables take 0.2–0.8 s on the event loop;
   - **B-028** (B3): a failed switch, after a re-check rebuilt the header with
     one workspace, throws on a null picker (reasoned, not reproduced);
   - B-011…B-020 (S29's review of S28's code), B-022 and B-023 (F4), B-025
     and B-026 (S31);
   - B-005 and B-009, which wait on his call about the Deferred
     fabricated-specifics item.

For each bug B4 takes:
- **Reproduce before fixing**, and save the "before" to
  `docs/probes/<date>-b4-<bug>.md`.
- **Fix the cause**, with a test that fails before the fix and the exact
  offending input pinned as a fixture (org rule).
- **Check it live** against the rebuilt container. A page change is loaded in
  a real browser: B3's first B-024 build blanked every page with a TDZ error
  while every source-reading test stayed green.
- **Have a fresh agent review the fix** (SESSION-RULES.md). At B3 both reviews
  found something worth fixing; one found a fourth bug of the same class.
- When BUGS.md says `fixed <commit> (B4)`, comment on and close its GitHub
  issue, if it has one.

Constraints: everything in `SESSION-RULES.md`. Bugs only, this session:
- **One bug per fix commit**, naming its B-id; BUGS.md gets
  `fixed <commit> (B4)` the same session.
- A new bug found while fixing one goes to `/bug`, not this session, unless it
  blocks the fix. Then say so: that is a scope call, Burhan's.
- **Save evidence before any pytest run**, and take a live "before" run before
  the gate: `./ci.sh` redeploys the running container (STATE.md, Host notes).

Session end: `/session-end`, then put the work on `staging` the way STATE.md
says for this session (a push, or a PR for a collaborator), and `/promote`
only if Burhan asks.
