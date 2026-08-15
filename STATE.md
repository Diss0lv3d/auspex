# STATE — Auspex

_Last updated: 2026-08-16 (**S23 — the day-old output rail had two real defects,
and both are fixed.** Step 0 was the session's substance: promote #23 merged the
whole S22 slate, then a fresh-eyes review found that **a leak in pass 1 did not
stop the turn** and that **the scanner's carry crossed a boundary that does not
exist**. The chosen goal — wire AgentLoop into `/api/chat` — landed its
**groundwork (D-031), not its implementation**, and that is stated plainly below.
**1021 tests.**)_

## Where we are

**Phase 4 is contract (S17) + decision loop (S18) + hardened input and spend (S19)
+ a pipeline, docs and a demo anyone can run (S20) + the beta debt paid down (S21)
+ an output rail (S22) + that rail's defects found and fixed (S23). The ROADMAP
through S20 is complete; S21–S23 were each scoped by a decision rather than a
plan. S24 has the clearest goal in four sessions — see "Next session should".**

- **S23 Step 0 — `/promote` done first, and the slate was the real one S22
  predicted.** PR **#23** merged as squash `5f803fc` (2026-08-15 21:32 UTC),
  back-merged `a3a11a1`, tree verified **byte-identical**, `main` and `staging`
  converged. Real diff **23 files, +2704/-365**. As always the commit LIST showed
  every commit back to S2 — **read the diff, never the list.**
- **S23 Step 0 — fresh-eyes review of the S22 commits (DONE: 2 defects fixed, 1
  bound ratified, 34 assertions pinned sound).** Record:
  docs/probes/2026-08-16-s23-step0-review.md; harnesses in docs/probes/s23-step0/.
  Every finding was read out of the code first and then **confirmed by execution**
  before anything changed; both behavioural fixes were **proven to fail pre-fix**
  by neutralising only the changed line.
  - **(FIXED — the rail was off for a whole pass) a leak in pass 1 did not stop
    the turn.** `if scanner.feed(...): break` breaks only its own loop, and a
    tripped scanner returns `None` from every later `feed()` **by design** (one
    leak, one report). So pass 2 was not merely run — it was streamed
    **completely unscanned**. Measured: **2 chat_stream calls** after the leak was
    detected, and the full pass-2 answer delivered to the analyst. The done frame
    still said `output_guard` and nothing was persisted, which is exactly why
    S22's tests passed: **they asserted the verdict, not the control flow.** Both
    S22 leak tests also used `native_reasoning=True`, so **the two-pass path — the
    one a customer endpoint without native reasoning actually takes — had no leak
    coverage at all.** It has two tests now, including one pinning that a pass-2
    leak is still caught.
  - **(FIXED — a false positive on the most ordinary shape) the carry crossed the
    reasoning/answer boundary.** `_carry` exists to make CHUNKING invisible; it
    also made a DISCONTINUITY invisible. A run with its first half in the Thinking
    pane and its second half in the answer tripped the rail although it existed as
    a run in neither — controls first: both halves individually CLEAN. `feed()`
    now takes a `channel` and a change of channel drops the carry. **The
    over-correction control ships with it**, because "stopped carrying" and
    "stopped detecting" look identical from a green test.
  - **(RATIFIED — TD-034) the late-write is one column short of its own intent.**
    It matches `status = 'abandoned'`, which does not record WHICH operation was
    abandoned, so an undo late-write stamps an `undo_result` on an
    execute-abandoned row. **Unreachable**, and the reason belongs to the claim:
    `undo` claims `WHERE status = 'executed'`. Verified by execution
    (`ExecutionRefused: not_executed`) and **pinned by a test**, so loosening the
    undo claim fails loudly and points at the statement that must move with it.
  - **(SOUND) the question the brief actually asked** — an answer reproducing a
    **whole** deterministic verdict block stays CLEAN for both `alert_triage` and
    `phishing_analysis`, including the phishing block's own contract-pinning prose.
    Also sound: three-chunk straddle, punctuation-only chunk mid-run, one-word-short
    ending, index non-empty for all six modes (180–247 runs), the two-late-handler
    race, and the newline boundary against the real `.eml` corpus (5/5 clean).
  - **The measurement discipline earned its keep in BOTH directions** (fourth
    session running). It caught a probe measuring an API the caller does not call,
    and a route regression whose two halves were each long enough to contain an
    indexed run on their own. *A green test is not evidence about what it measured.*
  - **Found while fixing: the suite's usage isolation is incidental.** Five
    unrefunded `INFERENCE_CALLS` units made the full suite **429 in one run and
    pass in the next**. The only protection today is ordering —
    `test_hardening_surface` clears the same shared workspace's counter when it
    happens to run first. The new tests refund what they take.
- **S23 goal — AgentLoop wiring: GROUNDWORK ONLY, implementation NOT done.**
  Ratified as **D-031**; record: docs/probes/2026-08-16-s23-agentloop-streaming.md.
  This is the honest state, not a soft landing: **no route code changed.**
  - **Why groundwork came first.** The loop is blocking and multi-step
    (`client.chat`, auspex/agent/loop.py:321); `/api/chat` is SSE. Which way to
    resolve that depends on a fact about the customer's endpoint, so it was
    **probed on real Scout, twice, identical both times** rather than assumed.
  - **The answer CAN stream honestly** — a tool turn emits `tool_call → finish →
    usage` with **content chars: 0**, so no prose precedes the tool results. The
    control (a question needing no tool) streamed 58 chars and `finish_reason:
    stop`, which shows the endpoint was **choosing**, not merely mute while
    `tools` was set.
  - **Arguments must be accumulated before parsing** — one IP arrived as **nine
    fragments split mid-token** (`'185', '.', '220'`). A loop parsing deltas on
    arrival fails on the first one. The non-streaming path never saw this.
  - **Three constraints that bound the work just as hard**, found by reading:
    **no `ToolRegistry` is populated anywhere in the running app** (the only
    callable surface is `app.state.action_registry`, one action — so a loop wired
    in today has **zero read tools**); the usage claim is taken up front for 1–2
    calls while a loop makes up to **9**, which breaks TD-018 unless the claim
    moves inside the loop; and the rail's index must be built from the **composed**
    system message, with tool results left unindexed as data and treated as their
    own scanner channel.
  - **`prompted_tools` is deliberately unmeasured** — it parses `<tool_call>` tags
    out of *content*, a different streaming shape that would reach the analyst as
    prose. It needs its own probe before being wired to a streaming surface.
- **CI-green: 1021 tests** (1014 at S22 end → **+7**). `./ci.sh` green including
  the installed-dist gate (**118 modules**); `/api/health/ready` 200. **Zero new
  env vars — ten sessions running.**

- **S20–S22 (kept for context).** S20 made CI a check anyone can see (D-028) and
  gave the repo its README and `scripts/demo.sh`. S21 closed TD-026 and TD-028a.
  S22 shipped TD-012(a) as `auspex/outguard.py` (D-030). Earlier sessions are in
  git history and DECISIONS.md.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: this session's four commits + this session-end commit.**
   `12b30da` (pass-1 leak ends the turn), `63cbb52` (the channel boundary),
   `4be3174` (Step-0 record + TD-034), `fdec17b` (the streaming probe + D-031).
   **A real slate — `/promote` first next session.**
   - **Read the diff at promote time. Never trust the commit LIST** — after a
     squash it is meaningless (PR #23's showed every commit back to S2; the real
     change was 23 files).
2. **Branch protection on `main` is STILL the one manual step left** — the CI
   check exists and is green, but nothing yet REQUIRES it before a promote merge.
   Repository settings, Burhan's call, not a commit's (D-028). One command:
   `gh api -X PUT repos/bh3082336888-cell/auspex/branches/main/protection -f 'required_status_checks[strict]=true' -f 'required_status_checks[contexts][]=ci.sh (lint + tests + container build + installed-dist)' -F 'enforce_admins=false' -F 'required_pull_request_reviews=null' -F 'restrictions=null'`
3. **TD-028b is the sharpest open half of TD-028** — a failed execute leaves
   effects it denies. (c) is sharper since S21, and **TD-034 now folds in**: all
   three want a terminal state that records what actually happened. S22 and S23
   have both worked in those four statements, so the code is freshly mapped twice.
4. **The card stream still emits only new cards, never status changes** — a client
   watching `/stream` is not told when a claim goes stale.
5. **TD-031 / TD-032 / TD-033 are ratified bounds, not a backlog.** Do **not**
   re-open the guard regex. S23 touched it **not at all** — the newline boundary
   was only re-measured, and it held 5/5 on the `.eml` corpus.
6. **TD-005 trigger, still armed:** cve pool > 300k chunks, curated pool > 5k, any
   new doc_type, any embedding-model change, **or before any free-text-over-CVEs
   surface ships** (TD-027 is a HARD GATE). Corpus at S21: **31,828**. Not tripped.
7. **`SHINGLE_WORDS` is a calibrated number, not a constant to edit** — re-run
   `docs/probes/s22-outguard/probe_calibrate2.py` before moving it. Same rule
   NEURAL_FLOORS has. **S23 did not touch it.**
8. **NEW — the suite's usage isolation is incidental, not designed.** All
   dev-login users share the `default` workspace against an **hourly** ceiling of
   100 inference calls, and nothing resets it at session start. Any new test that
   spends inference calls must refund them (`_no_usage_residue` in
   test_chat_sse.py is the pattern).

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop is still not wired into
   `/api/chat`. **Its design is now settled and measured (D-031); the code is
   not written.** Open: TD-012**(b)**, TD-014, TD-015, TD-016, TD-017, TD-019,
   TD-020, TD-021, TD-022, TD-023, TD-024, TD-025, TD-027, **TD-028b/c/d**,
   TD-029, TD-030, TD-031/032/033, **TD-034**. **TD-018, TD-026, TD-028a and
   TD-012(a) are CLOSED.**
3. **The agent has no tools.** `grep` for `ToolRegistry()` across `auspex/` finds
   nothing outside the class. The platform's real capabilities (enrichment, CVE
   lookup, KB retrieval) exist as shortcut code paths, not as agent tools. **This
   is the substance of the agent work, and it is not started.**
4. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
5. **Corpus 31,828 docs and growing while the container runs.** TD-011 tracks the
   index rollover trigger.
6. **Two rails, and neither is a closure.** The INPUT guard bounds accidents and
   naive attempts (D-027, D-029). The OUTPUT rail (D-030) catches our
   configuration coming back out, **but not a paraphrase, and not an injection
   that merely made the answer wrong**. S23 narrowed the gap between what the
   output rail claims and what it does — it was off for an entire pass — but the
   stated bounds are unchanged.
7. **An intermittent, unattributed test failure was observed once in S22.** Not
   reproduced in S23's **six** further full-suite runs. Still recorded rather than
   dismissed.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`.
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
  **Primary dev LLM is Northflank Scout (D-015)** — reachable, and it is what
  S23's streaming probe was measured against.
- **S23 session-end (2026-08-16):** staging, tree clean, identity
  `bh3082336888-cell`. All three containers healthy; `./ci.sh` **green, 1021
  tests, 118 modules**; `/api/health/ready` **200**.
- **`gh` did NOT flip to the work account at S23** (checked at the ritual, before
  `gh pr create`, and before `gh pr merge`). It DID at S18 and S16; did not at
  S17, S13–S15, S19–S23. **Unpredictable is the pattern** — re-check before EVERY
  `gh` call.
- **`gh pr merge` works.** `gh pr edit` still fails with a Projects-classic
  GraphQL deprecation — use `gh api -X PATCH repos/.../pulls/N`.
- **`./ci.sh | tail` HIDES THE EXIT CODE.** A piped run reports `tail`'s status,
  and S23 read "exit 0" off a run that had actually failed lint. Redirect to a
  file and read `$?`, never pipe the gate into `tail`.
- **Run the suite the way `ci.sh` does** — `.venv`, where the package is installed
  editable. A bare `python3 -m pytest` uses the system interpreter and fails the
  packaging test for that reason alone.
- **This repo HAS GitHub Actions** (S20, D-028) — `.github/workflows/ci.yml` runs
  `./ci.sh` on push and PR. Cold run ~5m30s; PR #23's took 5m54s.
- **Local `main` ref goes stale every promote.** `git fetch origin` and read
  `git diff origin/main..staging --stat`, never the commit list.
- **The app container runs the BUILT IMAGE, not the working tree** —
  `docker compose up -d --build app`.
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
**Start with `/promote`** — four commits plus this session-end commit.

Then **finish what S23 started: the agent path.** For the first time the design is
settled and measured rather than argued (D-031), and the blocking unknown is gone.
The order below is deliberate — (1) before (2), because a loop with no tools has
nothing to do:

1. **Expose the platform's existing capabilities as agent read tools.** Enrichment,
   CVE lookup and KB retrieval already exist as shortcut code paths; the agent
   registry is empty. Reuse the same code, do not re-implement it — this is what
   makes an agent turn worth taking, and it is additive and testable on its own.
2. **Wire AgentLoop into `/api/chat`, streaming, per D-031.** Narrate tool steps,
   stream the answer after them, accumulate tool-call arguments before parsing,
   move the usage claim inside the loop (TD-018), and build the rail's index from
   the composed system message with tool results as their own channel.
3. **TD-028 (b/c/d) + TD-034 together** — all four want a terminal state that
   records what actually happened, and the code has been freshly mapped twice.
4. **TD-012(b)** — contract-conformance repair, the original S9 entry.

NEXT-SESSION.md has the full prompt.
