# STATE — Auspex

_Last updated: 2026-10-10 (**S26 IN PROGRESS — not closed; no session-end ritual
has run.** Step 0 done on 2026-08-16 (promote #26, review: 1 defect fixed). The
session then stopped mid goal-item-1 for eight weeks. Resumed 2026-10-10 to find
**the dev LLM gone** (Scout's Northflank host is NXDOMAIN); the day went to
replacing it: **D-033** (base URL = the provider's documented root; thinking
read under either spelling) and **D-034** (dev LLM = glm-4.5-air on Z.ai's
general pay-as-you-go API). `./ci.sh` green, **1094 tests**, 119 modules.
**Goal item 1 — the routing decision — is untouched since 2026-08-16 and must
now be re-measured on the new model.**)_

## S26 so far (read this first)

- **Step 0 (2026-08-16):** promote #26 merged; fresh-eyes review fixed `f931c98`
  (a turn the endpoint never answered reported that it answered), strengthened
  the anti-drift test (`e684671`), gave TD-036 a second consequence. Record:
  docs/probes/2026-08-16-s26-step0-review.md.
- **Goal item 1 (2026-08-16, unfinished, UNCOMMITTED):** three probes in
  `docs/probes/s26-step0/` — `probe_refusal_cause.py` (got **0 refusals in 12**
  through `run_stream` with the loop's own system message — S25's "Scout
  refuses" may not hold on the route's real conditions), `probe_s25_refusal_replay.py`
  (S25's exact cell ×6 — never confirmed run), `probe_routing.py` (the proposed
  rule: agent path iff mode is not ALERT_TRIAGE/PHISHING_ANALYSIS **and** the
  classifier found an actionable observable; plus the first multi-step
  measurement). **All three measured SCOUT. Scout no longer exists — re-run them
  against glm-4.5-air before deciding anything.**
- **The LLM replacement (2026-10-10), 11 commits `7f07676`…`56213c1`:**
  - Docs read first (6 agents, ~30 pages + openapi.json), then the wire:
    docs/probes/2026-10-10-zai-endpoint.md. Four doc claims failed on the wire.
  - **D-033** — `LLM_BASE_URL` is the provider's documented API root, the client
    appends only `/chat/completions` and `/models` (`e09e6f9`); thinking is read
    as `reasoning` OR `reasoning_content`, never configured (`9431e03`);
    `LLM_EXTRA_BODY` admissible only on measurement — **not born**, the native
    path made it unnecessary. Every Ollama root is now spelled `…:11434/v1`.
  - **D-034** — four models through the platform's own harness: glm-4.5-air
    **95 % completion, 348 s, $0.20/$1.10** (best any dev endpoint has posted);
    glm-5.3-flash 95 % but 2.9× slower; glm-5.2 92.5 % at 7×/4× the price;
    glm-4.7-flashx 87.5 % and 1.6 tok/s. **General endpoint + pay-as-you-go
    only** (Coding Plan terms forbid app use); **dev only** (Singapore — never
    KSA-tenant data).
  - Adversarial review (12 agents) of the two client commits: 2 real gaps fixed
    (`fd07cd0` two missed Ollama roots, `e9c55b2` three test boundaries pinned
    by mutants), 42 suspicions cleared, and **one pre-existing defect made
    load-bearing** — see follow-up 9.
  - `GLM_API_KEY` (Burhan's) born in `.env.example` + ENV_VARS.md — the
    zero-new-env-vars run ends at twelve sessions, deliberately.
  - **Live through the app:** as configured, deep turns run TWO-PASS and the
    Thinking pane is **empty** (the model's thinking eats pass 1's 256 tokens);
    on the native path it streams thinking from ~3 s, one call instead of two.

## Where we are

**Phase 4 is contract (S17) + decision loop (S18) + hardened input and spend
(S19) + a pipeline, docs and a demo anyone can run (S20) + the beta debt paid
down (S21) + an output rail (S22) + that rail's defects found (S23) + the rail's
FIX's defects found and the agent given something to do (S24) + the tools proven
as prompts and the loop taught to stream (S25). The ROADMAP through S20 is
complete; S21–S25 were each scoped by a decision rather than a plan.**

- **S25 Step 0 — `/promote` done first.** PR **#25** merged as squash `c3e6728`
  (2026-08-16), back-merged `b5201b2`, tree verified **byte-identical to both**
  pre-merge and `origin/main`. Real diff **17 files, +1921/-300**. The commit LIST
  again showed ~280 commits back to S2 — **read the diff, never the list.**
  Both PR checks SUCCESS; `gh pr merge --squash` again printed **nothing** on
  success.
- **S25 Step 0 — fresh-eyes review (DONE: 2 defects fixed, 4 suspicions cleared).**
  Record: docs/probes/2026-08-16-s25-step0-review.md; harness in
  docs/probes/s25-step0/. Both fixes **proven to fail pre-fix** by neutralising
  only the changed statement.
  - **(FIXED) one tool argument holding three indicators was answered about one.**
    `_resolve` kept `parsed[0]` per item. The analyst's "check these three" came
    back reading as complete while two were **never sent to a provider** —
    `unresolved` empty, nothing in the payload saying so. That is *not-checked*
    rendering as *no-signals*, the collapse `capabilities.py`'s own docstring
    calls "the whole of the DEFERRED rail", and its own promise ("never dropped")
    inverted. **Latent, not unreachable:** measured live, Scout sends three
    separate array items — but `_as_list` exists specifically to accept a bare
    string, and a bare comma-separated string arrives as ONE item (measured).
    Same argument that ratified S24's carry fix. Now every observable a string
    yields is kept, bounded by the existing `MAX_TOOL_ARG_ITEMS` and named as
    `omitted_observables` when it overflows.
  - **(FIXED) a bare number in a tool argument raised.** `list(5)` → `TypeError`,
    degraded by the loop to `tool raised TypeError` — a message naming a Python
    type, which the model cannot act on, costing it a step. A bare *string* was
    already treated as a formatting choice; a bare number now gets the same
    honest answer.
  - **(CLEARED, and recorded as cleared) 4 suspicions.** `autouse` is sound (no
    test in test_chat_sse.py asserts a limit or a usage count; `clean_usage`
    resets before AND after; `ci.sh:23` runs pytest **serially** so the DELETE
    cannot race the app's claim). The stale-read pin's monkeypatch cannot leak
    (`ActionExecutor` builds its own `ProposalSettlement`). **No provider failure
    can leak configuration into a tool result** — every reason is a fixed literal,
    the raw exception goes only to the logger. The "unbounded model string" lead
    dissolves: `max_tokens=2000` bounds one call's whole argument blob to
    single-digit KB, `lookup_ids` builds **term** clauses not a query-string, and
    `enrich` does not persist so no NUL reaches Postgres.
- **S25 — D-032 ratified: `main`'s protection is procedural.** Burhan's call,
  asked once at the start ritual. It **cannot** be enabled (private repo, free
  plan; both mechanisms 403 — probed at S24), publishing the repo would expose
  candid working documents, and what has actually held for eight promotes is
  `/promote` refusing anything but a CLEAN check. **This item has left in-flight
  follow-ups permanently.**
- **S25 goal item 2 — DONE: the tool descriptions work as PROMPTS.** Record:
  docs/probes/2026-08-16-s25-tool-choice.md. Nothing had measured this — every
  S24 call was made directly. Live against Scout: **8 of 8**, right tool and right
  arguments, including the `lookup_cve` / `search_knowledge` boundary. D-031's
  streaming shape re-confirmed independently (`content chars: 0` before every
  tool call).
  - **The control found something the wiring must handle.** Asked a question no
    tool answers, Scout **refused** — "the functions provided are insufficient" —
    despite a system message telling it to answer anyway. **Offering tools changes
    what the model does with questions the tools do not cover.**
- **S25 goal item 1 — the MECHANISM shipped; the route deliberately untouched.**
  `AgentLoop.run_stream` + 15 tests + a live probe
  (docs/probes/2026-08-16-s25-run-stream-live.md).
  - All five D-031 decisions: tool steps **narrated before** the answer streams;
    arguments folded by `fold_stream_event` — extracted from `accumulate_stream`
    so the streaming and blocking turns cannot hold two opinions; the presence of
    tool calls is the step signal, read through the channel; the usage claim is
    **per model call** including the synthesis pass (TD-018 breaks otherwise);
    and `system_message()` is public so the rail can index the **composed**
    message.
  - **`run` and `run_stream` share `wire_specs`/`_initial_messages`**, pinned by a
    test asserting both compose identical messages.
  - **Proven by three neutralisations**, each failing exactly its own tests: the
    one-blob buffer (a bug I wrote first — the delta-count floor caught it),
    claiming once up front, and last-fragment-wins folding. The fragment test is
    parametrized 1/4/9 so **1 stays green** while 4 and 9 fail — the control is
    arithmetic.
  - **Live-verified** against Scout and the real services: 1 tool step (real
    enrichment, `executed`), **79 content deltas**, **2 claims for 2 calls**,
    `max(tool_index) < min(content_index)`. The model wrote its answer from tool
    **data**, not our renderers.
- **CI-green: 1073 tests** (1052 at S24 end → **+21**). `./ci.sh` green including
  the installed-dist gate (**119 modules**); `/api/health/ready` 200;
  `./scripts/demo.sh` **exit 0** end to end. **Zero new env vars — twelve
  sessions running.**

- **S20–S24 (kept for context).** S20 made CI a check anyone can see (D-028) and
  gave the repo its README and `scripts/demo.sh`. S21 closed TD-026/TD-028a. S22
  shipped TD-012(a) as `auspex/outguard.py` (D-030). S23 fixed two rail defects
  and measured the loop's streaming shape (D-031). S24 fixed three defects and
  gave the agent its three READ tools. Earlier sessions are in git history and
  DECISIONS.md.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: EMPTY.** Promote **#27** merged 2026-10-10 as squash `8631307`
   (S25 slate + S26 Step 0 + the LLM replacement + D-035 + D-036; real diff 82
   files, +9847/−91), back-merged `856c1da`, staging tree **byte-identical** to
   `origin/main`. Both PR checks SUCCESS; `gh pr merge --squash` again printed
   nothing on success. **`gh` WAS on the work account at the start of the promote**
   — switched back with `gh auth switch --user bh3082336888-cell`.
   - **Read the diff at promote time. Never trust the commit LIST.**
2. ~~**Branch protection on `main`.**~~ **CLOSED at S25 — D-032 ratified.** It is
   procedural, by decision. Not a task, not a blocker. Do not re-open it.
3. **TD-028b is the sharpest open half of TD-028** — a failed execute leaves
   effects it denies. (c) is sharper since S21, and **TD-034 folds in**. S22–S25
   have all worked in those four statements — freshly mapped four times now.
4. **The card stream still emits only new cards, never status changes** — a client
   watching `/stream` is not told when a claim goes stale.
5. **TD-031 / TD-032 / TD-033 are ratified bounds, not a backlog.** Do **not**
   re-open the guard regex. **S23, S24 and S25 all touched it not at all.**
6. **TD-005 trigger, still armed:** cve pool > 300k chunks, curated pool > 5k, any
   new doc_type, any embedding-model change, **or before any free-text-over-CVEs
   surface ships** (TD-027 is a HARD GATE). Corpus at S21: **31,828**. Not tripped.
7. **`SHINGLE_WORDS` is a calibrated number, not a constant to edit** — re-run
   `docs/probes/s22-outguard/probe_calibrate2.py` before moving it. Same rule
   NEURAL_FLOORS has. **S25 did not touch it.**
8. **Test usage isolation is DESIGNED for test_chat_sse.py and still incidental
   everywhere else.** Verified independently at S25: that file is safe and its
   DELETE cannot race within a run (pytest is serial). Any *other* file whose
   tests spend inference calls has the same 29-unit problem waiting — all
   dev-login users share the `default` workspace against an **hourly** ceiling of
   100, and nothing resets it at session start. **test_agent_stream.py is fakes
   only and spends nothing.**
9. **FIXED at S26 (D-035, `b3f8a4e`) — live-verified: the default endpoint now
   finds its own scorecard** (reserved `__deployment__` workspace; harness writes
   it, chat reads it; no user can be provisioned into it). The hand-seeded row is
   deleted; the dev deployment's row is `a8113b41…`, written by the harness.
   **TD-037, now LOW (D-036, `332fa35`):** nothing in a production deployment
   writes that scorecard, but two-pass no longer breaks on a thinking model — a
   pass 1 that opens with the model's own thinking hands the turn to the native
   path (live: pane 0 → 5527 chars, two calls claimed and made). What remains is
   one abandoned pass-1 (~2 s) per turn on an unprobed thinking endpoint.
   History of the defect below.
   **(was) The scorecard's writer and reader disagree on scope.**
   The only writer (`scripts/llm_harness.py`) saves to workspace `dev`; the only
   reader (`_default_native_reasoning`, chat.py) reads the ANALYST's workspace
   (`default`). So the configured default endpoint never finds its scorecard,
   and on a thinking model the two-pass path it falls back to is **measured
   broken** (empty Thinking pane, a wasted call per turn — probe record
   2026-10-10 §"Through the running app"). **Dev workaround in place:** the
   glm-4.5-air row was copied into `default` by hand (row `b747b841…`). The real
   fix needs Burhan's call — the default endpoint is configured per DEPLOYMENT,
   so either its scorecard is looked up deployment-wide by fingerprint, or the
   app probes it at startup into a deployment-scoped row. Original note follows.
   **The persisted scorecards have no `native_reasoning` key.** All four rows
   predate the field (probed 2026-07-15), so `_default_native_reasoning` resolves
   **False** and the default endpoint takes the **two-pass** path. The native path
   is therefore **unexercised in the running app** — and D-031's measurements, plus
   S25's live `run_stream` probe, were both taken on the native one. **This is now
   directly load-bearing:** the route wiring must not assume the path it wires is
   the path that runs.
10. **(S26: measured on SCOUT only — re-measure on glm-4.5-air.)** **NEW — offering tools changes what the model does with questions the tools do
    not cover.** Scout refused a general question rather than answering it, with
    an instruction telling it to answer. The route wiring must decide this
    deliberately: either the 92/8 classifier keeps such turns off the agent path,
    or the composed system message handles it — and **the obvious instruction was
    measured not to be enough.**
11. **NEW — the tool-results scanner channel must be ONE literal.** The S24
    comment closes `OutputScanner._carries`'s key space by convention ("call sites
    pass literals"). A per-tool-call channel name would grow that dict without
    bound inside one turn. No defect exists yet; the wiring must not create one.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — `/api/chat` still does not use the
   agent loop. **The design is settled and measured (D-031), the tools exist and
   are live-verified (S24), they are proven to work as prompts (S25), and the
   streaming mechanism exists and is live-verified (S25). What remains is the
   ROUTE.** Open: TD-012**(b)**, TD-014 … TD-025, TD-027, **TD-028b/c/d**, TD-029,
   TD-030, TD-031/032/033, TD-034, **TD-035**, **TD-036**.
   **TD-018, TD-026, TD-028a and TD-012(a) are CLOSED.**
3. ~~**The agent has no tools.**~~ **CLOSED in S24.** ~~**No model has chosen
   one.**~~ **CLOSED in S25** — 8 of 8 live, right arguments. What remains
   unmeasured is **multi-step** behaviour: whether a model chains tools and stops
   when it has enough. Every measured turn so far is one tool call.
4. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
5. **Corpus 31,828 docs and growing while the container runs.** TD-011 tracks the
   index rollover trigger.
6. **Two rails, and neither is a closure.** The INPUT guard bounds accidents and
   naive attempts (D-027, D-029). The OUTPUT rail (D-030) catches our
   configuration coming back out, **but not a paraphrase, and not an injection
   that merely made the answer wrong**. S23 found it off for a whole pass; S24
   found its fix had a hole. **S25 did not touch it** — the run_stream work is
   upstream of it. Two consecutive sessions found a defect there; **assume a third
   exists**, and the route wiring runs straight through it.
7. **An intermittent, unattributed test failure was observed once in S22.** Not
   reproduced in S23's six, S24's four or S25's three further full-suite runs.
   Still recorded rather than dismissed.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`.
- Ollama 0.34.0 on :11434 (was 0.32.5; seen 0.34.0 at the 2026-10-10 S26
  resume ritual) (root `http://localhost:11434/v1`, D-033); models
  qwen3:14b / llama3.1:8b / mistral:latest.
- **Primary dev LLM is glm-4.5-air on Z.ai (D-034)** — `https://api.z.ai/api/paas/v4`,
  pay-as-you-go key in `.env` as both `GLM_API_KEY` and `LLM_API_KEY`. **Never the
  Coding Plan endpoint.** Thinking is on by default and billed inside
  `completion_tokens`; **prose precedes tool calls** (TD-036 triggered);
  `json_schema` is silently ignored. glm-4.7-flash (free) answered 429
  "overloaded"; glm-4.7-flashx hung once past 180 s. Rate limits are console-only.
- **Scout on Northflank is GONE** — `p01--new-llm--…code.run` is NXDOMAIN (2026-10-10).
- **S25 session-end (2026-08-16):** staging, tree clean, identity
  `bh3082336888-cell`. All three containers healthy; `./ci.sh` **green, 1073
  tests, 119 modules**; `/api/health/ready` **200**; `./scripts/demo.sh` **exit 0**.
- **`gh` did NOT flip to the work account at S25** (checked at the ritual and
  before every `gh` call — six of them). It DID at S18 and S16; did not at S17,
  S13–S15, S19–S25. **Unpredictable is the pattern** — re-check before EVERY call.
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
- **A live `run_stream` probe against Scout takes ~15s** and needs no container —
  it runs from `.venv` against the app's own `from_settings` constructors.
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
**Resume S26 in a fresh window (NEXT-SESSION.md has the full prompt).** Nothing to
promote; Step 0 is done; the dev LLM is glm-4.5-air (D-034).

Then the S26 goal, unchanged in substance: **wire the agent path into
`/api/chat` (D-031).**

1. **Re-measure the routing question on glm-4.5-air FIRST.** The three
   uncommitted probes in `docs/probes/s26-step0/` all measured Scout, which no
   longer exists; Scout's "refuses a question no tool answers" (S25) was already
   0-for-12 under the route's real conditions. Re-run them, record, then decide.
2. **The wiring itself** — as before, PLUS the TD-036 buffer, which is no longer
   optional: on this endpoint prose precedes tool calls (one sentence of
   narration, measured; probe record Finding 9).
3. ~~Check which path actually runs~~ — **answered at S26**: on dev the default
   endpoint has a deployment scorecard (D-035) and runs NATIVE; an unprobed
   thinking endpoint switches to native from pass 1 (D-036).
4. **TD-028 (b/c/d) + TD-034 together.**
5. **TD-012(b)** — contract-conformance repair.
