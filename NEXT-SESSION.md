# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: **PR #15 is OPEN, unmerged, and now carries EVERYTHING** —
https://github.com/bh3082336888-cell/auspex/pull/15. It is `staging → main`, so
S16's pushes extended it rather than creating a "#16"; its title and body were
rewritten to match (S14 retro-hunt + S15 watchers + both Step-0 reviews), but
the four S16 commits landed after that rewrite, so re-read it before merging.
`gh pr merge` is blocked by the permission classifier — merge by hand, then
Claude back-merges. S16 shipped: Step 0 found the analyst-facing `falsifies`
link survived only by the order `FanoutSink` happened to be built in, that its
loss was silent AND permanent, and — the part that decided the fix — that a
retro-hunt failure loses it with the order intact, so the link is derived at
read time now. Then the verdict timeline: `effective_confidence` renders for the
first time since S5, staleness is a band vocabulary in half-lives (D-022),
TD-020's open question is answered with a derived `standing` that never touches
`status`, and a quiet digest has to be earned. CI-green 720 tests.)_

---

SESSION S17 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S17` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
**it DID flip at S16 start**, so assume it has flipped again and re-check before
every `gh` call. Note `gh pr edit` fails on this repo with a Projects-classic
GraphQL error — use `gh api -X PATCH repos/.../pulls/N`. Also: local `main` goes
stale every promote — `git fetch` and read `git diff origin/main..staging --stat`
rather than the commit list, which the squash workflow makes meaningless.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **Check the TD-005 re-battery trigger first — it is close and may have
  tripped.** The corpus was **26,711** docs in `auspex-knowledge` at S16 end and
  grows ~770/day while the container runs. Over 30k → re-run the labeled
  retrieval battery before trusting any RAG-backed answer this session. (`curl -s
  "localhost:9200/_cat/indices/auspex-knowledge?v"`.)
- **Fresh-eyes review of the S16 commits** — scope: `44ccaa4` (the derived
  falsifies link + migration), `1b9e8e2` (the timeline package, `auspex/checks.py`,
  the routes and the page), plus `704dd87`/`b6a2eda` for what was claimed. This
  code is live-verified with 41 new tests but has had no independent adversarial
  pass. Angles S16 did NOT test:
  - **(the uncosted query — strongest lead) `_DECAYED_SQL` is the only new read
    in three sessions without an asserted plan,** and TD-021 says so out loud
    rather than hiding it. It `DISTINCT ON`s the latest verdict per observable
    and filters on an expression over `half_life_days`, so the crossing test
    cannot use an index — it is proportional to a workspace's whole enriched
    history, not to the handful of rows that crossed a band. Seed ~100k enriched
    observables, VACUUM, EXPLAIN. The digest is the page an analyst opens FIRST
    after a week away, so this is the read that must not be the slow one.
  - **(derived-link fan-out) the read-time LATERAL takes `ORDER BY satisfied_at
    DESC, id LIMIT 1`.** S16 pinned two verdicts of the SAME kind. Test the
    different-kinds case: a CVE that is KEV-added and later NVD-withdrawn with no
    re-enrichment between produces two matches and two satisfied claims sharing
    one doc id. Verify the pairing stays one-to-one and neither event borrows the
    other's claim.
  - **(clock authority) staleness is computed against the READER's `now`.**
    `timeline_for`/`digest` default to `datetime.now(UTC)` in the app process
    while `created_at` is `clock_timestamp()` in Postgres — two clocks decide one
    band. The negative-age clamp is tested; agreement between the two clocks is
    not. Verify what a skewed app container actually reports.
  - **(checker health honesty) `FailureCounter` resets on process restart.** A
    crash-looping app would report a pristine roster and a trustworthy digest
    forever — i.e. "degraded" may be unreachable in the failure mode most likely
    to happen. Verify by execution, then decide whether that is acceptable for v1
    or whether the counter belongs in Postgres (TD-021 has the note).
  Verify findings BY EXECUTION before fixing; fix with regressions.
- **Then `/promote`** (S16 will have been reviewed once by then). Expect
  `gh pr merge` to be blocked — I merge by hand, then Claude back-merges.

Goal (scope-locked, from ROADMAP.md S17 — Actions SDK contract, **Phase 4**):

This is the first session that is not Living Verdicts. Auspex's pitch is "an AI
co-analyst with SOAR-grade action capabilities built in"; everything so far
READS. S17 is the contract that lets it act, and the contract is the whole
deliverable — no action that touches a real system ships this session.

1. **The `@action` decorator and its typed contract.** Semantics, scope and risk
   declared in code, not prose (D-006 "code over prompts", D-007 "specs over
   prompts": the typed contract generates the prompt, the tests and the UI — not
   the other way around). An action declares what it does, what it needs, and
   what it can break.
2. **Destructive ⇒ undo is REQUIRED, and `dry_run` is required everywhere.**
   Not a convention, not a lint rule: registration must FAIL for a destructive
   action with no undo. The S14/S15/S16 rail applied to writes — "correct by
   construction, not by everyone remembering" — and this session is where it is
   cheapest to enforce and most expensive to skip.
3. **Registration API + planner manifest.** How an action becomes visible to the
   agent loop, and how the loop is told what it may propose. Reuse the S13
   capability negotiation shape rather than inventing a second manifest.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic. Zero LLM on the
  contract itself — a decorator and a registry are code.
- **Nothing executes against a real external system this session.** Proposals
  and approvals are S18. If a step needs a live side effect to be meaningful,
  that is the signal it belongs in S18.
- The dark-first brand palette is locked (CLAUDE.md Brand, D-002) — Night
  `#0A0D12`, Aurora `#4FF2C0`, Signal `#FFB454`, Ember `#FF5D5D`, Slate
  `#8B93A7`. Space Grotesk / Inter / JetBrains Mono. Never leak the underlying
  model or provider name into user-visible strings.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth. (S14, S15
  and S16 each added zero — hold that line.)
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly if you forget —
  do not work around it.
- Plan assertions must VACUUM first, and only at table sizes where a scan would
  actually cost something. Data-modifying CTEs cannot see each other's rows
  through a table scan — chain `INSERT ... RETURNING`, do not re-read the table
  (cost an hour in S16).
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 10× now); TD-012 (post-hoc
  validation); TD-014 (unbounded history); TD-015 (brand/confusable coverage);
  TD-016 (ACH surface bounds); TD-017 (chat-side NUL hardening); TD-018
  (per-workspace inference-call bound — S19 owns it); TD-019 (retro-hunt v1
  bounds); TD-020 (watcher v1 bounds — the expiry half is ANSWERED, the rest
  stands); TD-021 (timeline v1 bounds); model-PROPOSED hypotheses/evidence and
  model-PROPOSED falsifiers (D-019-later, D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move
  on. Tired human = short session; rituals anyway.
- End with `/session-end`; S17 done = an action can be declared, registered and
  described to the planner; a destructive action without undo cannot be
  registered at all; and every one of those claims is pinned by a hermetic test.
