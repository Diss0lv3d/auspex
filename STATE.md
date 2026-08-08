# STATE — Auspex

_Last updated: 2026-08-08 (S12 COMPLETE — Step 0: S11 review, 9 findings fixed,
promoted #13; then the ACH hypothesis engine v1: deterministic matrix +
info-gain lookup picker + /api/investigations, hardened by a 16-finding
verification workflow, live-verified in-container. S12 work on `staging`
awaits the S13 Step-0 fresh-eyes review + promote #14)_

## Where we are
- **S12 COMPLETE.** Three parts:
  - **Step 0 — S11 adversarial review → promote #13 (DONE, on `main`).**
    9 findings (A–I), every one verified by execution before fixing: body-prose
    BENIGN manufacture (A), BEC sender victim-filtered (B), unflattened 50 KB
    indicator line (C), ccTLD brand false positives + hidden mismatches (D/E),
    a vacuous sender test (F), "can NEVER launder" overclaim corrected to
    detected-not-prevented (G), ARC relay passes reaching BENIGN (H), and the
    live-only self-spoof directive contradiction (I). PR #13 squash-merged
    (human merged after a permission block on `gh pr merge`), back-merged
    `5d3d2dc`, main==staging at the time.
  - **S12 feature — ACH hypothesis engine v1 (DONE, on staging, NOT promoted).**
    `auspex/ach/` (D-019): closed 4-hypothesis catalog per subject kind
    (alert/email) → evidence adapters reusing the S5/S10/S11 typed shapes with
    curated cell-vector doctrine tables → Heuer matrix (LEAST-inconsistency
    ranking, support = tiebreak only; rejection needs threshold + a hard
    contradiction; honesty rails: no evidence / non-diagnostic evidence →
    ranking NOT claimed) → next-lookup by expected information gain
    (curated P(outcome|H) rows, entropy/Bayes over plausibility weights
    2^(−inc/2), itemized outcome terms). Postgres: investigations + hypotheses
    + ach_evidence (inputs only — scores/statuses recompute on every read).
    Surface: zero-LLM REST `/api/investigations` (create from an alert/email
    paste; GET recompute; POST /lookups EXECUTES the recommendation through
    the real S5 fan-out and folds the result back in). NO model call anywhere
    on the path — model rendering is S13+, through a contract, per D-019.
  - **S12 verification (DONE) — a 4-lens adversarial workflow over the new
    code: 16 findings (13 unique), ALL verified by execution, all fixed** with
    regressions in 5 commits: Heuer property was unpinned (a most-support
    mutation passed the suite); Postgres `real` returned 0.7 as 0.699999988
    and silently disarmed the ≥0.7 hard-contradiction rail across every
    round-trip (the API served FP=surviving where the pinned math rejects it);
    hypothesis load order flipped TP/TEST ties via the API; one auth header
    triple-counted into permanently rejecting BENIGN on ordinary forwarded
    mail (now ONE collapsed row; softfail alone = 0.5 credibility); the
    engine recommended EMAIL lookups no provider accepts (zero-progress loop —
    now structurally pinned: recommendable types must be provider-covered);
    a 32 KB paste amplified to a 1.9 MB response (ranked plan capped at 20 +
    named total_candidates; snapshot capped at 200 + named iocs_truncated);
    plus retired-kind load bricking, add_evidence tenancy guard, unscoped
    test teardown deleting cross-workspace verdict history, dishonest route
    docstring, missing lookup_status, statement cap moved into _make.
- **Live-verified in-container (zero LLM, keyless enrichment):**
  docs/probes/2026-08-08-s12-ach-live-loop.md + postscript. Post-fix state:
  the typosquat email → TP/TEST 50/50 (1.0 bit), FP + BENIGN rejected with
  named reasons, ONE auth row, top lookup mail.paypa1.com at **0.181584 bits
  — equal to the independently hand-computed fixture to 6 decimals**; the
  executed lookup answered no-signal → weak ENRICHMENT_NO_SIGNAL row, nudge
  toward TEST, candidate retired.
- **SARA recon (probe: docs/probes/2026-08-08-sara-ach-analogues.md):** SARA
  has NO ACH engine — its prompt-only version is structurally discarded by its
  own output template (the cautionary tale D-019 is built against). Verified
  negatives recorded with the greps.
- **CI-green: 572 tests** (was 516 at S12 start: +2 S11-review additions
  already counted there, +26 ach core, +18 investigations/store routes/
  regressions, +10 verification regressions). `./ci.sh` green; container
  rebuilt with `auspex.ach`; `/api/health/ready` 200.
- **Primary dev LLM (D-015):** Llama-4-Scout via Northflank; secondary/offline
  Ollama `qwen3:14b` (D-013). S12 sent ZERO prompts to either — the ACH core
  and surface are deterministic end-to-end. The S12 Step-0 review fixes were
  live-verified against Scout (docs/probes/2026-08-08-s12-phishing-review-live.md).
  TD-005 battery NOT re-triggered (no new doc_type, no model change).

## In-flight / standing follow-ups (carry forward until DONE)
1. **S13 Step 0: fresh-eyes review of the S12 feature work → `/promote` (#14).**
   Scope: the 17 commits `5d3d2dc..staging` (~3,094 insertions) — `auspex/ach/`
   (types/evidence/matrix/gain/store), `auspex/routes/investigations.py`, the
   3 new tables in migrations.py, tests. NOTE: this code already survived a
   same-session 4-lens verification workflow (16 findings fixed) — the Step-0
   drill should be FRESH-EYES + different angles, not a re-run: (design) are
   the curated cell vectors and likelihood rows defensible to an analyst — is
   TEST_ACTIVITY's likelihood row justified? (security) tenancy on the new
   routes end-to-end via two real workspaces; jsonb subject round-trip
   adversarial values; (correctness) matrix math edge cases the workflow
   lenses missed (duplicate hypothesis keys? empty catalog? cells jsonb
   hand-edited in DB?); (honesty) the API field names vs what they claim.
   Verify by execution before fixing. DO NOT promote unreviewed.
2. **TD-005 re-battery trigger (standing):** corpus > 30k chunks, ANY new
   doc_type, or embedding-model change → re-run the labeled battery. (S12
   added no doc_type — not tripped.)

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat; the ACH engine's lookup execution calls EnrichmentService
   directly (code-driven, no agent loop, no proposals — read-only lookups
   only). TD-012 (post-hoc contract validation), TD-014 (unbounded history),
   TD-015 (brand-list/confusable coverage, registrable-domain item FIXED in
   the S12 review), TD-016 (ACH v1 surface bounds) open.
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
4. **Corpus ~3.4k chunks, grows ~770 docs/day** while the container runs.
   TD-011 tracks the rollover trigger (>150k chunks / RSS >70% / p95 >500 ms).

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`
  (ENRICHMENT_ENABLED=false, KB_ENABLED=false, INGEST_ENABLED=false).
- Ollama **0.32.5** on :11434 (host upgraded from 0.24.0 between S11 and S12);
  models qwen3:14b / llama3.1:8b / mistral:latest.
- `gh` flips to SIRP-Burhan between sessions AND mid-session (D-011) —
  re-check before EVERY `gh` call. **At S12 start it HAD flipped back to
  SIRP-Burhan** — caught by the ritual, switched. Assume it flips again.
- `ingest_state` rows: `nvd-delta`, `kev`, `attack-enterprise` (v19.1).
- auspex-knowledge: ~3,417+ chunks (seed + live NVD/KEV/EPSS + ATT&CK).
- **S12 demo (zero-LLM, works in any shell):**
  1. `TOKEN=$(curl -s -X POST localhost:8000/api/auth/dev-login -H 'Content-Type: application/json' -d '{"email":"burhan@auspexdev.com"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')`
  2. POST `/api/investigations` with the spoofed typosquat email (probe doc has
     it) → 4 hypotheses, TP/TEST 50/50, FP+BENIGN rejected with named reasons,
     ranked lookups with itemized gain bits.
  3. POST `/api/investigations/{id}/lookups` → executes the top lookup through
     live keyless enrichment, folds the answer in, re-assesses; `lookup_status`
     says completed/not_completed honestly.
- **S11 demo turns (PHISHING_ANALYSIS, live Scout)** still valid — see the
  2026-08-08 review probe: MALICIOUS floor + BENIGN gate + self-spoof named.
- **S10/S9/S8 demo turns** unchanged (see git history of this file).

## Reference intelligence (from the SARA Open architecture study)
Base: `/home/burhan/sara-open/` — key snapshots in docs/probes/:
- ACH analogues (S12): 2026-08-08-sara-ach-analogues.md — **SARA has no ACH**;
  falsification guards + doctrine tables are the reusable patterns.
- Phishing/header/typosquat (S11): 2026-07-18-sara-phishing-header-patterns.md
- Alert additive scorer (S10): 2026-07-18-sara-alert-triage-scorer.md
- DEFERRED rail (S9): 2026-07-18-sara-orchestrator-deferred.md
- Fast classifier / 92-8: 2026-07-16-sara-fastpath-pattern.md
- RRF retrieval + ID bypass: 2026-07-17-sara-rrf-retriever-pattern.md

## Next session should
Run the S13 Step-0 fresh-eyes review of `5d3d2dc..staging` → `/promote` (#14) →
then S13 exactly as written in NEXT-SESSION.md (Evidence graph + cited output:
typed evidence objects — `ach_evidence` was designed as the substrate — every
generated claim carries a citation, output guard rejects uncited claims). S13
REJOINS the LLM path (cited rendering through a contract), so the S10/S11
directive+pin pattern applies and live verification against Scout is required.
