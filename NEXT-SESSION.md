# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**One commit is waiting to promote:** `839d574`, the S17 Actions SDK — it is the
only thing in `origin/main..staging`. The Step-0 review fixes already went up as
PR #16 (squash `ed0443b`) and were back-merged. Two operational facts re-probed at
S17 and worth trusting: `gh pr merge` works (Claude merged #16 first try), and
**this repo has no GitHub Actions at all** — `gh pr checks` reports 0, so `./ci.sh`
locally IS the gate; do not wait on remote CI. S17 shipped: Step 0 found the
digest's decay read was reading a workspace's whole verdict history and spilling
its sort to disk — 143 ms → **4.6 ms** — plus a crash-looping app that reported a
trustworthy digest forever and a truncated digest that announced its page size as
the total. Then the Actions SDK contract (D-023): a destructive action with no undo
cannot be constructed, `dry_run` is required of everything, and the planner
manifest reuses the S13 capability decision. CI-green 772 tests, 110 modules.)_

---

SESSION S18 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S18` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
it did NOT flip at S17 but DID at S16, so assume it has and re-check before every
`gh` call. `gh pr edit` fails on this repo with a Projects-classic GraphQL error —
use `gh api -X PATCH repos/.../pulls/N`. Local `main` goes stale every promote —
`git fetch` and read `git diff origin/main..staging --stat`, never the commit list.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **`/promote` FIRST this time** — `839d574` (the Actions SDK) is on staging and
  not on `main`. It is reviewed by nobody yet, which is fine: the review below is
  what Step 0 is for, and holding an unreviewed commit off `main` for a whole
  session is worse than promoting a green one. Confirm the gh ACTIVE account is
  `bh3082336888-cell` immediately before the call, then back-merge and assert the
  tree is unchanged.
- **Check the TD-005 re-battery trigger.** Corpus was **27,475** docs in
  `auspex-knowledge` at S17 end, ~2,525 short of 30k. Over 30k → re-run the
  labeled retrieval battery before trusting any RAG-backed answer.
  (`curl -s "localhost:9200/_cat/indices/auspex-knowledge?v"`.)
- **Fresh-eyes review of the S17 commits** — scope: `e57ab0c` (the Step-0 review
  fixes: the rewritten `_DECAYED_SQL`, `reader_now`, the checker-liveness rule,
  digest truncation) and `839d574` (`auspex/actions/` + the loop integration), plus
  `dc6dd6a` for what was claimed. Angles S17 did NOT test:
  - **(the rewrite's blind spot — strongest lead) the new `_DECAYED_SQL` enumerates
    a workspace's half-lives with a recursive loose-index-scan, and it was measured
    on a workspace with exactly THREE.** The bounds set is `edges × half-lives`, so
    every extra distinct `half_life_days` value adds three more LATERAL descents.
    Seed a workspace with many distinct half-lives (S7 floors, a future per-source
    curve — 20-50 values) and EXPLAIN. Related and explicitly unfinished: the
    365-day window is ~9% SLOWER than the old query and the crossover was never
    bounded — find it, and decide whether `MAX_SINCE_DAYS` should move.
  - **(the invisible fence) `OFFSET 0` in `_DECAYED_SQL` is load-bearing and looks
    like dead syntax.** Delete it and the query still returns the RIGHT rows, 15×
    slower. Verify the plan test actually FAILS with it removed — if it passes, the
    fence is unprotected and the test is decoration.
  - **(the new trustworthy rule) four clauses now decide whether a quiet digest may
    be believed.** Execute the matrix, especially: does a healthy `ingest-cycle`
    counter MASK a degraded consumer? What does a workspace with ingest DISABLED
    report now (empty roster vs a roster of never-run counters)? And does the
    "failed but never succeeded" clause fire on a first-cycle transient that then
    heals, i.e. is it too eager in practice?
  - **(the contract's own rails) every refusal in `validate_spec` is a claim that
    something cannot be built.** Try to break each: reach `planner_description` on
    a destructive action with no undo, get a `wire_spec` whose `required` disagrees
    with its properties, register an action whose name collides on the wire with an
    existing TOOL (`isolate_host` vs a tool of the same name — the loop resolves
    names in the ToolRegistry, so what happens?). The `object.__setattr__` forge in
    the tests proves one door is shut; look for the others.
  Verify findings BY EXECUTION before fixing; fix with regressions.

Goal (scope-locked, from ROADMAP.md S18 — Approval flow, **Phase 4**):

S17 made an action declarable. S18 is where the declaration stops being a
document: a human sees a proposal, decides, and something actually happens — which
makes this the session where every S17 bound comes due (TD-023).

1. **Approval cards over SSE.** A proposal reaches the analyst as a card carrying
   what the action WOULD do — the `dry_run` outcome, the systems touched, and
   whether it can be undone (including what the undo cannot restore). The card is
   rendered from the spec, not from model prose (D-023, D-007).
2. **Atomic claim-first settlement.** Two approvers, one proposal, exactly one
   execution. `UPDATE ... WHERE status='pending_approval' RETURNING` — the claim
   wins the row before anything runs, which is the D-001 reason Postgres holds
   truth. A double-approve must be provably impossible, not unlikely.
3. **Permission re-check at execute time**, extended per TD-023 to the SPEC: an
   action approved an hour ago must not execute against a changed declaration.
   Carry a spec fingerprint on the proposal row and re-validate before running.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic.
- **This is the first session where something REALLY executes.** An action that
  touches a real external system needs a real credential and a real blast radius —
  so S18's executor runs only actions whose scope is a system we control (start
  with an internal one: a verdict annotation, a workspace note), and anything
  reaching a third party stays proposal-only until there is a sandbox to point it
  at. If a step needs a live third-party side effect to be meaningful, that is the
  signal it belongs later.
- **Undo must be exercised, not just declared** (TD-023): if an execution path
  ships, its undo ships with a test that runs it.
- The dark-first brand palette is locked (CLAUDE.md Brand, D-002) — Night
  `#0A0D12`, Aurora `#4FF2C0`, Signal `#FFB454`, Ember `#FF5D5D`, Slate `#8B93A7`.
  Space Grotesk / Inter / JetBrains Mono. Never leak the underlying model or
  provider name into user-visible strings.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth. (S14–S17 each
  added zero — hold that line.)
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly if you forget — do
  not work around it. (S17 added `auspex.actions` to both; 110 modules now.)
- Plan assertions must VACUUM first, and only at sizes where a scan would cost
  something. **Delete seeded probe workspaces before running the suite** — a 100k
  row leftover made the timeline plan tests take 150 s instead of 21 s (S17).
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 11× now); TD-012 (post-hoc
  validation); TD-014 (unbounded history); TD-015 (brand/confusable coverage);
  TD-016 (ACH surface bounds); TD-017 (chat-side NUL hardening); TD-018
  (per-workspace inference-call bound — S19 owns it); TD-019 (retro-hunt v1
  bounds); TD-020 (watcher v1 bounds); TD-021 (timeline v1 bounds — two items
  resolved at S17); TD-022 (durable checker heartbeat); TD-023 (Actions SDK v1
  bounds — items (a) and (c) are IN scope this session); model-PROPOSED
  hypotheses/evidence and model-PROPOSED falsifiers (D-019-later, D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
  Tired human = short session; rituals anyway.
- End with `/session-end`; S18 done = a proposal can be approved exactly once, the
  approval renders what the action would do from its spec, an approved action
  re-checks both permission AND spec before running, and an executed action can be
  undone by a test that actually runs the undo.
