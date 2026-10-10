# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**S29.** S28 closed on 2026-10-11. Burhan's call at its start ritual was
"all" for the candidates, so:
- promote #29 shipped S27, and a review of S27's code found 3 issues, all
  dealt with;
- **D-046:** `search_knowledge` has a per-turn budget of 3. Measured first;
  S27's prompts went 37 → 23 calls;
- **D-048:** an approval no run ever started rejoins the queue, with two doors:
  run now, or withdraw;
- **D-047:** the identity shortcut catches 18/45 held-out identity questions
  (was 0). D-002 kept, on Burhan's call;
- **D-049:** what the agent looks up is recorded like the IOC check;
- **D-050:** note requests never take the shortcut, and note-only ones get an
  eighth mode, `action_request`;
- JSON alerts read the documented ECS and Graph keys.

**Nothing after promote #29 is on main.** 1292 tests, 120 modules.)_

---

SESSION S29 of Auspex. The working dir must be /home/burhan/auspex-new. Run
`/session-start S29` first (the full ritual).

**LLM endpoints.**
- The primary dev LLM is **glm-4.5-air on Z.ai's general API (D-034)**:
  `LLM_BASE_URL=https://api.z.ai/api/paas/v4`, key in `.env` as `LLM_API_KEY`.
- Local Ollama `qwen3:14b` at `http://localhost:11434/v1` is the
  secondary/offline endpoint (D-013), and it is what the session-start
  local-Ollama gate validates.
- The app probes its endpoint at startup and re-checks every 6 h (D-038, D-042).
  The dev scorecard expires **2026-10-17**; after that a running container
  re-probes it (~15 calls). **If it logs the "endpoint changed" WARNING,
  re-measure D-040's thinking floor before anything else.**
- Any mismatch → STOP and tell me.

**`gh` (D-011).** `gh` flips to the work account between and during sessions;
assume it has and re-check before every call:
`gh auth switch --hostname github.com --user bh3082336888-cell`. Also:
- `gh pr edit` fails on this repo with a Projects-classic GraphQL error; use
  `gh api -X PATCH repos/.../pulls/N`.
- `gh pr merge --squash` printed nothing on success at S24, S25, #27, #28 and
  #29; verify with `gh pr view <n> --json state,mergeCommit`.
- Local `main` goes stale every promote. `git fetch`, then read
  `git diff origin/main..staging --stat`, **never the commit list**.

**Running things.**
- The app container runs the built image, so live verification needs
  `docker compose up -d --build app`.
- Run the suite the way `ci.sh` does (`.venv`, package installed editable).
- **Never pipe `./ci.sh` into `tail`**: the pipeline reports `tail`'s exit code.
- **Run the full gate before calling a change done.** Twice now (S27, S28) a
  change passed every file it touched and broke a test in one it did not.
- Do not edit code while `./ci.sh` is running: the edit lands in its container
  build.

Step 0 (do BEFORE new scope):

1. **`/promote` the S28 slate (#30).** It is everything after `31f7fc1`:
   D-046…D-050, the review fixes `831dedc` and `3a09fcd`, and the alert key fix
   `e2af082`. Read the diff, not the list.
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
   - `e2af082`: JSON alert name precedence and the new keys.

   Same discipline as before: reproduce by execution first, fix with a test
   that fails pre-fix, and record what you clear in a probe record.
3. **The two untracked overview files are Burhan's and stay untracked.** Do not
   ask about them, commit, move, publish or delete them.

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
2. **TD-044: re-calibrate the output rail with the index as it now stands.**
   S27 added D-043's repair directive and D-045's action surface; S28 added
   D-050's `action_request` directive. Re-run
   `docs/probes/s22-outguard/probe_calibrate2.py` and
   `docs/probes/s26-step0/probe_calibrate_agent.py`, including action-request
   turns. Record the new legitimate ceilings next to the floors. A floor moves
   only on that measurement.

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

Constraints:
- **Process.**
  - Tests ship with each step (CLAUDE.md rule 8). CI stays hermetic.
  - Thrash brake: two failed approaches on one problem → STATE.md Blockers,
    then move on. Tired human = short session; rituals anyway.
  - One concern per commit, and never amend (org rule).
  - End with `/session-end`.
- **Inference costs real money.**
  - Z.ai is pay-as-you-go: glm-4.5-air is $0.20/$1.10 per 1M tokens, and
    thinking is billed inside `completion_tokens`. A thin-topic agent turn is
    now at most ~5 calls (D-046). Budget probes.
  - General endpoint only, pay-as-you-go only, dev only. Never
    `api/coding/paas/v4`. Z.ai processes in Singapore, so **no KSA-tenant data,
    ever** (org policy).
  - **Do not run pytest while running live `/api/chat` probes.** The suite purges
    the shared `analyst@auspex.dev` user mid-turn.
  - **Any new test that spends inference calls must refund them.** Chat tests
    belong in test_chat_sse.py, whose autouse fixture refunds them.
  - **A probe that files proposals must reject them afterwards.** A probe that
    creates observables deletes only what it created. Enrichment skips
    reserved address space, so use a routable IP when one must be recorded.
- **Judging a classifier or resolver change.** Have TWO subagents write
  batteries without reading the repo. Build on one; open the other once, after
  the rule is frozen. Three operating points are pinned (D-044, D-047,
  D-050), and every battery behind them is training data now.
- **The output rail.**
  - **Two calibrated floors.** `SHINGLE_WORDS = 8` and
    `THINKING_SHINGLE_WORDS = 40` (D-040, margin only 1.4× over the live
    legitimate ceiling of 28). The index has grown three times without a
    re-calibration: TD-044, this session's goal 2.
  - **Assume the rail has a fourth defect** (S23, S24 and S26 each found one).
    Any new text the agent is told in the system message or the descriptions
    goes into the index. Tool-result text is unindexed by D-031's design.
  - **Do NOT re-open the guard regex.** TD-031/032/033 are ratified.
- **Code-decided verdicts (D-043).** Alert and phishing answers are held,
  re-asked once, then code-rendered. Any change to those modes keeps
  `contract_repair` honest.
- **Approval state machine (D-041, D-048).**
  - **One status-CHECK migration block, edited in place** (it now includes
    `withdrawn`). `test_startup_survives_every_status_a_proposal_can_be_in`
    reads the live constraint.
  - **Claims are tokens.** Any new claim mints `claim_token`, and any new finish
    must match it.
  - **The approval lives in `decided_by`/`decided_at`.** Later human decisions
    (keep, abandon, run-now, withdraw, anything new) write
    `resolved_by`/`resolved_at`.
  - A door that can race an in-flight approve must be stale-only
    (STALE_CLAIM_SECONDS), like abandon and D-048's two.
- **Code conventions.**
  - Reuse caps, never re-declare them. A tunable that belongs to us is a code
    constant (D-026).
  - **Any new assertion over an EXTRACTED set needs a floor.**
  - Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
  - New package directory? → `pyproject.toml` packages AND the Dockerfile
    skeleton (**120 modules**).
  - The classify package must never contain the name of an HTTP library, even
    in a comment: a structural test scans its source.
- **Gates and promises.**
  - The CI gate is real (D-028): `.github/workflows/ci.yml` runs `./ci.sh` only.
  - The README is a promise pinned by `tests/test_docs.py`: its test count must
    equal the collected count on a full run, and the honesty claims are
    pinned. Every test-adding commit updates the count.
  - `./scripts/demo.sh` must keep running end to end.
  - DECISIONS.md entries are immutable once ratified; overturning one is a NEW
    numbered decision naming which it supersedes. D-033…D-050 are ratified.
    **D-002 was re-affirmed at S28 (D-047): the engine is never named
    user-visibly.**
- **Brand (D-002, locked).** Never leak the underlying model or provider name
  into user-visible strings, including "glm", "zhipu" and "z.ai"
  (`FORBIDDEN_ENGINE_NAMES`). Endpoint errors use `LLMError.public`. On an
  identity question the shortcut misses, the model may still name a vendor in
  the answer or the Thinking pane. That is recorded, not owned; do not fix it
  unasked.
- **Deferred; do NOT pick up unless explicitly re-scoped:**
  - KB-doc citability / ioc_check→KB-CVE-context (parked 20×);
  - TD-014; TD-015; TD-016; TD-017; TD-019; TD-020; TD-021; TD-022; TD-023;
    TD-024; TD-025 (idempotency matters the day an action reaches a network);
  - **TD-027 (HARD GATE)**; TD-029; TD-030; TD-031/032/033;
  - the card stream emitting status changes;
  - model-PROPOSED hypotheses/evidence and falsifiers (D-019-later, D-021);
  - the model fabricating incident specifics the contract validator passes
    (probe record 2026-10-10-zai-endpoint, seen on every run).
