# NEXT-SESSION-BUGS — track: bugs · session: B4

_Paste everything below the line into a fresh Claude Code window opened in
your clone of the Auspex repo. **B4 is handed to Hunaiza (Burhan, 2026-10-28;
D-059): she owns it fully. It runs now, before S33** (order table row 5b in
`NEXT-SESSION-BE.md`), which is hers too. **Its scope is fixed by Burhan: six
bugs, every one required.** B3 closed 2026-10-19 (Hunaiza): B-010 and B-024
fixed. S32 closed 2026-10-27 (Hunaiza); its PR #43 was merged 2026-10-28._

---

SESSION B4 of Auspex, **bugs track** (D-051). The working dir is your clone of
the Auspex repo. Run `/session-start bugs B4` first (the full ritual). It reads
`SESSION-RULES.md` (standing rules for every track) and STATE.md.

**The handoff (D-059).** Burhan handed B4 to Hunaiza (`HunaizaK`, on
SESSION-RULES.md's "Who works here" table). She works on her own machine, in
her own clone, under her own personal identity. **She owns B4 fully: every
call inside its scope, and new D-entries** (Burhan, 2026-10-28). Wherever this
prompt, a rule or a command says "Burhan's call" or "ask Burhan", ask her.
**Re-scoping stays Burhan's:** B4 takes the six bugs below and no others; a
bug that cannot be fixed in B4 is said so in STATE.md, and she passes it on.
One session at a time spans both machines: Burhan runs no session while B4
runs. **S33 follows B4** (`NEXT-SESSION-BE.md`), and starts only after B4's
PR is merged.

Step 0 (do BEFORE new scope):

1. **Start from GitHub.** `git checkout staging && git pull --ff-only origin
   staging`, then confirm STATE.md says S32 closed and PR #43 merged. If
   `origin/staging` moves while B4 runs and you did not move it, stop.
2. **B4 does not promote.** The slate holds S32, and S32 is on `staging` with
   PR #43's review unfixed (docs/probes/2026-10-28-pr43-review.md); Burhan's
   call is that S33 fixes it before any promote. S33's promote carries S32,
   B4 and S33 together.
3. **The scope, in this order** (Burhan, 2026-10-28). Each has its GitHub
   issue, assigned to her, with its done line:
   1. **B-018** (#44): a URL pasted with credentials keeps `user:pass`
      (`auspex/classify/observables.py:207-218`); it is sent to URLhaus and
      stored in `observables`. Strip it before either. Pin the input with a
      placeholder, never a real credential.
   2. **B-025** (#45): `enter()` decides access and reads the home
      organization in two queries (`auspex/tenancy/entry.py:24-27`); a rehome
      between them shows the old organization's admins the new one's name.
      Tenancy: a cross-tenant test that fails first.
   3. **B-017** (#46): a non-string tool name from the customer's endpoint
      crashes the agent turn (`auspex/llm/client.py:388-389`).
   4. **B-027** (#47): `extract()` is O(matches × spans) in `_spans_overlap`;
      sort or bisect, with a differential check that its output did not
      change.
   5. **B-030** (#48): `_QUOTE_LINE_RE` in `auspex/guard.py` is quadratic on
      a newline run after a rule hits; add a rule-hit input to the timing
      fixture (`tests/fixtures/classify/b010_redos.json`).
   6. **B-032** (#49): the guard's live-rule test misses a new start
      character its corpus lacks; pin both run-led rules' regex text, and
      re-run the `{{system}}` mutant from
      docs/probes/2026-10-22-b032-run-led-scan-mutants.md to show the new
      test catches it.

For each bug:
- **Reproduce before fixing**, and save the "before" to
  `docs/probes/<date>-b4-<bug>.md`.
- **Fix the cause**, with a test that fails before the fix and the exact
  offending input pinned as a fixture (org rule).
- **Check it live** against the rebuilt container.
- **Have a fresh agent review the fix** (SESSION-RULES.md). B-025 touches
  tenancy and B-030 the guard: their reviews are adversarial. At B3 both
  reviews found something worth fixing; one found a fourth bug of the same
  class.
- When BUGS.md says `fixed <commit> (B4)`, comment on and close its GitHub
  issue.

Constraints: everything in `SESSION-RULES.md`. Bugs only, this session:
- **One bug per fix commit**, naming its B-id; BUGS.md gets
  `fixed <commit> (B4)` the same session.
- A new bug found while fixing one goes to `/bug`, not this session, unless it
  blocks the fix. Then say so in STATE.md: that is a scope call, Burhan's.
- **Save evidence before any pytest run**, and take a live "before" run before
  the gate: `./ci.sh` redeploys the running container (STATE.md, Host notes).
- Nothing of S33's in B4 (scope lock), PR #43's review included.

Session end: `/session-end`. It writes the bugs track's next prompt, B5,
unscoped (Burhan's call), and leaves S33's prompt as the next to run. Then
open one PR from your B4 branch into `staging` for Burhan to review and
merge; `/promote` only if Burhan asks.
