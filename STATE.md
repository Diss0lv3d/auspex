# STATE — Auspex

_Last updated: 2026-08-11 (S17 COMPLETE — Step 0: independent adversarial review
of the S16 timeline commits, 4 angles executed, **3 defects fixed, 1 verified
sound, 1 found off-list**, promoted as PR #16. Then **S17 Actions SDK contract**
(Phase 4, D-023): an action declares what it does, needs and can break; a
destructive action with no undo cannot be constructed; `dry_run` is required of
everything; the planner manifest reuses the S13 capability decision. Nothing
executes.)_

## Where we are

**Phase 3 (Living Verdicts) is closed and reviewed. Phase 4 has started.**

- **S17 Step 0 — fresh-eyes review of `44ccaa4`/`1b9e8e2` (DONE, PROMOTED).**
  Every finding reproduced BY EXECUTION before being fixed (probe:
  docs/probes/2026-08-11-s17-step0-review.md). On `main` as squash `ed0443b`.
  - **A (DEFECT, the strongest lead, worse than the lead said):** `_DECAYED_SQL`
    read the workspace's ENTIRE verdict history and spilled its sort to disk
    (`external merge 6200kB`) to find the handful of rows that crossed a band —
    **143 ms at 99k observables / 109k verdicts**, on the page an analyst opens
    FIRST after a week away. The predicate was fine; its spelling was not. Moving
    `created_at` to one side (`since - e*hl < created_at <= now - e*hl`) makes a
    crossing a created_at RANGE per (edge, half-life) pair, as wide as the window
    whatever the half-life — which an index serves. **4.6 ms, 33×**, no scan, no
    temp files, new index `idx_verdicts_ws_hl_created`, and it now has the plan
    assertion at 25k that TD-021 said it lacked. Two things recorded because the
    wrong version looks right: the half-lives are enumerated from the DATA (a
    parameter carrying `HALF_LIFE_DAYS` would make a new half-life silently
    absent), and `OFFSET 0` is an optimisation FENCE — without it the planner
    flattens the LATERAL and hash-joins the table (71 ms). **Logged not buried:**
    at the widest legal window (365 days) the new shape is ~9% SLOWER.
  - **B (SOUND):** a CVE that is KEV-added then withdrawn does produce two
    matches and two claims on one doc id, and the pairing stays one-to-one —
    the LATERAL matches `satisfied_change_kind` too. No change made.
  - **C (real, small, fixed by construction):** `created_at` is
    `clock_timestamp()` in Postgres, `now` defaulted to the app process. Measured:
    a 2-day skew moves a 365-day verdict by 0.005 half-lives and no band moves.
    `timeline.store.reader_now()` — the clock that stamps a row now ages it.
  - **D (DEFECT, exactly as suspected):** 3 restarts, every cycle failing,
    `degraded=False` and `trustworthy=True` throughout, because the counter resets
    before `DEGRADED_AFTER`; and a fresh process vouched for the quiet having
    checked nothing. **The obvious fix does not work** — requiring
    `ever_succeeded` would false-alarm every quiet week, because every `emit()` is
    guarded on a non-empty doc list and nothing in the system meant "a cycle ran".
    Now `IngestScheduler` counts completed cycles, and `trustworthy` requires both
    a success somewhere and no checker whose only evidence is failure. TD-021's
    "trade" turned out to be a false choice.
  - **E (DEFECT, not on the list, found while measuring A):** a 365-day window
    finds **32,930** decayed verdicts, returns 50, and said nothing — and the page
    rendered the arrival count as the total. Lists are now fetched at `limit + 1`
    and the payload carries `limit`/`complete`/`truncated`; the page states cut
    counts as "at least N".
- **S17 feature — Actions SDK contract (DONE, ratified D-023).**
  `auspex/actions/` = `types.py` (the contract + its validation), `decorator.py`
  (`@action`), `registry.py` (registration + planner manifest). Everything through
  S16 READS; this is what lets the co-analyst ACT, and **the contract is the whole
  deliverable — nothing executes, against a real system or otherwise.**
  1. **The declaration is the source of truth (D-007).** One `@action` compiles to
     the wire schema, the planner directive and the approval summary — the S9
     `ModeContract` relationship applied to acting. `planner_description` is
     generated, so an action cannot describe itself as safe while declaring itself
     destructive.
  2. **Destructive ⇒ undo is unrepresentable otherwise.** `ActionSpec` cannot be
     CONSTRUCTED without it (ImportError at the moment someone writes it), and the
     registry re-runs the same validation so the decorator is not the only door.
     Also refused: `dry_run` that is `execute`; an undo that is the action; an undo
     restoring nothing; a READ action whose scope writes (the gate reads risk, so
     that one would auto-execute); an action naming no system.
  3. **Risk IS `ToolLevel`** — the same enum the D-014 gate already reads, not a
     parallel vocabulary that could become a second opinion about approval.
  4. **An undo names what it CANNOT restore**, and such an action reports itself
     as not reversible. An undo that silently fails is worse than none, because
     the approval it unlocked was granted on its strength.
  5. **The manifest reuses the S13 capability decision:** native_tools → wire
     specs, prompted_tools → the same specs as prose, plan_only → names only. The
     modes differ in how an action is DESCRIBED, never in whether approval is
     required.
  6. **The loop is TOLD about actions and given no way to call one.** Dispatch is
     the proposal round-trip S18 owns; a callable name resolving to "unknown tool"
     would invite the model to believe it acted. Pinned: a model that calls one
     anyway gets an error, never an execution.
- **One check exists because the contract was RUN, not read** (probe:
  docs/probes/2026-08-11-s17-actions-contract-live.md). `dry_run is execute` sees
  one spec at a time, so `dry_run=some_other_action` slipped past and would have
  really performed that other action while reporting itself as a preview. The
  registry sees every spec and refuses it in both orders. **Third session running
  where executing found what reading had not** (S15 sink order, S16 the permanent
  silent link loss, now this).
- **CI-green: 772 tests** (720 at S16 end → +36 Step-0 regressions, +32 contract,
  +4 loop integration). `./ci.sh` green including the installed-dist gate
  (**110 modules**, was 106); `/api/health/ready` 200.
- **Zero new env vars** this session (and none across S14–S17).
- **LLM untouched by S17** — a decorator and a registry are code.

## In-flight / standing follow-ups (carry forward until DONE)
1. **PR #16 MERGED** (2026-08-11, squash `ed0443b`) — the Step-0 review fixes,
   back-merged into staging (`0fc6e58`) with the tree asserted unchanged.
   **`839d574` (the Actions SDK) is on staging and NOT yet promoted** — it is the
   only thing in `origin/main..staging`. Next session's `/promote` carries it.
2. **S18 Step 0: fresh-eyes review of the S17 commits** (`e57ab0c`, `839d574`).
   Angles S17 did NOT adversarially test:
   - **(the rewrite's blind spot — strongest lead) `_DECAYED_SQL` now depends on a
     recursive loose-index-scan** to enumerate a workspace's half-lives. It was
     measured on a workspace with THREE. What happens with 50 (every observable
     type plus S7 floors plus a future per-source half-life)? The bounds set is
     `edges × half-lives`, so the LATERAL count grows multiplicatively and each is
     an index descent. Seed a workspace with many distinct `half_life_days` values
     and EXPLAIN. Also: the 365-day regression is recorded but not BOUNDED — find
     where the crossover actually is.
   - **(the fence) `OFFSET 0` is load-bearing and invisible.** Nothing fails if a
     future reader deletes it as dead syntax — the query still returns correct
     rows, 15× slower. The plan test asserts the index is used; verify it actually
     FAILS with the fence removed, and if not, make it.
   - **(the new trustworthy rule) four clauses now decide it.** Verify the matrix
     by execution, especially: a degraded checker alongside a healthy
     `ingest-cycle` (does the cycle counter mask a dead consumer?), and a workspace
     whose ingest is DISABLED (empty roster vs a roster of never-run counters).
   - **(the contract's own rails) every refusal in `validate_spec` is a claim
     about what cannot be built.** Try to construct a legal-looking destructive
     action that reaches `planner_description` with no undo, or an action whose
     `wire_spec` names parameters its `required` list disagrees with. The
     `object.__setattr__` forge in the tests proves one door; look for others.
   Verify findings BY EXECUTION before fixing; fix with regressions.
3. **TD-005 re-battery trigger (standing, NOT tripped, CLOSE):** corpus > 30k
   chunks, ANY new doc_type, or embedding-model change → re-run the labeled
   battery. S17 added no doc_type and no model change. Corpus **27,475 docs** at
   S17 end (27,460 at S17 start — the container was mostly rebuilding, so almost
   no growth this session). ~2,525 short of the line. Check it at Step 0.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat. Open: TD-012 (post-hoc validation, incl. the citation guard),
   TD-014 (unbounded history), TD-015 (brand/confusable coverage), TD-016 (ACH
   surface bounds), TD-017 (chat-side NUL hardening), TD-018 (no per-workspace
   bound on the NUMBER of inference calls), TD-019 (retro-hunt v1 bounds),
   TD-020 (watcher v1 bounds — expiry half ANSWERED by D-022), TD-021 (timeline
   v1 bounds — the uncosted query and the `ever_succeeded` trade are now
   RESOLVED), TD-022 (a checker that dies after succeeding once still reads
   healthy — needs a durable heartbeat), TD-023 (Actions SDK v1 bounds).
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
4. **Corpus ~27.5k docs** while the container runs. TD-011 tracks the rollover
   trigger; TD-005's 30k line is close.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via
  `auspex.devhost` (ENRICHMENT/KB/INGEST disabled on host).
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- **`gh` did NOT flip at S17 start** (active = `bh3082336888-cell`), but it DID at
  S16 start and did not at S13/S14/S15. The pattern is "unpredictable", which is
  why D-011 says re-check before EVERY `gh` call rather than once per session.
- **`gh pr merge` works** — re-verified at S17 (PR #16 merged by Claude, first
  try). `gh pr edit` still fails on this repo with a Projects-classic GraphQL
  deprecation error — use `gh api -X PATCH repos/.../pulls/N`.
- **This repo has NO GitHub Actions** — `gh pr checks` reports 0 checks, so
  `./ci.sh` locally IS the gate. Do not wait on remote CI that does not exist.
- **Local `main` ref goes stale every promote.** `/promote` and any `main..staging`
  diff must `git fetch origin` and compare against `origin/main`, and the commit
  LIST is meaningless after a squash — read `git diff origin/main..staging --stat`.
- **Probe residue is expensive to leave behind.** A 100k-row seeded workspace left
  in the dev DB made the timeline plan tests take **150 s instead of 21 s**, purely
  through VACUUM cost. Delete seeded workspaces before running the suite.
- **Plan assertions on this dev DB must VACUUM first** — bloat, not the query,
  decides the plan. **Small tables legitimately seq-scan**; assert plans only at
  sizes where a scan would cost something (the suites seed 25k).
- **Data-modifying CTEs cannot see each other's rows through a table scan** —
  chain `INSERT ... RETURNING`; re-reading the table silently seeds zero rows.
- **S17 demo (zero-LLM, ~30 s):**
  1. `docker compose exec -T --workdir /tmp app python` — the script in
     docs/probes/2026-08-11-s17-actions-contract-live.md. A destructive action with
     no undo is REFUSED at declaration; the same action with an undo registers and
     requires approval; the planner text is compiled from the spec; a weak endpoint
     gets nothing on the wire; the capability row shows `reversible: False` for an
     undo that named what it cannot restore.
  2. Timeline half (S16 + the S17 fixes): open `localhost:8000/timeline` → sign in
     → the digest now states its page size and what it cut, and a quiet week says
     whether the silence can be believed.
- **S16/S15/S14/S13/S12–S8 demo turns** unchanged (see git history of this file).

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
Start with `/promote` — **`839d574` (the Actions SDK) is on staging and not yet on
`main`**, and it is the only unpromoted commit. Then S18 Step 0: fresh-eyes review
of the S17 commits (see In-flight 2 — the loose-index-scan's behaviour at many
half-lives is the strongest lead, and the invisible `OFFSET 0` fence is the
cheapest real risk). Check the TD-005 30k trigger at start. Then S18 per ROADMAP:
**Approval flow** — approval cards over SSE, atomic claim-first settlement,
permission re-check at execute time. This is where the S17 contract stops being a
contract, so TD-023's items (scope declared-but-not-enforced, spec identity across
time) come due. NEXT-SESSION.md has the full prompt.
