# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**S21 is done — the first session with no roadmap entry, scoped by a decision
instead of a plan.** You chose "pay down what beta exposed" and both items closed.
**TD-026 went 3/7 → 7/7** (the definition path now renders the page the question is
about) — but the brief was wrong about the labels: only *one* of the two "stale"
ones was in that battery, the other belongs to the CVE battery. **TD-028a closed**
— a wedged claim is now visible in the queue with a `POST .../abandon` door out,
**and deliberately with NO reaper**, reversing what S19 asked for, because a timer
cannot know whether the handler ran before the process died. Step 0 came first and
found the sharpest thing in the session: **S20 fixed one invisible-character hole by
opening its inverse** — folding deletes invisibles, deletion welds words, and
`previous<ZWSP>instructions` came back CLEAN, 18 escapes measured. Also fixed: an
attribution two sentences back attributed nothing (6/6), and an inch mark opened a
covering quote span. Two bounds ratified rather than chased (**D-029**, TD-031/032),
and **a docs test was caught passing with its entire input removed**. The probe's
own first draft repeated, verbatim, a measurement mistake this repo had already
written down once — that is in the record too. **964 tests, 117 modules, zero new
env vars — eight sessions running.**)_

---

SESSION S22 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S22` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
it did at S18 and S16, did NOT at S17, S13–S15, S19, S20 or S21, so assume it has
and re-check before every `gh` call. `gh pr edit` fails on this repo with a
Projects-classic GraphQL error — use `gh api -X PATCH repos/.../pulls/N`. Local
`main` goes stale every promote — `git fetch` and read
`git diff origin/main..staging --stat`, **never the commit list**. And: **the app
container runs the built image, not the working tree** — anything you live-verify
needs `docker compose up -d --build app`, not `restart`.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **`/promote` FIRST.** The slate is **docs-only** — `a306106` (the PR #21 promote
  record) plus the S21 session-end commit. That is the normal steady state, not a
  divergence: the commit recording a promote lands *after* the promote, so the slate
  is never empty between sessions. **Verify by reading the real diff**
  (`git fetch origin && git diff origin/main..staging --stat`), never the commit
  list — after a squash the list is meaningless. `gh pr checks <n> --watch
  --interval 20` works; merge only on CLEAN.
- **Fresh-eyes review of the S21 commits** — scope: `72a7b84` (the folded∪raw union,
  sentence-scoped reported speech, the quote-adjacency lookarounds, the
  `len(called) >= 8` floor), `7b6e061` (`rrf_fuse_docs`, `auspex/kb/canonical.py`,
  depth-then-truncate), `9f023f0` (`claimed_at`, `pending()`'s stale-claim arm,
  `POST /api/proposals/{id}/abandon`). Angles S21 did NOT adversarially test:
  - **(strongest lead — the union can only ever refuse MORE.)** `inspect` now
    matches the folded copy **and** the raw one and unions the spans. Every
    false-positive argument S19/S20 made was measured against one pass, not two.
    Find an input the raw pass refuses that the folded pass was silently rescuing
    — the corpus was re-run, but was it re-run *per pass*? Also check the span
    union itself: two overlapping spans from different passes, a raw span that
    starts inside a folded one, and whether a carve-out boundary computed on one
    copy is applied to the other.
  - **(the sentence scoper is a new parser.)** How is a sentence boundary decided?
    `e.g.`, `i.e.`, `T1566.001`, `192.168.1.1`, `Dr.`, a decimal, a URL, and a
    newline-only break are all candidates for splitting where a human would not —
    and each wrong split either refuses legitimate reported speech or hands an
    attacker a cheap way to end a sentence early. Measure against the S11 `.eml`
    corpus the way S19's carve-outs were.
  - **(TD-026's promotion has no floor of its own.)** `title_score` re-orders
    candidates that cleared the neural floor — so the *worst* above-floor page can
    be promoted to first if its title happens to match. Try a question whose exact
    words appear in an irrelevant page's title. Also: the harmonic mean over an
    empty or one-word title, a title with punctuation, and a question that is a
    single word.
  - **(`abandon` is a state transition a human can trigger.)** Two concurrent
    abandons on the same row; an abandon that races the handler finishing at exactly
    `STALE_CLAIM_SECONDS`; abandon on a row that was never claimed; abandon across a
    tenant boundary (a workspace abandoning another's proposal). The claim-age guard
    is in the UPDATE — verify by racing it, the way S18 raced settlement 8-way.
  - **(the stale-claim arm changed a query every approver reads.)** `pending()` now
    returns two kinds of row. Check tenancy on the new arm specifically, and check
    that a stale claim cannot be approved/rejected through the ordinary buttons in a
    way that contradicts what `abandon` is for.
  Verify findings BY EXECUTION before fixing; fix with regressions. **And read
  docs/probes/2026-08-15-s21-step0-review.md §"The measurement error, first" before
  you start** — twice now a probe has passed because its payload tripped a second
  pattern. Assert your payload measures what you think it measures.

Goal — **THERE IS STILL NO ROADMAP ENTRY. Do not improvise one.** Put the choice to
me and get an answer before any implementation. The candidates, in the order the
repo's own evidence argues for:

1. **TD-012 — post-hoc output validation. Recommended, and the repo has now said so
   three times in its own words.** D-027 declined to chase forgeries and pointed
   here; TD-031 and TD-032 were both ratified in S21 with "the real answer is TD-012"
   written into them. Three sessions have gone into the input rail and the output
   side has none — an injection that got in *however* it got in is still uncaught,
   and TD-031 is a **two-character** bypass we have deliberately kept. It is also the
   prerequisite that option 2 carries.
2. **Wire AgentLoop into `/api/chat`.** Still the largest gap between what the
   platform is and what its own README says: the loop is built,
   capability-negotiated and tested, and the deep path does not use it. It changes
   what the guard and the ceilings are protecting, which is exactly why (1) reads as
   its prerequisite rather than a competitor.
3. **Finish TD-028 (b/c/d) with TD-025's terminal-state semantics.** (b) is the
   sharpest measured defect left in the repo: a failed execute reports that nothing
   happened while the handler's INSERT is really in the table. (c) got *sharper* in
   S21, not softer — `abandoned` joins `failed` as a state whose effects are unknown
   and whose `undo` is gated shut. Smaller than (1) or (2) and fully specified.
4. **Phase 5 / Herd Immunity groundwork** — needs multi-workspace and a privacy
   review before any code; a design session, not an implementation one.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic.
- **Do NOT re-open the guard regex.** S19, S20 and S21 each spent a session there,
  and TD-031 says in writing not to spend a third on it. D-029 ratified what it
  admits. If the answer feels like a new carve-out or a tighter lookaround, it is
  TD-012 wearing a disguise.
- **The CI gate is real (D-028) and must stay honest.** `.github/workflows/ci.yml`
  runs `./ci.sh` and nothing else — if a step needs adding, add it to `ci.sh`.
  `tests/test_docs.py::test_ci_runs_the_same_gate_a_developer_runs` fails loudly if
  the workflow grows its own `ruff`/`pytest`/`pip install`. Do not work around it.
- **The README is a promise, and S21 edited its honesty section twice** (TD-026 and
  TD-028a both left it). It is pinned by `tests/test_docs.py`; if a bound stops
  being true the test sends you there to change it deliberately. That is the point.
- **`./scripts/demo.sh` must keep running end to end.** It is the beta demo, tested
  against the live route table, and it now demonstrates the abandon path too.
- **A docs test was caught being vacuous in S21** (`len(called) >= 8` is the floor
  that fixed it). Any new assertion over an *extracted* set needs a floor, or it
  reports green with its input removed.
- DECISIONS.md entries are immutable once ratified; overturning one is a NEW
  numbered decision naming which it supersedes. **D-029 was added in S21.**
- Brand is locked (CLAUDE.md Brand, D-002) — Night `#0A0D12`, Aurora `#4FF2C0`,
  Signal `#FFB454`, Ember `#FF5D5D`, Slate `#8B93A7`; Space Grotesk / Inter /
  JetBrains Mono. **Never leak the underlying model or provider name into
  user-visible strings** — enforced on the docs too, not just app strings.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth (a test enforces
  the second half). **S14–S21 each added zero.** A tunable that belongs to us and
  not to the operator is a code constant (`STALE_CLAIM_SECONDS = 300`), per D-026.
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly if you forget — do not
  work around it. (**117 modules now.**)
- **Tests that touch `usage_counters` must clean up** — all dev-login users share the
  `default` workspace. (`./scripts/demo.sh` deliberately spends there; that is a
  demo, not a test.) Same for probes that write proposals: S21's deleted its row and
  asserted 0 residue.
- **Branch protection on `main` is still OFF** — the check exists and is green but
  nothing requires it before a merge. It is a repo-settings change and my call; the
  exact command is in STATE.md in-flight item 2. Ask me once, do not enable it
  unprompted.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 15× now); TD-014; TD-015; TD-016;
  TD-017; TD-019; TD-020; TD-021; TD-022; TD-023 (remaining: grant-checked scope,
  array params); **TD-024 (the decay-read crossover — costed, measured, deliberately
  not taken)**; TD-025; **TD-027 (HARD GATE: re-run the CVE battery before any
  free-text-over-CVEs surface ships)**; **TD-029 (no CHECK constraint on
  `workspaces.plan`)**; **TD-030 (a failed turn is charged in full — D-027)**;
  **TD-031/032 (ratified guard bounds — see the constraint above)**; the card stream
  emitting status changes and not just new cards (opened by the TD-028a fix);
  model-PROPOSED hypotheses/evidence and model-PROPOSED falsifiers (D-019-later,
  D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
  **S21 used it as intended twice** (two carve-out scopings measured, one shipped;
  two arm-removals measured, neither shipped). Tired human = short session; rituals
  anyway.
- End with `/session-end`.
