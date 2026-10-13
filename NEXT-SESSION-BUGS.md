# NEXT-SESSION-BUGS — track: bugs · session: B3

_Paste everything below the line into a fresh Claude Code window opened in
/home/burhan/auspex-new. The bugs track works from BUGS.md (D-051). The front
end is the current focus (STATE.md); start B3 only when Burhan picks it._

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
   B2 fixed B-002, B-004, B-006 and B-008. The only open entries are **B-005
   and B-009, and both sit next to the deferred fabricated-specifics item**
   (SESSION-RULES.md, Deferred: "a fix that needs this item goes to Burhan
   first"). Ask him, with the evidence:
   - **Does that item come out of Deferred?** That is a scope decision, so it
     gets a new D-entry, and the fix approach is his call too.
   - If not, has he **seen anything broken using the platform?** Log each with
     `/bug` and take the one he picks.
   - If neither, **end early with the ritual.** A short session is fine.

Goal (only if Burhan re-scopes; one bug at a time, his order):

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
