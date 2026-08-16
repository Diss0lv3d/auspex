# STATE — Auspex

_Last updated: 2026-08-16 (**S24 — the agent registry is no longer empty, and
Step 0 found three defects in day-old code.** The output rail's channel fix was
itself defective (a drop loses things), the TD-034 pin guarded the wrong
statement, and the usage refund fixture protected 3 tests out of 33. Then the
session's goal landed its **first half in full**: enrichment, CVE lookup and KB
retrieval are now agent READ tools, live-verified against the real services.
**Wiring the loop into `/api/chat` was deliberately NOT started.** 1052 tests.)_

## Where we are

**Phase 4 is contract (S17) + decision loop (S18) + hardened input and spend
(S19) + a pipeline, docs and a demo anyone can run (S20) + the beta debt paid
down (S21) + an output rail (S22) + that rail's defects found (S23) + the rail's
FIX's defects found, and the agent given something to do (S24). The ROADMAP
through S20 is complete; S21–S24 were each scoped by a decision rather than a
plan. S25 is the first session in five with a goal that is purely constructive —
see "Next session should".**

- **S24 Step 0 — `/promote` done first.** PR **#24** merged as squash `d0d6f57`
  (2026-08-16), back-merged `c74914c`, tree verified **byte-identical**, `main`
  and `staging` converged. Real diff **16 files, +1825/-354**. The commit LIST
  showed **281 commits** back to S2 — **read the diff, never the list.**
- **S24 Step 0 — fresh-eyes review of the S23 commits (DONE: 3 defects fixed,
  1 debt accepted, 1 documented claim corrected).** Record:
  docs/probes/2026-08-16-s24-step0-review.md; harnesses in docs/probes/s24-step0/.
  Every finding was read out of the code first, then **confirmed by execution**;
  both behavioural fixes were **proven to fail pre-fix** by neutralising only
  the changed statement.
  - **(FIXED — the fix was the defect) S23's channel fix is a carry DROP, and
    drops lose things.** The carry was ONE shared slot, so **any** delta of the
    other kind evicted it. A leak split across two chunks of the **same** pane,
    separated by one interleaved delta of the other, walked through the rail —
    **in both directions**. Now one carry **per channel**, so both guarantees
    hold at once instead of being traded. **Latent, not unreachable:** the
    two-pass path is immune by construction (each pass feeds one channel), the
    default endpoint takes it (**Scout's persisted scorecard has no
    `native_reasoning` key at all**, so it resolves False), and qwen3 emits 361
    reasoning deltas then 32 content — **1 switch**. But the switch count is a
    property of the *endpoint*, and the platform's premise is whatever endpoint
    the customer brings.
  - **(FIXED — the pin named the wrong statement) TD-034's guarantee was
    unguarded.** `undo` has two guards: a read-then-check (`not_executed`) and
    the atomic claim `AND status = 'executed'` (`already_undone`). S23's pin
    asserts the *pre-check* while its docstring credits the *claim* and promises
    it fails if the claim is loosened. Measured: loosening the claim left **all
    34 settlement tests green**. The new pin drives the shape a claim exists for
    — a **stale read** saying `executed` while the row is already `abandoned` —
    and with the claim loosened it fails with `DID NOT RAISE ExecutionRefused`,
    i.e. the undo proceeds and TD-034 becomes reachable. TD-034's text corrected.
  - **(FIXED — opt-in did not hold) the usage refund protected 3 tests of 33.**
    Measured with those 3 deselected: one run of test_chat_sse.py left **29
    unrefunded inference calls** against an hourly ceiling of 100. The file
    looked clean only because the fixture DELETEs the row rather than
    decrementing and the 3 tests that use it happen to run last — the same
    incidental ordering S23 recorded as a risk, **moved rather than removed**.
    Now `autouse`; residue **29 → 0**. Safe at function scope, *verified*:
    nothing in that file asserts a limit or a usage count.
  - **(ACCEPTED — TD-035) a pass-1 leak is charged for the call it prevented.**
    The claim is `1 if native_reasoning else 2`, taken up front; S23's guard
    means a pass-1 leak ends the turn after one call. Over-charges rather than
    under-charges, TD-030 already ratifies that a failed turn is charged in full,
    and `UsageLimiter` **has no refund path at all**. It dissolves when the claim
    moves inside the loop — it must not be patched here first.
  - **The measurement discipline failed and was caught for the FIFTH session
    running — this time inside my own first harness.** A 6/8-word split made the
    second half an indexed run *on its own*, so the result would have held with
    the carry deleted entirely. Controls are asserted arithmetically in the
    harness now. *A green test is not evidence about what it measured.*
- **S24 goal, part 1 — DONE: the agent has tools.** `auspex/agent/capabilities.py`
  + 27 tests. The blocker recorded since S23 ("the agent has no tools",
  `grep ToolRegistry()` finding nothing outside the class) **is closed**.
  - **Wraps existing code, does not re-implement it.** Same
    `EnrichmentService.enrich`, `KnowledgeService.lookup_ids` /
    `search_definition`, same observable extractor, **same CVE fetch sizing**
    (`max(8, 4*len)` — the S6 false-miss finding). A wrapper that diverges is how
    the agent's answer and the shortcut's answer start disagreeing in one session.
  - **All three READ (D-014).** Handlers return **data, not the renderers'
    prose** — the model writes its own answer, and rendered copy would come back
    as paraphrase *and* put configuration-shaped text into the turn for the
    output rail to trip over.
  - **Three failures stay three truths** — not connected / connected but
    unavailable / connected but ignorant. An observable that was never checked
    never reads as one with no signals.
  - **Caps reused, not re-declared.** The enrichment service already applies
    `ENRICH_MAX_OBSERVABLES` **and reports each over-cap observable as a skip**;
    CVE ids use `MAX_IDS_PER_LOOKUP`. The one new constant bounds argument
    *parsing*, a different concern.
  - **Live-verified against the real services** (record:
    docs/probes/2026-08-16-s24-capability-tools-live.md), not just fakes: real
    NVD Log4Shell record with two fabricated ids in `not_found` **in the same
    call**, real ATT&CK TA0008 through the curated filter, live enrichment with
    **5 sources answered** (AbuseIPDB 100/100, OTX 50 pulses), and a private
    address returning `not_checked` with its reason. **My first miss control was
    wrong and is recorded as wrong** — "quokka exfiltration ritual" returned
    TA0010 because it contains a real ATT&CK term, so it measured recall, not the
    miss path.
- **S24 goal, part 2 — NOT STARTED, deliberately.** Wiring AgentLoop into
  `/api/chat` was the agreed second half *if Step 0 and part 1 left real time*.
  Step 0 was three defects, not a quick pass. **No route code changed** — the
  same honest statement S23 had to make, for a different reason: last session the
  design was unknown, this session the clock ran out. The design (D-031) and the
  tools are both ready now.
- **CI-green: 1052 tests** (1021 at S23 end → **+31**). `./ci.sh` green including
  the installed-dist gate (**119 modules**); `/api/health/ready` 200.
  **Zero new env vars — eleven sessions running.**

- **S20–S23 (kept for context).** S20 made CI a check anyone can see (D-028) and
  gave the repo its README and `scripts/demo.sh`. S21 closed TD-026/TD-028a. S22
  shipped TD-012(a) as `auspex/outguard.py` (D-030). S23 fixed two rail defects
  and measured the loop's streaming shape (D-031). Earlier sessions are in git
  history and DECISIONS.md.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: this session's five commits + this session-end commit.**
   `33011c5` (per-channel carry), `6a3b6a1` (the undo claim pinned), `622687d`
   (autouse refund), `db1a616` (Step-0 record + TD-035), `fa7959e` (the
   capability tools), `949a335` (the live tool probe).
   **A real slate — `/promote` first next session.**
   - **Read the diff at promote time. Never trust the commit LIST** — PR #24's
     showed **281 commits** while the real change was 16 files.
2. **Branch protection on `main` is BLOCKED, not pending — this changed in S24.**
   Burhan authorised enabling it; it **cannot be enabled on this repo**. Both
   classic protection and rulesets return
   `403 "Upgrade to GitHub Pro or make this repository public"` (both probed —
   docs/probes/2026-08-16-s24-branch-protection.md). The repo is **private on a
   free plan**, so this was never a settings toggle. Three ways out: make the
   repo public (publishes STATE/DECISIONS/probes — candid working documents),
   pay for Pro, or name option 3 as the decision: **`main`'s protection is
   procedural** — `/promote` refuses to merge on anything but a CLEAN check, and
   every promote so far has waited for green. **Burhan's call, and it is a
   plan/visibility decision, not an unfinished task.**
3. **TD-028b is the sharpest open half of TD-028** — a failed execute leaves
   effects it denies. (c) is sharper since S21, and **TD-034 folds in**. S22, S23
   and S24 have all worked in those four statements — freshly mapped three times.
4. **The card stream still emits only new cards, never status changes** — a client
   watching `/stream` is not told when a claim goes stale.
5. **TD-031 / TD-032 / TD-033 are ratified bounds, not a backlog.** Do **not**
   re-open the guard regex. **S23 and S24 both touched it not at all.**
6. **TD-005 trigger, still armed:** cve pool > 300k chunks, curated pool > 5k, any
   new doc_type, any embedding-model change, **or before any free-text-over-CVEs
   surface ships** (TD-027 is a HARD GATE). Corpus at S21: **31,828**. Not tripped.
7. **`SHINGLE_WORDS` is a calibrated number, not a constant to edit** — re-run
   `docs/probes/s22-outguard/probe_calibrate2.py` before moving it. Same rule
   NEURAL_FLOORS has. **S24 did not touch it.**
8. **Test usage isolation is DESIGNED for test_chat_sse.py and still incidental
   everywhere else.** That file's refund is now `autouse`. Any *other* file whose
   tests spend inference calls has the same 29-unit problem waiting — all
   dev-login users share the `default` workspace against an **hourly** ceiling of
   100, and nothing resets it at session start.
9. **NEW — the persisted scorecards have no `native_reasoning` key.** All four
   rows predate the field (probed 2026-07-15), so `_default_native_reasoning`
   resolves **False** and the default endpoint takes the **two-pass** path. The
   native path is therefore **unexercised in the running app** — worth knowing
   before the loop is wired, since D-031's measurements were taken on it.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop is still not wired into
   `/api/chat`. **Design settled and measured (D-031); tools now exist (S24); the
   route code is not written.** Open: TD-012**(b)**, TD-014 … TD-025, TD-027,
   **TD-028b/c/d**, TD-029, TD-030, TD-031/032/033, TD-034, **TD-035**.
   **TD-018, TD-026, TD-028a and TD-012(a) are CLOSED.**
3. ~~**The agent has no tools.**~~ **CLOSED in S24** — three READ tools, live-
   verified. What remains is that **no model has yet chosen one**: every call in
   the probe was made directly. Whether an endpoint picks the right tool from
   these descriptions is a property of the endpoint and is **not yet measured**.
4. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
5. **Corpus 31,828 docs and growing while the container runs.** TD-011 tracks the
   index rollover trigger.
6. **Two rails, and neither is a closure.** The INPUT guard bounds accidents and
   naive attempts (D-027, D-029). The OUTPUT rail (D-030) catches our
   configuration coming back out, **but not a paraphrase, and not an injection
   that merely made the answer wrong**. S23 found it was off for a whole pass;
   S24 found its fix had a hole. **Two consecutive sessions have found a defect
   in this rail — assume a third exists.**
7. **An intermittent, unattributed test failure was observed once in S22.** Not
   reproduced in S23's six or S24's four further full-suite runs. Still recorded
   rather than dismissed.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`.
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
  **Primary dev LLM is Northflank Scout (D-015)** — reachable.
- **S24 session-end (2026-08-16):** staging, tree clean, identity
  `bh3082336888-cell`. All three containers healthy; `./ci.sh` **green, 1052
  tests, 119 modules**; `/api/health/ready` **200**.
- **`gh` did NOT flip to the work account at S24** (checked at the ritual and
  before every `gh` call — five of them). It DID at S18 and S16; did not at S17,
  S13–S15, S19–S24. **Unpredictable is the pattern** — re-check before EVERY call.
- **`gh pr merge` works.** `gh pr edit` still fails with a Projects-classic
  GraphQL deprecation — use `gh api -X PATCH repos/.../pulls/N`.
- **`gh pr merge --squash` printed NOTHING on success at S24** — do not read
  silence as failure; verify with `gh pr view <n> --json state,mergeCommit`.
- **`./ci.sh | tail` HIDES THE EXIT CODE.** Redirect to a file and read `$?`.
  S24 did this four times; every run's exit code was read directly.
- **Run the suite the way `ci.sh` does** — `.venv`, where the package is installed
  editable. A bare `python3 -m pytest` fails the packaging test for that alone.
- **This repo HAS GitHub Actions** (S20, D-028) — `.github/workflows/ci.yml` runs
  `./ci.sh` on push and PR. PR #24 ran it twice (push + PR): 5m19s and 4m54s.
- **Local `main` ref goes stale every promote.** `git fetch origin` and read
  `git diff origin/main..staging --stat`, never the commit list.
- **The app container runs the BUILT IMAGE, not the working tree** —
  `docker compose up -d --build app`. In-container probes: `docker compose cp`
  the script in, then `docker compose exec -T app python /tmp/<script>.py`.
- **qwen3:14b is SLOW to first token** — a 400-token probe timed out at 5 minutes
  cold. Budget 1500 tokens and run it in the background.
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
**Start with `/promote`** — six commits including this session-end commit.

Then **wire AgentLoop into `/api/chat`, streaming (D-031).** For the first time
both halves are ready: the design is measured, and **the tools exist and are
live-verified**. This is the whole session's goal — it is a large change to the
most load-bearing route in the app, and S24 stopped short of it deliberately
rather than half-wire it.

1. **The wiring itself**, per D-031: narrate the tool steps, stream the answer
   after them (measured safe — zero content precedes tool calls), **accumulate
   tool-call arguments before parsing** (nine fragments split mid-token), use
   `finish_reason` as the step signal, **move the usage claim inside the loop**
   (TD-018 breaks otherwise; TD-035 dissolves when it does), and **build the
   output rail's index from the COMPOSED system message**, leaving tool results
   unindexed as data on **their own scanner channel**.
2. **Measure whether a model actually picks the right tool** from S24's
   descriptions. Nothing has yet: every probe call was made directly. This is a
   property of the endpoint and belongs in a probe before it is trusted.
3. **TD-028 (b/c/d) + TD-034 together** — all four want a terminal state that
   records what actually happened; the code is freshly mapped three times now.
4. **TD-012(b)** — contract-conformance repair, the original S9 entry.

NEXT-SESSION.md has the full prompt.
