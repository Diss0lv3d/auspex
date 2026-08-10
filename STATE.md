# STATE — Auspex

_Last updated: 2026-08-10 (S16 COMPLETE — Step 0: adversarial review of the S15
watcher commits, 4 angles executed, 1 defect fixed, 1 gap confirmed and closed
inside the feature, 2 sound. Then **S16 Verdict timeline** (Phase 3): a
verdict's whole life renders in one place, `effective_confidence` is rendered
for the first time since S5, staleness becomes a band vocabulary (D-022),
TD-020's open question is answered, and a quiet digest now has to be earned.)_

## Where we are
- **S16 COMPLETE and PROMOTED to `main` (squash `4829eaf`).** Two parts:
  - **Step 0 — adversarial review of `233c132`/`e940efd` (DONE).** Four angles
    S15 never took, every finding reproduced by execution BEFORE the fix
    (probe: docs/probes/2026-08-10-s16-step0-review.md).
    **1 DEFECT fixed (44ccaa4):** the analyst-facing `falsifies` link existed
    only by the order `FanoutSink` happened to be constructed in —
    `satisfy_documents` wrote `retrohunt_matches.watcher_id`, which could only
    land if `RetroHuntSink` had already written the match. Executing the lead
    found two things it did not say: **the loss is PERMANENT** (the satisfy
    UPDATE is guarded on `status='open'`, so no later cycle retries it, not even
    a correctly-ordered redelivery), and **order is not the only trigger** — the
    retro-hunt sink is DESIGNED to swallow its failures, so one survivable sweep
    failure erases the claim with the order intact. That ruled out "enforce the
    order" and made the link **derived at read time** from
    `watchers.satisfied_change_kind`; `retrohunt_matches.watcher_id` is dropped
    with its links backfilled in one guarded idempotent statement.
    **1 CONFIRMED GAP, closed inside the S16 feature** (see below): 50
    consecutive failed watcher checks were indistinguishable from 50 quiet ones
    at every surface.
    **2 SOUND, recorded as such:** concurrent `check_escalation` (the
    observables row lock already serializes it — executed with `asyncio.gather`,
    no interleaving, no duplicate open set) and `claim` text bounds (CVE regex
    caps the value at 16 chars; measured worst case **197 chars** at 12
    providers; zero signals produce no verdict at all).
  - **S16 feature — Verdict timeline (DONE).** `auspex/timeline/` (staleness,
    types, store) + `auspex/checks.py` + `auspex/routes/timeline.py` +
    `auspex/static/timeline.html` + the `/timeline` page. Design ratified as
    **D-022**. Three things it decides rather than inherits:
    1. **Staleness in HALF-LIVES, not days** — `fresh` <0.5, `aging` 0.5–1.5,
       `stale` 1.5–3, `lapsed` ≥3, plus `held` for a floored verdict (a floor
       means "does not decay"; reporting it as lapsed would invert that). The
       edges live in ONE module and travel as data — into the digest's crossing
       SQL as a parameter, into the payload as descriptions, and the page holds
       no decay arithmetic of its own.
    2. **TD-020 answered** — an open claim on a decayed verdict gets a derived
       `standing` (`load_bearing`/`lapsed`) and `status` is left alone. Two
       different questions; merging them would erase the difference between
       never-contradicted, contradicted and superseded. The claim stays open and
       still fires.
    3. **A quiet answer has to be earned** — every empty field in the digest is
       an absence claim. Each consumer counts consecutive failures
       (`auspex/checks.py`, the breaker shape minus the circuit) and
       `Digest.trustworthy` requires a roster that is present AND healthy; an
       unknown roster reads as untrustworthy rather than defaulting to healthy.
    Nothing about decay is stored — every value is derived from columns already
    written, so a verdict's staleness cannot fall out of date with itself. And
    **no third notification shape** (D-020, D-021 held a third time): the digest
    reuses `retrohunt_matches`, `verdict_flips` and `watchers`, and re-open
    events are still acked at `POST /api/retrohunt/matches/{id}/ack`.
- **Plans probed, not assumed** for the derived link
  (docs/probes/2026-08-10-s16-step0-review.md): 25k satisfied watchers + 25k
  matches, new PARTIAL index `idx_watchers_satisfied_obs` mirroring S15's
  open-watcher index at the other end of a watcher's life. The outer LIMIT is
  applied before the LATERAL, so the derivation runs once per event on screen
  (51 loops for a 50-row page) — **0.373 ms**. **The one exception is logged:**
  `_DECAYED_SQL` is the only new read S16 did not cost (TD-021).
- **Live-verified in-container** against the installed dist (probe:
  docs/probes/2026-08-10-s16-timeline-live.md): a verdict asserted at 0.80 still
  standing at 0.28 after 1.504 half-lives → `stale`; its 3 open claims correctly
  `lapsed` while STILL `open`; a real band crossing surfacing as `aging → stale`
  inside the 7-day window while a tiny window correctly reports it as no news;
  the real KEV DocChange through the real sinks leaving the trail untouched
  (0 flips) and carrying `falsifies`; and a degraded checker turning a quiet
  digest untrustworthy. Residue deleted.
- **CI-green: 720 tests** (676 → +5 Step-0 regressions, +36 timeline, +3 UI).
  `./ci.sh` green including the installed-dist gate (**106 modules**, was 100);
  container rebuilt; `/api/health/ready` 200.
- **Zero new env vars** this session (and none across S14–S16).
- **LLM untouched by S16** — the whole path is rows we already have plus the
  D-017 curve.

## In-flight / standing follow-ups (carry forward until DONE)
1. ~~**PR #15**~~ **MERGED (2026-08-10, squash `4829eaf`)** — S14 + S15 + S16
   and both Step-0 reviews promoted to `main` as one commit, merged by
   `bh3082336888-cell`. Back-merged into staging (`0bd3d9a`) with the tree
   asserted unchanged; **`main` and `staging` are now identical in both content
   and history** (`staging..origin/main` = 0 commits). Nothing is in flight
   here. **Next promote starts from a clean slate — do not carry this forward.**
2. **S17 Step 0: fresh-eyes review of the S16 commits** (`44ccaa4`, `1b9e8e2`).
   Angles S16 did NOT adversarially test:
   - **(the uncosted query — strongest lead) `_DECAYED_SQL` is the only new read
     in three sessions without an asserted plan** (TD-021, and it says so out
     loud). It `DISTINCT ON`s the latest verdict per observable and filters on an
     expression over `half_life_days`, so the crossing test cannot use an index.
     Seed a workspace with ~100k enriched observables and EXPLAIN it; the digest
     is the page an analyst opens FIRST after a week away.
   - **(derived-link fan-out) the read-time LATERAL takes `ORDER BY satisfied_at
     DESC, id LIMIT 1`.** S16 pinned the two-verdict case. What happens when two
     watchers of DIFFERENT kinds are satisfied by the same doc id (a CVE that is
     KEV-added and later withdrawn with no re-enrichment between)? There are two
     matches and two claims; verify the pairing is still one-to-one and that
     neither event borrows the other's claim.
   - **(clock authority) staleness is computed against the READER's `now`.**
     `timeline_for` and `digest` default to `datetime.now(UTC)` in the app
     process while `created_at` is `clock_timestamp()` in Postgres. Two clocks
     decide one band. The skew guard clamps negative ages, but nothing checks
     the two agree — verify what a skewed app container reports.
   - **(checker health honesty) `FailureCounter` resets on process restart.**
     A crash-looping app would report a pristine roster and a trustworthy digest
     forever. Is "degraded" reachable in the failure mode most likely to occur?
   Verify findings BY EXECUTION before fixing; fix with regressions.
3. **TD-005 re-battery trigger (standing, NOT tripped, CLOSER):** corpus > 30k
   chunks, ANY new doc_type, or embedding-model change → re-run the labeled
   battery. S16 added no doc_type and no model change. Corpus **26,711 docs** at
   S16 end (was 25,938 at S15 start) — ~770/day while the container runs, so
   **this likely trips at S17 or S18**. Check it at Step 0.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat. Open: TD-012 (post-hoc validation, incl. the citation guard),
   TD-014 (unbounded history), TD-015 (brand/confusable coverage), TD-016 (ACH
   surface bounds), TD-017 (chat-side NUL hardening), TD-018 (no per-workspace
   bound on the NUMBER of inference calls), TD-019 (retro-hunt v1 bounds),
   TD-020 (watcher v1 bounds — the expiry half is now ANSWERED by D-022),
   TD-021 (timeline v1 bounds).
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
4. **Corpus ~26.7k docs, grows ~770/day** while the container runs. TD-011
   tracks the rollover trigger; TD-005's 30k line is now close.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via
  `auspex.devhost` (ENRICHMENT/KB/INGEST disabled on host).
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- **`gh` DID flip at S16 start** — active account was SIRP-Burhan (work), fixed
  with `gh auth switch --user bh3082336888-cell`. It did NOT flip at S13/S14/S15,
  which is exactly why D-011 says re-check before EVERY `gh` call. Also: `gh pr
  edit` fails on this repo with a Projects-classic GraphQL deprecation error —
  use `gh api -X PATCH repos/.../pulls/N` instead.
- **`gh pr merge` is NOT blocked — corrected 2026-08-10.** S14/S15 recorded it
  as blocked by the Claude permission classifier and S16 carried that forward
  without re-probing; the human merged three promotes by hand on a claim nobody
  had re-tested. Executed at S16 end: `gh pr merge 15 --squash` succeeded
  outright. Whatever refused it earlier no longer does. **This is the cost of a
  remembered fact in a file that is supposed to hold probed ones** (CLAUDE.md
  rule 4) — the rule was being applied to the codebase and not to our own
  workflow notes. Re-probe before believing any operational claim in this
  section.
- **Local `main` ref goes stale every promote** (the human squash-merges on
  GitHub; nothing here checks out `main`). `/promote` and any `main..staging`
  diff must `git fetch origin` and compare against `origin/main`. The commit
  LIST is meaningless after a squash — read `git diff origin/main..staging
  --stat` (currently **53 files, +7,898/-265**).
- **Plan assertions on this dev DB must VACUUM first.** Seeding and dropping
  25k rows leaves dead tuples behind; the planner costs a scan in PAGES, so
  bloat — not the query — decides the plan.
- **Small tables legitimately seq-scan.** Assert plans only at sizes where a
  scan would cost something (the suites seed 25k).
- **Data-modifying CTEs cannot see each other's rows through a table scan.**
  Cost an hour in the S16 plan fixture: `INSERT ... RETURNING` chained into the
  next CTE works; re-reading `observables` in a later CTE silently seeds zero
  rows and the plan test then asserts against an empty table.
- **S16 demo (zero-LLM, ~30 s):**
  1. Open `localhost:8000/timeline` → sign in → the digest. Quiet weeks say so
     AND say whether the silence can be believed.
  2. Paste an `obs_id` (or click one) → the verdict's whole life: the decay bar
     (asserted vs still-stands), every claim with its `standing`, every re-open
     event with what it falsified, every flip, and the full trail.
  3. Script version: `docs/probes/2026-08-10-s16-timeline-live.md`.
- **S15 demo (zero-LLM)**, **S14 demo (zero-LLM)**, **S13 demo (needs Scout)**,
  **S12/S11/S10/S9/S8 demo turns** unchanged (see git history of this file).

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
Nothing to merge — S16 is already on `main`. Start with S17 Step 0: fresh-eyes
review of the S16 commits
(see In-flight 2 — `_DECAYED_SQL`'s uncosted plan is the strongest lead, and it
is already logged as TD-021 rather than hidden). Check the TD-005 30k trigger at
start; it is close. Then S17 per ROADMAP: **Actions SDK contract** — the
`@action` decorator (semantics/scope/risk), undo required for destructive,
dry_run required, registration API, planner manifest integration. This is the
first session of Phase 4 and the first that is not Living Verdicts.
NEXT-SESSION.md has the full prompt.
