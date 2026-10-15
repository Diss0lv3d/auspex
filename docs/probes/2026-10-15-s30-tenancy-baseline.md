# S30 Step 0 — the tenancy baseline (2026-10-15)

_Reality before S30 builds D-061. Probed read-only against the dev database
(compose `postgres`, `psql -U auspex -d auspex`) and the working tree at
`4db7c51` (`staging`). No emails, names or tenant data are recorded: counts
only, plus the three system workspace names._

## 1. The live schema

### `workspaces`

| column | type | null | default |
|---|---|---|---|
| id | uuid | not null | `gen_random_uuid()` |
| name | text | not null | |
| created_at | timestamptz | not null | `now()` |
| plan | text | not null | `'free'` (S19, `auspex/migrations.py:599`) |

- `workspaces_pkey` (id); `idx_workspaces_name` UNIQUE (name).
- Referenced by `workspace_id` (all `ON DELETE CASCADE`) from 17 tables:
  ach_evidence, api_keys, chat_sessions, hypotheses, ingest_state,
  investigations, llm_endpoint_scorecards, messages, observable_notes,
  observables, proposals, retrohunt_matches, turn_spend, usage_counters,
  users, verdict_flips, verdicts, watchers.
- No `org_id`, no `region`.

### `users`

| column | type | null | default |
|---|---|---|---|
| id | uuid | not null | `gen_random_uuid()` |
| workspace_id | uuid | not null | FK workspaces, CASCADE |
| email | text | not null | |
| display_name | text | not null | `''` |
| google_sub | text | null | |
| role | text | not null | `'analyst'` (never read: §4) |
| created_at | timestamptz | not null | `now()` |

- `users_pkey` (id); `idx_users_workspace` (workspace_id);
  `users_workspace_id_email_key` UNIQUE (workspace_id, email). **Email is not
  unique across the deployment, and not case-folded.**

### `api_keys`

| column | type | null | default |
|---|---|---|---|
| id | uuid | not null | `gen_random_uuid()` |
| workspace_id | uuid | not null | FK workspaces, CASCADE |
| user_id | uuid | not null | FK users, CASCADE |
| name | text | not null | `''` |
| key_prefix | text | not null | |
| key_hash | text | not null | UNIQUE |
| created_at | timestamptz | not null | `now()` |
| last_used_at | timestamptz | null | |
| revoked_at | timestamptz | null | |

### Every column that references `users(id)`

| column | on delete |
|---|---|
| `api_keys.user_id` | CASCADE |
| `chat_sessions.user_id` | CASCADE |
| `proposals.decided_by` | SET NULL |
| `proposals.resolved_by` | SET NULL |

Migrating a user row in place (keeping its `id`) keeps all four valid; nothing
else points at a user.

### `workspace_id` across the schema

Every public table has a `workspace_id` column except `workspaces`. All are
`NOT NULL` except `ingest_state.workspace_id` (NULL = a global feed, S7,
`auspex/migrations.py:173`). `tests/test_schema.py:30` exempts only
`workspaces`, and checks the column's existence, not its nullability
(`:47`).

## 2. Row counts the migration must carry

| what | count |
|---|---|
| workspaces | 3: `__deployment__`, `default`, `dev` (no others; all plan `free`) |
| users | 13, **all in `default`** |
| distinct emails / distinct case-folded emails | 13 / 13 |
| emails present in more than one workspace | **0** (max workspaces per email: 1) |
| distinct email domains | 6 |
| `users.role` values | `analyst` × 13 |
| users with `google_sub` | 0 |
| api_keys | 0 (0 revoked) |
| api_keys whose workspace differs from its user's | 0 |
| chat_sessions | 84 (0 whose workspace differs from its user's) |
| proposals | 1 (`decided_by` set: 0; `resolved_by` set: 0) |

So on this database the same-email-in-two-workspaces case does not occur. The
suite creates and deletes its own workspaces and users (§5), so the migration
must still handle it for any deployment where it does.

## 3. Routes, by `file:line`

Every authenticated route depends on `resolve_user` (`auspex/auth.py:80`)
through a module-level `Auth = Annotated[AuthContext, Depends(resolve_user)]`.

| module | `Auth` alias | routes (decorator line) |
|---|---|---|
| `auspex/routes/auth.py` | `:27` | `POST /api/auth/api-keys` `:123` (JWT only), `GET /api/auth/whoami` `:147` |
| `auspex/routes/chat.py` | `:97` | `GET /api/usage` `:529`, `GET /api/chat/sessions/{id}/spend` `:541`, `GET /api/chat/sessions` `:569`, `GET /api/chat/sessions/{id}/turns` `:619`, `GET /api/models` `:649`, `POST /api/chat` `:674`; also `get_endpoint_resolver` `:298` takes `auth` |
| `auspex/routes/investigations.py` | `:67` | `POST ""` `:252`, `GET /{id}` `:303`, `POST /{id}/lookups` `:315`, `POST /{id}/summary` `:427` |
| `auspex/routes/proposals.py` | `:61` | `GET ""` `:159`, `GET /stream` `:174`, `GET /{id}` `:233`, `POST /{id}/reject` `:243`, `/abandon` `:261`, `/keep` `:292`, `/approve` `:314`, `/execute` `:386`, `/withdraw` `:409`, `/undo` `:431` |
| `auspex/routes/retrohunt.py` | `:35` | `GET /matches` `:70`, `POST /matches/{id}/ack` `:97`, `GET /flips` `:113` |
| `auspex/routes/watchers.py` | `:36` | `GET ""` `:50` |
| `auspex/routes/timeline.py` | `:43` | `GET /digest` `:236`, `GET /{obs_id}` `:269` |

Unauthenticated: `GET /api/auth/google/login` `:46`, `GET /api/auth/google/callback`
`:62` (503 until Google is configured; TD-001 gate), `POST /api/auth/dev-login`
`:107` (404 unless `APP_ENV=dev`), `/api/health` and `/api/health/ready`
(`health.py:16,22`), and the static pages (`ui.py:60,68,79,84`).

**No route reads a workspace or tenant id from input.** Every route takes it
from `auth.workspace_id`. The request bodies (`DevLoginBody` `auth.py:102`,
`ApiKeyBody` `:119`, `ChatBody` `chat.py:213`, `CreateInvestigationBody`
`investigations.py:70`, `RunLookupBody` `:76`) carry no workspace, tenant or
organization field.

**No route reads `users.role`.** No admin route exists yet.

### How a request becomes a workspace today

- `issue_jwt` (`auth.py:48`) writes one `wid`; `decode_jwt` (`:60`) requires
  it.
- `resolve_user` with a JWT (`:86-99`) selects the user `WHERE id = sub AND
  workspace_id = wid`: the user row's own workspace is the membership check.
  With an API key (`:101-116`) the key row's `workspace_id` is used as is.
- `get_or_create_user` (`:124`) is called from exactly two places, both in
  `auspex/routes/auth.py`: the Google callback (`:93`) and dev-login (`:113`).
  Both pass no workspace, so every sign-in lands in `default`. It refuses
  `__deployment__` (`:132`, D-035).

## 4. Where the engine and third parties are reached (the region guard's surface)

Engine turns from a workspace's request:
- `POST /api/chat` (`chat.py:674`), its endpoint from `get_endpoint_resolver`
  (`:298`, `LLMClient.from_settings` `:323`).
- `POST /api/investigations/{id}/summary` (`investigations.py:427`), via
  `get_summary_client_factory` (`:410`).

Deployment-level, not a workspace's turn: the startup autoprobe
(`auspex/llm/autoprobe.py`, `app.py` lifespan) and `scripts/llm_harness.py`.

Third-party enrichment (`EnrichmentService.enrich`, fanned out per provider in
`auspex/enrich/fanout.py:65`) is entered from three places:
- the chat IOC shortcut, `chat.py:747`;
- an investigation lookup, `investigations.py:358`;
- the agent's lookup tool, `auspex/agent/capabilities.py:319`.

Seven providers, all subclasses of `Provider` (`auspex/enrich/providers/base.py:24`):
AbuseIPDB, ThreatFox, OTX, InternetDB, CIRCL hashlookup, GreyNoise, URLhaus. None
declares a region.

## 5. How the suite provisions tenants (what a migration of identity touches)

- 14 test files and `scripts/demo.sh` / `scripts/demo_propose.py` sign in with
  `POST /api/auth/dev-login`.
- `tests/test_deployment_scorecard.py` calls `get_or_create_user` with a
  `workspace_name` (`:140`, and `:287` for the reserved-name refusal).
- 21 statements in 12 test files insert workspaces directly, and four insert
  users directly with `(workspace_id, email…)`: `tests/test_chat_history.py:185`,
  `tests/test_schema.py:211`, `tests/test_investigations.py:713`,
  `tests/test_action_settlement.py:2068`. Dropping `users.workspace_id` breaks
  those four inserts.
