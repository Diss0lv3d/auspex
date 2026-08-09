# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: S14 is COMPLETE on `staging` but **NOT promoted** — `main`
is still at #14 (87eb279). Step 0 fixed 4 executed findings in the S13 cited-
summary path (attacker text could poison the citation guard; the uncited check
failed 3 of 4 faithful renderings; the pin broke on bold; the directive was
unbounded in evidence count). Then Retro-hunt shipped: new intel sweeps
historical observables through a bounded indexed join, re-open events never touch
a verdict, verdict label changes became provenanced rows. Live-verified against a
genuinely KEV-listed CVE — which also exposed that **every container image since
the Dockerfile was written shipped a broken install** (all `__init__.py` at 0
bytes, `auspex.modes` never declared), invisible because uvicorn's cwd shadows
site-packages. CI-green 643 tests, `ci.sh` now gates the installed dist.)_

---

SESSION S15 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S15` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
re-check before every `gh` call. It did NOT flip at S13 or S14 start; assume it
flips anyway. Also: local `main` goes stale every promote — `git fetch` and diff
against `origin/main`, never local `main`.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **Check the TD-005 re-battery trigger first — it is close.** The corpus was
  ~25.9k docs in `auspex-knowledge` at S14 end and grows ~770/day while the
  container runs. Over 30k → re-run the labeled retrieval battery before
  trusting any RAG-backed answer this session. (`curl -s
  "localhost:9200/_cat/indices/auspex-knowledge?v"`.)
- **Fresh-eyes review of the S14 commits** — scope: `404b092` (retro-hunt:
  sweep, events, flips, routes, 2 tables), `792929f` (packaging), and the
  Step-0 fixes `d06ad1b`/`a795fe6`. This code is live-verified and has 31 tests
  but no independent adversarial pass. Angles S14 did NOT test:
  - **(tenancy) the sweep deliberately does not filter by workspace.** It runs
    across tenants on `(type, value)` by design. Verify by execution that every
    write and read path is scoped — including `open_match_for`, which runs
    inside *whichever* tenant's enrichment transaction is calling it. Can a
    flip in workspace A ever link a match belonging to workspace B?
  - **(concurrency) flip-writer contention.** `latest_verdict` reads before the
    insert. Two concurrent enrichments of the SAME observable: two flips? a
    wrong `from_label`? a flip whose `from_verdict_id` is the other run's row?
    The S13 review found exactly this class in `add_evidence` and fixed it with
    `FOR UPDATE` — check whether this needs the same, and verify with
    `asyncio.gather` against the live DB, not by reading.
  - **(cost) the KEV first-run sweep inside an ingest cycle.** ~1,600 ids = 32
    sequential queries plus 32 `record_matches` transactions, all inside
    `run_cycle`. Measure it; decide whether it belongs off the cycle's critical
    path (the TD-008 precedent) or is fine as-is.
  - **(honesty) `change_kind: "deleted"` as a re-open reason.** An NVD-rejected
    CVE is currently recorded with the same payload wording as a KEV addition
    ("New intel touches an observable…"). "This CVE was withdrawn" is a
    different claim and may deserve different copy, or may not belong in
    TRIGGER_KINDS at all. Decide deliberately.
  Verify findings BY EXECUTION before fixing; fix with regressions.
- **Then `/promote` #15** (S12+S13+S14 have all been reviewed once by then).
  Expect `gh pr merge` to be blocked by the permission classifier — I merge by
  hand, then Claude back-merges.

Goal (scope-locked, from ROADMAP.md S15 — Falsification watchers, Phase 3
flagship):

1. **Verdicts register "what would flip me".** When a verdict is written, record
   the concrete, checkable conditions that would falsify it — typed, not prose
   (e.g. "this hash appears in a KEV-listed CVE's exploitation chain", "this
   domain's registrar changes", "a higher-severity provider signal arrives").
   Start by reading `auspex/enrich/verdict.py` (synthesize + D-017 fields) and
   `auspex/retrohunt/flips.py` — S14's flip rows are the first evidence of a
   verdict actually being falsified, and the watcher vocabulary should be able
   to describe what already happened there.
2. **Watchers monitor feeds/enrichment for exactly that.** The retro-hunt sink
   (`auspex/retrohunt/sink.py`) is the existing on-ingest hook — extend or
   parallel it so a DocChange can satisfy a registered watcher, not just match
   an observable. Same constraint as S14: **indexed join, never a scan per
   change**, EXPLAIN-probed and saved to docs/probes/ before it is called done.
3. **A satisfied watcher is a reason to re-examine, never an auto-flip**
   (D-020's rail, and D-017's "new evidence, not the calendar, changes labels").
   It should reuse or extend the S14 re-open event surface rather than inventing
   a second notification shape.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic — watcher logic
  pinned by fixtures, zero LLM on this path (model-PROPOSED falsifiers, if ever,
  go through a contract and are NOT required for S15 done).
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` will fail loudly if you forget,
  which is new as of S14 — do not work around it.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 8× now); TD-012 (post-hoc
  validation, no re-ask); TD-014 (unbounded history); TD-015 (brand/confusable
  coverage); TD-016 (ACH surface bounds); TD-017 (chat-side NUL hardening);
  TD-018 (per-workspace inference-call bound — S19 owns it); TD-019 (retro-hunt
  v1 bounds: CVE-only sweep, no pagination, cycle timing unobserved);
  model-PROPOSED hypotheses/evidence (D-019-later).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move
  on. Tired human = short session; rituals anyway.
- End with `/session-end`; S15 done = verdicts carry typed falsification
  conditions, an on-ingest watcher check satisfies them through an
  EXPLAIN-probed indexed join, a satisfied watcher surfaces as an honest
  re-examine event (never an auto-flip), all pinned by hermetic fixtures and
  live-verified in-container.
