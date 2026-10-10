# STATE — Auspex

_Last updated: 2026-10-11 — **S27 CLOSED** (session-end ritual run). `./ci.sh`
green: **1257 tests, 120 modules**. `/api/health/ready` 200,
`./scripts/demo.sh` exit 0, branch `staging`, tree clean apart from Burhan's two
untracked overview files. **Not promoted:** everything after promote #28
(`d87469a`) is on staging only: D-042…D-045 and the review fixes._

## S27 — what happened (read this first)

S27 ran 2026-10-10 into 2026-10-11. At the start ritual Burhan answered the
candidates question with **"dont park anything, do everything"**, so all three
candidates joined the goal. Six things happened, each recorded where it lives:

1. **Promote #28** (`d87469a`) shipped the S26 slate (D-037…D-041), with the
   back-merge `e907678`.
2. **A fresh-eyes review of the D-041 review's own seven fixes** found three
   defects, all fixed with tests that failed first:
   - `922f30c`: a queue row nobody looked up twins for said `[]`, which reads as
     "no twins".
   - `9458518`: `keep` and `abandon` overwrote `decided_by`/`decided_at`, which
     erased who approved the run. They now write `resolved_by`/`resolved_at`.
   - `94abbeb`: a lost undo claim said "already being undone" about a row a
     keep or an abandon had taken.

   It cleared 4 commits, recorded one bound (`be81543`: the twin index misses
   numbers that differ only in scale), and logged **TD-042**. Record:
   docs/probes/2026-10-10-s27-d041-fixes-review.md.
3. **Goal: TD-012(b) → D-043, measured first.**
   - Drift was **0/60** on security questions across both deep paths, every
     mode, and **laundering 0/6** on glm-4.5-air.
   - The repair therefore guards the one field that matters. An alert or
     phishing verdict is **held until it passes, re-asked once, then rendered
     by code**, so the analyst is never shown a verdict off the code's pin.
   - Narrative modes still stream and report. The JSON pass was declined on
     measurement.
   - Commits `51c6161`, `e96e27c`; live `5d70d7e`. Record:
     docs/probes/2026-10-10-s27-contract-drift.md.
4. **TD-041 → D-042.** The deployment scorecard expires after 7 days, and the
   running app looks every 6 h (`keep_scorecard_fresh`, `9d97ddd`).
   - A re-probe that measures nothing leaves the old scorecard standing.
   - A changed endpoint logs each changed field.
5. **Mode fallback → D-044.** A seventh mode, `general`, for deep questions
   with no security, IT, identity or payments vocabulary and no observable
   (`87a0ccb`).
   - Judged on batteries written by independent agents that never saw the
     code: approach 1 misrouted 15/40 security questions out of sample (one
     thrash-brake strike).
   - Approach 2 misroutes **9/50** and sends **24/30** non-security questions
     to general. That point is pinned as a test.
   - Live, a misrouted security question still gets a security answer; it
     loses only the section structure. Record:
     docs/probes/2026-10-11-s27-mode-fallback.md.
6. **Actions on the chat agent path → D-045** (`0e85f3f`).
   - The agent may **propose**. A call files a pending proposal, shown in the
     turn and outside the folding Thinking pane.
   - A dry run that affects nothing is not filed (`NothingToPropose`).
   - Live: one explicit ask filed one correct proposal; two turns that did
     not ask filed none.
   - Wiring it found a latent bug, fixed in `9130c39`: a real proposal id is a
     UUID, and the loop's JSON feedback died on it. Record:
     docs/probes/2026-10-11-s27-chat-actions.md.

**How the work was proven.**
- Every fix and feature shipped with tests, and every test that guards a fix
  failed first.
- Mutants were run on each new guarantee: D-043 5/5 caught, D-045 3/3, D-042
  the age gate, plus the review fixes.
- Every behaviour was checked live through the rebuilt container.
- About 120 inference calls on Z.ai, under a dollar.
- **One commit left the suite red in between:** `e96e27c` (D-043) broke a
  hardening test's call count, fixed in the next commit `c8a3fe2`. The full
  gate caught it, and no amend was made (org rule).

## Where we are

Phase 4: contract (S17), decision loop (S18), hardened input and spend (S19),
pipeline/docs/demo (S20), beta debt (S21), output rail (S22–S24), tools as
prompts and a streaming loop (S25), the agent path live in chat (S26), and
**S27: verdicts the code decides are guaranteed on screen, the deployment
re-measures its engine, non-security questions stop failing a security
contract, and the chat agent can propose actions.** The ROADMAP through S20 is
complete; S21–S27 were each scoped by a decision rather than a plan.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: NOT EMPTY.** Everything after promote #28 (`d87469a`) is
   on staging only: D-042…D-045, the three review fixes, the UUID fix. That is
   about 20 commits, 51 files, +3.3k.
   - Read `git diff origin/main..staging --stat`, never the commit list.
   - **Promote first next session.**
   - **The two untracked overview files stay untracked — Burhan's call,
     2026-10-10.** `Auspex-Product-Architecture-Overview.pdf` and
     `docs/auspex-overview.html` are his; never commit, move, publish or delete
     them, and do not ask again.
2. **S27's own code has had no second-pass review.** Each guarantee was
   mutant-checked by its author, but nobody else has read it adversarially:
   - D-043's `repaired_answer` (chat.py);
   - D-044's resolver vocabulary;
   - D-045's chat wiring, `NothingToPropose` and the page;
   - D-042's `keep_scorecard_fresh`;
   - the three review fixes.

   This is the same discipline S26 applied to its own work.
3. **The card stream still emits only new cards, never status changes.** A
   client watching `/stream` is not told when a claim goes stale, or when a row
   becomes `incomplete`/`kept`. The polled list is where those surface.
4. **TD-031 / TD-032 / TD-033 are ratified bounds, not a backlog.** Do **not**
   re-open the guard regex.
5. **TD-005 trigger, still armed:** cve pool > 300k chunks, curated pool > 5k,
   any new doc_type, any embedding-model change, **or before any
   free-text-over-CVEs surface ships** (TD-027 is a HARD GATE).
6. **Two calibrated rail numbers, neither a constant to edit.**
   - `SHINGLE_WORDS = 8` (answer, tool lines, narration, two-pass): re-run
     `docs/probes/s22-outguard/probe_calibrate2.py`.
   - **`THINKING_SHINGLE_WORDS = 40`** (a thinking model's own thinking, D-040):
     re-run `docs/probes/s26-step0/probe_calibrate_agent.py`. **Its margin is
     only 1.4×** over the live legitimate ceiling of 28, so re-measure it
     **first** on any model change. D-042 now logs a WARNING when the endpoint
     changes under the same name. That line is the trigger.
   - **S27 grew the index** with D-043's repair directive and D-045's action
     directive and descriptions. They are covered by recital tests, and every
     live S27 turn was `output_valid: true`. The legitimate ceiling was **not
     re-calibrated** with them in (TD-044).
7. **Test usage isolation is designed for test_chat_sse.py (autouse refund) and
   incidental elsewhere.** Any other file whose tests spend inference calls has
   the 29-unit problem waiting; the `default` workspace has an hourly ceiling of
   100. All S27 chat tests live in test_chat_sse.py.
8. **TD-036's bound is live, so watch for it.** Narration over 400 chars before
   a tool call would stream as answer. The route logs "agent answer differs
   from the streamed content (TD-036 bound)" when that happens. Seeing that
   line is the trigger to re-measure.
9. **The agent proposes; D-045's bounds.**
   - An action can only target an observable already persisted, which happens
     through the 92/8 IOC check. The agent path's enrichment does not persist
     (IDEAS).
   - The approvals surface serves the stored, code-rendered card unscanned.
   - A turn the rail cuts at a tool frame can still leave a filed proposal.
   - `prompted_tools` is still unwired, and the narration hold is native-only.
10. **D-041's bound, and TD-025.** A merely slow handler on an abandoned run can
    land after its put-back. It is recorded on the row, not prevented. There is
    no idempotency key: **both matter the day an action reaches a network.**
    With D-045 the chat agent can file proposals, so the approvals path will
    see more traffic. **TD-042** (approved, never started, no door) now
    matters more.
11. **Brand, unowned.** A thinking model may name itself in its reasoning, and
    the Thinking pane is user-visible. Nothing guards that: D-030/D-040 check
    for OUR configuration, not the model's name.
12. **D-043's drift log is no longer a clean trigger for the narrative modes.**
    An action-request turn ("add a note to X") resolves to `ioc_enrichment` and
    cannot fill its sections, so it logs contract drift honestly (live, D-045
    probe). Separate those before reading the log as model drift (IDEAS).
13. **D-044's operating point is pinned.** A vocabulary edit must keep
    `test_the_measured_operating_point_on_the_independent_battery_holds`. If it
    claims an improvement, prove it on a **fresh** independently written
    battery, because both existing ones are now training data.

**Closed at S27, so they leave this list:**
- the old #8 "the agent reads; it does not act" (done, D-045);
- TD-012(b) (done, D-043);
- TD-041 (done, D-042);
- the mode-resolver IDEAS line (done, D-044).

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** is a hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Open debt.**
   - Still open: TD-014 … TD-025, TD-027, TD-029, TD-030, TD-031/032/033,
     TD-035 (the two-pass path only), TD-036 (its bound), **TD-042, TD-043,
     TD-044 (new at S27)**.
   - **Closed at S27:** TD-012(b), TD-041.
   - Closed earlier: TD-018, TD-026, TD-028, TD-034, TD-037…TD-040, TD-012(a).
3. **The KB bootstrap needs outbound HTTPS once per fresh volume**, and ingest
   needs NVD/CISA/FIRST/GitHub reachability. Failures degrade honestly.
4. **The corpus keeps growing while the container runs.** TD-011 tracks the
   index rollover trigger.
5. **Two rails, and neither is a closure.**
   - The INPUT guard bounds accidents and naive attempts (D-027, D-029).
   - The OUTPUT rail (D-030) catches our configuration coming back out, but not
     a paraphrase, and not an injection that merely made the answer wrong.
     D-043 now **prevents** a wrong code-decided verdict from being shown;
     it cannot prevent a wrong narrative answer.
   - Three defects in three sessions (S23, S24, S26). **Assume a fourth
     exists.**
6. **An intermittent, unattributed test failure was observed once in S22.** Not
   reproduced in any later full run, including about six at S27. Still
   recorded rather than dismissed.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`.
- Ollama 0.34.0 on :11434 (root `http://localhost:11434/v1`, D-033); models
  qwen3:14b / llama3.1:8b / mistral:latest.
- **Primary dev LLM is glm-4.5-air on Z.ai (D-034)** — `https://api.z.ai/api/paas/v4`,
  pay-as-you-go key in `.env` as both `GLM_API_KEY` and `LLM_API_KEY`. **Never the
  Coding Plan endpoint.** Thinking is on by default and billed inside
  `completion_tokens`; **prose precedes tool calls** (TD-036 triggered);
  `json_schema` is silently ignored, `json_object` works (scorecard; D-043 uses
  neither). glm-4.7-flash (free) answered 429 "overloaded"; glm-4.7-flashx hung
  once past 180 s. Rate limits are console-only.
- **Scout on Northflank is GONE** — `p01--new-llm--…code.run` is NXDOMAIN (2026-10-10).
- **S27 session-end (2026-10-11):** staging, identity `bh3082336888-cell`.
  `gh` stayed on the personal account through promote #28; the switch was
  re-run before every call anyway. All three containers are healthy,
  `./ci.sh` is **green, 1257 tests, 120 modules**, `/api/health/ready` returns
  **200**, and `./scripts/demo.sh` **exits 0**.
- **`gh` flipped to the work account at promote #27** (also S18 and S16; not
  S17, S13–S15, S19–S25, S27). **Unpredictable is the pattern**, so re-check
  before EVERY call: `gh auth switch --hostname github.com --user bh3082336888-cell`.
- **`gh pr merge` works.** `gh pr edit` still fails with a Projects-classic
  GraphQL deprecation — use `gh api -X PATCH repos/.../pulls/N`.
- **`gh pr merge --squash` printed NOTHING on success at S24, S25, #27 AND #28**
  — do not read silence as failure; verify with `gh pr view <n> --json state,mergeCommit`.
- **`./ci.sh | tail` HIDES THE EXIT CODE.** Redirect to a file and read `$?`.
- **Run the suite the way `ci.sh` does** — `.venv`, where the package is installed
  editable. A bare `python3 -m pytest` fails the packaging test for that alone.
- **Run the FULL gate before calling a change done.** S27's `e96e27c` passed every
  file it touched and broke `test_hardening_surface.py`, which it did not.
- **This repo HAS GitHub Actions** (S20, D-028) — `.github/workflows/ci.yml` runs
  `./ci.sh` on push and PR. PR #28 ran it twice; both SUCCESS.
- **Local `main` ref goes stale every promote.** `git fetch origin` and read
  `git diff origin/main..staging --stat`, never the commit list.
- **The app container runs the BUILT IMAGE, not the working tree** —
  `docker compose up -d --build app`. In-container probes: `docker compose cp`
  the script in, then `docker compose exec -T app python /tmp/<script>.py`.
- **qwen3:14b is SLOW to first token** — a 400-token probe timed out at 5 minutes
  cold. Budget 1500 tokens and run it in the background.
- **Live probes run from `.venv`** against the app's own constructors
  (docs/probes/s26-step0/, s27-td012/) or through `/api/chat` from the host
  (`probe_app_*.py`). A glm-4.5-air agent turn takes 6–21 s and makes 1–9 calls
  (TD-043).
- **Independent batteries:** to judge a classifier/resolver change honestly,
  have a subagent write the battery WITHOUT reading the repo (S27, D-044). A
  battery that informed a change is training data from then on.
- **Startup autoprobe (D-038/D-042):** the container logs `endpoint autoprobe: known`
  and now re-checks every 6 h; the dev scorecard (row `a8113b41…`, probed
  2026-10-10 09:33 UTC) expires **2026-10-17**, after which the running
  container re-probes it (~15 calls).
- **Do NOT run pytest during live `/api/chat` probes.** The suite purges the
  shared `analyst@auspex.dev` user, and a live turn then dies on an FK
  violation.
- **All dev-login users share the `default` workspace**, hourly ceiling 100
  inference calls. See standing follow-up 7.
- **Probe residue is expensive.** Plan assertions must VACUUM first. Probes that
  file proposals must reject them afterwards (`probe_app_chat_actions.py` does).
- **THE DEMO IS ONE COMMAND: `./scripts/demo.sh`** (~3 min, end to end).

## Reference intelligence (from the SARA Open architecture study)
Base: `/home/burhan/sara-open/` — key snapshots in docs/probes/:
- ACH analogues (S12): 2026-08-08-sara-ach-analogues.md
- Phishing/header/typosquat (S11): 2026-07-18-sara-phishing-header-patterns.md
- Alert additive scorer (S10): 2026-07-18-sara-alert-triage-scorer.md
- DEFERRED rail (S9): 2026-07-18-sara-orchestrator-deferred.md
- Fast classifier / 92-8: 2026-07-16-sara-fastpath-pattern.md
- RRF retrieval + ID bypass: 2026-07-17-sara-rrf-retriever-pattern.md

## Next session should
**S28, in a fresh window (NEXT-SESSION.md has the full prompt).**
1. **Step 0: `/promote` the S27 slate** (D-042…D-045). Read the diff, not the
   list; re-check `gh` before every call.
2. **Step 0: an adversarial second-pass review of S27's own code** (standing
   follow-up 2). Reproduce by execution, fix with a test that fails first.
3. **Goal: TD-043**, the agent spending its whole step cap re-searching (9
   calls a turn). Measure, fix, re-measure with the same prompts.
4. **Goal: TD-042**, an approved run that never started has no door. Needs a
   decision (re-run vs withdraw); D-045 made it matter more.
5. Candidates only on Burhan's call at the start ritual (IDEAS.md): agent-path
   enrichment persistence; the action-request mode fit; alert-normaliser JSON
   coverage.
