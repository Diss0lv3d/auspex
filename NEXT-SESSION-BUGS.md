# NEXT-SESSION-BUGS — track: bugs · session: B3

_Paste everything below the line into a fresh Claude Code window opened in
/home/burhan/auspex-new. The bugs track works from BUGS.md (D-051). The
backend is the current focus (S30, STATE.md); start B3 only when Burhan picks
it. S29's review of S28's code logged B-010…B-020, so B3 has work now._

---

SESSION B3 of Auspex, **bugs track** (D-051). The working dir must be
/home/burhan/auspex-new. Run `/session-start bugs B3` first (the full ritual).
It reads `SESSION-RULES.md` (standing rules for every track) and STATE.md.

Step 0 (do BEFORE new scope):

1. **One window at a time (D-051).** If anything moves that you did not move,
   check `ps` for a second `claude` in this directory and stop.
2. **If STATE.md says the promote slate is not empty, `/promote` it.** Read
   the diff, not the list.
3. **Read BUGS.md, then put the scope question to Burhan before any bug.**
   B2 fixed B-002, B-004, B-006 and B-008. S29's review of S28's code logged
   **B-010…B-020** (record: docs/probes/2026-10-14-s29-s28-code-review.md,
   scripts in docs/probes/s29-review/). **B-010 is the most severe:** three
   older classify rules let one crafted message stall the chat route's event
   loop for seconds (the refang rules, `_GREETING_RE`, `_DOMAIN_CAND_RE`; S29
   fixed the two S28 rules with possessive quantifiers, `8187925`). **B-005
   and B-009 still sit next to the deferred fabricated-specifics item**
   (SESSION-RULES.md, Deferred). Ask him, with the evidence:
   - **Which open bug first?** The track's default is the top open entry;
     B-010's severity argues for it.
   - **Does the fabricated-specifics item come out of Deferred** (for B-005 and
     B-009)? That is a scope decision and a new D-entry.
   - Has he **seen anything broken using the platform?** Log each with `/bug`.
   - **B-011 and B-012 change classifier rules**, so they are judged on blind
     batteries (SESSION-RULES.md) against pinned operating points. **B-012 is
     partly Burhan's call:** D-047 counts "bot / chat / platform" as the
     assistant.

Goal (one bug at a time, Burhan's order; the S29 entries are in BUGS.md with
their evidence and the reviewer's repro sketch):
- **B-010: the classify pass can still be stalled by crafted whitespace or
  dotted input.** A plain possessive would stop `_DOMAIN_CAND_RE` matching
  "evil.com." at the end of a sentence, so candidates must start only at the
  beginning of a dotted run. Pin each rule with a timing test like
  `tests/test_classifier.py`'s, and prove by differential fuzz that what it
  matches did not change.
- **The S29 entries B-011…B-020**, as Burhan picks.

- **B-009: the agent calls a no-signal IP "legitimate"**, inferred from its
  operator and from the absence of signals.
  - B-006's fix handed the model `"reputation": "unknown"`, and it says
    unknown 3/3 now, but it still writes "legitimate Google infrastructure"
    3/3.
  - Evidence: docs/probes/2026-10-13-b2-b006-reproduce.md and
    docs/probes/b2-b006/raw-repro-after.jsonl. The probe that reproduces it
    is `docs/probes/b2-b006/probe_repro.py`.
- **B-005: on the conversational path glm forges the `⟦DATA⟧` fence** and
  writes invented "platform data" inside it.
  - Evidence: docs/probes/b1-b001/raw-replay-glm*.log.
  - Replay with docs/probes/b1-b001/probe_replay_conversational.py, which
    uses the route's own composition.

For whichever is picked:
- **Reproduce before fixing.**
- **Fix the cause**, with a test that fails before the fix and the exact
  offending text pinned as a fixture (org rule).
- **Check it live.**
- **Have a fresh agent review the fix** (SESSION-RULES.md). At B2, two of the
  four reviews found a real defect.
- A check on what the model WRITES is a new kind of rail. Put its design to
  Burhan with the numbers, as a D-entry. It must not loosen the output rail
  (D-030, D-040, D-058).

Candidates from B2's reviews. These are debt, not bugs, so take one only if
Burhan picks it:
- **TD-055:** claim before writing. Only the ceiling refusal discards a
  stored question; other failures before the claim still leave one.
- **TD-054:** pin a note's target when it is filed. A note named by its
  indicator is re-resolved at execute time.

Constraints: everything in `SESSION-RULES.md`. Bugs-only, this session:
- **One bug per fix commit.** Each one names its B-id, and BUGS.md gets
  `fixed <commit> (B3)` in the same session.
- A new bug found while fixing one → `/bug`, not this session's scope, unless
  it blocks the fix. In that case say so and let Burhan decide.
- **Save evidence before any pytest run**, and take a live "before" run before
  the gate: `./ci.sh` redeploys the running container (STATE.md, Host notes).
