# NEXT-SESSION-BUGS — track: bugs · session: B3

_Paste everything below the line into a fresh Claude Code window opened in
your clone of the Auspex repo. **B3 is handed to Hunaiza (Burhan, 2026-10-19;
D-059) and is the focus: it runs before S32.** Its scope is set: **B-010, then
B-024** (GitHub #38 and #39, both assigned to her). Promote #40 shipped all of
S31, so the slate is empty._

---

SESSION B3 of Auspex, **bugs track** (D-051). The working dir is your clone of
the Auspex repo. Run `/session-start bugs B3` first (the full ritual). It reads
`SESSION-RULES.md` (standing rules for every track) and STATE.md.

**The handoff (D-059).** Burhan handed B3 to Hunaiza (`HunaizaK`, on
SESSION-RULES.md's "Who works here" table). She works on her own machine, in
her own clone, under her own personal identity. **Every call inside B3's scope
is hers, B-024's UX call included**: wherever a rule says "Burhan's call" or
"ask Burhan" about B-010 or B-024, ask her. Re-scoping (another bug, a
Deferred item, a D-entry beyond these two bugs) stays Burhan's: say so, and
she passes it on.

Step 0 (do BEFORE new scope):

1. **Start from GitHub.** `git checkout staging && git pull --ff-only origin
   staging`. One session at a time holds across machines (D-051, D-059): if
   `origin/staging` moves while B3 runs and you did not move it, stop and tell
   Burhan. Never force-push.
2. **The promote slate is empty** (promote #40 shipped S31, STATE.md), so B3
   does not promote at its start. **B3 does not promote at its end either**:
   S32's Step 0 ships B3's fixes from Burhan's window.
3. **The scope is set; do not ask it again.** Read BUGS.md's B-010 and B-024
   entries and GitHub #38 and #39. The rest of BUGS.md is not B3's.

Goal, in this order, one bug at a time:

**1. B-010: the classify pass can be stalled by crafted whitespace or dotted
input** (GitHub #38). Three older rules backtrack quadratically and run
synchronously on the chat route's event loop, so one message stalls every
request on the worker:
- the refang rules in `extract()` (`auspex/classify/observables.py:120-121`):
  `extract("x" + " " * 31998 + "x")` took 3.65 s;
- `_GREETING_RE` (`auspex/classify/classifier.py:158`): 1.1 s at 8,000
  characters, ~18 s at the 32,000-character cap;
- `_DOMAIN_CAND_RE` (`auspex/classify/observables.py:181`) on `"a." * n`:
  `classify("a." * 16000)` took 5.7 s; `_EMAIL_RE` (`:153`) is slow on the
  same input.

S29 fixed two S28 rules of the same class with possessive quantifiers
(`8187925`); follow that. **But a plain possessive would stop
`_DOMAIN_CAND_RE` matching "evil.com." at the end of a sentence**: candidates
must start only at the beginning of a dotted run.
- Reproduce first with `docs/probes/s29-review/classify/redos.py` (record:
  docs/probes/2026-10-14-s29-s28-code-review.md, finding 8). Save the before
  timings to `docs/probes/<date>-b3-b010-redos.md`.
- Pin each rule with a timing test like `tests/test_classifier.py`'s
  (`time.perf_counter`, around `:267`).
- **Prove by differential fuzz that what each rule matches did not change**
  (the old pattern against the new one, on generated and on real inputs).

**2. B-024: arrow keys on the closed workspace switcher may switch at every
step** (GitHub #39). **Unverified**: F4's review reasoned it from the code.
- The switcher is a native `<select>` that switches on `change`
  (`auspex/static/js/shell.js:173`; `switchTo` at `:123`, `showSignedIn` at
  `:165`). On Windows and Linux browsers, arrow keys on a closed, focused
  select fire `change` at each step, so a keyboard user would be reloaded into
  every client they pass (WCAG 3.2.2).
- Reproduce with a keyboard in Chrome on Windows or Linux. The switcher shows
  from two workspaces (`shell.js:169`); give the user three, so one arrow step
  can be seen passing through a client. Save what happens to
  `docs/probes/<date>-b3-b024-keyboard.md`. **If it does not reproduce, record
  that in BUGS.md, close #39 with the evidence, and fix nothing.**
- If it does: the fix (a Switch button, or handling the keys) changes the
  switcher's UX. **The call is hers.** Put the options and her pick in the
  session record. **D-070 stays intact**: a switch reloads, leaves nothing of
  the last client, Back and Forward included.
- Pin it in the shell's tests (`tests/js/shell_logic.test.mjs`, or a new test
  beside it), and check it live with a keyboard.

For each bug:
- **Reproduce before fixing.**
- **Fix the cause**, with a test that fails before the fix and the exact
  offending input pinned as a fixture (org rule).
- **Check it live.**
- **Have a fresh agent review the fix** (SESSION-RULES.md). At B2, two of the
  four reviews found a real defect.
- When BUGS.md says `fixed <commit> (B3)`, close its GitHub issue with that
  commit in the comment (`gh` as her own account).

Not B3's scope (Burhan places them later): the other open entries (B-011…
B-020, B-022, B-023, B-025, B-026); B-005 and B-009, which still wait on his
call about the Deferred fabricated-specifics item; TD-054 and TD-055. Ending
with both bugs done and the rituals run beats starting a third.

Constraints: everything in `SESSION-RULES.md`. Bugs-only, this session:
- **One bug per fix commit.** Each one names its B-id, and BUGS.md gets
  `fixed <commit> (B3)` in the same session.
- A new bug found while fixing one → `/bug`, not this session's scope, unless
  it blocks the fix. In that case say so: that is a scope call, Burhan's.
- **Save evidence before any pytest run**, and take a live "before" run before
  the gate: `./ci.sh` redeploys the running container (STATE.md, Host notes).

Session end: `/session-end` (the focus then moves to S32, backend), then
`git push origin staging`. No `/promote` (Step 0 item 2). Send Burhan the
summary, or `/briefing` for a plain-language one.
