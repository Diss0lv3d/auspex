# STATE — Auspex

_Last updated: 2026-08-09 (S15 COMPLETE — Step 0: adversarial review of the S14
retro-hunt commits, 4 angles executed, 2 sound and 2 defects fixed (the verdict
trail's head was decided by transaction start, not write order; a withdrawn CVE
was announced as if new intel had arrived). Then **S15 Falsification watchers**
(Phase 3 flagship): verdicts register what would flip them, at write time, in
typed vocabulary; feeds and re-enrichment check those claims; a satisfied
watcher upgrades the S14 re-open event and never touches a label.)_

## Where we are
- **S15 COMPLETE, on `staging`, not yet promoted.** Three parts:
  - **Step 0 — adversarial review of `404b092`/`792929f`/`d06ad1b`/`a795fe6`
    (DONE).** Four angles S14 never took, every finding reproduced by execution
    BEFORE the fix (probe: docs/probes/2026-08-09-s15-step0-review.md).
    **2 SOUND, recorded as such:** (a) tenancy of the cross-workspace sweep — no
    match, verdict or flip crosses; the named "flip links another tenant's
    match" attack cannot happen because `open_match_for` is scoped on
    workspace_id AND observable_id and observable ids are already
    workspace-unique. (b) first-run sweep cost inside `run_cycle` — 1,600 ids
    where every one hits = **175 ms**, so the TD-008 move-it-off-the-cycle
    precedent does NOT apply.
    **2 DEFECTS fixed (4c00af9, 1e8e5dc):** (1) `created_at DEFAULT now()` is
    transaction_timestamp, and `latest_verdict` + the sweep's LATERAL both
    define "the current verdict" as the newest row by it. A transaction that
    began earlier, blocked on the observable's row lock, and committed LAST
    wrote the newest belief with the OLDEST stamp — executed: the trail reported
    a superseded `malicious` when the last committed belief was `suspicious`,
    and the re-open event published that stale label as `verdict_label_at_match`.
    `clock_timestamp()` on verdicts/retrohunt_matches/verdict_flips.
    (2) both emitters of `deleted` mean NVD REJECTED a CVE we hold, and S14
    rendered it with the sentence written for a KEV addition — the opposite
    motion. Per-kind copy in `MATCH_NOTES` beside `TRIGGER_KINDS`.
    Also: the `SWEEP_CHUNK` comment claimed "index-driven at every scale",
    measured false at 1,600 rows (harmless — 22 pages) and corrected.
  - **S15 feature — Falsification watchers (DONE).** `auspex/watchers/` (types,
    derive, store, sink) + `auspex/routes/watchers.py` + 1 table + 2 indexes +
    1 column on `retrohunt_matches`. Design ratified as **D-021**. Every verdict
    registers typed falsification conditions AT WRITE TIME in the same
    transaction; the vocabulary is a closed enum of 3 kinds derived in code
    (never prose, never model-proposed); each kind is owned by a checker and the
    partition is ASSERTED, so a watcher nobody evaluates cannot be added. Ingest
    checks via an indexed join per 50-id chunk on a **PARTIAL index**
    (`status='open'`); enrichment checks escalation by SEVERITY, not inequality.
    **A satisfied watcher never writes a verdict** — it upgrades the S14 re-open
    event (`falsifies`) rather than minting a second notification, and is
    acknowledged through that one event. Empty is a legitimate answer: a
    `malicious` CVE registers no `kev_listing` watcher because KEV agrees with
    it.
  - **A circular import fixed (in 233c132).** `auspex.watchers` ↔ `auspex.enrich`
    resolved only when enrich was imported first — true of the app and the test
    suite, false for `import auspex.watchers` alone, which raised ImportError.
    Same class as S14's packaging defect (correct by import order, not by
    construction). Import moved to call time; a subprocess test pins all three
    orders from OUTSIDE the source root.
- **Both query plans probed, not assumed** (docs/probes/2026-08-09-s15-watchers-
  explain.md). At the shipped chunk of 50 with 75k watchers the plan is a pure
  nested loop of index descents (unnest → `idx_observables_type_value` →
  `idx_watchers_open_obs_kind`), 0.139 ms. **The partial index is measured, not
  argued:** tripling the table with 50k CLOSED watchers left the check at
  0.190 ms vs 0.174 ms at 25k. A 1,600-id KEV first run = 34 ms of watcher check
  on top of the sweep's 175 ms. Same honest caveat as S14: below ~a few thousand
  rows the planner scans and is right to.
- **Live-verified in-container** against KEV-listed CVE-2026-35273 (probe:
  docs/probes/2026-08-09-s15-watchers-live.md): suspicious verdict registers 3
  claims → real KEV DocChange through the real `FanoutSink` satisfies ONLY the
  contradicted one → verdict trail untouched, 0 flips → re-open event carries
  `falsifies` → re-enrichment contradicts the escalation claim too
  (`satisfied_by=flip:…`) → the new `malicious` verdict correctly registers only
  `record_withdrawn`. Both satisfied claims SURVIVE the supersession performed
  in the same transaction. Re-emit is not news twice. HTTP surface confirmed
  with a real token (401 unauthenticated, 422 on a bad filter). Residue deleted.
- **CI-green: 676 tests** (643 → +2 Step-0 regressions, +2 copy, +29 watchers).
  `./ci.sh` green including the installed-dist gate (100 modules); container
  rebuilt; `/api/health/ready` 200.
- **Zero new env vars** this session (watchers read no configuration).
- **LLM untouched by S15** — the whole path is derivation, joins and events.

## In-flight / standing follow-ups (carry forward until DONE)
1. **PROMOTE #15 IS OPEN AND UNMERGED.** https://github.com/bh3082336888-cell/auspex/pull/15
   — MERGEABLE/CLEAN, raised this session with S14 + the S15 Step-0 fixes.
   `gh pr merge` is blocked by the Claude permission classifier: **the human
   merges it by hand, then Claude back-merges** (`git merge -X ours origin/main`
   on staging, verify the tree is unchanged, push). The S15 feature commits
   (233c132, e940efd) landed on staging AFTER the PR was raised, so they are
   NOT in it — promote #16 carries them.
2. **S16 Step 0: fresh-eyes review of the S15 commits** (`233c132`, `e940efd`,
   plus `4c00af9`/`1e8e5dc`/`fa7b70b` if #15 has not shipped them). Angles S15
   did NOT adversarially test:
   - **(order dependency) `satisfy_documents` links the re-open event by natural
     key including `change_kind`.** It only finds the match if `RetroHuntSink`
     has already written it — and `FanoutSink` happens to emit retro-hunt
     first. Reorder the sinks and `falsifies` silently stops appearing, with no
     error anywhere. This is the exact class of defect this session fixed twice
     (correct by order, not by construction); decide whether the link should be
     order-free or the order should be enforced.
   - **(double swallow) `FanoutSink` catches per sink, and both sinks already
     catch internally.** A watcher check that fails every cycle logs and is
     otherwise invisible — nothing counts consecutive failures. Is a silently
     dead falsification checker distinguishable from one with nothing to do?
   - **(concurrency) escalation satisfaction under concurrent enrichment.**
     S15 pinned concurrent REGISTRATION (one set of claims) but not concurrent
     `check_escalation` — two enrichments racing on one observable, one
     escalating and one not.
   - **(claim text) `claim` is built from `observable.value` and provider
     names** and stored unbounded. The classifier validates CVE shape, so this
     is probably fine — verify it rather than assume, and check what a
     non-CVE/edge observable produces.
3. **TD-005 re-battery trigger (standing, NOT tripped):** corpus > 30k chunks,
   ANY new doc_type, or embedding-model change → re-run the labeled battery.
   S15 added no doc_type and no model change. Corpus **25,938 docs** at S15
   start (checked) — closer to the 30k line, likely trips at S16/S17.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat. Open: TD-012 (post-hoc validation, incl. the citation guard),
   TD-014 (unbounded history), TD-015 (brand/confusable coverage), TD-016 (ACH
   surface bounds), TD-017 (chat-side NUL hardening), TD-018 (no per-workspace
   bound on the NUMBER of inference calls), TD-019 (retro-hunt v1 bounds),
   TD-020 (watcher v1 bounds).
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
4. **Corpus ~25.9k docs, grows ~770/day** while the container runs. TD-011
   tracks the rollover trigger; TD-005's 30k line is now close.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via
  `auspex.devhost` (ENRICHMENT/KB/INGEST disabled on host).
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- `gh` did NOT flip at S13/S14/S15 start, but D-011 stands: re-check before
  EVERY `gh` call. `gh pr merge` is blocked by the Claude permission
  classifier — the human merges PRs.
- **Local `main` ref goes stale every promote** (the human squash-merges on
  GitHub; nothing here checks out `main`). `/promote` and any `main..staging`
  diff must `git fetch origin` and compare against `origin/main`. Note the
  commit LIST is meaningless after a squash (222 commits at S15) — read
  `git diff origin/main..staging --stat` for the real delta.
- **Plan assertions on this dev DB must VACUUM first.** Seeding and dropping
  25k rows leaves dead tuples behind; the planner costs a scan in PAGES, so
  bloat — not the query — decides the plan and fails tests for reasons
  unrelated to the code.
- **Small tables legitimately seq-scan.** Both the S14 sweep and the S15 watcher
  check plan as scans below a few thousand rows, and are right to. Assert plans
  only at sizes where a scan would cost something (both suites seed 25k).
- **S15 demo (zero-LLM, ~20 s):**
  1. `TOKEN=$(curl -s -X POST localhost:8000/api/auth/dev-login -H 'Content-Type: application/json' -d '{"email":"burhan@auspexdev.com"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')`
  2. Copy `docs/probes/2026-08-09-s15-watchers-live.md`'s script into the app
     container and run it from `/tmp` → 3 registered claims, the KEV change
     satisfying only the contradicted one, verdict trail provably untouched,
     then the escalation claim contradicted by a real flip.
  3. `curl -s "localhost:8000/api/watchers?status=satisfied" -H "Authorization: Bearer $TOKEN"`
     → the claims that stopped being true, each with `checked_by` and the
     evidence in `satisfied_by`; `/api/retrohunt/matches` → the same fact as ONE
     upgraded event carrying `falsifies`.
- **S14 demo (zero-LLM)**, **S13 demo (needs Scout)**, **S12/S11/S10/S9/S8
  demo turns** unchanged (see git history of this file).

## Reference intelligence (from the SARA Open architecture study)
Base: `/home/burhan/sara-open/` — key snapshots in docs/probes/:
- ACH analogues (S12): 2026-08-08-sara-ach-analogues.md — SARA has no ACH;
  falsification guards + doctrine tables are the reusable patterns.
- Phishing/header/typosquat (S11): 2026-07-18-sara-phishing-header-patterns.md
- Alert additive scorer (S10): 2026-07-18-sara-alert-triage-scorer.md
- DEFERRED rail (S9): 2026-07-18-sara-orchestrator-deferred.md
- Fast classifier / 92-8: 2026-07-16-sara-fastpath-pattern.md
- RRF retrieval + ID bypass: 2026-07-17-sara-rrf-retriever-pattern.md

## Next session should
Merge PR #15 first (human), then Claude back-merges. Then S16 Step 0: fresh-eyes
review of the S15 commits (see In-flight 2 — the sink ORDER dependency in
`satisfy_documents` is the strongest lead). Also check the TD-005 30k trigger at
start. Then `/promote` #16, then S16 per ROADMAP: **Verdict timeline UI** —
decay/staleness surfaces, flip history, "your past got re-scored". S14's
`verdict_flips` and S15's watcher rows are the substrate; TD-020's "open
watchers never expire" is a design question S16 should answer rather than
inherit. NEXT-SESSION.md has the full prompt.
