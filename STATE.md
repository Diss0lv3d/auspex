# STATE — Auspex

_Last updated: 2026-08-16 (**S25 — two more defects in day-old code, the tool
descriptions validated as prompts, and the loop learned to stream.** Promote #25
landed the S24 slate. The review found both S24 defects in one place: the
model-controlled tool-argument boundary. Then the goal's mechanism half shipped —
`AgentLoop.run_stream`, all five D-031 decisions, live-verified end to end.
**The route was deliberately NOT touched — Burhan's call.** 1073 tests.)_

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
1. **Promote slate: this session's five commits + this session-end commit.**
   `d47adea` (three indicators check three), `554623c` (a bare number is an honest
   miss), `e1722b8` (Step-0 record + tool-choice probe + D-032), `7a82697`
   (`run_stream`), `7fe35a7` (the live run_stream probe).
   **A real slate — `/promote` first next session.**
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
9. **The persisted scorecards have no `native_reasoning` key.** All four rows
   predate the field (probed 2026-07-15), so `_default_native_reasoning` resolves
   **False** and the default endpoint takes the **two-pass** path. The native path
   is therefore **unexercised in the running app** — and D-031's measurements, plus
   S25's live `run_stream` probe, were both taken on the native one. **This is now
   directly load-bearing:** the route wiring must not assume the path it wires is
   the path that runs.
10. **NEW — offering tools changes what the model does with questions the tools do
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
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
  **Primary dev LLM is Northflank Scout (D-015)** — reachable; model id
  `nvidia/Llama-4-Scout-17B-16E-Instruct-FP8`.
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
**Start with `/promote`** — five commits plus this session-end commit.

Then **wire the agent path into `/api/chat` (D-031).** Everything it depends on
now exists and is measured: the design (S23), the tools (S24), the tools proven
as prompts (S25), and the streaming mechanism, live-verified (S25). **What is
left is the route, and only the route.**

1. **Decide the routing question FIRST, because it is not a detail.** Scout
   refuses a question no tool answers. Either the 92/8 classifier keeps those
   turns off the agent path, or the composed system message handles it — and the
   obvious instruction was **measured not to be enough**. Whichever is chosen
   needs its own probe.
2. **The wiring itself:** consume `run_stream`, map its events to the SSE
   protocol, narrate `tool` events, build the leak index from
   `loop.system_message(loop.wire_specs())`, leave tool results **unindexed** and
   scan them on **one literal** channel, pass a `claim` that calls `UsageLimiter`
   per call (TD-018; **TD-035 dissolves the moment it moves**), and persist the
   `done` event's `text` as the assistant turn.
3. **Check which path actually runs.** All four persisted scorecards lack
   `native_reasoning`, so the default endpoint takes the **two-pass** path while
   every measurement was taken on the native one.
4. **TD-028 (b/c/d) + TD-034 together** — all four want a terminal state that
   records what actually happened.
5. **TD-012(b)** — contract-conformance repair, the original S9 entry.

NEXT-SESSION.md has the full prompt.
