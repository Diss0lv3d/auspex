# STATE — Auspex

_Last updated: 2026-08-15 (S18 COMPLETE — Step 0: `/promote` cleared the slate
(PR #17), then a fresh-eyes review of the S17 commits: **the strongest lead was
refuted by measurement, two leads verified sound, and three defects were found on
an angle nobody had listed**. Then **S18 Approval flow** (Phase 4, D-024): a
proposal is claimed exactly once, its card is compiled from the spec and frozen,
and an approved action re-checks both the D-014 gate and a spec fingerprint before
it runs. **Something really executes for the first time, and its undo is really
run.**)_

## Where we are

**Phase 4 has a contract (S17) AND a decision loop (S18). Actions execute.**

- **S18 Step 0 — `/promote` FIRST (DONE).** `839d574` (the Actions SDK) is on
  `main` as squash `19d7953` via PR #17; back-merged `517f76c` with the tree
  asserted unchanged. **`gh` HAD flipped to the work account** at session start —
  D-011 earned its keep again; switched and re-verified before every `gh` call.
- **S18 Step 0 — fresh-eyes review of `e57ab0c` + `839d574` (DONE).** Record:
  docs/probes/2026-08-15-s18-step0-review.md. Everything reproduced BY EXECUTION.
  - **(REFUTED — the strongest lead) the half-life fan-out costs almost nothing.**
    The worry was multiplicative (`bounds = edges × half-lives`, measured at S17
    on THREE families). Measured at 25k rows: 3 → 1.9 ms, 50 → 3.6 ms, 500 →
    4.9 ms, **2000 families / 6000 LATERAL descents → 12.2 ms, still faster than
    the query it replaced**, never a seq scan. The same rows partition into more
    families, so each descent finds proportionally fewer. Pinned by a 50-family
    plan test — the cost is not at risk, the SHAPE is.
  - **(REAL — TD-024) the 365-day regression S17 logged as "~9%" is worse and now
    bounded.** At **100k verdicts the widest legal window costs 161 ms vs the old
    query's 134 ms** — slower than the 143 ms defect the rewrite existed to fix,
    and `days` is a user-supplied parameter capped at 365. Crossover ≈300 days at
    100k/12 families, ≈185 at 25k/50. A fix was built and measured (**2.2–2.9× at
    every window, byte-identical output, 59 probes instead of ~30 000**) and
    **deliberately not shipped**: its early stop depends on candidate ordering
    surviving into the outer query, which Postgres does not guarantee, and losing
    that renders **the wrong rows first** rather than merely slowly. `MAX_SINCE_DAYS`
    stays 365. TD-024 carries the numbers so S19 inherits a costed decision.
  - **(SOUND) the `OFFSET 0` fence is genuinely protected.** Removing it exactly as
    a future reader would gives `Hash Join` + `Seq Scan on verdicts`, 2.8 → 16.2 ms,
    and the plan test's "no Seq Scan" assertion **does** fail. Not decoration.
  - **(SOUND) the four-clause `trustworthy` rule.** Matrix executed: a healthy
    `ingest-cycle` does **not** mask a degraded consumer; ingest-disabled reports
    never-run counters and is refused; the "failed but never succeeded" clause
    heals on the first success. The one case that looks like a hole (a 0/0
    consumer vouched for by the cycle counter) is the designed behaviour — its
    residual is TD-022.
  - **(3 DEFECTS, off-list) the contract's own rails.** All eight documented rails
    held, including the `object.__setattr__` forge. Three got through:
    **(a) the undo slot had exactly one guard** — an undo could be the action's own
    `dry_run`, another action's `dry_run`, or another action's **execute**
    (undoing an isolation really ran `delete_file`); all three registered, all
    three ran, all three reported `reversible=True` to an approver.
    **(b) parameter names were unvalidated wire identifiers** — `''`, `'host id'`,
    `'π'` all reached `wire_spec`; found while fixing it, the action-name rule used
    `.isalnum()`, **true for `π`**, so it never was ASCII-only.
    **(c) an action could silently shadow a tool** — model told "destructive,
    requires approval", `_dispatch` resolves in the ToolRegistry, D-014 reads the
    **tool's** level and auto-executes. Latent in S17, live the moment S18 wired
    dispatch, so fixed at loop construction.
- **S18 feature — Approval flow (DONE, ratified D-024).**
  `auspex/actions/{proposal,settlement,builtin}.py` + `auspex/routes/proposals.py`.
  1. **Settlement is a claim, not a check.** One
     `UPDATE ... WHERE status='pending_approval' RETURNING`. Verified by racing
     **eight distinct Postgres backends at a barrier, 5 trials, 1 winner each** —
     the probe asserts the backend COUNT too, because a race that quietly
     serialised would pass a winner-count check while proving nothing. The same
     device claims the execution and the undo.
  2. **The card is compiled from the spec and FROZEN on the row.** Re-rendering on
     read would show today's declaration for yesterday's decision.
  3. **An approval does not survive a change to what was approved** (TD-023's
     hardest item). A canonical fingerprint of the declared facts is re-checked at
     execute time alongside a re-run of the D-014 gate. Handler BODIES are
     explicitly out of scope — that is deploy integrity, and D-024 says so rather
     than letting the rail look stronger than it is.
  4. **Only systems we own execute.** `EXECUTABLE_SYSTEMS = {"auspex"}`, in code.
     Live-demonstrated: a destructive EDR action is filed, approved by a human,
     and still refused.
  5. **Calling an action files a proposal** — D-023's deferred round-trip. Actions
     reach the wire only when a proposer is wired in.
- **Two defects found by RUNNING this session's own code** (probe:
  docs/probes/2026-08-15-s18-approval-flow-live.md): a module-global pool two
  registries silently shared (`another operation is in progress`, two event loops)
  — removed, which also stopped handing third-party actions a DB handle; and an
  SSE generator whose only exit was `is_disconnected()`, which does not reliably
  fire. **Fourth session running where executing found what reading had not.**
- **CI-green: 801 tests** (772 at S17 end → +9 Step-0 regressions, +20 S18).
  `./ci.sh` green including the installed-dist gate (**114 modules**, was 110);
  `/api/health/ready` 200.
- **Zero new env vars** this session (and none across S14–S18).

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: EMPTY (corrected at S19 start).** S18's commits reached `main`
   as squash `7813e43` via **PR #18**, back-merged as `295c5bb` — this happened
   *after* the S18 session-end commit `005cc01` was written, so STATE.md and
   NEXT-SESSION.md both shipped stale ("three commits waiting to promote").
   Verified at S19 start: `git diff origin/main..staging --stat` is **empty**.
   S19 Step 0 therefore skips `/promote`.
2. **TD-005 re-battery trigger: TRIPPED (2026-08-15).** Corpus is **31,819 docs**
   in `auspex-knowledge` (27,475 at S17 end, 27,460 at S17 start — it grew ~4.3k
   THIS session because ingest ran). The 30k line is crossed for the first time.
   Doc-type mix: cve 30,553 · technique 1,248 · tactic 15 · concept 3 — **no new
   doc_type and no embedding-model change**, so it is the size trigger alone.
   **Re-run the labeled retrieval battery before trusting any RAG-backed answer**,
   and re-check the per-doc_type neural floors calibrated at S8 against the grown
   corpus. This is S19 Step 0's first item.
3. **S19 Step 0: fresh-eyes review of the S18 commits** (`a3b431b`, `b536f1e`,
   `c21beb8`). Angles S18 did NOT adversarially test:
   - **(the fingerprint's blind spots) `canonical_spec` is hand-listed on purpose.**
     Add a field to `ActionSpec` and it is silently absent from the identity — the
     comment says "consider it on purpose", and nothing ENFORCES that. Try it: add
     a field, confirm the fingerprint does not change, and decide whether a
     structural check (dataclass field set vs the canonical key set) belongs here.
     Also: `FINGERPRINT_VERSION` is never exercised — what actually happens to
     approved-but-unexecuted proposals when it bumps?
   - **(the status machine) 'executing' and 'undoing' are claims with no timeout.**
     A process that dies mid-execution leaves a row stuck in `executing` forever —
     it can never be executed, undone or rejected, and nothing reaps it. Kill the
     app between the claim and the handler and see what the surface says.
   - **(the executor's failure paths) `execute` marks `failed` and re-raises**, but
     the note may or may not have been written depending on WHERE it raised. There
     is no idempotency key and no partial-effect reasoning (TD-025 names this as
     unwritten). Force a failure after the INSERT and see what state the world is
     in, and whether `undo` can still clean up (it is keyed on proposal_id, so it
     might — verify).
   - **(the SSE stream) tenancy and the reconnect path.** `stream()` closes over
     `auth.workspace_id` at connect time; confirm a second workspace's proposals
     can never appear, and that the `reconnect` frame is actually reached at
     `STREAM_MAX_TICKS` (nothing consumes this stream yet, so it has never been
     driven by a real client).
   - **(the round-trip's honesty) a model that calls an action twice in one turn**
     files two proposals for the same thing. Nothing dedupes. Is that right?
   Verify findings BY EXECUTION before fixing; fix with regressions.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat, which is why S18's cards stream on the approvals surface rather
   than inside a chat turn. Open: TD-012 (post-hoc validation, incl. the citation
   guard), TD-014 (unbounded history), TD-015 (brand/confusable coverage), TD-016
   (ACH surface bounds), TD-017 (chat-side NUL hardening), TD-018 (no per-workspace
   bound on the NUMBER of inference calls), TD-019 (retro-hunt v1 bounds), TD-020
   (watcher v1 bounds), TD-021 (timeline v1 bounds), TD-022 (durable checker
   heartbeat), TD-023 (Actions SDK v1 bounds — **two items closed by S18**),
   TD-024 (the decay-read crossover, costed), TD-025 (approval flow v1 bounds).
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
4. **Corpus 31,819 docs and growing while the container runs.** TD-011 tracks the
   rollover trigger; **TD-005's 30k line is now CROSSED** (see In-flight 2).

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via
  `auspex.devhost` (ENRICHMENT/KB/INGEST disabled on host).
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- **`gh` DID flip to the work account at S18 start** (active was `SIRP-Burhan`).
  It did not at S17, did at S16, did not at S13/S14/S15. Unpredictable is the
  pattern — D-011's "re-check before EVERY `gh` call" is the only safe reading.
- **`gh pr merge` works** — re-verified at S18 (PR #17 merged by Claude, first
  try). `gh pr edit` still fails with a Projects-classic GraphQL deprecation —
  use `gh api -X PATCH repos/.../pulls/N`.
- **This repo has NO GitHub Actions** — `gh pr checks` reports 0 checks, so
  `./ci.sh` locally IS the gate. Do not wait on remote CI that does not exist.
- **Local `main` ref goes stale every promote.** `/promote` and any `main..staging`
  diff must `git fetch origin` and compare against `origin/main`, and the commit
  LIST is meaningless after a squash — read `git diff origin/main..staging --stat`.
- **The app container runs the BUILT IMAGE, not the working tree.** A migration
  added this session did not appear after `docker compose restart app`; it needed
  `docker compose up -d --build app`. Costs a minute and a wrong conclusion if
  forgotten.
- **Probe residue is expensive to leave behind.** A 100k-row seeded workspace left
  in the dev DB made the timeline plan tests take **150 s instead of 21 s**.
  Every S18 probe script deletes its workspaces and VACUUMs.
- **Plan assertions on this dev DB must VACUUM first** — bloat, not the query,
  decides the plan. **Small tables legitimately seq-scan**; assert plans only at
  sizes where a scan would cost something (the suites seed 25k).
- **Data-modifying CTEs cannot see each other's rows through a table scan** —
  chain `INSERT ... RETURNING`; re-reading the table silently seeds zero rows.
- **S18 demo (zero-LLM, ~60 s):**
  1. Propose + approve + undo through the real HTTP surface — the exact commands
     and their real output are in
     docs/probes/2026-08-15-s18-approval-flow-live.md §1–§4: the card is compiled
     from the action's own dry run, the second approve is a **409**, the undo
     removes exactly what the approval added, and the notes table returns to 0.
  2. The blast-radius rule (§5): a DESTRUCTIVE EDR action is filed and approved by
     a human and **still refuses to run** — `system_not_executable`.
  3. `.venv/bin/python docs/probes/s18-step0/probe_race.py` — 8 distinct backends,
     1 winner, 5 trials.
- **S17/S16/S15/S14/S13/S12–S8 demo turns** unchanged (see git history of this file).

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
~~Start with `/promote`~~ — **already done: PR #18 merged S18 to `main` and
`origin/main..staging` is empty (corrected at S19 start).** **Start instead with
TD-005: the corpus crossed 30k during S18
(31,819), so re-run the labeled retrieval battery and re-check the S8 neural
floors before trusting any RAG-backed answer** — this is the first time that
trigger has fired. Then S19 Step 0: fresh-eyes review of the S18 commits (see
In-flight 3 — the `canonical_spec` blind spot and the un-reaped `executing` status
are the strongest leads). Then S19 per ROADMAP: **Hardening** — input guard
(injection patterns + security-content carve-outs), rate limits, usage-based plan
gating skeleton; TD-018 (per-workspace inference-call bound) is explicitly S19's.
NEXT-SESSION.md has the full prompt.
