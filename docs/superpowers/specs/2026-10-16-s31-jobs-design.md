# S31 — The jobs queue and TD-025's first half, the design S31 builds

_Written 2026-10-16 in S31 (backend). D-065 (the queue) and D-066 (TD-025's
order) and the phase's spec
(docs/superpowers/specs/2026-10-15-integration-phase-design.md, sections D-065
and D-066) are the contract; this addendum answers the questions they left to
S31, each put to Burhan one at a time and answered by him, and records the
design he approved section by section. Reality it stands on:
docs/probes/2026-10-16-s31-jobs-baseline.md._

## Burhan's calls (S31)

| # | Question | Answer |
|---|---|---|
| 1 | How long a proposal waits for a decision | **24 hours** (`PROPOSAL_TTL_SECONDS = 86400`, a code constant, D-026). Approve and reject refuse an overdue proposal in the same UPDATE; the sweep only makes the status visible. |
| 2 | Where an expired proposal shows | **Listed for 24 h after it expires, then gone.** The approvals list and a reopened chat turn both read "Expired: nobody decided in time; propose it again", with no doors. |
| 3 | What the idempotency key identifies | **One key per operation, stable across retries**: one for "execute proposal P", one for "undo proposal P". The built-in note action uses it (one note per key). |
| 4 | Lease, retries, backoff | **Per kind, with defaults**: each job kind declares its lease and max attempts in code (default 60 s, 5). Backoff 30 s doubling, capped at 15 min; then `dead`. No lease extension until S33. An expired lease counts as an attempt. |
| 5 | What the queue runs in S31 | **The proposal-expiry sweep as a real job**, enqueued per workspace by a code-declared schedule. |

## 1. The `jobs` table and the claim

**Package.** `auspex/jobs/` (new: `pyproject.toml` packages and the
Dockerfile skeleton).

**`jobs`** (every row in one workspace, D-008):

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `workspace_id` | uuid NOT NULL | FK `workspaces` ON DELETE CASCADE |
| `kind` | text NOT NULL | a code-declared kind |
| `integration_id` | uuid NULL | no FK until S33's `integrations` exists; NULL for in-app kinds |
| `payload` | jsonb NOT NULL DEFAULT `'{}'` | |
| `idempotency_key` | text NOT NULL | **UNIQUE `(workspace_id, idempotency_key)`** |
| `status` | text NOT NULL DEFAULT `'queued'` | CHECK `queued, claimed, done, failed, dead` (one block, edited in place, like proposals) |
| `attempts` | int NOT NULL DEFAULT 0 | incremented by each claim |
| `max_attempts`, `lease_seconds` | int NOT NULL | copied from the kind at enqueue, so the claim needs no code lookup |
| `run_after` | timestamptz NOT NULL DEFAULT now() | backoff moves it |
| `lease_expires_at` | timestamptz | set by a claim |
| `claim_token` | uuid | minted by each claim, cleared by each finish |
| `claimed_by` | text | the claimer's name (the in-app worker; S33: an agent) |
| `result` | jsonb | what `complete` stored |
| `last_error` | text | the last failure's type and message, capped |
| `created_at`, `finished_at` | timestamptz | |

Indexes: the unique key; `(status, run_after)` for the ready scan;
`(workspace_id, status)`.

**`job_turns(workspace_id PK, last_served_at)`**: whose turn it was. Also
workspace-scoped (FK, cascade).

**Enqueue.** `enqueue(pool, workspace_id, kind: JobKind, idempotency_key,
payload, integration_id=None, run_after=None) -> (job, created)` takes the
kind itself (its name, lease and max attempts go on the row) and is `INSERT … ON
CONFLICT (workspace_id, idempotency_key) DO NOTHING`, and on a conflict
returns the existing row with `created=False`. A key stays taken for the life
of its row, `done` and `dead` included.

**The claim.** `claim(pool, scope, claimer) -> ClaimedJob | None`, in one
transaction:
1. Leases that expired with no attempts left go `dead`
   (`last_error = 'lease expired'`), inside the scope.
2. One statement picks and claims. Ready means `status = 'queued' AND
   run_after <= now()`, or `status = 'claimed' AND lease_expires_at < now()
   AND attempts < max_attempts`. Candidates are ordered by
   `job_turns.last_served_at NULLS FIRST, run_after, id`, taken with
   `LIMIT 1 FOR UPDATE OF j SKIP LOCKED`, and updated: `status = 'claimed'`,
   a fresh `claim_token`, `claimed_by`, `attempts + 1`, `lease_expires_at =
   now() + lease_seconds`.
3. `job_turns` for that workspace is upserted to `now()`.

Serving the least-recently-served workspace first is round-robin across
workspaces. A one-pass "oldest job first" order would let a client that
bulk-enqueued earlier starve every other until it drained.

**The scope.** `ClaimScope(kinds, workspace_ids=None, integration_ids=None)`:
- `kinds` is required and non-empty; a claimer names what it can run.
- `workspace_ids=None`: every workspace (the in-app worker). S33's Edge Agent
  passes its one workspace.
- `integration_ids=None`: **only jobs bound to no integration**. A set: only
  jobs bound to one of those integrations. Nobody claims an integration's job
  without naming the integration.

S33 calls the same function behind its HTTP route, with the agent's scope
built from its credential, never from the request.

**Finishing, token-checked.** Both match `status = 'claimed' AND claim_token
= $token`; a claimer that no longer holds the job is refused (`JobLost`),
whether its lease was re-claimed or the job went `dead`.
- `complete(pool, job_id, token, result)` → `done`, `result`,
  `finished_at`; the token, lease and claimer are cleared.
- `fail(pool, job_id, token, error, permanent=False)` → with attempts left:
  `queued`, `run_after = now() + min(30 · 2^(attempts−1), 900)` s; with none
  left: `dead`; `permanent=True`: `failed`. `last_error` records it.

A completion that arrives after the lease expired but before anyone
re-claimed is accepted: the token still holds the row.

## 2. Kinds, schedules, the worker, and the expiry job

**Kinds are code.** `JobKind(name, handler, lease_seconds=60,
max_attempts=5)`, declared beside the handler; `handler(pool, job) -> dict`
(the result). **A handler must be idempotent on `job.idempotency_key`**: an
expired lease means it can run again, which is why D-065 has a lease. A
claimed row whose kind the worker does not know fails permanently.

**Schedules are code.** `Schedule(kind, every_seconds,
due_workspaces(pool) -> list[UUID])`. When a schedule is due, each workspace it
names gets one job keyed `<kind>:<bucket>`, where `bucket = floor(epoch /
every_seconds)`. Two ticks, or two app replicas, in one bucket enqueue once.

**`JobWorker`** (`auspex/jobs/worker.py`), in the ingest scheduler's shape:
injected `now` and `sleep`; `tick()` is the testable unit; `run()` loops
forever, re-raises `CancelledError`, logs and survives anything else. Each
tick:
1. runs the due schedules;
2. claims and runs jobs (scope: its kinds, every workspace, no integration)
   until none is ready, at most 50 per tick;
3. the loop then sleeps `POLL_SECONDS = 5`.

A handler that raises gets `fail`; one that returns gets `complete`; a
`JobLost` is logged, never raised.

**In the lifespan.** Started beside the ingest task after the action registry
exists (`auspex/app.py`), cancelled and awaited in the same `finally`, before
the pool closes. A job cut off by shutdown keeps its claim until its lease
expires and is then re-claimed.

**`JOBS_WORKER_ENABLED`** (default `true`), born with `.env.example` and
`docs/ENV_VARS.md`. `pin_host_defaults` sets it `false`, as it does
`INGEST_ENABLED`, so the suite stays hermetic and no background claimer races
a test. Tests drive `tick()` directly.

**The first kind, `proposals.expire`** (`auspex/actions/expiry.py`):
- **Its schedule:** every 300 s, the workspaces holding a `pending_approval`
  proposal created at or before `now() - PROPOSAL_TTL_SECONDS`. That one read
  across workspaces is system code choosing whom to enqueue for, like
  retro-hunt's sinks; it reads ids only.
- **The job:** one `UPDATE proposals SET status = 'expired', resolved_at =
  now() WHERE workspace_id = $job.workspace AND status = 'pending_approval'
  AND created_at <= now() - TTL`. Scoped to its own workspace; a retry
  changes nothing twice. Result: `{"expired": <count>}`.
- Lease 60 s, 5 attempts (the defaults).

## 3. TTL enforcement, `expired`, and the idempotency key

**The guarantee is in the WHERE, not the sweep.**
- `ProposalSettlement.settle` (approve and reject) gains `AND created_at >
  now() - make_interval(secs => TTL)`.
- On a loss, its after-the-fact read says which. A row still
  `pending_approval` but overdue is moved to `expired` there, by the same
  conditional UPDATE the job runs (idempotent with it), and `settle` returns
  a new `Settlement.EXPIRED`. A row already `expired` returns it too.
- The routes answer **409, "expired: nobody decided within 24 h; propose it
  again"**, for approve and reject alike.

So an approval one second past the TTL is refused whether or not the sweep has
run.

**`expired`**:
- Joins the ONE `proposals_status_check` block, edited in place
  (`auspex/migrations.py:489-499`);
  `test_startup_survives_every_status_a_proposal_can_be_in` gains it.
- `resolved_at` = when it expired; `resolved_by` stays NULL (the system).
- Terminal. Every other door's WHERE names the statuses it moves from (probe
  §2), so none moves an expired row; the tests prove approve, reject,
  execute, withdraw, run-now and undo each refuse one.
- `pending()` adds `OR (p.status = 'expired' AND p.resolved_at > now() -
  TTL)`: listed for 24 h after it expires.

**The page** (a small front-end touch in this backend session):
- `statusText`: "Expired: nobody decided in time; propose it again". No hour
  count on the page, so the TTL lives only in the backend.
- `undoLineFor` treats `expired` like `rejected` (no undo line).
- `doorsFor` already returns no doors for an unknown status; a Node test pins
  `expired` there.

**The idempotency key** is derived, not stored:
`operation_key(proposal_id, op)` in `auspex/actions/settlement.py` returns
`proposal:<id>:execute` or `proposal:<id>:undo`.
- `execute` receives the execute key (both doors: approve's run and D-048's
  run-now); every `undo` attempt receives the undo key; `observe` (via
  `_effects`, after a raising execute) receives the execute key, because it
  looks for the execute's effects.
- A re-run, a stale-approval run, or (S34) a re-claimed execute job carries
  the same key. S34's execute job uses it as the job's `idempotency_key`.
- `validate_spec` refuses an action whose `execute`, undo handler or `observe`
  cannot take an `idempotency_key` keyword (a parameter of that name, or
  `**kwargs`). An S32 connector fails at registration, not at run time.
- `dry_run` is not an execution attempt and gets no key.

**The built-in note action uses it.**
- `observable_notes` gains `idempotency_key text` and a unique index on
  `(workspace_id, idempotency_key)` where it is not NULL; existing rows stay
  NULL.
- `run` inserts with `ON CONFLICT DO NOTHING`; the same key twice leaves one
  note, and the second call's outcome says the note was already there.
- `put_back` deletes by `proposal_id` as now, which is idempotent already.

## 4. Testing, review and scope

**The queue** (`tests/test_jobs_*.py`, live Postgres, `t-s31-…` prefixes,
cleaned):
- **Race.** Two claimers, one job, concurrent on separate connections:
  exactly one claim. Twenty jobs, four concurrent claimers: every job claimed
  exactly once.
- **Fairness.** Workspace A enqueues 50 jobs, then B enqueues one; B is served
  within the first two claims, and claims alternate while both have work.
- **Lease.** An expired lease is re-claimed with a new token; the old token's
  `complete` and `fail` are refused; an expired lease with no attempts left
  goes `dead`.
- **Retry.** The backoff schedule (30, 60, 120 … capped at 900 s); `dead` at
  the cap; `failed` on a permanent failure; an unknown kind fails
  permanently.
- **Enqueue.** The same key twice is one row; the same key in two workspaces
  is two.
- **Cross-tenant.** A scope naming workspace A never claims B's job;
  `integration_ids=None` never claims an integration's job; a set claims only
  its own. `jobs` and `job_turns` pass `tests/test_schema.py`'s workspace rule.
- **Worker.** `tick()` runs schedules, then jobs; a raising handler is
  failed and the tick goes on; a bucket enqueues once. With the gate on, the
  lifespan starts the worker and shutdown cancels it.

**Proposals:**
- Approve and reject at TTL + 1 s are refused (409) and the row is `expired`,
  with no sweep; at TTL − 1 s they still work.
- The expiry job expires only its own workspace's overdue rows; its schedule
  names only workspaces that have one.
- `pending()` lists an expired row within 24 h of expiring, not after.
- Startup survives a row in `expired`.
- A spy action proves `execute`, `undo` and `observe` each receive the
  operation's key, on both run doors.
- `validate_spec` refuses a handler that cannot take the keyword.
- The note action run twice with one key leaves one note.
- Node tests for the page text, the undo line and the doors.

**Proof beyond the tests.**
- Mutants on every guard: the TTL clause, the lazy expiry, the token match,
  the fairness order, each scope filter, the unique key, the dead cap, the
  key handed to each handler.
- The full gate.
- **Live**, against the rebuilt container with the worker on: a proposal aged
  by SQL expires through the real job; the job row is read; both are cleaned
  up. Recorded in `docs/probes/`.
- **A fresh-agent adversarial review of the approvals state machine and the
  queue** (SESSION-RULES.md), then a review of its fixes.

**Debt to log:** pruning old `done`/`dead` job rows; lease extension (S33's
heartbeats); no `LISTEN/NOTIFY` (D-065's stated bound).

**Out of scope (S32 and later):** connectors and their job kinds, the edge
API and agent claims over HTTP (S33 reuses `claim` as is), the per-workspace
catalogue (TD-023), grant-checked scope.
