# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**S25 found two more defects in day-old code, proved the tools work as prompts,
and taught the loop to stream.** Both review findings sat in one place — the
model-controlled tool-argument boundary. The sharper: **`_resolve` kept only the
first observable per argument item**, so an analyst's "check these three" came
back answered about ONE, with `unresolved` empty and nothing saying so — two
indicators never sent to a provider, and an answer that read as complete. That is
*not-checked* rendering as *no-signals*, the collapse `capabilities.py`'s own
docstring exists to prevent, and its own promise ("never dropped") inverted.
Latent on Scout (it sends separate array items) but reachable by construction
through the bare-string shape `_as_list` exists to accept. Second: **a bare number
raised TypeError**, degraded to an unactionable "tool raised TypeError". Both
fixed, both proven to fail pre-fix. **Four suspicions were checked and CLEARED**
and recorded as cleared. **D-032 ratified**: main's protection is procedural — it
cannot be enabled, and that item is closed forever. Then goal item 2, which
nothing had ever measured: **the tool descriptions work as PROMPTS** — 8 of 8
live, right tool and right arguments — and the control earned its keep by
revealing that **Scout REFUSES a question no tool answers**. Finally the goal's
mechanism half: **`AgentLoop.run_stream`**, all five D-031 decisions, proven by
three neutralisations and **live-verified end to end** (1 tool step, 79 content
deltas, 2 claims for 2 calls, ordering held). **The route was deliberately NOT
touched — your call — so `/api/chat` is unchanged and main stays deployable.**
1073 tests, 119 modules, zero new env vars — twelve sessions running.)_

---

SESSION S26 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S26` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
it did at S18 and S16, did NOT at S17, S13–S15, S19–S25, so assume it has and
re-check before every `gh` call. `gh pr edit` fails on this repo with a
Projects-classic GraphQL error — use `gh api -X PATCH repos/.../pulls/N`. **`gh pr
merge --squash` printed nothing at all on success at BOTH S24 and S25** — do not
read silence as failure, verify with `gh pr view <n> --json state,mergeCommit`.
Local `main` goes stale every promote — `git fetch` and read
`git diff origin/main..staging --stat`, **never the commit list**: PR #25's listed
~280 commits while the real change was 17 files. The app container runs the built
image — live verification needs `docker compose up -d --build app`, and
in-container probes go `docker compose cp` then `docker compose exec -T app python
/tmp/<script>.py`. **Run the suite the way `ci.sh` does**: it uses `.venv`, where
the package is installed editable. And **never pipe `./ci.sh` into `tail`** — the
pipeline reports `tail`'s exit code.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **`/promote` FIRST.** The slate: `d47adea` (three indicators check three),
  `554623c` (a bare number is an honest miss), `e1722b8` (Step-0 record +
  tool-choice probe + D-032), `7a82697` (`run_stream`), `7fe35a7` (the live
  run_stream probe), plus the S25 session-end commit. **Verify by reading the real
  diff** (`git fetch origin && git diff origin/main..staging --stat`), never the
  commit list. `gh pr checks <n> --watch --interval 20` works; merge only on CLEAN.
- **Fresh-eyes review of the S25 commits** — scope: `d47adea` + `554623c`
  (`_resolve` / `_as_list`, the tool-argument boundary), `7a82697`
  (`AgentLoop.run_stream` + the `fold_stream_event` extraction, **the largest new
  surface and the one S26 is about to build on**). Angles S25 did NOT adversarially
  test:
  - **(strongest lead — `run_stream` was never driven by a MISBEHAVING stream.)**
    Every test scripts a well-formed sequence. What happens on: a stream that ends
    mid-tool-call (no `finish`), a `tool_call` delta with a name but no arguments,
    two tool calls in one step where the FIRST handler raises, an endpoint that
    emits `usage` and nothing else? `sealed[0]` assumes the generator completed —
    check what an exception mid-stream does to it.
  - **(the claim is called before the call, and never refunded.)** If the model
    call itself raises `LLMError` after the claim, the workspace is charged for a
    call the endpoint never served. TD-030 ratifies charging a failed turn in
    full, but TD-035 said the same thing and dissolved — decide whether this one
    is the same shape or a new one.
  - **(`fold_stream_event` was extracted from shared code.)** `accumulate_stream`
    now delegates to it. Verify no caller depended on the old inlined behaviour,
    and that `seal_stream_result` mutating `result` in place cannot surprise a
    caller that reuses a ChatResult.
  - **(the anti-drift test may be weaker than it reads.)**
    `test_run_and_run_stream_compose_the_same_messages` compares only the FIRST
    call's messages. The two paths could still diverge on the second step or on
    the synthesis pass.
  Verify findings BY EXECUTION before fixing; fix with regressions. **Read
  docs/probes/2026-08-16-s25-step0-review.md §"The measurement discipline" before
  you start** — it has now been applied up front once, after failing in five
  consecutive sessions. Assert the REASON, and make controls ARITHMETIC.

Goal — **wire the agent path into `/api/chat` (D-031).** Everything it depends on
now exists and is measured: the design (S23), the tools (S24), the tools proven as
prompts (S25), and the streaming mechanism, live-verified (S25). **What is left is
the route, and only the route.**

1. **Decide the routing question FIRST — it is not a detail.** Measured at S25:
   asked a question no tool answers, Scout **refused** — "the functions provided
   are insufficient" — despite a system message telling it to answer anyway. So
   "route every deep turn through the agent loop" is known to be wrong. Either the
   92/8 classifier keeps such turns off the agent path, or the composed system
   message handles it — and **the obvious instruction was measured not to be
   enough**, so whichever is chosen needs its own probe before it is trusted.
2. **The wiring:** consume `run_stream`; map its events onto the existing SSE
   protocol; narrate `tool` events; build the leak index from
   **`loop.system_message(loop.wire_specs())`** (D-031 decision 5 — not the four
   fixed strings); leave tool results **unindexed** and scan them on **one literal
   channel** (see constraint below); pass a `claim` that calls `UsageLimiter` per
   call (TD-018 — **TD-035 dissolves the moment it moves**); and persist the `done`
   event's `text` as the assistant turn.
3. **Check which path actually runs before trusting either.** All four persisted
   scorecards lack `native_reasoning`, so `_default_native_reasoning` resolves
   **False** and the default endpoint takes the **two-pass** path — while D-031's
   measurements AND S25's live `run_stream` probe were both taken on the native
   one.
4. **TD-028 (b/c/d) + TD-034 together** — all four want a terminal state that
   records what actually happened; the code is freshly mapped four times now.
5. **TD-012(b)** — contract-conformance repair, the original S9 entry.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic.
- **The tool-results scanner channel must be ONE LITERAL, not one per call.**
  `OutputScanner._carries` closes its key space by convention ("call sites pass
  literals"); a per-tool-call channel name would grow that dict without bound
  inside a single turn. No defect exists yet — do not create one.
- **TD-036 is a named assumption, not a bug.** `run_stream` streams content deltas
  on arrival, which is safe only because no prose precedes tool calls on the
  endpoints we have. Do not "fix" it without the measurement its entry names.
- **`prompted_tools` is deliberately unmeasured.** It parses `<tool_call>` tags out
  of *content*, so the tags would reach the analyst as prose. **Probe it before
  wiring it to a streaming surface.**
- **Any new test that spends inference calls must refund them.** test_chat_sse.py
  is `autouse` and safe (verified independently at S25); **any other file is not**.
  Hourly ceiling 100, shared `default` workspace. test_agent_stream.py is fakes
  only and spends nothing — keep it that way.
- **Do NOT re-open the guard regex.** S19, S20 and S21 each spent a session there;
  S23, S24 and S25 all left it entirely alone. TD-031/032/033 are ratified.
- **`SHINGLE_WORDS` is a calibrated number** — re-run
  `docs/probes/s22-outguard/probe_calibrate2.py` before touching it.
- **Two sessions found a defect in the output rail (S23, S24); S25 did not touch
  it.** Assume a third exists — **and the route wiring runs straight through it.**
- **Reuse caps, never re-declare them.** A calibrated number gets one home.
- **The CI gate is real (D-028) and must stay honest** — `.github/workflows/ci.yml`
  runs `./ci.sh` and nothing else.
- **The README is a promise** pinned by `tests/test_docs.py`. Wiring the agent path
  changes what the deep path IS — if a bound stops being true, the test sends you
  there to change it deliberately.
- **`./scripts/demo.sh` must keep running end to end** (exit 0 verified at S25 end).
- **Any new assertion over an EXTRACTED set needs a floor** (S21's
  `len(called) >= 8` lesson), or it reports green with its input removed.
- DECISIONS.md entries are immutable once ratified; overturning one is a NEW
  numbered decision naming which it supersedes. **D-032 is ratified — main's
  protection is procedural. Do not re-open it.**
- Brand is locked (CLAUDE.md Brand, D-002). **Never leak the underlying model or
  provider name into user-visible strings** — including into TOOL RESULTS, which
  the model writes its answer from.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth. **S14–S25 each
  added zero.** A tunable that belongs to us is a code constant, per D-026.
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly. (**119 modules**;
  `auspex.agent` is already packaged.)
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 19× now); TD-014; TD-015; TD-016;
  TD-017; TD-019; TD-020; TD-021; TD-022; TD-023; **TD-024**; TD-025; **TD-027
  (HARD GATE)**; **TD-029**; **TD-030**; **TD-031/032/033**; **TD-036**; the card
  stream emitting status changes; model-PROPOSED hypotheses/evidence and
  falsifiers (D-019-later, D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
  Tired human = short session; rituals anyway.
- End with `/session-end`.
