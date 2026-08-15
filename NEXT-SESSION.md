# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**S20 is done, and it was the last session the ROADMAP had written down.**
**Nothing is waiting to promote — S20 is already on `main` as `fc7c921` via PR #20,
the first promote merged on a check anyone can see.** S20 promoted S19 via PR #19
**and recorded the
promote at merge time**, then reviewed it and found the sharpest defect was not the
one the brief predicted: the guard was refusing **4 of 6 legitimate SOC questions**
— "write a Sigma rule that fires on 'ignore all previous instructions'" got a 400 —
because every S19 carve-out was justified against pasted artefacts and none against
an analyst writing *about* an attack. Also fixed: invisible characters and homoglyphs
returned **CLEAN**, and a 47-char subordinate clause walked through the `{0,40}` gap.
Three more behaviours were forced, found correct, and **ratified rather than
"fixed"** (D-027): the carve-outs are forgeable by construction, spend is charged for
our own outage, and the fixed window is a real 2× burst. Then Beta: **CI now runs
`./ci.sh` itself** (D-028) and caught two defects green-on-laptop/red-on-runner on
its very first run — IPv6 observable identity was delegated to a stdlib formatting
choice, and three tests depended on accumulated dev-DB state. The repo got the
**README it never had**, and `./scripts/demo.sh` replaced demo turns scattered over
nine STATE.md revisions. **912 tests, zero new env vars — seven sessions running.**)_

---

SESSION S21 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S21` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
it did at S18 and S16, did NOT at S17, S13–S15, S19 or S20, so assume it has and
re-check before every `gh` call. `gh pr edit` fails on this repo with a
Projects-classic GraphQL error — use `gh api -X PATCH repos/.../pulls/N`. Local
`main` goes stale every promote — `git fetch` and read
`git diff origin/main..staging --stat`, **never the commit list**. And: **the app
container runs the built image, not the working tree** — a new migration needs
`docker compose up -d --build app`, not `restart`.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **`/promote` is ALREADY DONE — do not repeat it.** S20 reached `main` as squash
  `fc7c921` via **PR #20** (merged 2026-08-15 17:13 UTC), back-merged `a5c9c7f`,
  tree verified unchanged, slate empty. It was the first promote in this repo
  merged on a check anyone can see: `gh pr checks` reported the `ci.sh` job **pass
  in 5m25s**, not the 0 checks every promote from #1 to #19 got.
  **Verify this at session start rather than trusting it** —
  `git fetch origin && git diff origin/main..staging --stat` must be EMPTY. If it
  is not, something landed after this file was written; fix STATE.md first.
  (The `--watch` flow works: `gh pr checks <n> --watch --interval 20`.)
- **Fresh-eyes review of the S20 commits** — scope: `0c7c092` (the guard's fifth
  carve-out + `_normalize`), `d45e70b` (`_canonical_ipv6`), `bbf3fec`
  (`tests/test_docs.py`), and `scripts/demo.sh`. Angles S20 did NOT adversarially
  test:
  - **(strongest lead — the new carve-out is a new attack surface.)**
    `_REPORTED_SPEECH_RE` admits anything whose PREAMBLE names a third party and a
    speech verb. "The attacker told the model to " is now a **prefix that turns any
    imperative into content** — exactly the off-switch shape D-025 warned about,
    admitted deliberately on the argument that it is the same class as "here is the
    email body:". Decide honestly whether that argument holds, and check the
    `\b(?:that|which|like|such\s+as|for|about|on)\s+(?:say|says|…)\b` arm, which is
    much broader than the others and was not measured against real analyst prose.
  - **(the inline-quote carve-out)** `"[^"\n]{1,300}"` has no letter-adjacency
    guard the way the apostrophe arm does. Two unrelated double quotes in one
    message bracket everything between them — try prose with a quoted product name
    early and an imperative later. Also: nothing stops an attacker simply wrapping
    their whole injection in quotes, which is now a carve-out.
  - **(the fold could HIDE a match rather than reveal one)** `_normalize` deletes
    characters and maps confusables. Verify no input exists where folding *creates*
    a false negative or an index-map error — e.g. a message that is entirely
    invisible characters, a match starting at index 0, a match at the very end, or
    text where `index_map[end-1]+1` walks past a carve-out boundary and flips a
    verdict. The span-mapping test covers one case; it is not a proof.
  - **(`_canonical_ipv6` is now on the identity path for EVERY IPv6 observable)**
    The 200,268-address equivalence was measured on THIS interpreter. Check the
    zero-run compression against RFC 5952 §4.2.2 explicitly (the "longest run wins,
    leftmost on a tie, never compress a single group" rules) rather than against
    the stdlib alone, since agreeing with a buggy stdlib is not correctness.
  - **(the docs tests could be vacuous)** `test_the_demo_only_calls_routes_that_exist`
    passes if its `called` set is empty. Confirm each docs test FAILS when it should
    — break the README deliberately, break the workflow deliberately, and watch.
  Verify findings BY EXECUTION before fixing; fix with regressions.

Goal — **THIS IS THE FIRST SESSION WITH NO ROADMAP ENTRY. Do not improvise one.**

The ROADMAP through S20 is complete. Before any implementation, put the choice to
me and get an answer. The three honest candidates, in the order the repo's own
evidence argues for:

1. **Pay down what beta exposed (recommended).** TD-026 — the definition path
   renders the wrong ATT&CK page 3 times in 7 — is the only defect a beta user hits
   in the first ten minutes, and it is now advertised in the README, which makes
   fixing it a promise rather than a preference. TD-028 — `executing`/`undoing` with
   no reaper, invisible to the approver — is the one that loses a human's work.
   **Both already have measurements and reproductions written down; TD-026 also has
   two failed fix attempts and their numbers, and two of its seven battery labels
   are corpus-stale and must be re-examined FIRST.**
2. **Wire AgentLoop into `/api/chat`.** The largest gap between what the platform is
   and what its own README says: the loop is built, capability-negotiated and
   tested, and the deep path still does not use it. Carries TD-012 (post-hoc
   validation) as a prerequisite worth arguing about, and would change what the
   guard and the ceilings are protecting.
3. **Phase 5 / Herd Immunity groundwork.** Needs multi-workspace and a privacy
   review before any code — a design session, not an implementation one.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic.
- **The CI gate is real now (D-028) and must stay honest.** `.github/workflows/ci.yml`
  runs `./ci.sh` and nothing else — if a step needs adding, add it to `ci.sh`.
  `tests/test_docs.py::test_ci_runs_the_same_gate_a_developer_runs` fails loudly if
  the workflow grows its own `ruff`/`pytest`/`pip install`. Do not work around it.
- **The README is now a promise.** Its "What Auspex does not do yet" section is
  pinned by `tests/test_docs.py`. If a bound stops being true, the test sends you
  there to change it deliberately — that is the point, not an obstacle.
- **`./scripts/demo.sh` must keep running end to end.** It is the beta demo and it
  is tested against the live route table. Any route rename breaks it in CI, which is
  the intended behaviour.
- DECISIONS.md entries are immutable once ratified; overturning one is a NEW
  numbered decision naming which it supersedes. D-027 and D-028 were added in S20.
- Brand is locked (CLAUDE.md Brand, D-002) — Night `#0A0D12`, Aurora `#4FF2C0`,
  Signal `#FFB454`, Ember `#FF5D5D`, Slate `#8B93A7`; Space Grotesk / Inter /
  JetBrains Mono. **Never leak the underlying model or provider name into
  user-visible strings** — now enforced on the docs too, not just app strings.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth (a test enforces
  the second half). **S14–S20 each added zero.**
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly if you forget — do
  not work around it. (116 modules now.)
- **Tests that touch `usage_counters` must clean up** — all dev-login users share
  the `default` workspace. (`./scripts/demo.sh` deliberately does spend there; that
  is a demo, not a test.)
- **Branch protection on `main` is still OFF** — the check exists and is green but
  nothing requires it before a merge. It is a repo-settings change and my call; the
  exact command is in STATE.md in-flight item 2. Ask me once, do not enable it
  unprompted.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 14× now); TD-012; TD-014; TD-015;
  TD-016; TD-017; TD-019; TD-020; TD-021; TD-022; TD-023 (remaining: grant-checked
  scope, array params); **TD-024 (the decay-read crossover — costed, measured,
  deliberately not taken)**; TD-025; **TD-027 (HARD GATE: re-run the CVE battery
  before any free-text-over-CVEs surface ships)**; **TD-029 (no CHECK constraint on
  `workspaces.plan` — fails safe, fails quiet)**; **TD-030 (a failed turn is charged
  in full — ratified in D-027, logged with a costed fix)**; model-PROPOSED
  hypotheses/evidence and model-PROPOSED falsifiers (D-019-later, D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
  Tired human = short session; rituals anyway.
- End with `/session-end`.
