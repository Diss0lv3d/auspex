# NEXT-SESSION-BUGS — track: bugs · session: B2

_Paste everything below the line into a fresh Claude Code window opened in
/home/burhan/auspex-new. The bugs track works from BUGS.md (D-051). The front
end is the current focus (STATE.md); start B2 only when Burhan picks it._

---

SESSION B2 of Auspex, **bugs track** (D-051). The working dir must be
/home/burhan/auspex-new. Run `/session-start bugs B2` first (the full ritual).
It reads `SESSION-RULES.md` (standing rules for every track) and STATE.md.

Step 0 (do BEFORE new scope):

1. **One window at a time (D-051).** If anything moves that you did not move,
   check `ps` for a second `claude` in this directory and stop.
2. **If STATE.md says the promote slate is not empty, `/promote` it.** Read
   the diff, not the list.
3. **Read BUGS.md and ask Burhan which open bug comes first.** Default: the
   top open entry, B-002. Mark it `fixing (B2)` when work starts.

Goal (default): **B-002, a definition question on the agent path is stopped
as a leak.** Read docs/probes/2026-10-12-b002-definition-rail-trip.md first.
In short: "What are the practical differences between EDR and XDR for a
small SOC deciding what to buy?" resolved to `definition` and was cut by the
output rail in 3 of 4 agent-path turns. The match was 40 words of the
definition contract's own section spec, on the `thinking` channel, at exactly
`THINKING_SHINGLE_WORDS` (D-040). That is TD-044's trigger firing as a live
false positive.

Reproduce before fixing:
- **Run the same question on the agent path at least 4 times** (the dev
  endpoint, glm-4.5-air). For each run, record the finish reason, the channel
  of the match, the match length and which issued text it came from.
- **Re-measure before touching a calibrated number.** `THINKING_SHINGLE_WORDS`
  and `SHINGLE_WORDS` are measured constants. Re-run
  `docs/probes/s26-step0/probe_calibrate_agent.py` (thinking floor) and
  `docs/probes/s22-outguard/probe_calibrate2.py` (answer floor) against
  today's issued text, and record the legitimate ceiling first.

Then:
- **Put the options to Burhan with the numbers.** Re-calibrating a floor, or
  changing what the definition contract issues, is a rail decision: it gets a
  new D-entry. The rail is security-relevant ("assume a fourth defect";
  SESSION-RULES.md, The output rail). Never fix it by skipping the scan.
- **Do NOT re-open the guard regex** (TD-031/032/033 are ratified).
- Fix the cause, with a test that fails before the fix, and pin the exact
  stopped turn's thinking text as a regression fixture (org rule).
- **TD-044 is also in S29's goal** (`NEXT-SESSION-BE.md`). If B2 re-calibrates,
  rewrite S29's TD-044 item at session end (3b) so it does not redo the work.

If B-002 closes early, ask Burhan before taking the next open entry:
- **B-004:** a note on a recorded indicator is refused as "doesn't exist".
- **B-005:** on the conversational path glm forges the `⟦DATA⟧` fence with
  invented platform lines. A fix that checks what the model writes is the
  deferred fabricated-specifics item (SESSION-RULES.md, Deferred): put it to
  Burhan first.
- **B-006:** a follow-up on a no-signal IP calls it "clean", because the
  follow-up resolves to `general`. A resolver change is judged by the
  two-battery rule.
- **B-008:** at the usage ceiling, a new chat's question is stored and then
  refused with a 429 and no session frame, so each retry leaves another empty
  chat in the sidebar ("No answer was stored"). Server ordering in
  `auspex/routes/chat.py` (F2's chat list made it visible).

Constraints: everything in `SESSION-RULES.md`. Bugs-only, this session:
- **One bug per fix commit.** Each one names its B-id, and BUGS.md gets the
  status `fixed <commit> (B2)` in the same session.
- A new bug found while fixing this one → `/bug`, not this session's scope,
  unless it blocks the fix. In that case say so and let Burhan decide.
- **Save evidence before any pytest run.** A chat the suite would purge goes
  into a probe record first.
