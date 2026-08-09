# STATE — Auspex

_Last updated: 2026-08-09 (S13 COMPLETE — Step 0: fresh-eyes review of the S12
diff, 7 findings all verified by execution and fixed; **promote #14 MERGED by
the human (squash 87eb279) and back-merged (9b61656), main == staging**; the
S13 scope: citable evidence objects + the first LLM-rendered path since S11 —
a cited investigation summary through a contract with a pinned leading
hypothesis and a code-owned citation guard, live-verified against Scout twice)_

## Where we are
- **S13 COMPLETE.** Three parts:
  - **Step 0 — fresh-eyes review of `5d3d2dc..staging` (DONE).** Four lenses
    the S12 same-session workflow did NOT run. 7 findings, every one verified
    by execution BEFORE fixing (probe:
    docs/probes/2026-08-09-s13-step0-review.md): a NUL byte in a paste 500'd
    the live container (Postgres can't store U+0000 — now stripped at the
    boundary); duplicate hypothesis keys double-rendered weights (sum 1.30 —
    score_matrix now refuses); hand-edited cells jsonb crashed every GET
    (string cell → TypeError) or manufactured a fake hard contradiction
    (−7 accepted — load now enforces the declared CELL_MIN..CELL_MAX, skip +
    warn); two CONCURRENT lookups folded the same provider claim twice
    (FP inconsistency 5.0 instead of 2.5 — add_evidence now takes FOR UPDATE
    + dedups per (kind, source, obs_id)); recipient_domains was unbounded in
    the snapshot (300 entries — capped 50 + named truncation); API `weight`
    renamed `plausibility_weight` (it is NOT a probability); zero-hypothesis
    edge messages now say what is true. Two-workspace tenancy verified
    end-to-end through the routes (404 both directions — pinned). Curated
    numbers judged defensible, documented in the probe. Fix commits:
    108f8d5, 9b53f72, cd13ea5, 52fc2ee.
  - **Promote #14 — DONE (merged same session).** `gh pr merge` was blocked
    by the permission classifier (same as #13 at S12); Burhan squash-merged
    by hand (87eb279), Claude back-merged with `-X ours` (9b61656, tree
    verified unchanged, main == staging content). NOTE: the PR tracked
    `staging`, so it carried ALL of S12+S13 — everything on it was
    reviewed, tested, and live-verified before merge.
  - **S13 feature — evidence graph + cited output (DONE, on staging).**
    (1) `ach_evidence` row uuids surface as the STABLE citation identity:
    store fills `Evidence.evidence_id` on load; labels are `E-<uuid hex8>`
    (collision-extending, deterministic); GET exposes `evidence_id` + `cite`
    per row. (2) `POST /api/investigations/{id}/summary` — the first LLM
    call on the investigations surface, third application of the S10/S11
    directive+pin doctrine: code compiles the AUTHORITATIVE directive
    (matrix state, per-hypothesis "bearing evidence" ids computed from the
    nonzero cells, statements flattened via auspex.untrusted at the
    boundary, the engine's top lookup); the model narrates; the leading
    hypothesis is PINNED (hyphen tokens: TRUE-POSITIVE… — underscores would
    truncate in the validator's tokenizer); contract machinery reused via a
    public `split_sections` seam (chat's six modes untouched). (3) The
    citation guard (`check_citations`) is post-hoc (TD-012: detected, never
    prevented): fabricated ids and uncited claim lines in the citable
    sections are named in the response (`citations.ok/unknown/
    uncited_lines`). No summary persistence — reads recompute, as everywhere.
    Zero new env vars. KB-doc citability deliberately NOT picked up.
- **Live-verified against Scout (D-015), twice** (probe:
  docs/probes/2026-08-09-s13-cited-summary-live.md): run 1 caught a REAL
  guard bug (Scout's legitimate grouped `[E-a, E-b]` citations were flagged
  uncited — guard now token-based, typography-agnostic) and a directive gap
  (rejected hypotheses had nothing to cite → literal `[ ]` — directive now
  names bearing evidence per row); run 2 clean: contract_valid=true, pin
  honored, **19 valid citations, 0 fabricated, 0 uncited**. Both probe
  investigations deleted from the dev workspace.
- **CI-green: 597 tests** (572 at S13 start → +7 Step-0 regressions/tenancy,
  +14 render/guard fixtures, +4 summary route tests). `./ci.sh` green;
  container rebuilt; `/api/health/ready` 200.
- **Primary dev LLM (D-015):** Llama-4-Scout via Northflank — used live for
  the summary path (1.2k prompt / 0.6k completion tokens per summary).
  Secondary/offline Ollama `qwen3:14b` (D-013) untouched this session.
  TD-005 battery NOT re-triggered (no new doc_type, no model change).

## In-flight / standing follow-ups (carry forward until DONE)
1. **S14 Step 0: fresh-eyes review of the S13 feature commits**
   (`3dd9b7c`, `62d332f`, `376dc13` — ~900 insertions: ach/render.py, the
   summary route, evidence_id plumbing, contract split_sections seam).
   Angles the S13 build did not adversarially test: prompt-injection through
   evidence statements INTO the rendered summary (the directive flattens,
   but is 160 chars of hostile statement enough to steer citations or the
   narrative?); the guard's line-based heuristic (multi-line prose claims);
   summary cost exposure (no per-workspace rate limit on an
   inference-spending route — chat shares this, maybe a TD); pinned-token
   edge cases (what does Scout do when NONE is pinned?). NOTE this code was
   live-verified but got NO independent adversarial pass — the S12→S13
   pattern says review before the next promote (#15).
2. **TD-005 re-battery trigger (standing):** corpus > 30k chunks, ANY new
   doc_type, or embedding-model change → re-run the labeled battery. (S13
   added no doc_type — not tripped.)

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired
   into /api/chat. TD-012 (post-hoc contract validation — now also covers
   the citation guard), TD-014 (unbounded history), TD-015 (brand/confusable
   coverage), TD-016 (ACH v1 surface bounds), TD-017 (NUL fixed only at the
   investigations boundary; chat likely shares the 500 shape) open.
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
4. **Corpus ~3.4k chunks, grows ~770 docs/day** while the container runs.
   TD-011 tracks the rollover trigger.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via
  `auspex.devhost` (ENRICHMENT/KB/INGEST disabled on host).
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- `gh` did NOT flip at S13 start (first session it stayed personal), but
  D-011 stands: re-check before EVERY `gh` call. `gh pr merge` is blocked by
  the Claude permission classifier — the human merges PRs.
- **Local `main` ref goes stale every promote** (the human squash-merges on
  GitHub; nothing ever checks out `main` here). Found at S14 start pointing at
  #13's 55e9875 while `origin/main` was #14's 87eb279 — fast-forwarded via
  `git update-ref refs/heads/main origin/main`. `/promote` and any
  `main..staging` diff must `git fetch origin` and compare against
  `origin/main`, not local `main`.
- **S13 demo (needs Scout reachable; ~30 s):**
  1. `TOKEN=$(curl -s -X POST localhost:8000/api/auth/dev-login -H 'Content-Type: application/json' -d '{"email":"burhan@auspexdev.com"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')`
  2. POST the flagship typosquat email to `/api/investigations` (probe doc
     has it) → note `evidence[].cite` labels (E-xxxxxxxx).
  3. `curl -s -X POST localhost:8000/api/investigations/<id>/summary -H "Authorization: Bearer $TOKEN"` →
     model-rendered summary where EVERY hypothesis line and evidence line
     carries [E-…] citations; `contract_valid`, `pinned`, and
     `citations.{ok,unknown,uncited_lines}` report the code's verdict on it.
- **S12 demo (zero-LLM)** unchanged: POST /api/investigations →
  4 hypotheses, FP+BENIGN rejected with named reasons, TP/TEST 50/50 at
  1.0 bit, ranked lookups with itemized gain; POST /{id}/lookups executes
  the top one through keyless enrichment.
- **S11/S10/S9/S8 demo turns** unchanged (see git history of this file).

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
S14 Step 0: fresh-eyes review of the S13 feature commits (see In-flight 1 —
injection-through-statements, guard heuristics, cost exposure). Then S14
per ROADMAP: **Retro-
hunt** — on-ingest sweep of historical observables (indexed join, never
scan), re-open notifications, verdict flip events. The S6/S7 ingest layer
already emits DocChange events into a NullSink hook built for exactly this
(ROADMAP S7 note). NEXT-SESSION.md has the full prompt.
