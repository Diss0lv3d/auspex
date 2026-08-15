# STATE — Auspex

_Last updated: 2026-08-16 (**S21 COMPLETE — the first session with no roadmap entry,
scoped by decision instead.** Chose "pay down what beta exposed" and closed both:
**TD-026 went 3/7 → 7/7** and **TD-028a** — a dead claim is now visible and only a
human resolves it, deliberately **without** the reaper S19 asked for. Step 0 first
found that **S20 fixed one invisible-character hole by opening its inverse**, and
that the probe measuring it repeated, verbatim, a mistake this repo had already
written down once. **964 tests.**)_

## Where we are

**Phase 4 is contract (S17) + decision loop (S18) + hardened input and spend (S19)
+ a pipeline, docs and a demo anyone can run (S20) + the beta debt paid down (S21).
The ROADMAP through S20 is complete; S21 was scoped by a decision, not a plan, and
S22 needs the same.**

- **S21 Step 0 — `/promote` was already done, and the standing claim was wrong in a
  new way.** S20 reached `main` as squash `fc7c921` via **PR #20**, back-merged
  `a5c9c7f`, recorded at merge time (`02318b5`) — the S20 fix working as designed.
  But the slate was **not empty**: it held the two docs commits that recorded the
  promote. **The commit recording a promote lands after the promote, so the steady
  state between sessions is docs-only, never empty** (`c1d8194`, `f6495b8`).
- **S21 Step 0 — fresh-eyes review of the S20 commits (DONE, 3 fixed, 2 ratified,
  3 sound).** Record: docs/probes/2026-08-15-s21-step0-review.md; harnesses in
  docs/probes/s21-step0/ (`probe_s20_review.py` pure; `probe_docs_tests_bite.sh`
  mutates 5 files and restores every one on an EXIT trap, 0 dirty verified).
  13 new regressions, all proven to fail on the pre-fix code.
  - **(FIXED — a regression S20 introduced) S20 fixed one invisible-character hole
    by opening its inverse.** S19 matched the raw message, so `ig<ZWSP>nore`
    returned CLEAN; S20 fixed that by matching the folded copy **instead**. Folding
    *deletes* invisibles, and deletion welds: `previous<ZWSP>instructions` folds to
    `previousinstructions` and destroys the boundary `\binstructions\b` needs.
    **18 escapes measured** (9 invisible characters × 3 weld positions), all
    returning CLEAN — invisible to the rail, the exact failure S20 was fixing.
    Matching now **unions the folded and raw passes**; folding is lossy in both
    directions and neither copy is sufficient alone. The S20 cases are pinned
    alongside so the union cannot become a quiet revert.
  - **(FIXED) an attribution two sentences back attributed nothing.** Reported
    speech was checked against the whole preamble, so **6 of 6** unrelated sentence
    pairs turned a bare imperative into CONTENT (`Open the ticket that contains the
    API key. <imperative>`). **Two designs measured, one shipped** (the thrash brake
    used as intended): scoping *both* carve-outs closes 4/4 but refuses `Is this
    phishing? <paste>`; scoping *only* reported speech closes 6/6 at zero corpus
    cost. **D-029** ratifies the asymmetry — reported speech is a relation that dies
    at a full stop, framing is an introducer that is *meant* to govern what follows.
  - **(FIXED) a stray quotation mark opened a covering span.** Only the apostrophe
    arm had letter-adjacency lookarounds, so an inch mark (`The rack is 42" deep.`)
    paired with the next real quote and covered everything between. Applied to all
    four pairs; zero corpus cost (every real opening quote follows a space).
  - **(RATIFIED — D-029, TD-031) two quotation marks still disarm the rail**, and
    it is the cheapest bypass we ship — no structure, no re-routing, unlike every
    forgery D-027 ratified. **Removing the arm was measured, not argued**: fully
    redundant against the pinned corpus (which the same commit wrote, so it is not
    evidence), and **load-bearing 7/7** against analyst prose that quotes a
    detection string. **Two designs tried, both cost more than they bought —
    TD-031 says do not spend a third session on this regex.**
  - **(RATIFIED — D-029, TD-032) the framing arm still licenses across sentences.**
    `Here is the plan for next quarter. <imperative>` is CONTENT, 2/2. Scoping it is
    what refused the paste shape above. Needs a framing detector that reports a
    *position*, which a bool-over-a-whole-string cannot. ~1 session, deferred.
  - **(SOUND) `_canonical_ipv6` is RFC 5952 §4-correct** — checked against an
    **independently written renderer coded from the RFC text**, not the stdlib:
    38,228 addresses, **0 mismatches**, every output re-parsing to its input,
    including §4.2.2 (never shorten a single group) and a genuine §4.2.3 tie.
  - **(SOUND) the fold's index map** — all-invisible, empty, match at index 0,
    match at end, and the fullwidth range edges all map back intact.
  - **(FIXED) a docs test passed with its entire input removed.** 7 of 8 deliberate
    mutations failed correctly; renaming `$API` → `$BASE` in `demo.sh` made
    `test_the_demo_only_calls_routes_that_exist` **pass**, because the extractor
    captured nothing and "no route is unknown" was trivially true. Floored at
    `len(called) >= 8` (currently 9).
  - **The measurement error is in the record, not quietly corrected.** The first
    draft called the fold SOUND using a payload that trips **two** patterns, so
    breaking one still printed a pass — **verbatim the mistake the S20 review wrote
    down about its own first pass. Reading that sentence did not prevent repeating
    it.** The probe now asserts each payload is single-pattern before using it. The
    same draft also accused `_canonical_ipv6` of an RFC violation it does not have.
    **A hand-written expectation is not an oracle.**
- **S21 — TD-026 CLOSED: the definition path renders the page the question is
  about.** Record: docs/probes/2026-08-15-s21-td026.md. **7/7 positives, 4/4 honest
  misses, live-verified through the rebuilt container.** Third attempt overall (S19
  measured two designs and shipped neither: 3/7 → 3/7, then 4/7).
  - **The labels were re-examined first, as the brief demanded — and the brief was
    wrong.** Only *one* of the two "corpus-stale" labels is in this battery
    (`what is lateral movement`, where TA0008 is titled exactly that and defines the
    term; the battery now accepts either page). The second stale label belongs to
    the **CVE** battery. STATE.md and NEXT-SESSION.md had both carried the pair here.
  - **Two mechanisms, both confirmed by execution first.** (1) RRF fused *chunks*
    while the answer is a *page* — T1566's three chunks scored separately at neural
    ranks 2/4/5 while single-chunk T1598 accumulated across both legs; `rrf_fuse_docs`
    gives one rank per document per leg. Deliberately **not** by summing a page's
    chunks, which inverts the bias. (2) Neither leg had a signal for "this page IS
    the term" — `auspex/kb/canonical.py` asks whether title and question are *about
    each other*, as the **harmonic mean of both directions**. The one-sided version
    reached 6/7 and then answered `what is credential dumping` with a page titled
    simply **Credentials**; each measure alone was observed picking a wrong page.
  - **Depth mattered as much as ranking** — T1003 sat above its floor at fused rank
    **9**, outside any top-5 cut. The path now fuses 12 and truncates **after**
    promotion. One wider fetch, no extra round trip.
  - **It cannot fabricate:** promotion re-orders a list that has already cleared the
    neural floor and never adds to it; the off-corpus half is unchanged at 4/4 and
    `test_promotion_cannot_resurrect_an_off_corpus_miss` pins the property.
  - **Found while live-verifying: only 5 of the 7 positives reach this path in
    production.** The classifier routes the other two deep — correct D-006 behaviour,
    but it means the battery is an acceptance test **for the retrieval function**,
    not a measurement of end-user answers. Said out loud, because the README now
    cites these numbers.
- **S21 — TD-028a CLOSED: a dead claim is visible, and only a human resolves it.**
  A process dying between the claim and the handler wedged a proposal forever
  (`execute` → `not_approved`, `undo` → `not_executed`, `reject` → `already_decided`)
  **and invisibly**, because the queue filtered `status = 'pending_approval'` — the
  half of TD-028 that loses someone's work.
  - `claimed_at` + `STALE_CLAIM_SECONDS` (300) + an `abandoned` state.
    `pending()` returns claims older than the threshold **beside** the pending rows,
    with their real status, so the row surfaces where the human already looks; a
    fresh claim stays hidden or every execution would flicker through the queue.
  - **`POST /api/proposals/{id}/abandon` is the door out**, guarded on claim age in
    the same UPDATE that moves the row (the D-024 claim-first device), so it cannot
    kill a handler that is still working. **409, not 404**, when the claim is too
    young: the proposal is fine and the request was early.
  - **NO REAPER — this reverses what the S19 note asked for.** A timer cannot know
    whether the handler ran before the process died, so every status it could pick
    asserts something nobody knows: `approved` invites a second run of a half-run
    action, `failed` claims nothing happened, `executed` claims it did. `abandoned`
    records that the answer was **lost**, and D-014 reserves that call for the human.
  - `claimed_at` is cleared by every exit from a claim, so a finished action never
    drifts into the queue five minutes later. Live-verified through the rebuilt
    container; probe row deleted, residue asserted 0. **TD-028b is now the sharpest.**
- **CI-green: 964 tests** (912 at S20 end → **+24** Step-0 guard/docs, of which 13
  are the review's regressions; **+20** TD-026; **+8** TD-028a). `./ci.sh` green
  including the
  installed-dist gate (**117 modules**, was 116 — `auspex/kb/canonical.py`);
  `/api/health/ready` 200. **Zero new env vars — eight sessions running**
  (`STALE_CLAIM_SECONDS` is a code constant, deliberately, per D-026's "limits are
  code" precedent).

- **S20 (kept for context) — Beta, D-028.** CI runs **`./ci.sh` and nothing else**
  (`test_ci_runs_the_same_gate_a_developer_runs` enforces it), and it paid for
  itself on run #1 with two defects green-on-laptop/red-on-runner: **IPv6 observable
  identity delegated to a stdlib formatting choice** (now our own code, and S21
  re-verified it against the RFC rather than the stdlib) and **three tests depending
  on accumulated dev-DB state**. The repo got the **README it never had**, honest
  bounds first; `scripts/demo.sh` replaced demo turns scattered over nine STATE.md
  revisions; `tests/test_docs.py` made docs a surface with regressions. Earlier
  sessions are in git history and in DECISIONS.md — this file no longer restates them.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: EMPTY at this instant — the S21 session-end record reached
   `main` as squash `4056070` via PR #22** (merged 2026-08-15 19:22 UTC),
   back-merged `7700d07`, tree verified unchanged (`git diff <pre> HEAD --stat`
   empty), `git diff origin/main..staging --stat` now **zero files**. Real diff
   promoted: **4 files, +376/-376, docs-only** — NEXT-SESSION, ROADMAP, STATE,
   TECHNICAL_DEBT. Exactly the steady state S21 predicted, promoted rather than
   skipped. This S22 promote-record commit re-opens the slate immediately, which
   is the point: **the slate is docs-only between sessions, never empty for long.**
   - **Read the diff at promote time. Never trust a quoted number or the commit
     LIST** — after a squash the list is meaningless. PR #22's list still showed
     **every commit back to S2**; the real change was 4 files.
   - PR #22 is the third promote merged on a visible check, and the second with
     **two** green runs (push-triggered 5m26s, PR-triggered 5m40s);
     `mergeStateStatus` **CLEAN** before the merge, 964 tests, 117 modules,
     `/api/health/ready` 200 after.
2. **Branch protection on `main` is the ONE manual step left** — the CI check exists
   and is green, but nothing yet REQUIRES it before a promote merge. Repository
   settings, Burhan's call, not a commit's (D-028). One command when wanted:
   `gh api -X PUT repos/bh3082336888-cell/auspex/branches/main/protection -f 'required_status_checks[strict]=true' -f 'required_status_checks[contexts][]=ci.sh (lint + tests + container build + installed-dist)' -F 'enforce_admins=false' -F 'required_pull_request_reviews=null' -F 'restrictions=null'`
3. **TD-028b is now the sharpest open half of TD-028** — a failed execute leaves
   effects it denies (the handler's INSERT is really in the table while the row says
   `failed`). (c) is *sharper* after S21, not softer: `abandoned` joins `failed` as
   a state whose effects are unknown and whose `undo` is gated shut. Both need
   terminal-state semantics that belong with TD-025's idempotency gap. (d) is card
   rendering.
4. **The card stream still emits only new cards, never status changes** — opened by
   the TD-028a fix. A client watching `/stream` is not told when a claim goes stale;
   the polled list is where it surfaces today.
5. **TD-031/TD-032 are ratified bounds, not a backlog.** Do **not** re-open the
   guard regex: S19, S20 and S21 have each spent a session there, and the last two
   ratifications both name **TD-012 (post-hoc output validation)** as the real
   answer — an injection that got in *however* it got in.
6. **TD-005 trigger, still armed:** cve pool > 300k chunks, curated pool > 5k, any
   new doc_type, any embedding-model change, **or before any free-text-over-CVEs
   surface ships** (TD-027 is a HARD GATE on that). Corpus today: **31,828** —
   cve 30,562, technique 1,248, tactic 15, concept 3. Not tripped.
   TD-026's battery labels belong on this trigger list too — one of seven was
   already stale when S21 started.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   `/api/chat`. Open: TD-012, TD-014, TD-015, TD-016, TD-017, TD-019, TD-020,
   TD-021, TD-022, TD-023, TD-024, TD-025, TD-027, **TD-028b/c/d**, TD-029, TD-030,
   **TD-031/032 (new, ratified)**. **TD-018, TD-026 and TD-028a are CLOSED.**
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
4. **Corpus 31,828 docs and growing while the container runs.** TD-011 tracks the
   index rollover trigger.
5. **The guard bounds INPUT only, and only against accidents.** It does not certify
   output (TD-012), and **it does not defeat a determined authenticated caller** —
   D-027 named the forgeries, and D-029 added the two cheapest: **two quotation
   marks** (TD-031) and an introducer phrase anywhere in the preamble (TD-032). The
   rail is stated honestly rather than made to look stronger than it is.
6. **There is still no next deliverable written down.** S21 was scoped by a decision
   rather than a plan, and S22 needs the same conversation before any code. A
   planning state, not a blocker on the code.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`.
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- **S21 session-end (2026-08-16):** staging, tree clean, identity
  `bh3082336888-cell`. All three containers healthy; `./ci.sh` **green, 964 tests,
  117 modules**; `/api/health/ready` **200** (postgres reachable, opensearch 2.19.4).
- **`gh` did NOT flip to the work account at S22 start or across the promote**
  (checked three times: ritual, before `gh pr create`, before `gh pr merge`).
  It DID at S18 and S16; did not at S17, S13–S15, S19–S22.
  **Unpredictable is the pattern** — re-check before EVERY `gh` call.
- **`gh pr merge` works.** `gh pr edit` still fails with a Projects-classic GraphQL
  deprecation — use `gh api -X PATCH repos/.../pulls/N`.
- **This repo HAS GitHub Actions** (S20, D-028) — `.github/workflows/ci.yml` runs
  `./ci.sh` on push and PR to `main`/`staging`. Cold run ~5m30s (local ~1m45s for
  tests, ~4m for the whole gate). `gh run list` / `gh run view <id> --log-failed`.
  **A clean runner is a different environment from this laptop and finds things it
  cannot** — not a theory, it happened on run #1.
- **Local `main` ref goes stale every promote.** `git fetch origin` and read
  `git diff origin/main..staging --stat`, never the commit list.
- **The app container runs the BUILT IMAGE, not the working tree.** Both S21
  live-verifications needed `docker compose up -d --build app`, not `restart`.
- **All dev-login users share the `default` workspace**, so any test or probe that
  spends/claims in it is visible to every other one. Tests touching `usage_counters`
  must clean up; S21's proposal probe deleted its row and asserted 0 residue.
- **Probe residue is expensive** (S18: a 100k-row seeded workspace made plan tests
  take 150 s instead of 21 s). Plan assertions must VACUUM first.
- **THE DEMO IS ONE COMMAND: `./scripts/demo.sh`** (~3 min, end to end). Stack
  health, the 92/8 split proven by a meter that does not move, the guard on all
  three cases, decay/watchers/retro-hunt, propose → approve → 409 → undo, then the
  honest bounds. **Stop hand-assembling demo curls; edit the script instead.**
  `--no-llm` skips the endpoint-dependent turns. It deliberately spends real
  inference and leaves `usage_counters` rows in `default` — correct for a demo.
  S21 updated its honesty section twice (TD-026 closed, TD-028a closed).

## Reference intelligence (from the SARA Open architecture study)
Base: `/home/burhan/sara-open/` — key snapshots in docs/probes/:
- ACH analogues (S12): 2026-08-08-sara-ach-analogues.md
- Phishing/header/typosquat (S11): 2026-07-18-sara-phishing-header-patterns.md
- Alert additive scorer (S10): 2026-07-18-sara-alert-triage-scorer.md
- DEFERRED rail (S9): 2026-07-18-sara-orchestrator-deferred.md
- Fast classifier / 92-8: 2026-07-16-sara-fastpath-pattern.md
- RRF retrieval + ID bypass: 2026-07-17-sara-rrf-retriever-pattern.md

## Next session should
**Start with `/promote`** — the slate is docs-only (`a306106` + this session-end
commit) and that is the normal state, not a reason to skip it. Read the real diff.

Then **S22 needs a scoping decision before it needs code**, the same as S21 did.
Do not improvise one. The candidates, in the order the repo's own evidence argues:

1. **TD-012 — post-hoc output validation. Recommended, and the repo has now said so
   three times.** D-027 declined to chase forgeries and pointed here; TD-031 and
   TD-032 were both ratified this session with "the real answer is TD-012" written
   into them. It is also the prerequisite the AgentLoop wiring carries. Three
   sessions have now been spent hardening the input rail; the output side has none.
2. **Wire AgentLoop into `/api/chat`.** Still the largest gap between what the
   platform is and what its own README says: the loop is built, capability-negotiated
   and tested, and the deep path does not use it. Changes what the guard and the
   ceilings are protecting, which is why (1) reads as its prerequisite.
3. **Finish TD-028 (b/c/d) with TD-025's terminal-state semantics.** (b) is the
   sharpest measured defect left: a failed execute reports that nothing happened
   while its INSERT is really in the table. Smaller than (1) or (2), and fully
   specified already.
4. **Phase 5 / Herd Immunity groundwork** — needs multi-workspace and a privacy
   review before any code; a design session, not an implementation one.

NEXT-SESSION.md has the full prompt.
