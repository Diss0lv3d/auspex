# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**S27.** S26 closed on 2026-10-10 after a long day:
- the dev LLM was replaced (D-033…D-036, promote #27);
- the agent loop was wired into `/api/chat` (D-037, plus two adversarial reviews);
- Burhan delegated four debts, all resolved: D-038 (the deployment probes its
  own endpoint), D-039 (only supplied indicators reach a provider), and the TD-038
  calibration, which uncovered **D-040** (the rail was cutting legitimate
  thinking-model turns; thinking now has its own floor);
- **D-041** gave the approval state machine honest terminal states, and a
  review found 8 more defects, all fixed.

**Nothing after promote #27 is on main.** 1217 tests, 120 modules.)_

---

SESSION S27 of Auspex. The working dir must be /home/burhan/auspex-new. Run
`/session-start S27` first (the full ritual).

**LLM endpoints.**
- The primary dev LLM is **glm-4.5-air on Z.ai's general API (D-034)**:
  `LLM_BASE_URL=https://api.z.ai/api/paas/v4`, key in `.env` as `LLM_API_KEY`.
- Local Ollama `qwen3:14b` at `http://localhost:11434/v1` is the
  secondary/offline endpoint (D-013), and it is what the session-start
  local-Ollama gate validates.
- The app now probes its configured endpoint at startup (D-038). The dev
  endpoint is already measured, so the container logs
  `endpoint autoprobe: known`.
- Any mismatch → STOP and tell me.

**`gh` (D-011).** `gh` flips to the work account between and during sessions. It
flipped at promote #27, so assume it has and re-check before every call;
`gh auth switch --hostname github.com --user bh3082336888-cell` fixes it. Also:
- `gh pr edit` fails on this repo with a Projects-classic GraphQL error; use
  `gh api -X PATCH repos/.../pulls/N`.
- `gh pr merge --squash` printed nothing on success at S24, S25 and #27; verify
  with `gh pr view <n> --json state,mergeCommit`.
- Local `main` goes stale every promote. `git fetch`, then read
  `git diff origin/main..staging --stat`, **never the commit list**.

**Running things.**
- The app container runs the built image, so live verification needs
  `docker compose up -d --build app`.
- Run the suite the way `ci.sh` does (`.venv`, package installed editable).
- **Never pipe `./ci.sh` into `tail`**: the pipeline reports `tail`'s exit code.

Step 0 (do BEFORE new scope):

1. **`/promote` the S26 slate (#28).** It is everything after `8631307`: D-037…D-041,
   59 commits, a large real diff. Read the diff, not the list.
2. **Fresh-eyes review of the newest unreviewed code, the D-041 review's own
   fixes:** `cd44b4f` (one status-CHECK block), `a3cf81d` (claim tokens),
   `20fefc0` (`kept` + `POST /keep`), `60eb36c` (observe rails), `cee69e4`
   (legacy failed rows), `4679da6` (twin index), `0a5c5b1` (surface copy).
   Every other S26 change was adversarially reviewed the same day, and these
   are the fixes that review produced. Same discipline as before: reproduce by
   execution first, fix with a test that fails pre-fix, record what you clear.
3. **The two untracked overview files are Burhan's and stay untracked.** He
   decided this at S26. Do not ask, commit, move, publish or delete them.

Goal: **TD-012(b), contract-conformance repair.** It is the original S9 entry,
carried since, and the one S26 goal item not started. Read TECHNICAL_DEBT.md
TD-012 in full. Today a non-conforming answer (missing `## Risk`, an
out-of-enum value) is REPORTED in the done frame and never repaired. Streaming
means the first attempt cannot be un-sent.

1. **Measure before designing.** How often does glm-4.5-air actually drift from
   each mode's contract, on both deep paths (agent and conversational)? The
   honest denominator matters, and it is small and known: `threat_intel` on a
   non-security question always fails (see IDEAS.md). Save a probe record.
2. **Then decide the repair.** TD-012 names the path: for structured-critical
   modes (alert_triage, phishing_analysis, which stay conversational per
   D-037), request a non-streamed structured pass when the endpoint can do it,
   validate before emitting, and re-ask once on failure. **Probe first:** Z.ai
   silently ignores `json_schema` (host notes), so check what
   `json_object_mode` the scorecard records for glm-4.5-air before relying on
   either. Record the design as a numbered decision.
3. Tests ship with it; the live check goes through the rebuilt container.

Candidates. **Ask Burhan at the start ritual. Do NOT start any of these
unasked:**
- Offer ACTIONS on the chat agent path (IDEAS.md). The proposer exists; the
  chat loop is built without it.
- TD-041: re-probe the deployment scorecard on a schedule.
- A mode-resolver fallback for non-security questions (IDEAS.md).

Constraints:
- **Process.**
  - Tests ship with each step (CLAUDE.md rule 8). CI stays hermetic.
  - Thrash brake: two failed approaches on one problem → STATE.md Blockers,
    then move on. Tired human = short session; rituals anyway.
  - End with `/session-end`.
- **Inference costs real money.**
  - Z.ai is pay-as-you-go: glm-4.5-air is $0.20/$1.10 per 1M tokens, thinking is
    on by default and billed inside `completion_tokens`. An agent turn is 1–3
    calls. Budget probes.
  - General endpoint only, pay-as-you-go only, dev only. Never
    `api/coding/paas/v4`. Z.ai processes in Singapore, so **no KSA-tenant data,
    ever** (org policy).
  - **Do not run pytest while running live `/api/chat` probes.** The suite purges
    the shared `analyst@auspex.dev` user mid-turn.
  - **Any new test that spends inference calls must refund them.** Agent-path
    tests belong in test_chat_sse.py, whose autouse fixture refunds them.
- **The output rail.**
  - **Two calibrated floors.** `SHINGLE_WORDS = 8`: re-run
    `docs/probes/s22-outguard/probe_calibrate2.py` to move it.
    `THINKING_SHINGLE_WORDS = 40` (D-040): re-run
    `docs/probes/s26-step0/probe_calibrate_agent.py`; its margin is only 1.4×
    over the live legitimate ceiling of 28.
  - **Assume the rail has a fourth defect** (S23, S24 and S26 each found one).
    Any repair pass that emits text runs through it.
  - **Do NOT re-open the guard regex.** TD-031/032/033 are ratified.
- **Approval state machine (D-041).**
  - **One status-CHECK migration block, edited in place.** A second block
    stopped the app booting (S26 review, HIGH).
    `test_startup_survives_every_status_a_proposal_can_be_in` covers every
    status the live constraint allows.
  - **Claims are tokens.** Any new claim must mint `claim_token`, and any new
    finish must match it (D-041 addendum).
- **Code conventions.**
  - Reuse caps, never re-declare them. A tunable that belongs to us is a code
    constant (D-026).
  - **Any new assertion over an EXTRACTED set needs a floor.**
  - Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth. S26 added
    `GLM_API_KEY` and `LLM_AUTOPROBE_ENABLED`.
  - New package directory? → `pyproject.toml` packages AND the Dockerfile
    skeleton (**120 modules**).
- **Gates and promises.**
  - The CI gate is real (D-028): `.github/workflows/ci.yml` runs `./ci.sh` only.
  - The README is a promise pinned by `tests/test_docs.py`, including its test
    count (which must equal the collected count on a full run) and the agent-path
    honesty claims. Every test-adding commit updates the count.
  - `./scripts/demo.sh` must keep running end to end.
  - DECISIONS.md entries are immutable once ratified; overturning one is a NEW
    numbered decision naming which it supersedes. D-033…D-041 are ratified
    (D-040 and D-041 carry addenda).
- **Brand (D-002, locked).** Never leak the underlying model or provider name
  into user-visible strings, including "glm", "zhipu" and "z.ai"
  (`FORBIDDEN_ENGINE_NAMES`). Endpoint errors now use `LLMError.public`. A
  thinking model may still name itself in the Thinking pane. That is unowned;
  record it, do not fix it unasked.
- **Deferred; do NOT pick up unless explicitly re-scoped:**
  - KB-doc citability / ioc_check→KB-CVE-context (parked 19×);
  - TD-014; TD-015; TD-016; TD-017; TD-019; TD-020; TD-021; TD-022; TD-023;
    TD-024; TD-025 (idempotency matters the day an action reaches a network);
  - **TD-027 (HARD GATE)**; TD-029; TD-030; TD-031/032/033; TD-041;
  - the card stream emitting status changes;
  - model-PROPOSED hypotheses/evidence and falsifiers (D-019-later, D-021);
  - the model fabricating incident specifics the contract validator passes
    (probe record 2026-10-10-zai-endpoint, seen on every run).
