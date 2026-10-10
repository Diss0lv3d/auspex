# STATE — Auspex

_Last updated: 2026-10-10 — **S26 CLOSED** (session-end ritual run). `./ci.sh`
green: **1217 tests, 120 modules**. `/api/health/ready` 200,
`./scripts/demo.sh` exit 0, branch `staging`, tree clean apart from Burhan's two
untracked overview files. **Not promoted:** everything after promote #27
(D-037…D-041) is on staging only._

## S26 — what happened (read this first)

S26 began 2026-08-16 (Step 0 and an unfinished goal item 1), stopped for eight
weeks, and resumed 2026-10-10. Five things happened, and each is recorded where
it lives:

1. **The dev LLM was replaced.** Scout's host is NXDOMAIN.
   - **D-033:** the base URL is the provider's documented root.
   - **D-034:** glm-4.5-air on Z.ai's general pay-as-you-go API. Dev only;
     never KSA data.
   - **D-035:** the scorecard is the deployment's.
   - **D-036:** two-pass survives a thinking model.
   - Shipped in promote #27 (`8631307`). Record: docs/probes/2026-10-10-zai-endpoint.md.
2. **Goal item 1, the routing decision → D-037.** Re-measured on glm-4.5-air:
   0 refusals in 25 tools-on runs. The agent path runs for any deep turn the
   code has not already decided (not alert triage or phishing), on an endpoint
   whose deployment scorecard compiles to native_tools **and** streams tool
   calls. Record: docs/probes/2026-10-10-s26-routing-glm.md.
3. **Goal item 2, `/api/chat` runs the agent loop.**
   - `1b86070` plus the TD-036 hold `39f1afc`, aclosing `1803253`, UI `44a040e`.
   - Two adversarial reviews; 8 fixes, including the per-turn enrichment
     budget `76be482`.
   - Live: units == calls on every turn.
   - Record: docs/probes/2026-10-10-s26-wiring-review.md.
4. **TD-037/038/039/040, delegated by Burhan → all resolved.**
   - **D-038:** autoprobe once per fingerprint (`315719c`, LLM_AUTOPROBE_ENABLED).
   - **D-039:** only supplied indicators reach a provider (`52f4fec`).
   - Brand-safe endpoint errors (`1f54b37`).
   - Tool descriptions indexed (`9e20217`).
   - **The calibration found a live rail defect → D-040** (`239df94`): a
     thinking model's thinking quotes its instructions (19–28 words, live), and
     the floor of 8 cut legitimate turns. Thinking's floor is now 40.
   - Records: docs/probes/2026-10-10-s26-rail-calibration-glm.md.
5. **Goal item 4, TD-028 b/c/d + TD-034 → D-041, what a proposal's terminal
   states say.**
   - `failed` is checked through `ActionSpec.observe`; otherwise the row is
     `incomplete` (queued).
   - Undo is allowed from incomplete/kept/abandoned; `POST /keep` → `kept`.
   - `identical_pending` twins are named, never merged.
   - Claims are tokens (`claim_token`/`abandoned_token`).
   - A review found 8 more defects, all fixed, including one **HIGH**: a second
     status-CHECK migration block that stopped the app booting with one
     `incomplete` row (`cd44b4f`).
   - Record: docs/probes/2026-10-10-s26-terminal-states.md.

**Not started: goal item 5, TD-012(b)** (contract-conformance repair).

**How the work was proven.** Every fix has a regression test that failed first.
31 mutants were run across the new guarantees; all were caught except one,
which is equivalent and recorded. Every behaviour was verified live through the rebuilt container.
About 200 inference calls on Z.ai over the day, a few dollars.

## Where we are

Phase 4: contract (S17), decision loop (S18), hardened input and spend (S19),
pipeline/docs/demo (S20), beta debt (S21), output rail (S22–S24), tools as
prompts and a streaming loop (S25), and **S26: the agent path live in chat,
the deployment measuring its own engine, and an approval state machine whose
every state says what it knows.** The ROADMAP through S20 is complete;
S21–S26 were each scoped by a decision rather than a plan.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: NOT EMPTY.** Everything after promote #27 (`8631307`) is on
   staging only: D-037…D-041, 59 commits.
   - The real diff is large; read `git diff origin/main..staging --stat`, never
     the commit list.
   - **Promote first next session.**
   - **The two untracked overview files stay untracked — Burhan's call,
     2026-10-10.** `Auspex-Product-Architecture-Overview.pdf` and
     `docs/auspex-overview.html` are his; never commit, move, publish or delete
     them, and do not ask again.
2. **The card stream still emits only new cards, never status changes.** A
   client watching `/stream` is not told when a claim goes stale, or when a row
   becomes `incomplete`/`kept`. The polled list is where those surface.
3. **TD-031 / TD-032 / TD-033 are ratified bounds, not a backlog.** Do **not**
   re-open the guard regex.
4. **TD-005 trigger, still armed:** cve pool > 300k chunks, curated pool > 5k,
   any new doc_type, any embedding-model change, **or before any
   free-text-over-CVEs surface ships** (TD-027 is a HARD GATE).
5. **Two calibrated rail numbers, neither a constant to edit.**
   - `SHINGLE_WORDS = 8` (answer, tool lines, narration, two-pass): re-run
     `docs/probes/s22-outguard/probe_calibrate2.py`.
   - **`THINKING_SHINGLE_WORDS = 40`** (a thinking model's own thinking, D-040):
     re-run `docs/probes/s26-step0/probe_calibrate_agent.py`. **Its margin is
     only 1.4×** over the live legitimate ceiling of 28, so re-measure it
     **first** on any model change (see TD-041).
6. **Test usage isolation is designed for test_chat_sse.py (autouse refund) and
   incidental elsewhere.** Any other file whose tests spend inference calls has
   the 29-unit problem waiting; the `default` workspace has an hourly ceiling of
   100. The S26 agent-path tests live in test_chat_sse.py, so they are refunded.
7. **TD-036's bound is live, so watch for it.** Narration over 400 chars before
   a tool call would stream as answer. The route logs "agent answer differs
   from the streamed content (TD-036 bound)" when that happens. Seeing that
   line is the trigger to re-measure.
8. **The agent reads; it does not act.** The chat agent path builds its loop
   with no actions, so proposals still come only from the loop's proposer,
   which chat does not offer (README honesty section; IDEAS). Also:
   `prompted_tools` is still unwired, and the narration hold is native-only.
9. **D-041's bound, and TD-025.** A merely slow handler on an abandoned run can
   land after its put-back. It is recorded on the row now, but not prevented.
   There is no idempotency key: **both matter the day an action reaches a
   network.**
10. **Brand, unowned.** A thinking model may name itself in its reasoning, and
    the Thinking pane is user-visible. Nothing guards that: D-030/D-040 check
    for OUR configuration, not the model's name.

**Closed at S26, so they leave this list:**
- the old #3 TD-028b (done, D-041);
- the old #9 TD-037 (done, D-038);
- the old #10 routing (done, D-037);
- the old #11 one-literal tool channel (done: the `tool` channel);
- the old #2 branch protection (D-032, closed since S25; do not re-open).

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** is a hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Open debt.**
   - Still open: TD-012**(b)**, TD-014 … TD-025, TD-027, TD-029, TD-030,
     TD-031/032/033, TD-035 (the two-pass path only), TD-036 (its bound),
     TD-041.
   - **Closed at S26:** TD-028 (b/c/d), TD-034, TD-037, TD-038, TD-039, TD-040.
   - Closed earlier: TD-018, TD-026, TD-028a, TD-012(a).
3. **The KB bootstrap needs outbound HTTPS once per fresh volume**, and ingest
   needs NVD/CISA/FIRST/GitHub reachability. Failures degrade honestly.
4. **The corpus keeps growing while the container runs.** TD-011 tracks the
   index rollover trigger.
5. **Two rails, and neither is a closure.**
   - The INPUT guard bounds accidents and naive attempts (D-027, D-029).
   - The OUTPUT rail (D-030) catches our configuration coming back out, but not
     a paraphrase, and not an injection that merely made the answer wrong.
   - The predicted third defect arrived at S26: the rail was cutting legitimate
     thinking-model turns (D-040). The rail is now per-channel. **Assume a
     fourth exists.**
6. **An intermittent, unattributed test failure was observed once in S22.** Not
   reproduced in any later full run, including about ten at S26. Still
   recorded rather than dismissed.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`.
- Ollama 0.34.0 on :11434 (root `http://localhost:11434/v1`, D-033); models
  qwen3:14b / llama3.1:8b / mistral:latest.
- **Primary dev LLM is glm-4.5-air on Z.ai (D-034)** — `https://api.z.ai/api/paas/v4`,
  pay-as-you-go key in `.env` as both `GLM_API_KEY` and `LLM_API_KEY`. **Never the
  Coding Plan endpoint.** Thinking is on by default and billed inside
  `completion_tokens`; **prose precedes tool calls** (TD-036 triggered);
  `json_schema` is silently ignored. glm-4.7-flash (free) answered 429
  "overloaded"; glm-4.7-flashx hung once past 180 s. Rate limits are console-only.
- **Scout on Northflank is GONE** — `p01--new-llm--…code.run` is NXDOMAIN (2026-10-10).
- **S26 session-end (2026-10-10):** staging, identity `bh3082336888-cell`
  (`gh` was not used at S26). All three containers are healthy, `./ci.sh` is
  **green, 1217 tests, 120 modules**, `/api/health/ready` returns **200**, and
  `./scripts/demo.sh` **exits 0**.
- **`gh` flipped to the work account at promote #27** (also S18 and S16; not
  S17, S13–S15, S19–S25). **Unpredictable is the pattern**, so re-check before
  EVERY call: `gh auth switch --hostname github.com --user bh3082336888-cell`.
- **`gh pr merge` works.** `gh pr edit` still fails with a Projects-classic
  GraphQL deprecation — use `gh api -X PATCH repos/.../pulls/N`.
- **`gh pr merge --squash` printed NOTHING on success at S24 AND S25** — do not
  read silence as failure; verify with `gh pr view <n> --json state,mergeCommit`.
- **`./ci.sh | tail` HIDES THE EXIT CODE.** Redirect to a file and read `$?`.
  S25 did this twice; both exit codes were read directly.
- **Run the suite the way `ci.sh` does** — `.venv`, where the package is installed
  editable. A bare `python3 -m pytest` fails the packaging test for that alone.
- **This repo HAS GitHub Actions** (S20, D-028) — `.github/workflows/ci.yml` runs
  `./ci.sh` on push and PR. PR #25 ran it twice (push + PR); both SUCCESS.
- **Local `main` ref goes stale every promote.** `git fetch origin` and read
  `git diff origin/main..staging --stat`, never the commit list.
- **The app container runs the BUILT IMAGE, not the working tree** —
  `docker compose up -d --build app`. In-container probes: `docker compose cp`
  the script in, then `docker compose exec -T app python /tmp/<script>.py`.
- **qwen3:14b is SLOW to first token** — a 400-token probe timed out at 5 minutes
  cold. Budget 1500 tokens and run it in the background.
- **Live agent-path probes run from `.venv`** against the app's own constructors
  (docs/probes/s26-step0/). A glm-4.5-air agent turn takes 6–20 s and makes 1–3
  calls.
- **Startup autoprobe (D-038):** the container logs `endpoint autoprobe: known`
  for the dev endpoint (row `a8113b41…`). A glm-5.3-flash deployment row also
  exists, written by the live probe; it is a real measurement and harmless.
- **Do NOT run pytest during live `/api/chat` probes.** The suite purges the
  shared `analyst@auspex.dev` user, and a live turn then dies on an FK
  violation.
- **All dev-login users share the `default` workspace**, hourly ceiling 100
  inference calls. See standing follow-up 8.
- **Probe residue is expensive.** Plan assertions must VACUUM first.
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
**S27, in a fresh window (NEXT-SESSION.md has the full prompt).**
1. **Step 0: `/promote` the S26 slate** (D-037…D-041). Read the diff, not the
   list; re-check `gh` before every call.
2. **Then a fresh-eyes look at the newest unreviewed code:** the D-041 review
   fixes `cd44b4f`…`0a5c5b1` (claim tokens, `kept`, observe rails, the twin
   index). Every other S26 change has had an adversarial review; these are
   the review's own fixes.
3. **Goal: TD-012(b)**, the contract-conformance repair carried since S9. It is
   the one S26 goal item not started.
4. Candidates only on Burhan's call at the start ritual (IDEAS.md): actions on
   the chat agent path; TD-041 re-probe; the mode-resolver fallback.
