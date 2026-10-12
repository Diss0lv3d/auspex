# SESSION-RULES — standing rules for every session, whatever its track

_D-051. `/session-start` reads this file together with the track's prompt
(`NEXT-SESSION-BE.md`, `NEXT-SESSION-FE.md` or `NEXT-SESSION-BUGS.md`). A rule
lives here ONCE. A track prompt holds only what is about that one session.
Numbers that move every session (test count, module count, the promote slate)
live in `STATE.md`, never here and never in a prompt. Change a rule here when
it changes, in its own commit._

## LLM endpoints

- The primary dev LLM is **glm-4.5-air on Z.ai's general API (D-034)**:
  `LLM_BASE_URL=https://api.z.ai/api/paas/v4`, key in `.env` as `LLM_API_KEY`.
- Local Ollama `qwen3:14b` at `http://localhost:11434/v1` is the
  secondary/offline endpoint (D-013), and it is what the session-start
  local-Ollama gate validates. **The page's endpoint switcher can route a turn
  to it** (dev-only, D-016). It is slow: ~30 s to first token, minutes per deep
  turn (docs/probes/2026-10-12-b001-ip-owner-claim.md). Know which endpoint a
  turn ran on before judging its speed or its answer.
- **A switcher endpoint always takes the conversational path, with no tools**
  (D-037: it carries no agent mode). So does a customer endpoint that is not
  `native_tools`. The dev endpoint itself takes the agent path. To see what
  the conversational path does on the dev endpoint, replay at it with the
  route's own composition
  (docs/probes/b1-b001/probe_replay_conversational.py, B1).
- The app probes its endpoint at startup and re-checks every 6 h (D-038, D-042).
  The scorecard expiry date is in STATE.md (Host notes). After it, a running
  container re-probes (~15 calls). **If it logs the "endpoint changed" WARNING,
  re-measure D-040's thinking floor before anything else.**
- Any mismatch → STOP and tell Burhan.

## `gh` (D-011)

- `gh` flips to the work account between and during sessions; assume it has and
  re-check before every call:
  `gh auth switch --hostname github.com --user bh3082336888-cell`.
- `gh pr edit` fails on this repo with a Projects-classic GraphQL error; use
  `gh api -X PATCH repos/.../pulls/N`.
- `gh pr merge --squash` prints nothing on success; verify with
  `gh pr view <n> --json state,mergeCommit`.
- Local `main` goes stale every promote. `git fetch`, then read
  `git diff origin/main..staging --stat`, **never the commit list**.

## Running things

- The app container runs the built image, so live verification needs
  `docker compose up -d --build app`. That includes the page: the static files
  are baked into the image too.
- Run the suite the way `ci.sh` does (`.venv`, package installed editable).
- **Never pipe `./ci.sh` into `tail`**: the pipeline reports `tail`'s exit code.
- **Run the full gate before calling a change done.** Twice (S27, S28) a change
  passed every file it touched and broke a test in one it did not.
- Do not edit code while `./ci.sh` is running: the edit lands in its container
  build.
- **One session at a time (D-051).** Every track shares `staging`, the compose
  stack and the `analyst@auspex.dev` test user. Two windows on two tracks would
  collide.

## Process

- Tests ship with each step (CLAUDE.md rule 8). CI stays hermetic.
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, then
  move on. Tired human = short session; rituals anyway.
- One concern per commit, and never amend (org rule).
- Scope lock: new ideas → `/idea` (IDEAS.md); a bug found mid-session →
  `/bug` (BUGS.md). Neither is worked on in the session that found it.
- **A promote slate is NOT EMPTY when STATE.md says so.** The first session of
  any track runs `/promote` as its Step 0.
- **The two untracked overview files are Burhan's and stay untracked**
  (`Auspex-Product-Architecture-Overview.pdf`, `docs/auspex-overview.html`).
  Do not ask about them, commit, move, publish or delete them.
- End with `/session-end`.

## Inference costs real money

- Z.ai is pay-as-you-go: glm-4.5-air is $0.20/$1.10 per 1M tokens, and thinking
  is billed inside `completion_tokens`. A thin-topic agent turn is at most ~5
  calls (D-046). Budget probes.
- General endpoint only, pay-as-you-go only, dev only. Never
  `api/coding/paas/v4`. Z.ai processes in Singapore, so **no KSA-tenant data,
  ever** (org policy).
- **Do not run pytest while running live `/api/chat` probes**, and do not run
  it while a chat you still need as evidence lives only in Postgres. The suite
  purges the shared `analyst@auspex.dev` user and its chats.
- **Any new test that spends inference calls must refund them.** Chat tests
  belong in test_chat_sse.py, whose autouse fixture refunds them.
- **A probe that files proposals must reject them afterwards.** A probe that
  creates observables deletes only what it created. Enrichment skips reserved
  address space, so use a routable IP when one must be recorded.

## Judging a classifier or resolver change

Have TWO subagents write batteries without reading the repo. Build on one; open
the other once, after the rule is frozen. Three operating points are pinned
(D-044, D-047, D-050), and every battery behind them is training data now.

## The output rail

- **Two calibrated floors.** `SHINGLE_WORDS = 8` and
  `THINKING_SHINGLE_WORDS = 40` (D-040, margin only 1.4× over the live
  legitimate ceiling of 28). Whether the index has grown since the last
  calibration is TD-044.
- **Assume the rail has a fourth defect** (S23, S24 and S26 each found one). Any
  new text the agent is told in the system message or the descriptions goes
  into the index. Tool-result text is unindexed by D-031's design.
- **Do NOT re-open the guard regex.** TD-031/032/033 are ratified.
- **The stream is scanned as it goes.** Anything that buffers, batches,
  re-chunks or re-orders what reaches the page (server or client) must keep
  the rail's carry (`OutputScanner.feed`), D-031's ordering guarantee and the
  native-only narration hold. A faster stream that skips the scan is a leak.

## Code-decided verdicts (D-043)

Alert and phishing answers are held, re-asked once, then code-rendered. Any
change to those modes keeps `contract_repair` honest.

## Approval state machine (D-041, D-048)

- **One status-CHECK migration block, edited in place** (it includes
  `withdrawn`). `test_startup_survives_every_status_a_proposal_can_be_in`
  reads the live constraint.
- **Claims are tokens.** Any new claim mints `claim_token`, and any new finish
  must match it.
- **The approval lives in `decided_by`/`decided_at`.** Later human decisions
  (keep, abandon, run-now, withdraw, anything new) write
  `resolved_by`/`resolved_at`.
- A door that can race an in-flight approve must be stale-only
  (STALE_CLAIM_SECONDS), like abandon and D-048's two.

## The page (front end)

- **Model and tool text reach the page as text, never as HTML.** The page
  writes them with `textContent`/`append` (`auspex/static/index.html`);
  `innerHTML` holds only fixed templates.
  - The answer bubble renders a safe markdown subset (D-053). A pure parser
    builds elements the page chose, with `createElement` and text nodes, and
    https-only links that show their host.
  - Widening that subset, or rendering any other pane, is a new decision, not
    a refactor.
- **The page's logic lives in its `// <page-logic>` block**: pure functions,
  run under Node by `tests/js/page_logic.test.mjs` inside the pytest gate.
  New page behaviour goes there, with tests, and the DOM wiring stays thin.
- **The stream is paced on the page within 200 ms (D-052)**, and a `status`
  frame says what a turn is waiting on. A new wait gets an announcement.
- Colours, fonts and voice are D-002's (CLAUDE.md, Brand). Labels are
  brand-safe: the engine is "the platform's engine", never a model or vendor.
- A page change is verified in a real browser against the rebuilt container,
  not only by reading the diff.

## Code conventions

- Reuse caps, never re-declare them. A tunable that belongs to us is a code
  constant (D-026).
- **Any new assertion over an EXTRACTED set needs a floor.**
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
- New package directory? → `pyproject.toml` packages AND the Dockerfile
  skeleton (module count: STATE.md).
- The classify package must never contain the name of an HTTP library, even in
  a comment: a structural test scans its source.

## Gates and promises

- The CI gate is real (D-028): `.github/workflows/ci.yml` runs `./ci.sh` only.
- The README is a promise pinned by `tests/test_docs.py`: its test count must
  equal the collected count on a full run, and the honesty claims are pinned.
  Every test-adding commit updates the count.
- `./scripts/demo.sh` must keep running end to end.
- DECISIONS.md entries are immutable once ratified; overturning one is a NEW
  numbered decision naming which it supersedes. **D-002 was re-affirmed at S28
  (D-047): the engine is never named user-visibly.**

## Brand (D-002, locked)

Never leak the underlying model or provider name into user-visible strings,
including "glm", "zhipu", "z.ai", "qwen" and "ollama" (`FORBIDDEN_ENGINE_NAMES`).
Endpoint errors use `LLMError.public`. On an identity question the shortcut
misses, the model may still name a vendor in the answer or the Thinking pane.
That is recorded, not owned; do not fix it unasked.

## Deferred; do NOT pick up in any track unless explicitly re-scoped

- KB-doc citability / ioc_check→KB-CVE-context (parked 20×);
- TD-014; TD-015; TD-016; TD-017; TD-019; TD-020; TD-021; TD-022; TD-023;
  TD-024; TD-025 (idempotency matters the day an action reaches a network);
- **TD-027 (HARD GATE)**; TD-029; TD-030; TD-031/032/033;
- the card stream emitting status changes;
- model-PROPOSED hypotheses/evidence and falsifiers (D-019-later, D-021);
- the model fabricating incident specifics the contract validator passes
  (probe record 2026-10-10-zai-endpoint, seen on every run). B-001 was fixed
  without it (D-055: the platform hands the model the owner it had). B-005
  lives next to it; a fix that needs this item goes to Burhan first.
