# NEXT-SESSION-BUGS — track: bugs · session: B5

_Paste everything below the line into a fresh Claude Code window opened in
your clone of the Auspex repo, **once Burhan has scoped B5**. B4 closed
2026-10-28 (Hunaiza, handed fully under D-059): B-017, B-018, B-025, B-027,
B-030 and B-032 fixed, as one PR from `b4-bugs` into `staging`. **S33 runs
next** (`NEXT-SESSION-BE.md`); B5 waits for Burhan to pick its bugs and its
owner._

---

SESSION B5 of Auspex, **bugs track** (D-051). The working dir is your clone of
the Auspex repo. Run `/session-start bugs B5` first (the full ritual). It reads
`SESSION-RULES.md` (standing rules for every track) and STATE.md.

Step 0 (do BEFORE new scope):

1. **Start from GitHub.** `git checkout staging && git pull --ff-only origin
   staging`, then confirm STATE.md names B5's scope and owner. **If it does
   not, stop: B5 is unscoped, and scoping it is Burhan's.** If `origin/staging`
   moves while B5 runs and you did not move it, stop.
2. **Promote only if Burhan asks.** The slate is in STATE.md, follow-up #1.
3. **The scope is the list Burhan writes into STATE.md**, in his order. The
   open entries are in BUGS.md; B4's reviews and PR #50's review added seven:
   - **B-033**: a pasted credential stays in the stored message text, and in
     `observables` rows saved before B-018's fix (partly a product call);
   - **B-034**: a membership change stamps the actor's home read at the start
     of the request (B-025's class, another path);
   - **B-035**: a reply envelope in the wrong shape still crashes the LLM
     parsers, and an unknown tool's name is echoed unbounded (B-017's class).
   - **B-036**: credentials outside an http(s) URL (ftp, a bare
     `user:pass@host`) are stored, a bare one as an email;
   - **B-037**: a membership removed mid sign-in still gets an entry event
     and a first token (B-025's family);
   - **B-038**: a URL with `\` before an `@` is read with another host by
     `urlsplit` downstream than a browser uses;
   - **B-039**: a tab, newline or quote inside a pasted URL cuts its match
     short (a credential can reach a value).

For each bug (the B4 pattern):
- **Reproduce before fixing**, and save the "before" to
  `docs/probes/<date>-b5-<bug>.md`.
- **Fix the cause**, with a test that fails before the fix and the exact
  offending input pinned as a fixture (org rule). Where a test pins behaviour
  that already holds, prove it with a mutant.
- **Check it live** against the rebuilt container.
- **Have a fresh agent review the fix** (SESSION-RULES.md); tenancy and the
  guard get adversarial reviews. At B4 every review found something.
- When BUGS.md says `fixed <commit> (B5)`, comment on and close its GitHub
  issue.

Constraints: everything in `SESSION-RULES.md`. Bugs only, this session:
- **One bug per fix commit**, naming its B-id.
- A new bug found while fixing one goes to `/bug`, not this session, unless it
  blocks the fix; then say so in STATE.md (a scope call, Burhan's).
- **Save evidence before any pytest run**, and take a live "before" run before
  the gate: `./ci.sh` redeploys the running container.
- A timing test pins growth or uses `tests/_timing.py`'s best-of-3, never a
  single wall-clock sample (B4's B-027 review).

Session end: `/session-end`. It writes B6's prompt, unscoped. Then open one PR
from your B5 branch into `staging` for Burhan to review and merge.
