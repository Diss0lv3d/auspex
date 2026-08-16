# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**S24 found three defects in day-old code, then gave the agent something to
do.** The sharpest: **S23's fix was itself defective.** Dropping the scanner's
carry on a change of channel stopped a false positive — and a drop loses things.
The carry was ONE shared slot, so **any** delta of the other kind evicted it, and
a leak split across two chunks of the **same** pane, separated by one interleaved
delta, walked through the rail in **both** directions. Now one carry per channel,
so both guarantees hold instead of being traded. Second: **the TD-034 pin guarded
the wrong statement** — it asserts the racy pre-check while its docstring credits
the atomic claim, and loosening that claim left **all 34 settlement tests green**.
Third: **the usage refund protected 3 tests out of 33** — measured, the other 30
left **29 unrefunded units** against a ceiling of 100, and the file only looked
clean because the fixture DELETEs the row and those 3 run last. All three fixed,
all proven to fail pre-fix. TD-035 accepted (a pass-1 leak is charged for the
call it prevented — it dissolves when the claim moves inside the loop). Then the
goal's first half landed in full: **enrichment, CVE lookup and KB retrieval are
agent READ tools**, wrapping the same code, live-verified against the real
services — real Log4Shell record, real ATT&CK TA0008, live enrichment with 5
sources answered. **The "agent has no tools" blocker, carried since S23, is
closed.** Wiring the loop was deliberately NOT started: Step 0 ate the session,
and a half-wired `/api/chat` is worse than none. **1052 tests, 119 modules, zero
new env vars — eleven sessions running.**)_

---

SESSION S25 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S25` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
it did at S18 and S16, did NOT at S17, S13–S15, S19–S24, so assume it has and
re-check before every `gh` call. `gh pr edit` fails on this repo with a
Projects-classic GraphQL error — use `gh api -X PATCH repos/.../pulls/N`. **`gh pr
merge --squash` printed nothing at all on success at S24** — do not read silence
as failure, verify with `gh pr view <n> --json state,mergeCommit`. Local `main`
goes stale every promote — `git fetch` and read
`git diff origin/main..staging --stat`, **never the commit list**: PR #24's listed
**281 commits** while the real change was 16 files. The app container runs the
built image — live verification needs `docker compose up -d --build app`, and
in-container probes go `docker compose cp` then `docker compose exec -T app python
/tmp/<script>.py`. **Run the suite the way `ci.sh` does**: it uses `.venv`, where
the package is installed editable. And **never pipe `./ci.sh` into `tail`** — the
pipeline reports `tail`'s exit code.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **`/promote` FIRST.** A real slate: `33011c5` (the carry survives an
  interleaved delta), `6a3b6a1` (the undo claim pinned, not the pre-check),
  `622687d` (the refund is autouse), `db1a616` (Step-0 record, TD-035, TD-034
  corrected), `fa7959e` (the capability tools), `949a335` (the live tool probe),
  plus the S24 session-end commit. **Verify by reading the real diff**
  (`git fetch origin && git diff origin/main..staging --stat`), never the commit
  list. `gh pr checks <n> --watch --interval 20` works; merge only on CLEAN.
- **Fresh-eyes review of the S24 commits** — scope: `33011c5`
  (`OutputScanner._carries` and the per-channel carry), `6a3b6a1` (the stale-read
  pin), `622687d` (`autouse` on the shared workspace), `fa7959e`
  (`auspex/agent/capabilities.py`, the largest new surface). Angles S24 did NOT
  adversarially test:
  - **(strongest lead — the tools take model-controlled strings and hand them to
    real services.)** `_resolve` calls `extract()` on whatever the model sends,
    and `lookup_cve` upper-cases and forwards ids. Nothing bounds the *content*
    of those strings beyond a 25-item count. Check what a 32k-char argument, a
    NUL, or an id shaped like an OpenSearch operator actually does — the guard
    regex work (S19–S21) was all about untrusted text reaching a service, and
    this is a **new, unguarded entry point** into the same services.
  - **(the per-channel carry is unbounded.)** `_carries` is keyed by whatever
    string the caller passes. Today those are four literals — but D-031 adds a
    tool-results channel, and a per-tool-call channel name would grow the dict
    without limit inside one turn. Decide whether the key space should be closed
    in code rather than by convention.
  - **(autouse changed 30 tests that never asked for it.)** Verify no test in
    test_chat_sse.py depended on counter state surviving, and that the fixture's
    DELETE cannot race the app's own claim when tests run in the same window.
  - **(the tools have never been chosen by a model.)** Every S24 probe call was
    made directly. A tool whose description a model cannot act on is a tool that
    does not exist — see goal item 2, and consider doing it FIRST if it would
    change the wiring.
  Verify findings BY EXECUTION before fixing; fix with regressions. **Read
  docs/probes/2026-08-16-s24-step0-review.md §"The measurement discipline" before
  you start** — it has now failed and been caught in **five** consecutive
  sessions, most recently inside my own first harness. Assert the REASON, and
  make controls ARITHMETIC where you can.

Goal — **wire AgentLoop into `/api/chat`, streaming (D-031).** This is the whole
session. Both halves are finally ready: the design is measured (S23) and the
tools exist and are live-verified (S24). It is a large change to the most
load-bearing route in the app — S24 stopped short rather than half-wire it, and
that judgement stands: **if Step 0 runs long, wire nothing and say so.**

1. **The wiring**, per D-031: narrate the tool steps; stream the answer after
   them (**measured safe** — a tool turn emits `tool_call → finish → usage` with
   **content chars: 0**); **accumulate tool-call arguments before parsing** (one
   IP arrived as **nine fragments split mid-token**); use `finish_reason` as the
   step signal; **move the usage claim inside the loop** (a loop makes up to 9
   calls against a claim of 1–2 — TD-018 breaks otherwise, and **TD-035 dissolves
   the moment it moves**; a refusal mid-loop synthesises from what was gathered);
   and **build the output rail's index from the COMPOSED system message**,
   leaving tool results **unindexed as data** and treated as **their own scanner
   channel**.
2. **Measure whether a model actually picks the right tool.** Nothing has yet —
   every S24 probe call was made directly, so the descriptions in
   `capabilities.py` are unvalidated as *prompts*. This is a property of the
   endpoint (D-014's capability-negotiation premise), so it belongs in a probe.
3. **TD-028 (b/c/d) + TD-034 together.** All four want a terminal state that
   records what actually happened, and S22/S23/S24 have each worked in those four
   statements — the code is freshly mapped three times.
4. **TD-012(b)** — contract-conformance repair, the original S9 entry.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic.
- **The native path is UNEXERCISED in the running app.** All four persisted
  scorecards predate the `native_reasoning` field, so `_default_native_reasoning`
  resolves **False** and the default endpoint takes the **two-pass** path — while
  D-031's streaming measurements were taken on the native one. Do not assume the
  path you wire is the path that runs; check the scorecard, or re-probe.
- **`prompted_tools` is deliberately unmeasured.** It parses `<tool_call>` tags
  out of *content*, so the tags would reach the analyst as prose. **Probe it
  before wiring it to a streaming surface.**
- **Any new test that spends inference calls must refund them.** test_chat_sse.py
  is now `autouse` and safe; **any other file is not** — the same 29-unit problem
  is waiting there. Hourly ceiling 100, shared `default` workspace.
- **Do NOT re-open the guard regex.** S19, S20 and S21 each spent a session
  there; S23 and S24 both left it entirely alone. TD-031/032/033 are ratified.
- **`SHINGLE_WORDS` is a calibrated number** — re-run
  `docs/probes/s22-outguard/probe_calibrate2.py` before touching it.
- **Two consecutive sessions have found a defect in the output rail** (S23: off
  for a whole pass; S24: its fix had a hole). Assume a third exists, and treat
  any change near it as high-risk.
- **Reuse caps, never re-declare them.** S24 nearly shipped a second, tighter
  copy of `ENRICH_MAX_OBSERVABLES` and `MAX_IDS_PER_LOOKUP`. A calibrated number
  gets one home.
- **The CI gate is real (D-028) and must stay honest** — `.github/workflows/ci.yml`
  runs `./ci.sh` and nothing else.
- **The README is a promise** pinned by `tests/test_docs.py`. Wiring the agent
  path changes what the deep path IS — if a bound stops being true, the test
  sends you there to change it deliberately.
- **`./scripts/demo.sh` must keep running end to end** (verified at S24 end).
- **Any new assertion over an EXTRACTED set needs a floor** (S21's
  `len(called) >= 8` lesson), or it reports green with its input removed.
- DECISIONS.md entries are immutable once ratified; overturning one is a NEW
  numbered decision naming which it supersedes.
- Brand is locked (CLAUDE.md Brand, D-002). **Never leak the underlying model or
  provider name into user-visible strings** — including into TOOL RESULTS, which
  the model writes its answer from.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth. **S14–S24
  each added zero.** A tunable that belongs to us is a code constant, per D-026.
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly. (**119 modules**;
  `auspex.agent` is already packaged, so a new module inside it needs nothing.)
- **Branch protection on `main` is BLOCKED, not pending — and it needs a decision
  from me, once.** I authorised it at S24; it **cannot be enabled**: classic
  protection AND rulesets both return `403 "Upgrade to GitHub Pro or make this
  repository public"` (both probed —
  docs/probes/2026-08-16-s24-branch-protection.md). Private repo, free plan.
  **Ask me once, early: make the repo public, pay for Pro, or ratify that main's
  protection is procedural** (which is what it has been for five sessions).
  Do not spend session time on it beyond asking.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 18× now); TD-014; TD-015; TD-016;
  TD-017; TD-019; TD-020; TD-021; TD-022; TD-023; **TD-024**; TD-025; **TD-027
  (HARD GATE)**; **TD-029**; **TD-030**; **TD-031/032/033**; the card stream
  emitting status changes; model-PROPOSED hypotheses/evidence and falsifiers
  (D-019-later, D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
  Tired human = short session; rituals anyway.
- End with `/session-end`.
