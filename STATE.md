# STATE — Auspex

_Last updated: 2026-08-09 (S14 COMPLETE — Step 0: adversarial review of the S13
cited-summary commits, 4 findings all verified by execution before fixing; then
**S14 Retro-hunt** (Phase 3 flagship): the S7 NullSink seam got its consumer —
new intel sweeps historical observables through a bounded indexed join, re-open
events never touch a verdict, and verdict label changes became provenanced rows.
Live verification also exposed two long-standing PACKAGING defects that made
every container image ship a broken install.)_

## Where we are
- **S14 COMPLETE, on `staging`, not yet promoted.** Three parts:
  - **Step 0 — adversarial review of `3dd9b7c..376dc13` (DONE).** The four
    angles the S13 build never tested. 4 defects, each verified by execution
    BEFORE the fix and re-executed after (probe:
    docs/probes/2026-08-09-s14-step0-review.md); 1 named angle confirmed sound.
    (1) An evidence statement is attacker-authored, so a citation-SHAPED token
    ("per case E-deadbeef") reached the model verbatim — and a summary that
    merely QUOTED the statement was reported as having fabricated a citation.
    One token in a paste made every honest summary of that investigation read as
    dishonest, deterministically. `_data` now redacts the shape at the same
    boundary that flattens, using the SAME regex the guard detects with.
    (2) The uncited check was per-LINE and so encoded Scout's markdown habits:
    3 of 4 faithful renderings (tables, wrapped prose, sub-headings) were called
    dishonest. `claim_blocks` checks claim BLOCKS; a planted uncited claim is
    still caught in every shape. `uncited_lines` → `uncited_claims`.
    (3) The pin failed on `**TRUE-POSITIVE**` — the S13 tokens are the first
    HYPHENATED allowed_values, so the first to hit the compound branch, which
    returned the chunk with its trailing markdown. Harmless for every pre-S13
    contract, which is why 9 sessions never surfaced it.
    (4) The directive was unbounded in the evidence count: 200 rows (reachable)
    compiled ~13.5k prompt tokens against a ~1.2k norm, with the pin on the LAST
    line. Caps at 40 rows / 12 bearing ids hold it flat; truncation is named to
    the model and to the analyst (`evidence_shown`/`evidence_total`).
    Fix commits: d06ad1b, a795fe6.
  - **S14 feature — Retro-hunt (DONE).** `auspex/retrohunt/` (types, store,
    sink, flips) + `auspex/routes/retrohunt.py` + 2 tables + 1 index. Design
    ratified as **D-020**. The sweep is ONE indexed join per 50-id chunk across
    workspaces on a new `(type, value)` index (the existing UNIQUE index leads
    with workspace_id, which the sweep does not know yet); each hit carries its
    workspace_id into the row it writes. **It is the first production READER of
    the `verdicts` table** — write-only from S5 through S13. Re-open events
    record the label as it stood AT MATCH TIME and never write a verdict
    (`record_matches` has no verdict write at all — the D-017 rail is
    structural). Trigger kinds are closed (`kev-added`, `deleted`); `upserted` is
    ~770 CVSS re-scores/day and is filtered out. Verdict label changes become
    `verdict_flips` rows with both verdict ids, the trigger, and the match that
    prompted the re-look — written inside the enrichment transaction by the only
    code that writes verdicts. A first-ever verdict is not a flip; an open match
    is never auto-closed by a flip. 3 zero-LLM routes, explicit ack.
  - **Packaging — two long-standing defects fixed (792929f).** Caught only by
    running a verification script from `/tmp` inside the container instead of
    from the source root. (a) `auspex.modes` (since S9) and `auspex.retrohunt`
    were never in `[tool.setuptools] packages`. (b) EVERY `__init__.py` in the
    installed distribution was **0 bytes** — all 13 packages, since the
    Dockerfile was written: the deps-only layer's skeleton `pip install .`
    leaves `build/lib/**/__init__.py` at 0 bytes and setuptools reuses build/lib.
    Both hid behind the same accident — `uvicorn server:app` runs with
    WORKDIR on sys.path, so the COPY'd source shadows site-packages. **The
    container served every request correctly on top of a broken install and
    `./ci.sh` was green**, because its container step only asked /api/health
    whether the process was alive. `ci.sh` now imports the app from `/tmp` in
    the container and asserts the installed tree byte-matches the source.
- **Query plan probed, and the first reading of it was WRONG** (probe:
  docs/probes/2026-08-09-s14-retrohunt-explain.md). EXPLAIN rejected
  `WHERE value = ANY($1)` at 500 ids: `Seq Scan ... Rows Removed by Filter:
  19760`. Rewriting it as a join over `unnest` did NOT fix that — measured, the
  array spelling holds the index to a LARGER batch than the join. **Chunking
  fixed it.** `SWEEP_CHUNK=50` comes from a measured crossover that RISES with
  table size (20k rows → index to batch 50; 200k rows → index at every size
  measured), so a chunk that stays on the index at the smallest size stays on it
  forever. The code comment says so — a comment crediting the wrong cause is
  worse than none.
- **Live-verified in-container** against CVE-2026-35273, genuinely KEV-listed in
  this deployment's KB (probe: docs/probes/2026-08-09-s14-retrohunt-live.md):
  settled `suspicious` → kev-added DocChange (with `upserted` noise in the same
  batch, correctly ignored) → 1 re-open event, verdict trail untouched, 0 flips
  → re-enrichment disagrees → 1 flip `suspicious→malicious`,
  `trigger=retrohunt:CVE-2026-35273`, match linked and still open → re-emit is
  not news twice. HTTP surface confirmed with a real token (ack 200, open list
  → 0, double-ack 404, unauthenticated 401). All probe residue deleted.
- **CI-green: 643 tests** (607 after Step 0 → +31 retro-hunt, +5 packaging,
  +2 schema/render). `./ci.sh` green including the new installed-dist gate;
  container rebuilt `--no-cache`; `/api/health/ready` 200.
- **Zero new env vars** this session (retro-hunt reads no configuration).
- **LLM untouched by S14 proper** — retro-hunt is ingest/join/event code, zero
  LLM by design. Scout (D-015) was exercised only via the S13 regressions.

## In-flight / standing follow-ups (carry forward until DONE)
1. **S15 Step 0: fresh-eyes review of the S14 commits** (`404b092`, `792929f`,
   plus the Step-0 fixes `d06ad1b`/`a795fe6` if #15 has not shipped them).
   Angles S14 did NOT adversarially test: **tenancy of the cross-workspace
   sweep** (it deliberately does not filter by workspace — is every write and
   read path really scoped, including `open_match_for` inside another tenant's
   enrichment transaction?); **flip-writer contention** (two concurrent
   enrichments of one observable — does `latest_verdict` race and produce two
   flips or a wrong `from_label`? the S13 review found exactly this class with
   `FOR UPDATE`); **sweep cost under a real KEV first-run** (1,600 ids = 32
   queries inside an ingest cycle — does it stall the cycle?); **`change_kind`
   `deleted` semantics** (an NVD-rejected CVE is recorded as a re-open reason —
   is "this CVE was withdrawn" honestly a reason to re-examine, or should it
   read differently in the payload?).
2. **TD-005 re-battery trigger (standing, NOT tripped):** corpus > 30k chunks,
   ANY new doc_type, or embedding-model change → re-run the labeled battery.
   S14 added no doc_type and no model change. Corpus now ~25.9k docs in
   `auspex-knowledge` — **closer to the 30k trigger than at S13; check it at
   S15 start.**
3. **Promote #15 not yet raised.** S14 is complete and demoable on `staging`;
   `main` is at #14 (87eb279).

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat. Open: TD-012 (post-hoc validation, incl. the citation guard),
   TD-014 (unbounded history), TD-015 (brand/confusable coverage), TD-016 (ACH
   surface bounds), TD-017 (chat-side NUL hardening), TD-018 (no per-workspace
   bound on the NUMBER of inference calls — narrowed at S14 Step 0, the
   per-CALL amplification is gone), TD-019 (retro-hunt v1 bounds).
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
4. **Corpus ~25.9k docs, grows ~770/day** while the container runs. TD-011
   tracks the rollover trigger; TD-005's 30k line is now close.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via
  `auspex.devhost` (ENRICHMENT/KB/INGEST disabled on host).
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- `gh` did NOT flip at S13 or S14 start, but D-011 stands: re-check before
  EVERY `gh` call. `gh pr merge` is blocked by the Claude permission
  classifier — the human merges PRs.
- **Local `main` ref goes stale every promote** (the human squash-merges on
  GitHub; nothing here checks out `main`). `/promote` and any `main..staging`
  diff must `git fetch origin` and compare against `origin/main`.
- **Plan assertions on this dev DB must VACUUM first.** Seeding and dropping
  25k rows left 25k dead tuples in 358 pages behind 10 live rows; the planner
  costs a scan in PAGES, so bloat — not the query — decided the plan and failed
  a test for reasons unrelated to the code.
- **S14 demo (zero-LLM, ~20 s):**
  1. `TOKEN=$(curl -s -X POST localhost:8000/api/auth/dev-login -H 'Content-Type: application/json' -d '{"email":"burhan@auspexdev.com"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')`
  2. Copy `docs/probes/2026-08-09-s14-retrohunt-live.md`'s script into the app
     container and run it from `/tmp` (`docker compose exec -T --workdir /tmp
     app python /tmp/live_retrohunt.py`) → settled verdict, one re-open event,
     verdict trail provably untouched, then a provenanced flip.
  3. `curl -s localhost:8000/api/retrohunt/matches -H "Authorization: Bearer $TOKEN"`
     → the event with `action: "re-examine"` and the label as it stood at match
     time; `/api/retrohunt/flips` → `trigger=retrohunt:CVE-…` linking the intel
     to the label change.
- **S13 demo (needs Scout):** POST the typosquat email to `/api/investigations`,
  then POST `/{id}/summary` → cited summary, `contract_valid`, `pinned`,
  `citations.{ok,unknown,uncited_claims}`, `evidence_shown`/`evidence_total`.
- **S12 demo (zero-LLM)** and **S11/S10/S9/S8 demo turns** unchanged (see git
  history of this file).

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
S15 Step 0: fresh-eyes review of the S14 commits (see In-flight 1 — sweep
tenancy, flip-writer contention, first-run sweep cost inside a cycle, `deleted`
semantics). Also check the TD-005 30k-chunk trigger at start. Then `/promote`
#15, then S15 per ROADMAP: **Falsification watchers** — verdicts register "what
would flip me" and watchers monitor feeds/enrichment for exactly that. S14's
`verdict_flips` trail and the retro-hunt sink are the substrate it builds on.
NEXT-SESSION.md has the full prompt.
