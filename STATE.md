# STATE — Auspex

_Last updated: 2026-08-15 (**S20 COMPLETE — the last roadmap session.** S19 promoted
via PR #19, then reviewed: the guard was refusing **4 of 6 legitimate SOC questions**
— the exact failure D-025 exists to prevent, through the door D-025 did not check.
Then Beta: **CI runs `./ci.sh` itself** (D-028) and caught two defects that were
green on the laptop and red on a clean runner, the repo got the **README it never
had**, and one runnable demo script replaced demo turns scattered over nine STATE.md
revisions. **912 tests.**)_

## Where we are

**Phase 4 is contract (S17) + decision loop (S18) + hardened input and spend (S19)
+ a pipeline, docs and a demo anyone can run (S20). The roadmap through S20 is
complete.**

- **S20 Step 0 — `/promote` DONE FIRST, and recorded at merge time.** S19 reached
  `main` as squash `45da831` via **PR #19**, back-merged `6c75190`, tree verified
  unchanged. The STATE.md line saying so was committed **immediately after the
  merge** (`5844777`), which is the fix for the S18 defect that cost S19 a
  correction. Slate is now empty except S20's own commits.
  - Accuracy note: S19's hand-off quoted the slate as 26 files/+3565/-18; the live
    diff was **27/+3811/-317**. The difference is S19's own session-end commit,
    which cannot count itself. **Read the diff at promote time.**
- **S20 Step 0 — fresh-eyes review of the S19 commits (DONE, 3 fixed, 3 ratified).**
  Record: docs/probes/2026-08-15-s20-step0-review.md; harnesses in
  docs/probes/s20-step0/ (both clean up after themselves).
  - **(FIXED, and NOT the defect the brief predicted) the guard refused its own
    core audience.** S19 justified every carve-out against pasted artefacts, which
    always have a format to carve them out, and never tested the case with **no
    artefact at all** — an analyst writing *about* an injection in their own words.
    **4 of 6 such sentences got a 400**, including *"write a Sigma rule that fires
    on 'ignore all previous instructions'"*. Fixed with reported speech as a fifth
    carve-out + inline quotation as a material marker, both position-checked.
  - **(FIXED) invisible characters and homoglyphs returned CLEAN** — not CONTENT,
    invisible. The first probe pass **mis-measured this**: the canonical string
    trips two patterns, so breaking "ignore" was still caught by the other one and
    printed `ok`. Isolated, the hole was total. `untrusted.flatten` would NOT have
    helped — it *replaces* invisibles with a space, leaving "ig nore" just as
    broken. Matching now runs on a folded copy with spans mapped back.
  - **(FIXED) the `{0,40}` gap** bought 47 chars with a subordinate clause →
    widened to 80, measured cost **zero false positives**.
  - **(RATIFIED, not fixed — D-027) the carve-outs are forgeable by construction.**
    Two forged RFC-5322 lines, a `{"k":"v"}` prefix, or 600 chars of padding each
    turn an issued imperative into CONTENT. Every carve-out is decided by text the
    sender controls; that is what a structural carve-out *is*. Named the bound
    instead of chasing forgeries. Base64/rot13 explicitly out of scope.
  - **(RATIFIED — D-027) spend is charged for our own outage** (claim, then 502 →
    `charged=2 for 0 inference received`, no refund seam) and **the fixed window is
    a real 2x burst** (full ceiling at 13:59:59 and again at 14:00:01). Both kept,
    both now said out loud. TD-030 logged with a costed fix.
  - **(SOUND) `plan_for` survived being attacked** — all ten hostile inputs
    (`None`, `''`, `'   '`, `'Enterprise'`, `'enterprise '`, `'legacy_gold'` …)
    land on `free`. **(SOUND) the migration is genuinely idempotent** — re-run
    preserves every value, a `pro` workspace stays `pro`, 0 NULL plans.
    No CHECK constraint though → TD-029 (fails safe, fails quiet).
- **S20 feature — Beta (DONE, D-028).**
  1. **Deploy pipeline.** `.github/workflows/ci.yml` runs **`./ci.sh` and nothing
     else** — a workflow that re-listed the steps would be a second definition of
     "green" that lies the first time someone edits one and not the other
     (`test_ci_runs_the_same_gate_a_developer_runs` enforces it). No secrets, none
     referenced; a fork PR runs the identical gate. `gh pr checks` reported **0
     checks on every promote PR from #1 to #19** — that is now fixed.
  2. **It paid for itself on the first run.** Two defects green-on-laptop,
     red-on-runner: **IPv6 observable identity was delegated to a stdlib
     formatting choice** (`ip.compressed` renders IPv4-mapped addresses in mixed
     notation on newer CPython — a silent interpreter upgrade would have forked
     every such observable and split its verdict history), now canonicalised in our
     own code and **measured equal to the stdlib over 200,268 addresses**; and
     **three tests depended on accumulated dev-DB state** (a fixture SELECTed the
     `default` workspace and asserted it existed).
  3. **README — the repo had none.** What it is, quick start, architecture, and an
     honest **"What Auspex does not do yet"** placed *before* the feature list.
  4. **`scripts/demo.sh`** — one ordered, narrated, ~3-minute run against the real
     stack, replacing demo turns scattered across nine STATE.md revisions. Ends on
     the honest part: `EXECUTABLE_SYSTEMS`, the ceiling copy, TD-026/028/030.
  5. **Docs are a shipped surface, so they get regressions** (`tests/test_docs.py`):
     no engine/provider name may leak into reader-facing docs, every
     `.env.example` var must be documented, the demo may only call routes that
     exist, and the README's honesty claims are pinned to the code that makes them
     true.
- **CI-green: 912 tests** (883 at S19 end → +19 guard review, +4 IPv6 identity,
  +6 docs). `./ci.sh` green including the installed-dist gate (**116 modules**);
  `/api/health/ready` 200. **Zero new env vars — seven sessions running.**

- **S19 Step 0 — `/promote` was ALREADY DONE (divergence, fixed `2bb20ad`).**
  STATE.md and NEXT-SESSION.md both said "three commits waiting to promote". Wrong:
  S18 reached `main` as squash `7813e43` via **PR #18**, back-merged `295c5bb`,
  *after* the S18 session-end commit was written — so the hand-off shipped stale.
  `git diff origin/main..staging --stat` was empty at session start. **Lesson: the
  session-end commit cannot describe a promote that happens after it.**
- **S19 Step 0 — TD-005 re-battery (DONE, the >30k trigger's first-ever fire).**
  Record: docs/probes/2026-08-15-td005-rebattery.md; re-runnable scripts in
  docs/probes/s19-step0/. Corpus 3,417 (S8) → **31,819** (9.3×), same embedding
  model, same queries, so rows compare directly.
  - **BOTH FLOORS VERIFIED SOUND, AND NOTHING FABRICATES.** All four off-corpus
    queries still return an honest miss through the real `search()` path. curated
    0.65: gap `[0.6184 .. 0.6905]` vs S8's `[0.618 .. 0.691]` — the pool is
    structurally bounded and barely moved. Recall 7/7 in the leg.
  - **cve 0.70: gap `[0.6563 .. 0.7660]`.** That pool grew **15×** and its noise
    ceiling rose 0.624 → 0.6563; headroom fell 0.076 → **0.0437**. Still holds, and
    the floor is **dormant in v1** — no shipped surface reaches it.
  - S8's "growth is flattening logarithmically" claim **confirmed across a 9× jump**.
  - **(TD-026, the real find) the battery was measuring the wrong thing.** S8
    labeled the neural *leg*; users read the RRF-**fused** top hit. Labeled through
    the real path for the first time: **3/7 positives render the WRONG ATT&CK page**
    ("what is phishing" → T1598 *Phishing for Information*, T1566 not in the
    returned 5). Not a safety failure — everything is above floor, nothing
    fabricates. Two fixes measured (3/7 → 3/7, then 4/7) → **thrash brake, nothing
    shipped**.
  - **(TD-027) a structural guarantee eroded silently.** "A `doc_types` filter
    makes kNN exact over a small subset" is **false for `cve`** now that cve is 96%
    of the corpus — filtered and unfiltered returned **byte-identical** results.
  - The "SharePoint recall miss" is **honest crowding, not HNSW collapse**: the
    doc still scores 0.7660 (S8: 0.766); 22 real SharePoint/Office CVEs now
    outrank it. The *label* went stale.
- **S19 Step 0 — fresh-eyes review of the S18 commits (DONE).** Record:
  docs/probes/2026-08-15-s19-step0-review.md; harness
  docs/probes/s19-step0/probe_s18_review.py. All five angles RUN.
  - **(FIXED) the fingerprint's blind spot was real.** A spec carrying a new
    declared field fingerprinted **byte-identically** — an approver could be shown
    a changed declaration and the re-check would call it unchanged. Coverage is
    complete today at all four levels, so the guard is a test; **proven to bite**
    (added a field → fails; reverted → passes).
  - **(FIXED) a `FINGERPRINT_VERSION` bump told the analyst a lie** — "the action
    has changed" when only our hashing had. `matches_older_scheme` re-hashes the
    unchanged spec under earlier versions and reports `fingerprint_scheme_changed`.
    Found while fixing it: `version: int = FINGERPRINT_VERSION` binds **once at
    import**, so constant and function drifted; same trap in settlement.py.
  - **(TD-028, reproduced, NOT fixed) `executing`/`undoing` have no reaper, and
    it is worse than predicted** — the wedged row can never be executed, undone or
    rejected **and is invisible** (the queue is pending-only), so a human sees the
    action vanish. Also: a failed execute leaves effects it denies, and `undo` is
    gated shut on exactly those rows.
  - **(SOUND) stream tenancy** — two workspaces, zero leakage.
- **S19 feature — Hardening (DONE, ratified D-025 + D-026).**
  1. **The input guard asks the right question** (`auspex/guard.py`). Not "does
     this contain an injection?" but "is it being **ISSUED** or **ANALYSED**?"
     Carve-outs **import the classifier's own** `_is_email_paste` /
     `_is_alert_paste` / `_is_analytical` — format beats keywords, one vocabulary.
     **Position is the signal**: framing must precede the text, or appending "is
     this phishing?" becomes an off switch (pinned). Justified against the **real
     S11 `.eml` corpus** with the injection spliced into each body, and the
     unmodified fixtures asserted clean so the test measures the splice.
  2. **Rate limits close TD-018** (`auspex/limits.py` + `usage_counters`). The
     ceiling is enforced **in the same UPSERT that reads the counter** — D-024's
     claim-first device applied to spend. **Raced 8-way over one unit: one winner.**
     **Both** routes TD-018 named are wired and share one counter; a two-pass turn
     claims **2**, because it really makes two requests.
  3. **Plan gating skeleton.** Plan is a column, the tier list is **code**, and an
     **unknown plan resolves to the most restrictive** — a typo must not buy
     unlimited inference. Unmetered still counts. `GET /api/usage`. No billing.
  4. **A ceiling is not an outage.** 429 names meter/ceiling/reset and says what
     still works; the LLM-free paths are untouched (the claim is after the 92/8 gate).
- **Live-verified against the running container, not just TestClient**
  (docs/probes/2026-08-15-s19-hardening-live.md): injection issued → **400**; the
  same sentence inside a real phishing fixture → **streams from the real endpoint**;
  one deep turn meters **exactly 2**. The first usage reading disagreed with the
  claim — chasing it found **our own suite** leaking a counter row into the shared
  dev workspace. Fixed; the suite now leaves 0 (asserted).
- **CI-green: 883 tests** (801 at S18 end → +13 Step-0, +69 S19). `./ci.sh` green
  including the installed-dist gate (**116 modules**, was 114); `/api/health/ready` 200.
- **Zero new env vars** this session — and none across S14–S19 (six sessions).

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: EMPTY at this instant — S21 reached `main` as squash `f8d8c19`
   via PR #21** (merged 2026-08-15), back-merged `d83b998`, tree verified unchanged
   (`git diff 9f023f0 HEAD --stat` empty), `git diff origin/main..staging --stat`
   empty. Real diff was **30 files, +2578/-128**.
   - **The second promote merged on a check anyone can see**, and the first with
     TWO green runs on the PR: the push-triggered `ci.sh` job passed in 5m18s and
     the PR-triggered one in 4m41s. `mergeStateStatus` went UNSTABLE → CLEAN as
     they landed; merged only on CLEAN.
   - **Written and committed immediately after the merge, not at session-end** —
     the fix for the S18 defect that cost S19 and S20 a correction each.
   - **It will not stay empty.** The S21 start ritual corrected the standing claim
     that this line goes to "empty": the commit recording a promote lands *after*
     the promote, so the steady state between sessions is **docs-only, never
     empty**. This entry and every session-end commit after it are already the
     next slate. Read the diff at promote time; never trust a quoted number or
     the commit LIST (after a squash the list is meaningless — PR #21's list
     still showed every S20 commit).

2. **Branch protection on `main` is the ONE manual step left** — the CI check now
   exists and is green, but nothing yet REQUIRES it before a promote merge. That is
   a repository-settings change and Burhan's call, not a commit's (D-028). One
   command when wanted:
   `gh api -X PUT repos/bh3082336888-cell/auspex/branches/main/protection -f 'required_status_checks[strict]=true' -f 'required_status_checks[contexts][]=ci.sh (lint + tests + container build + installed-dist)' -F 'enforce_admins=false' -F 'required_pull_request_reviews=null' -F 'restrictions=null'`
3. **TD-026 — the definition path renders the wrong ATT&CK page (3/7).** User-visible
   bad output on a shipped surface, measured, with both attempted fixes and their
   numbers written down. **Two of the seven battery labels are corpus-stale and must
   be re-examined BEFORE the next attempt** — "what is lateral movement" → TA0008 is
   arguably correct. **Now named in the README and the demo**, so it is a stated
   bound rather than a surprise.
4. **TD-028 — the proposal status machine has three states with no way back.** The
   un-reaped `executing` row is the sharpest: invisible to the approver and
   unrecoverable. S18's "something really executes" claim quietly assumes nothing
   crashes mid-run.
5. **TD-005 trigger refreshed so it can fire again:** cve pool > 300k chunks,
   curated pool > 5k, any new doc_type, any embedding-model change, **or before any
   free-text-over-CVEs surface ships** (TD-027 is a HARD GATE on that).

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat. Open: TD-012 (post-hoc validation), TD-014 (unbounded history),
   TD-015, TD-016, TD-017, TD-019, TD-020, TD-021, TD-022, TD-023 (2 items closed
   by S18), TD-024 (decay-read crossover, costed), TD-025 (approval flow v1
   bounds), TD-026/027/028, **TD-029/030 (new this session)**. **TD-018 CLOSED.**
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
4. **Corpus 31,820 docs and growing while the container runs.** TD-011 tracks the
   index rollover trigger.
5. **The guard bounds INPUT only, and only against accidents.** It does not
   certify output (TD-012), and **it does not defeat a determined authenticated
   caller** — every carve-out is decided by text the sender controls, so a forged
   header block or 600 chars of padding dresses an imperative as content. D-027
   says this out loud rather than letting the rail look stronger than it is.
6. **The roadmap through S20 is complete.** There is no NEXT-SESSION deliverable
   waiting in ROADMAP.md — S21+ needs a scoping decision from Burhan first (the
   "Later / explicitly deferred" list is the menu). This is a planning state, not
   a blocker on the code.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`.
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- **S21 start ritual (2026-08-15):** staging, tree clean, identity
  `bh3082336888-cell`. All three containers healthy (app rebuilt 16 min prior);
  `/api/health/ready` **200** (postgres reachable, opensearch 2.19.4). Ollama
  0.32.5 up with `qwen3:14b` present. **Corpus 31,822** — cve 30,556, technique
  1,248, tactic 15, concept 3: **TD-005 not tripped** (cve trigger 300k, curated
  trigger 5k, curated pool is 1,266). Slate docs-only, see in-flight item 1.
- **`gh` did NOT flip to the work account at S20 start** (active was
  `bh3082336888-cell`), nor at any point mid-session across ~6 `gh` calls. It DID
  at S18 and S16, did not at S17, S13–S15, S19 or S20. **Nor at S21 start.**
  **Unpredictable is the pattern** — re-check before EVERY `gh` call.
- **`gh pr merge` works** (re-verified S18). `gh pr edit` still fails with a
  Projects-classic GraphQL deprecation — use `gh api -X PATCH repos/.../pulls/N`.
- **This repo NOW HAS GitHub Actions** (S20, D-028) — `.github/workflows/ci.yml`
  runs `./ci.sh` on push and PR to `main`/`staging`. A cold run is **~5m30s**
  (local is ~4m). `gh run list` / `gh run view <id> --log-failed` to read it.
  **A clean runner is a different environment from this laptop and finds things it
  cannot** — that is not a theory, it happened on run #1.
- **Local `main` ref goes stale every promote.** `git fetch origin` and read
  `git diff origin/main..staging --stat`, never the commit list.
- **The app container runs the BUILT IMAGE, not the working tree.** The S19
  migration needed `docker compose up -d --build app`, not `restart`.
- **All dev-login users share the `default` workspace.** So any test or probe that
  spends/claims in it is visible to every other one — this is exactly what made a
  live usage reading disagree with the code this session. Tests that touch
  `usage_counters` must clean up.
- **Probe residue is expensive** (S18: a 100k-row seeded workspace made plan tests
  take 150 s instead of 21 s). Every S19 probe deletes its workspaces and VACUUMs.
- **Plan assertions must VACUUM first**, and only at sizes where a scan would cost
  something (suites seed 25k).
- **THE DEMO IS NOW ONE COMMAND: `./scripts/demo.sh`** (~3 min, runs end to end,
  verified this session). It consolidates the demo turns that were scattered across
  nine STATE.md revisions — stack health, the 92/8 split proven by a meter that does
  not move, the guard on all three cases, decay/watchers/retro-hunt, propose →
  approve → 409 → undo, then the honest bounds. **Stop hand-assembling demo curls;
  edit the script instead.** `--no-llm` skips the endpoint-dependent turns.
  - It spends real inference on the two deep turns (that is the point) and leaves
    `usage_counters` rows in the shared `default` workspace. Correct for a demo;
    still true that TESTS touching that table must clean up.
- **S19–S8 demo turns** are all folded into the script (see git history for the
  originals).

## Reference intelligence (from the SARA Open architecture study)
Base: `/home/burhan/sara-open/` — key snapshots in docs/probes/:
- ACH analogues (S12): 2026-08-08-sara-ach-analogues.md
- Phishing/header/typosquat (S11): 2026-07-18-sara-phishing-header-patterns.md
- Alert additive scorer (S10): 2026-07-18-sara-alert-triage-scorer.md
- DEFERRED rail (S9): 2026-07-18-sara-orchestrator-deferred.md
- Fast classifier / 92-8: 2026-07-16-sara-fastpath-pattern.md
- RRF retrieval + ID bypass: 2026-07-17-sara-rrf-retriever-pattern.md

## Next session should
**Start with `/promote`** — S20's commits (`0c7c092`, `cb94994`, `d45e70b`,
`7e5c712`, `f33081f`, `bbf3fec` + the session-end commit) are on staging and `main`
has nothing since PR #19. **Read the real diff, not this list** — after a squash the
list is meaningless. `gh pr checks` now reports a real check; wait for it.

Then **S21 needs a scoping decision before it needs code.** The ROADMAP through S20
is complete, so for the first time in this project there is no next deliverable
written down. Do not improvise one. The three honest candidates, in the order the
repo's own evidence argues for:

1. **Pay down what beta exposed.** TD-026 (wrong ATT&CK page, 3/7, user-visible on
   a shipped surface) is the only defect a beta user would hit in the first ten
   minutes. TD-028 (`executing` with no reaper) is the one that loses a human's
   work. Both are measured, reproduced, and now advertised in the README — which
   makes fixing them a promise, not a preference. **Recommended.**
2. **Wire AgentLoop into `/api/chat`.** The single largest gap between what the
   platform is and what the README says it is: the loop is built,
   capability-negotiated and tested, and the deep path still does not use it.
   Carries TD-012 (post-hoc validation) as a prerequisite worth arguing about.
3. **Phase 5 / Herd Immunity groundwork** — needs multi-workspace and a privacy
   review before any code, so it is a design session, not an implementation one.

Whatever is chosen: **the first `/promote` of S21 is the first one with a real CI
check on it.** If branch protection has been enabled by then (in-flight item 2),
that check is enforcing rather than advisory. NEXT-SESSION.md has the full prompt.
