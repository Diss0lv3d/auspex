# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**S23 found two real defects in the output rail S22 shipped the day before, and
fixed both.** The sharper one: **a leak in pass 1 did not stop the turn.** `break`
left only its own loop, and a tripped scanner returns `None` from every later
`feed()` **by design** — so pass 2 made a second inference call and streamed a
whole answer **completely unscanned**. The done frame still said `output_guard`
and nothing persisted, which is exactly why S22's tests passed: **they asserted
the verdict, not the control flow** — and both used `native_reasoning=True`, so
the two-pass path a customer endpoint actually takes had **no leak coverage at
all**. The second: the scanner's carry **crossed the reasoning/answer boundary**,
tripping on a run that existed in neither. Both regressions **proven to fail
pre-fix**. TD-034 ratified (unreachable, and the reachability is now pinned by a
test). 34 assertions pinned sound. Then the chosen goal — wiring AgentLoop —
landed **its groundwork, not its implementation**, and that is deliberate: the
loop is blocking, `/api/chat` is SSE, and which way to resolve that is a **fact
about the endpoint**, so it was probed on real Scout. **D-031**: tool calls arrive
with **zero content before them** (the answer can stream honestly), arguments come
**fragmented across nine deltas split mid-token** (they must be accumulated), and
`finish_reason` is the step signal. Three hard constraints came with it — the app
populates **no ToolRegistry at all**, the usage claim must move inside the loop or
TD-018 breaks, and the rail's index must follow the composed system message.
**1021 tests, 118 modules, zero new env vars — ten sessions running.**)_

---

SESSION S24 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S24` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
it did at S18 and S16, did NOT at S17, S13–S15, S19–S23, so assume it has and
re-check before every `gh` call. `gh pr edit` fails on this repo with a
Projects-classic GraphQL error — use `gh api -X PATCH repos/.../pulls/N`. Local
`main` goes stale every promote — `git fetch` and read
`git diff origin/main..staging --stat`, **never the commit list**. The app
container runs the built image — live verification needs
`docker compose up -d --build app`. **Run the suite the way `ci.sh` does**: it uses
`.venv`, where the package is installed editable. And **never pipe `./ci.sh` into
`tail`** — the pipeline reports `tail`'s exit code, and S23 read "exit 0" off a run
that had actually failed lint. Redirect to a file and read `$?`.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **`/promote` FIRST.** A real slate: `12b30da` (a pass-1 leak ends the turn),
  `63cbb52` (the scanner's carry stops at the channel boundary), `4be3174` (Step-0
  record + TD-034), `fdec17b` (the streaming probe + D-031), plus the S23
  session-end commit. **Verify by reading the real diff**
  (`git fetch origin && git diff origin/main..staging --stat`), never the commit
  list — PR #23's list showed every commit back to S2 while the real change was 23
  files. `gh pr checks <n> --watch --interval 20` works; merge only on CLEAN.
- **Fresh-eyes review of the S23 commits** — scope: `12b30da` (the
  `if not scanner.tripped:` guard in `routes/chat.py::event_stream`), `63cbb52`
  (`OutputScanner.feed`'s `channel` parameter and the four labelled call sites),
  `4be3174` (the `undo` reachability pin). Angles S23 did NOT adversarially test:
  - **(strongest lead — the channel fix is a carry DROP, and drops lose things.)**
    The native path interleaves `reasoning` and `content` events. If an endpoint
    alternates them (reasoning, content, reasoning, content), every switch drops
    the carry — so a leak split across two chunks **within** the answer, separated
    by one interleaved reasoning delta, is now missed. Measure whether Scout ever
    interleaves; if it does, the channel key may need to be "the pane" rather than
    "the last event kind".
  - **(the pass-2 guard changed what a turn COSTS.)** The usage claim is taken up
    front for 2 calls on the two-pass path, and a pass-1 leak now makes only 1.
    The workspace is charged for a call it never made. Decide whether that is
    acceptable (it fails safe, toward charging more) or whether the claim should
    be reconciled — and note TD-030 already says a failed turn is charged in full.
  - **(the reachability pin asserts about a state machine, not a statement.)**
    `test_an_undo_cannot_start_on_a_row_abandoned_during_execute` guards TD-034.
    Check it actually fails if the undo claim is loosened, rather than passing for
    an unrelated reason — the S22/S23 lesson is that a test can pass with its
    subject removed.
  - **(the refund fixture is new shared state.)** `_no_usage_residue` DELETES the
    default workspace's `inference_calls` row. Verify it cannot mask a genuine
    limit assertion elsewhere, and that it is not order-dependent.
  Verify findings BY EXECUTION before fixing; fix with regressions. **Read
  docs/probes/2026-08-16-s23-step0-review.md §"The measurement discipline" before
  you start** — it has now failed and been caught in four consecutive sessions, in
  both directions. Assert the REASON, not just the verdict.

Goal — **the agent path, and for the first time the design is settled and measured
rather than argued (D-031).** Do (1) before (2): a loop with no tools has nothing
to do. Put the split to me before starting, but this is the recommended shape.

1. **Expose the platform's existing capabilities as agent READ tools.** The agent
   registry is **empty in the running app** — `grep ToolRegistry()` across
   `auspex/` finds nothing outside the class. Enrichment, CVE lookup and KB
   retrieval already exist as shortcut code paths; wrap the SAME code, do not
   re-implement it. Additive, testable on its own, and it is what makes an agent
   turn worth taking. Watch the D-014 levels: these are all READ.
2. **Wire AgentLoop into `/api/chat`, streaming, per D-031.** Narrate the tool
   steps, stream the answer after them (measured safe: zero content precedes tool
   calls), **accumulate tool-call arguments before parsing** (nine fragments split
   mid-token), use `finish_reason` as the step signal, **move the usage claim
   inside the loop** (up to 9 calls vs a claim of 1–2 — TD-018 breaks otherwise;
   a refusal mid-loop synthesises from what was gathered), and **build the output
   rail's index from the COMPOSED system message**, leaving tool results unindexed
   as data and treated as their own scanner channel.
3. **TD-028 (b/c/d) + TD-034 together.** All four want a terminal state that
   records what actually happened, and S22 and S23 have each worked in those four
   statements — the code is freshly mapped twice.
4. **TD-012(b)** — contract-conformance repair, the original S9 entry: re-ask once
   on a non-conforming answer. Smallest of the four.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic.
- **`prompted_tools` is deliberately unmeasured.** It parses `<tool_call>` tags out
  of *content*, so the tags would reach the analyst as prose before the loop could
  strip them. **Probe it before wiring it to a streaming surface** — do not assume
  the native findings transfer.
- **Any new test that spends inference calls must refund them.** All dev-login
  users share the `default` workspace against an **hourly** ceiling of 100, and
  nothing resets it at session start. Five unrefunded units made the S23 suite 429
  in one run and pass in the next. `_no_usage_residue` in test_chat_sse.py is the
  pattern.
- **Do NOT re-open the guard regex.** S19, S20 and S21 each spent a session there.
  S23 did not touch it at all. TD-031/032/033 are ratified bounds.
- **`SHINGLE_WORDS` is a calibrated number, not a constant to edit** — re-run
  `docs/probes/s22-outguard/probe_calibrate2.py` before touching it.
- **The CI gate is real (D-028) and must stay honest.** `.github/workflows/ci.yml`
  runs `./ci.sh` and nothing else — if a step needs adding, add it to `ci.sh`.
- **The README is a promise** and is pinned by `tests/test_docs.py`. Wiring the
  agent path changes what the deep path IS — if a bound stops being true, the test
  sends you there to change it deliberately.
- **`./scripts/demo.sh` must keep running end to end.**
- **Any new assertion over an EXTRACTED set needs a floor** (S21's `len(called) >= 8`
  lesson), or it reports green with its input removed.
- DECISIONS.md entries are immutable once ratified; overturning one is a NEW
  numbered decision naming which it supersedes. **D-031 was added in S23.**
- Brand is locked (CLAUDE.md Brand, D-002). **Never leak the underlying model or
  provider name into user-visible strings.**
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth. **S14–S23 each
  added zero.** A tunable that belongs to us is a code constant, per D-026.
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly. (**118 modules.**)
- **Branch protection on `main` is still OFF** — the check exists and is green but
  nothing requires it before a merge. Repo settings, my call; command in STATE.md
  in-flight item 2. Ask me once, do not enable it unprompted.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 17× now); TD-014; TD-015; TD-016;
  TD-017; TD-019; TD-020; TD-021; TD-022; TD-023; **TD-024**; TD-025; **TD-027
  (HARD GATE)**; **TD-029**; **TD-030 (a failed turn is charged in full — and S23's
  pass-1 guard just made that sharper)**; **TD-031/032/033**; the card stream
  emitting status changes; model-PROPOSED hypotheses/evidence and falsifiers
  (D-019-later, D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
  Tired human = short session; rituals anyway.
- End with `/session-end`.
