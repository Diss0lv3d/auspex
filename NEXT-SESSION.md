# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**S22 is done — the output side of the platform finally exists.** You chose
TD-012, and it was the choice the repo had already argued for four times:
**`auspex/outguard.py` shipped, ratified as D-030.** It does not ask whether an
answer was *influenced* — undecidable from text, and a model grading itself is what
D-006 refuses — but whether **the platform's own configuration is coming back out**,
which is decidable because we hold both halves. `SHINGLE_WORDS = 8` is **calibrated
on 34 live Scout answers**, not chosen: legitimate ceiling 6, the one extraction
attempt that complied reproduced **60** words — and **the model refused 3 of 5**,
which is exactly why a rail beats trust. A leak is cut off mid-stream and **not
persisted**, live-verified through the rebuilt container with no assistant row left
behind. Step 0 found two defects: **S21's sentence-scoping fix closed only one of
three spellings** — a newline and an end-of-input full stop each left it open 6/6,
and deleting one space undid it — and **a late handler was overwriting the human who
abandoned it** (`abandoned` → `executed`, with `decided_by` still naming that human).
Four designs were measured against the **real 129-test corpus** rather than one
written alongside them, and the probe's own first draft was caught measuring the
wrong carve-out. **1014 tests, 118 modules, zero new env vars — nine sessions
running.**)_

---

SESSION S23 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S23` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
it did at S18 and S16, did NOT at S17, S13–S15, S19–S22, so assume it has and
re-check before every `gh` call. `gh pr edit` fails on this repo with a
Projects-classic GraphQL error — use `gh api -X PATCH repos/.../pulls/N`. Local
`main` goes stale every promote — `git fetch` and read
`git diff origin/main..staging --stat`, **never the commit list**. The app
container runs the built image, not the working tree — live verification needs
`docker compose up -d --build app`. And **run the suite the way `ci.sh` does**: it
uses `.venv`, where the package is installed editable; a bare `python3 -m pytest`
uses the system interpreter where `auspex` is not installed and the packaging test
fails for that reason alone — it cost time in S22.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **`/promote` FIRST.** The slate is a **REAL** one this time, not the docs-only
  steady state: `e8a5607` (the guard sentence boundary), `4957b5e` (the late-handler
  overwrite), `711e85f` (Step-0 record + TD-033), `6ae733a` (the output rail), plus
  the S22 session-end commit. **Verify by reading the real diff**
  (`git fetch origin && git diff origin/main..staging --stat`), never the commit
  list — PR #22's list still showed every commit back to S2 while the real change
  was 4 files. `gh pr checks <n> --watch --interval 20` works; merge only on CLEAN.
- **Fresh-eyes review of the S22 commits** — scope: `6ae733a` (`auspex/outguard.py`,
  the `instruction_index`/`OutputScanner` pair, and the wiring in
  `routes/chat.py::event_stream`), `e8a5607` (`_SENTENCE_END_RE`), `4957b5e`
  (`_finish_claim`). Angles S22 did NOT adversarially test:
  - **(strongest lead — the rail's index is built ONCE, from four fixed strings.)**
    If any instruction text becomes dynamic, the index silently protects less than
    it appears to. Check what happens on a turn where `deterministic_triage_block`
    or `deterministic_phishing_block` is appended — those are deliberately NOT
    indexed, so an answer echoing them is fine, but **verify that is still true when
    a contract pins values that also appear in the indexed directives.** Also: the
    index is built before `event_stream` runs, so confirm nothing mutates
    `contract` or the directives between the two.
  - **(the scanner is stateful and the stream can end mid-run.)** `_carry` keeps
    `shingle - 1` words. Test: a leak split so the run straddles THREE chunks; a
    chunk that is pure punctuation (tokenises to nothing) in the middle of a run; a
    stream that ends one word short of a match; and the two-pass path where pass 1
    and pass 2 feed the SAME scanner — a run half in reasoning and half in the
    answer is not a real leak, but the scanner cannot tell. Measure it.
  - **(`_finish_claim` now has a late-write path.)** The `status = 'abandoned' AND
    <column> IS NULL` write is a second writer to a terminal row. Race two late
    handlers; race a late handler against a human doing something else to the same
    row; check that an `undo` late-write cannot land on a row abandoned during
    `execute` (the column differs, the status does not).
  - **(the newline boundary is new and the chat UI is not the only surface.)**
    `Enter` sends in the browser, but `/api/chat` takes any string. Re-measure the
    S11 `.eml` corpus and the phishing suite for messages whose reported speech now
    spans a line break — S22 measured 129 tests green, but did not go looking for
    the shape specifically.
  Verify findings BY EXECUTION before fixing; fix with regressions. **And read
  docs/probes/2026-08-16-s22-step0-review.md §"The measurement discipline" before
  you start** — three sessions running, a probe has passed because its payload
  measured the wrong thing. Assert the REASON, not just the verdict.

Goal — **there IS a clear candidate this time, for the first time in three
sessions, but still put it to me before implementing.** In order:

1. **Wire AgentLoop into `/api/chat`. Recommended.** The largest remaining gap
   between what the platform is and what its own README says: the loop is built,
   capability-negotiated and tested, and the deep path does not use it. It kept
   losing because TD-012 read as its prerequisite — **that prerequisite now
   half-exists (D-030).** One thing to carry into the design: the output rail
   indexes four fixed strings today, and a tool-calling loop makes the instruction
   set **dynamic**. The rail's index has to follow it, or it silently protects less
   than it looks like it does. That is a design constraint, not an afterthought.
2. **Finish TD-028 (b/c/d) with TD-025's terminal-state semantics.** (b) is the
   sharpest measured defect left in the repo: a failed execute reports that nothing
   happened while the handler's INSERT is really in the table. S22 fixed the
   adjacent defect in the same four statements, so the code is freshly mapped.
   Smaller than (1) and fully specified.
3. **TD-012(b) — contract-conformance repair.** The ORIGINAL S9 entry, and still
   open: re-ask once on a non-conforming answer. The TD-012 entry now distinguishes
   (a) shipped from (b) open — read it before assuming the number is closed.
4. **Phase 5 / Herd Immunity groundwork** — needs multi-workspace and a privacy
   review before any code; a design session, not an implementation one.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic.
- **Do NOT re-open the guard regex.** S19, S20 and S21 each spent a session there.
  S22 touched only the sentence *boundary*, and only because it was a defect in
  S21's own fix. TD-031, TD-032 and TD-033 are ratified bounds, and all three name
  TD-012 — **which now exists.** A new carve-out is not the answer to anything.
- **`SHINGLE_WORDS` is a calibrated number, not a constant to edit.** It was
  measured against Scout specifically. A more verbose customer endpoint, or a
  materially longer instruction set, moves the legitimate ceiling — re-run
  `docs/probes/s22-outguard/probe_calibrate2.py` before touching it. Same rule
  NEURAL_FLOORS has.
- **The CI gate is real (D-028) and must stay honest.** `.github/workflows/ci.yml`
  runs `./ci.sh` and nothing else — if a step needs adding, add it to `ci.sh`.
  `tests/test_docs.py::test_ci_runs_the_same_gate_a_developer_runs` fails loudly if
  the workflow grows its own `ruff`/`pytest`/`pip install`.
- **The README is a promise, and S22 rewrote its honesty bullet** — "the guard
  bounds input, not output" stopped being true. It is pinned by `tests/test_docs.py`;
  if a bound stops being true the test sends you there to change it deliberately.
- **`./scripts/demo.sh` must keep running end to end.** S22 added the output rail to
  its honest section as a real `grep` of the calibrated constant — deliberately not
  a live turn, because the rail's firing against a real model is not deterministic
  (the model refused 3 of 5 extraction attempts).
- **Any new assertion over an EXTRACTED set needs a floor** (S21's `len(called) >= 8`
  lesson), or it reports green with its input removed.
- DECISIONS.md entries are immutable once ratified; overturning one is a NEW
  numbered decision naming which it supersedes. **D-030 was added in S22.**
- Brand is locked (CLAUDE.md Brand, D-002) — Night `#0A0D12`, Aurora `#4FF2C0`,
  Signal `#FFB454`, Ember `#FF5D5D`, Slate `#8B93A7`; Space Grotesk / Inter /
  JetBrains Mono. **Never leak the underlying model or provider name into
  user-visible strings** — enforced on the docs too, not just app strings.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth (a test enforces
  the second half). **S14–S22 each added zero.** A tunable that belongs to us and
  not to the operator is a code constant (`STALE_CLAIM_SECONDS`, `SHINGLE_WORDS`),
  per D-026.
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly if you forget.
  (**118 modules now** — `auspex/outguard.py` needed neither, because it is a module
  inside a package that is already listed.)
- **Tests that touch `usage_counters` must clean up** — all dev-login users share the
  `default` workspace. Same for probes that write rows: S22's live verification
  deleted its two chat sessions and asserted 0 residue.
- **Branch protection on `main` is still OFF** — the check exists and is green but
  nothing requires it before a merge. It is a repo-settings change and my call; the
  exact command is in STATE.md in-flight item 2. Ask me once, do not enable it
  unprompted.
- **An intermittent test failure was seen ONCE in S22** — pytest's "multiple
  unraisable exception warnings" ExceptionGroup, no test named, not reproduced in
  five subsequent full runs. If it reappears, it is an async-teardown flake; chase
  it then, not before.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 16× now); TD-014; TD-015; TD-016;
  TD-017; TD-019; TD-020; TD-021; TD-022; TD-023 (remaining: grant-checked scope,
  array params); **TD-024 (the decay-read crossover — costed, measured, deliberately
  not taken)**; TD-025; **TD-027 (HARD GATE: re-run the CVE battery before any
  free-text-over-CVEs surface ships)**; **TD-029 (no CHECK constraint on
  `workspaces.plan`)**; **TD-030 (a failed turn is charged in full — D-027)**;
  **TD-031/032/033 (ratified guard bounds — see the constraint above)**; the card
  stream emitting status changes and not just new cards; model-PROPOSED
  hypotheses/evidence and model-PROPOSED falsifiers (D-019-later, D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
  Tired human = short session; rituals anyway.
- End with `/session-end`.
