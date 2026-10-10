# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**S28.** S27 closed on 2026-10-11. Burhan's call at its start ritual was
"dont park anything, do everything", so:
- promote #28 shipped S26, and a fresh-eyes review of the D-041 fixes found 3
  more defects, all fixed (TD-042 logged);
- **D-043:** a code-decided alert or phishing verdict is held until it passes,
  re-asked once, then rendered by code. It was measured first: drift 0/60,
  laundering 0/6;
- **D-042:** the deployment scorecard expires after a week, and the app
  re-measures it;
- **D-044:** a seventh mode, `general`, for questions with no security signal,
  judged on independently written batteries;
- **D-045:** the chat agent may propose actions; nothing runs until a human
  approves.

**Nothing after promote #28 is on main.** 1257 tests, 120 modules.)_

---

SESSION S28 of Auspex. The working dir must be /home/burhan/auspex-new. Run
`/session-start S28` first (the full ritual).

**LLM endpoints.**
- The primary dev LLM is **glm-4.5-air on Z.ai's general API (D-034)**:
  `LLM_BASE_URL=https://api.z.ai/api/paas/v4`, key in `.env` as `LLM_API_KEY`.
- Local Ollama `qwen3:14b` at `http://localhost:11434/v1` is the
  secondary/offline endpoint (D-013), and it is what the session-start
  local-Ollama gate validates.
- The app probes its configured endpoint at startup and re-checks every 6 h
  (D-038, D-042). The dev scorecard was probed 2026-10-10 09:33 UTC, so it
  expires **2026-10-17**. After that, a running container re-probes it (~15
  calls) and logs a WARNING if anything changed. If you see that WARNING,
  re-measure D-040's thinking floor before anything else.
- Any mismatch → STOP and tell me.

**`gh` (D-011).** `gh` flips to the work account between and during sessions;
assume it has and re-check before every call:
`gh auth switch --hostname github.com --user bh3082336888-cell`. Also:
- `gh pr edit` fails on this repo with a Projects-classic GraphQL error; use
  `gh api -X PATCH repos/.../pulls/N`.
- `gh pr merge --squash` printed nothing on success at S24, S25, #27 and #28;
  verify with `gh pr view <n> --json state,mergeCommit`.
- Local `main` goes stale every promote. `git fetch`, then read
  `git diff origin/main..staging --stat`, **never the commit list**.

**Running things.**
- The app container runs the built image, so live verification needs
  `docker compose up -d --build app`.
- Run the suite the way `ci.sh` does (`.venv`, package installed editable).
- **Never pipe `./ci.sh` into `tail`**: the pipeline reports `tail`'s exit code.
- **Run the full gate before calling a change done.** At S27 one commit passed
  every file it touched and broke a test in a file it did not touch.

Step 0 (do BEFORE new scope):

1. **`/promote` the S27 slate (#29).** It is everything after `d87469a`:
   D-042…D-045, the three review fixes and the UUID fix. Read the diff, not the
   list.
2. **An adversarial second-pass review of S27's own code.** Each guarantee was
   mutant-checked by its author, but nobody else has read it adversarially.
   Read and attack:
   - `repaired_answer` and the hold in `auspex/routes/chat.py` (D-043): order
     against the leak path, usage accounting, the two-pass and thinks-natively
     branches, what the analyst sees on every failure;
   - `_SECURITY_RE` and the `general` contract (D-044);
   - the chat wiring, `NothingToPropose`, the loop's `model_feedback` and the
     page's proposal line (D-045);
   - `keep_scorecard_fresh` and the re-probe (D-042);
   - the review fixes `922f30c`, `9458518` and `94abbeb`.

   Same discipline as before: reproduce by execution first, fix with a test
   that fails pre-fix, and record what you clear in a probe record.
3. **The two untracked overview files are Burhan's and stay untracked.** Do not
   ask about them, commit, move, publish or delete them.

Goal (two items, in order):

1. **TD-043: an agent turn on a thinly covered topic spends the whole step cap
   re-searching.** Measured at S27: 4 of 6 `threat_intel` agent turns (LockBit
   initial access, RMM abuse) made 8 `search_knowledge` calls plus synthesis,
   9 inference calls for one turn. Read TECHNICAL_DEBT.md TD-043.
   - **Measure first** with the same prompts
     (`docs/probes/s27-td012/probe_contract_drift.py` holds them). Find out
     what the tool returned on each re-search. Are they misses, near-misses,
     or the same chunks again?
   - Then fix the cause. Candidates: a miss that says rewording will not help;
     a per-tool repeat cap; the cap counting distinct results. Re-measure on the
     same prompts and record before/after. Tests ship with it. If the fix
     changes what the agent is told, it changes the rail's index too.
2. **TD-042: an approved run that never started has no door and no queue
   slot.** D-045 lets the chat agent file proposals, so this path will see
   traffic. Reproduction: `docs/probes/s27-review/probe_approved_wedge.py`.
   Decide the door, re-run (`POST /{id}/execute`, re-checking every
   `check_executable` guarantee) or withdraw (to `rejected`) or both, and record
   it as a numbered decision. Then build it with tests, live-check it, and keep
   D-041's rule: one status-CHECK block, edited in place.

Candidates. **Ask Burhan at the start ritual. Do NOT start any of these
unasked:**
- Persist the agent path's enrichment (observables and verdicts) like the 92/8
  IOC check does. Today an action can target only an indicator checked on the
  shortcut path first (D-045 bound; IDEAS).
- The action-request mode fit: "add a note to X" resolves to `ioc_enrichment`
  and reads `contract_valid: false` (IDEAS).
- Alert-normaliser coverage of JSON EDR key spellings (IDEAS).

Constraints:
- **Process.**
  - Tests ship with each step (CLAUDE.md rule 8). CI stays hermetic.
  - Thrash brake: two failed approaches on one problem → STATE.md Blockers,
    then move on. Tired human = short session; rituals anyway.
  - One concern per commit, and never amend (org rule).
  - End with `/session-end`.
- **Inference costs real money.**
  - Z.ai is pay-as-you-go: glm-4.5-air is $0.20/$1.10 per 1M tokens, thinking is
    on by default and billed inside `completion_tokens`. An agent turn is 1–9
    calls (TD-043). Budget probes.
  - General endpoint only, pay-as-you-go only, dev only. Never
    `api/coding/paas/v4`. Z.ai processes in Singapore, so **no KSA-tenant data,
    ever** (org policy).
  - **Do not run pytest while running live `/api/chat` probes.** The suite purges
    the shared `analyst@auspex.dev` user mid-turn.
  - **Any new test that spends inference calls must refund them.** Chat tests
    belong in test_chat_sse.py, whose autouse fixture refunds them.
  - **A probe that files proposals must reject them afterwards**, as
    `probe_app_chat_actions.py` does.
- **Judging a classifier or resolver change.** Have a subagent write the battery
  without reading the repo. A battery that informed a change is training data
  from then on (D-044). D-044's operating point is pinned by
  `test_the_measured_operating_point_on_the_independent_battery_holds`.
- **The output rail.**
  - **Two calibrated floors.** `SHINGLE_WORDS = 8`: re-run
    `docs/probes/s22-outguard/probe_calibrate2.py` to move it.
    `THINKING_SHINGLE_WORDS = 40` (D-040): re-run
    `docs/probes/s26-step0/probe_calibrate_agent.py`. Its margin is only 1.4×
    over the live legitimate ceiling of 28.
  - S27 grew the index with D-043's repair directive and D-045's action
    surface, and the legitimate ceiling was not re-calibrated with them in.
  - **Assume the rail has a fourth defect** (S23, S24 and S26 each found one).
    Any new text the agent is told goes into the index; any text shown goes
    through the scanner.
  - **Do NOT re-open the guard regex.** TD-031/032/033 are ratified.
- **Code-decided verdicts (D-043).** Alert and phishing answers are held,
  re-asked once, then code-rendered. Any change to those modes keeps
  `contract_repair` honest, and the code-rendered answers must stay conformant
  by construction (pinned).
- **Approval state machine (D-041, S27 review).**
  - **One status-CHECK migration block, edited in place.**
    `test_startup_survives_every_status_a_proposal_can_be_in` covers every
    status the live constraint allows.
  - **Claims are tokens.** Any new claim must mint `claim_token`, and any new
    finish must match it.
  - **The approval lives in `decided_by`/`decided_at`.** Later human decisions
    (keep, abandon, anything new) write `resolved_by`/`resolved_at`.
- **Code conventions.**
  - Reuse caps, never re-declare them. A tunable that belongs to us is a code
    constant (D-026).
  - **Any new assertion over an EXTRACTED set needs a floor.**
  - Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
  - New package directory? → `pyproject.toml` packages AND the Dockerfile
    skeleton (**120 modules**).
- **Gates and promises.**
  - The CI gate is real (D-028): `.github/workflows/ci.yml` runs `./ci.sh` only.
  - The README is a promise pinned by `tests/test_docs.py`: its test count must
    equal the collected count on a full run, and the honesty claims are pinned
    (agent path, D-043 hold, D-045 propose-never-act). Every test-adding commit
    updates the count.
  - `./scripts/demo.sh` must keep running end to end.
  - DECISIONS.md entries are immutable once ratified; overturning one is a NEW
    numbered decision naming which it supersedes. D-033…D-045 are ratified.
- **Brand (D-002, locked).** Never leak the underlying model or provider name
  into user-visible strings, including "glm", "zhipu" and "z.ai"
  (`FORBIDDEN_ENGINE_NAMES`). Endpoint errors use `LLMError.public`. A thinking
  model may still name itself in the Thinking pane. That is unowned; record it,
  do not fix it unasked.
- **Deferred; do NOT pick up unless explicitly re-scoped:**
  - KB-doc citability / ioc_check→KB-CVE-context (parked 20×);
  - TD-014; TD-015; TD-016; TD-017; TD-019; TD-020; TD-021; TD-022; TD-023;
    TD-024; TD-025 (idempotency matters the day an action reaches a network);
  - **TD-027 (HARD GATE)**; TD-029; TD-030; TD-031/032/033;
  - the card stream emitting status changes;
  - model-PROPOSED hypotheses/evidence and falsifiers (D-019-later, D-021);
  - the model fabricating incident specifics the contract validator passes
    (probe record 2026-10-10-zai-endpoint, seen on every run).
