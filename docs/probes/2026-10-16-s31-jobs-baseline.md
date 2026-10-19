# 2026-10-16 — S31 Step 0: the approvals state machine and background work, as they stand

Reality snapshot before the jobs queue and TD-025's first half (D-065, D-066).
Code cited at `0c86c1b` plus the uncommitted D-069 build (only `auspex/app.py`
moved, by 9 lines, above the lifespan's tasks). Live schema read from the dev
Postgres with `\d proposals`.

## 1. `proposals`, live

21 columns: `id`, `workspace_id` (NOT NULL, FK workspaces ON DELETE CASCADE),
`session_id`, `tool_name`, `tool_level` (`write|destructive`), `tool_input`
(jsonb NOT NULL), `status` (default `pending_approval`), `created_at`,
`decided_at`, `decided_by`, `result`, `spec_fingerprint`, `card`,
`undo_result`, `undone_at`, `claimed_at`, `abandoned_from`
(`executing|undoing`), `claim_token`, `abandoned_token`, `resolved_by`,
`resolved_at`.

Indexes: `idx_proposals_ws_status (workspace_id, status, created_at DESC)`,
`idx_proposals_ws_claimed (workspace_id, claimed_at) WHERE claimed_at IS NOT
NULL`, `idx_proposals_ws_id_status`, `idx_proposals_pending_twins
(workspace_id, tool_name, md5(tool_input::text)) WHERE status =
'pending_approval'`.

**The one status CHECK** (`auspex/migrations.py:489-499`, a `DO $$` block that
drops and re-adds `proposals_status_check`; the comment above it says new
statuses go HERE, in place): `pending_approval, approved, rejected, executing,
executed, failed, incomplete, kept, undoing, undone, abandoned, withdrawn` —
12 statuses. Pinned by `tests/test_schema.py:229`
(`test_startup_survives_every_status_a_proposal_can_be_in`).

Live rows at the probe: none (the suite clears its own; the dev database holds
no proposals).

**Nothing expires.** No column records a deadline, and no query compares
`created_at` with now except the stale-claim and stale-approval windows below.

## 2. Every claim and finish path (`auspex/actions/settlement.py`)

`STALE_CLAIM_SECONDS = 300` (`:64`). `UNDOABLE_FROM = executed, incomplete,
kept, abandoned` (`:68`). Every transition is one conditional `UPDATE …
RETURNING`; the loser re-reads to say why.

| Door | Lines | From → to | Guard in the WHERE |
|---|---|---|---|
| `settle` (approve / reject) | `:370-411`, UPDATE `:388-401` | `pending_approval` → `approved`/`rejected`; `decided_at/by` | `status = 'pending_approval'` |
| `execute` claim | `:533-570`, UPDATE `:552-561` | `approved` → `executing`; `claimed_at = now()`, `claim_token = gen_random_uuid()` | `status = 'approved'` (after `check_executable`, `:455-517`) |
| `run_stale_approval` claim (D-048) | `:572-648`, UPDATE `:613-627` | `approved` → `executing`, plus `resolved_at/by` | `status = 'approved' AND claimed_at IS NULL AND decided_at` older than 300 s |
| `_run_claimed` | `:650-683` | runs `spec.execute`; raise → `_effects` → `failed` (effects `none`) or `incomplete` | — |
| `_finish_claim` | `:685-773` | `executing` → `executed/failed/incomplete`; `undoing` → `undone` or back to where it started | `status = $from AND claim_token = $token`; a lost claim's late answer lands only on the row whose `abandoned_token` matches, only into an empty column (`:759-772`) |
| `undo` claim | `:775-895`, UPDATE `:833-844` | the read status (`UNDOABLE_FROM`, or a legacy `failed`) → `undoing`, fresh token, `undo_result = NULL` | `status = $was` |
| `abandon` | `:237-292`, UPDATE `:268-284` | `executing`/`undoing` → `abandoned`; `abandoned_from = status`, `abandoned_token = claim_token` | `claimed_at` older than 300 s |
| `keep` | `:294-329`, UPDATE `:311-321` | `incomplete` → `kept` | `status = 'incomplete'` |
| `withdraw` (D-048) | `:331-368`, UPDATE `:347-360` | `approved` → `withdrawn` | unclaimed, `decided_at` older than 300 s |
| `pending()` (the approvals list) | `:167-235`, query `:206-234` | read | `pending_approval`, `incomplete`, any claim older than 300 s, an unclaimed approval older than 300 s |

The routes (`auspex/routes/proposals.py`): `approve` settles then runs
`execute` in the same request (`:323-370`); `execute` is D-048's run-now door
(`:395`); `undo` (`:440`); `reject`, `abandon`, `keep`, `withdraw`; `GET ""`
and `GET /stream` read `pending()`.

The page (`auspex/static/js/page-logic.js`): `doorsFor` (`:188-212`) and
`statusText` (`:221-240`) switch on the status; an unknown status gets no doors
and is shown as its raw word (`default: return p.status`).

## 3. What an execution attempt hands the handlers today

- `execute`: `spec.execute(workspace_id=…, proposal_id=str(proposal_id),
  **tool_input)` (`settlement.py:658-660`).
- `undo`: `spec.undo.handler(workspace_id=…, proposal_id=str(proposal_id),
  **tool_input)` (`:873-875`).
- `observe`: `spec.observe(workspace_id=…, proposal_id=str(proposal_id),
  **tool_input)` (`:907-909`), via `_effects`, only after a raising execute.

**No attempt identity and no idempotency key.** The claim token is not handed
to any handler. The only per-operation identity a handler sees is
`proposal_id`, the same for the execute and for every undo of that proposal.

The one built-in action, `annotate_observable` (`auspex/actions/builtin.py`),
keys its effects on `proposal_id`: `run` inserts into `observable_notes` with
it (`:124-139`), `put_back` deletes by it (`:148-163`), `count_mine` counts by
it (`:173-182`). **`observable_notes` has no uniqueness on `proposal_id`**
(`migrations.py:576-589`): only the proposal's claim stops a second note today.
A handler run twice for one approval would write twice.

## 4. Background work in the lifespan (`auspex/app.py`)

- `app.state.ingest_task = asyncio.create_task(app.state.ingest.run())`
  (`:81`); the autoprobe task (`:87`) when `LLM_AUTOPROBE_ENABLED` and an
  endpoint is set.
- Both cancelled in the lifespan's `finally` (`:92-103`), each awaited with
  `CancelledError` suppressed, before the pool closes.
- `IngestScheduler.run` (`auspex/ingest/scheduler.py:174-191`): `while True`,
  one `run_cycle()`, `CancelledError` re-raised, any other exception logged and
  survived, then an injected `sleep(interval)`; `now` and `sleep` are injected
  for tests (`:105-106`); `enabled` comes from settings, and host/test runs pin
  `INGEST_ENABLED=false` (hermetic).
- **No jobs table, no worker, no `FOR UPDATE SKIP LOCKED` anywhere** in
  `auspex/` (grep).

## 5. The cursor pattern, `ingest_state`

`auspex/migrations.py:173-187`: `id`, `workspace_id` (nullable: a global feed
has none), `feed`, `cursor jsonb DEFAULT '{}'`, `last_run_at`, `last_status`,
`docs_upserted`, `updated_at`; one row per global feed
(`idx_ingest_state_global_feed (feed) WHERE workspace_id IS NULL`). Live: 3
rows, all global (`nvd-delta`, `attack-enterprise`, `kev`), each cursor a JSON
object. S35's per-integration cursor follows this shape; S31 needs none.

## What this means for S31

- An `expired` status joins the twelve in the one block at `:489-499`, and
  every door's WHERE above already excludes it (each names the statuses it
  moves from), so an expired row is closed to approve, reject, execute and the
  stale doors without touching them. `pending()` lists it only if its query is
  changed to. The page shows it as a raw word with no doors until
  `statusText` learns it.
- The idempotency key has nowhere to come from today; the handler signature
  takes keyword arguments, so a new keyword reaches every handler (the
  built-in's `**_` swallows unknown ones).
