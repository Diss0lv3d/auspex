# NEXT-SESSION-BE — track: backend · session: S29

_Paste everything below the line into a fresh Claude Code window opened in
/home/burhan/auspex-new. **This track is PAUSED** (Burhan, 2026-10-10: "pause
BE for a bit", front end first). Start it only when he picks it._

_(S28 closed on 2026-10-11 with D-046…D-050 and the alert key fix. Where the
code stands, and whether the promote slate is still pending, is in STATE.md.)_

---

SESSION S29 of Auspex, **backend track** (D-051). The working dir must be
/home/burhan/auspex-new. Run `/session-start be S29` first (the full ritual).
It reads `SESSION-RULES.md` (standing rules for every track) and STATE.md.

Step 0 (do BEFORE new scope):

1. **If STATE.md says the promote slate is not empty, `/promote` it.** Read the
   diff, not the list.
2. **An adversarial second-pass review of S28's own code.** Each change was
   mutant-checked or battery-judged by its author, but nobody else has read it
   adversarially. Read and attack:
   - D-046: `_on_offer`, `_dispatch_within_budget` and the last-call notice
     (`auspex/agent/loop.py`), and the budget declaration
     (`auspex/agent/capabilities.py`). Check `run` and `run_stream` parity,
     and what a call refused for budget looks like on the page;
   - D-048: `run_stale_approval`, the shared `_run_claimed`, `withdraw`, and
     the queue's new clause (`auspex/actions/settlement.py`), plus the two
     routes. Check against every claim-token and `resolved_by` rule;
   - D-049: `record` in `enrich_observable` and the route's lambda. What gets
     written, for which workspace, and what the model is told on failure;
   - D-047: `_IDENTITY_RE` (`auspex/classify/classifier.py`);
   - D-050: `_NOTE_ASK_RE`, `_NOTE_REQUEST_RE`, the shortcut veto, and the
     `action_request` contract;
   - `e2af082`: JSON alert name precedence and the new keys;
   - the review fixes `831dedc` and `3a09fcd`.

   Same discipline as before: reproduce by execution first, fix with a test
   that fails pre-fix, and record what you clear in a probe record.

Goal (two items, in order):

1. **TD-036: the analyst reads the answer twice.** Its trigger fired live at
   S28: in 2 of 3 D-049 probe turns, glm-4.5-air wrote a full answer BEFORE its
   annotate call. It passed the 400-char narration hold, streamed as answer,
   and then the real answer followed. Raw logs:
   `docs/probes/s28-candidates/raw-app-agent-records-run*.log`. Read
   TECHNICAL_DEBT.md TD-036.
   - **Measure first.** On action-calling turns (and the S26 routing prompts),
     what is the longest pre-tool content, and how often does it pass 400?
   - Then fix the cause, with tests, and live-check through the container. The
     hold is native-only, so keep D-031's ordering guarantee.
   - If a front-end session has changed how the page renders the stream since,
     read that first (STATE.md, Tracks). **F1 did:**
     - D-052 adds a `status` frame before each wait and paces painting
       within 200 ms;
     - D-053 renders answers as safe markdown;
     - D-054 adds `engine_calls` to the done frame and a `turn_spend` row.

     The pacing only paints what the server already sent, so it neither hides
     nor adds a doubled answer.
2. **TD-044: re-calibrate the output rail with the index as it now stands.**
   S27 added D-043's repair directive and D-045's action surface; S28 added
   D-050's `action_request` directive. Re-run
   `docs/probes/s22-outguard/probe_calibrate2.py` and
   `docs/probes/s26-step0/probe_calibrate_agent.py`, including action-request
   turns. Record the new legitimate ceilings next to the floors. A floor moves
   only on that measurement.
   - **F1: the trigger fired as a live false positive, B-002.** A definition
     question on the agent path was cut 3 of 4 times. The match was 40 words
     of the definition contract's section spec on the thinking channel
     (docs/probes/2026-10-12-b002-definition-rail-trip.md). Measure against
     it; B-002 is on the bugs list too, so tell Burhan if S29 closes it.

Candidates. **Ask Burhan at the start ritual. Do NOT start any of these
unasked:**
- The additive alert scorer under-rates credential theft. Documented ECS and
  Graph lsass-dump alerts score LOW 35 (IDEAS;
  docs/probes/2026-10-11-s28-alert-json-keys.md). A scoring change needs its
  own independently written battery.
- Look an indicator up before annotating it. Live, a note-only request on a
  never-seen IP was refused as NothingToPropose instead (IDEAS).
- Ingest ATT&CK groups and software as KB documents. This is a new doc_type,
  so the TD-005 trigger and TD-027 HARD GATE apply (IDEAS).
- More identity recall: 27/45 held-out identity questions still reach the
  model. This needs a FRESH battery.

Constraints: everything in `SESSION-RULES.md`. Backend-only, this session:
- **The rail is this session's goal 2.** Its floors move only on goal 2's
  measurement; the rest of SESSION-RULES.md's rail section applies unchanged.
- **TD-036 touches the stream.** Any fix keeps the rail's carry, D-031's
  ordering guarantee and the native-only hold (SESSION-RULES.md, The output
  rail).
