# S30 — MSSP tenancy, the design S30 builds

_Written 2026-10-15 in S30 (backend). D-061 and the phase's spec
(docs/superpowers/specs/2026-10-15-integration-phase-design.md, D-061 section)
decided the model; this addendum answers the five questions D-061 left to S30,
each put to Burhan one at a time and answered by him, and records the design he
approved section by section. Reality it stands on:
docs/probes/2026-10-15-s30-tenancy-baseline.md._

## Burhan's calls (S30)

| # | Question | Answer |
|---|---|---|
| 1 | Who creates organizations and workspaces? | **A CLI plus a membership API.** Only the CLI creates organizations and workspaces, with the first admin; over HTTP, workspace admins manage memberships only. No operator role; `__deployment__` stays memberless (D-035). |
| 2 | What a dev login becomes | **Auto-provision as today.** An unknown email (dev only) becomes a user homed in `default`'s organization, with an `analyst` membership in `default`. Google sign-in never auto-provisions (and stays 503 behind TD-001). |
| 3 | The migration | **One organization per workspace.** Each existing workspace except `__deployment__` becomes a `direct` organization of its name; users keep their ids; two user rows sharing a case-folded email stop the migration. |
| 4 | Who reads the audit trail | **Workspace admins**, the active workspace's events only. |
| 5 | The region vocabulary | **`global` and `ksa`; a `global` processor serves only `global` workspaces.** `ENGINE_REGION` unset means `global`. |

## 1. The data model and the migration

**New tables.**
- `organizations(id, name, kind, parent_id, restricted, created_at)`.
  - `name` unique; `kind IN ('direct','provider','client')`.
  - CHECK: a `client` has a `parent_id` and no other kind does.
  - CHECK: only a `client` may be `restricted`.
  - A parent is a `provider`: enforced by the one module that creates
    organizations (`auspex/tenancy/admin.py`).
- `memberships(id, workspace_id, user_id, role, provider_wide, created_at, updated_at)`.
  - `role IN ('admin','analyst','viewer')`; `provider_wide` boolean, default
    false.
  - `UNIQUE (workspace_id, user_id)`; both foreign keys `ON DELETE CASCADE`.
- `audit_events(id, workspace_id, actor_kind, actor_user_id, actor_org_id, action, subject_user_id, details, created_at)`.
  - `actor_kind IN ('user','cli')`; `action` a closed CHECK list (§3).
  - The actor columns carry no foreign key: purging a user must not erase who
    acted.
  - `created_at` defaults to `clock_timestamp()` (the S15 rule for rows read in
    order).
  - Append-only: no code in `auspex/` updates or deletes a row (pinned by a
    structural test).

**Changed tables.**
- `workspaces`:
  - gains `org_id` (FK organizations), NULL only for `__deployment__` (CHECK
    `org_id IS NOT NULL OR name = '__deployment__'`);
  - gains `region text NOT NULL DEFAULT 'global'`, CHECK `IN ('global','ksa')`.
- `users`:
  - gains `home_org_id NOT NULL` (FK organizations);
  - loses `workspace_id`, `role` and `UNIQUE (workspace_id, email)`;
  - gains a unique index on `lower(email)`.
- `api_keys` keeps `workspace_id`. A key names one workspace, as a token does,
  and is re-checked the same way (§2).
- `tests/test_schema.py`'s exemptions become `workspaces`, `organizations` and
  `users` (D-061 named the latter two).

**The migration** is one idempotent `DO` block appended to `SCHEMA_V0`, guarded
on `users.workspace_id` still existing (the S16 `watcher_id` pattern,
`auspex/migrations.py:420`). In order:
1. **Refuse** with a count and no emails if two user rows share a
   case-folded email (in two workspaces, or in one, differing only by case),
   or if any user sits in `__deployment__`.
2. Each workspace other than `__deployment__` with no organization becomes a
   `direct` organization of the same name.
3. Each user keeps its `id` and gets its workspace's organization as its home
   organization and a membership in that workspace. Its role carries over if it
   is `admin`, `analyst` or `viewer`, and is `viewer` otherwise (today every
   row is `analyst`).
4. Drop the old constraint, index and columns; set `home_org_id NOT NULL`;
   create the `lower(email)` index.

The old `idx_users_workspace` statement (`auspex/migrations.py:188`) leaves the
list: on a migrated database it would fail the next boot. Because user ids are
kept, `api_keys.user_id`, `chat_sessions.user_id` and
`proposals.decided_by/resolved_by` all stay valid.

On the dev database this migrates 3 workspaces (`__deployment__` stays without
an organization; `default` and `dev` each become one) and 13 users, all in
`default`. Tests that insert a bare workspace or a user directly move to one
helper that creates the organization too.

## 2. Identity, tokens and roles

**`enterable_workspaces(conn, user_id, only=None)`** (`auspex/tenancy/access.py`)
is one SQL statement and the only code that answers "may this person enter,
and as what". It returns `{workspace_id: Access(role, via, org, region)}`:
- **explicit memberships**, counted only where the workspace's organization is
  the user's home organization or a client of it (the write path refuses
  anything else; the read side re-checks, so a stray row grants nothing);
- **provider-wide grants**: a `provider_wide` membership on a workspace of the
  user's own `provider` home organization reaches every workspace of that
  provider's clients that are not `restricted`;
- `__deployment__` has no organization, so nothing reaches it;
- **an explicit membership's role wins over a provider-wide grant** on the same
  workspace. It is the more specific statement, and it lets an MSSP narrow one
  client to `viewer` without restricting it for everyone.

**`resolve_user`** (`auspex/auth.py:80`) calls that function with `only=` the
token's `wid` (or the API key's workspace) on every request.
- No access: **403 "You no longer have access to this workspace."** 401 stays
  for a bad token or a deleted user.
- The role is never read from the token; it is resolved live, so a removed
  membership or a changed role takes effect at the next request.
- `AuthContext` gains `role`, `home_org_id` and `region`.
- The proposals stream (`auspex/routes/proposals.py:174`) re-checks access on
  each tick and ends when it is gone.

**Roles, enforced.** `require_role(*roles)` sits beside `resolve_user` and
builds three dependency aliases:
- `AnyRole`: every GET.
- `Analyst` (`analyst` or `admin`): every write that exists today. That is the
  chat turn, the investigation writes, the seven proposal doors and the
  retro-hunt ack. A viewer is read-only (the spec's role table).
- `Admin`: the membership API and the audit read.

**Sign-in and switching.**
- Dev login (and Google sign-in once TD-001 is fixed) lands in the first
  enterable workspace: the home organization's workspaces first, then the
  rest, each group ordered by name. None: 403.
  Each landing is audited as `workspace.enter` with `via: login`.
- **`POST /api/auth/switch {workspace_id}` is the one route that takes a
  workspace id from input**, and it only reaches what `enterable_workspaces`
  returns.
  - It answers the same 404 for "not yours" and "does not exist".
  - It mints a new token and is audited (`workspace.enter`, `via: switch`).
  - It needs a login session, not an API key, so a leaked key cannot become a
    session.
- A token for the workspace left stays valid until it expires and is re-checked
  like any other.
- **`GET /api/auth/me`** returns:
  - the user;
  - the home organization;
  - the active workspace, with its region and role;
  - the switchable set, each workspace with its organization, role and `via`.

  `whoami` is unchanged.

## 3. The admin surface: the membership API, the CLI, the audit trail

**One write module, `auspex/tenancy/admin.py`.** The CLI, the API and the tests
all go through it. Every function writes its audit event in the same
transaction as the change.

**The membership API** acts only on the admin's active workspace; no other
workspace id appears in it.
- `GET /api/workspace/members`: the explicit members, each with email, display
  name, home organization, role and `provider_wide`.
- `POST /api/workspace/members {email, role}`:
  - a known person is added only if the workspace belongs to their home
    organization or a client of it; otherwise 409 "This person belongs to
    another organization", without naming it;
  - an unknown email becomes a user homed in the workspace's own organization
    (an MSSP admin acting in a client workspace creates a client user).
- `PATCH /api/workspace/members/{user_id} {role?, provider_wide?}`;
  `provider_wide` only on a `provider` organization's workspace.
- `DELETE /api/workspace/members/{user_id}`.
- **Every self-targeted change is refused**: no one sets their own role or
  grants themselves provider-wide, and so the API can never remove a
  workspace's last admin.
- A target that is not a member: 404.
- A client workspace's admins can be the client's users, the MSSP's people, or
  both. The `restricted` flag, set by the CLI in S30, decides who may see a
  client through provider-wide grants.

**The CLI**, run as `docker compose exec app python -m auspex.tenancy …`:
- `create-org --kind direct|provider --name N --workspace W [--region R] --admin EMAIL`:
  the organization, its workspace and its first admin, in one transaction. An
  admin email already homed elsewhere is refused.
- `create-client --provider P --name N --workspace W [--region R] [--admin EMAIL] [--restricted]`.
- `set-restricted --client N on|off`.
- `set-member --workspace W --email E --role R [--provider-wide]` and
  `remove-member --workspace W --email E`: the recovery path, under the same
  home-organization rule.
- `list`: organizations, workspaces, regions and member counts; no emails.
- A workspace's region is set at creation only.

**The audit trail.**
- Actions:
  - `workspace.enter` (`via`: login or switch);
  - `membership.add`, `membership.role`, `membership.remove`;
  - `membership.provider_wide` (on or off);
  - `org.create`, `org.restricted`, `workspace.create`.
- Each event belongs to the workspace it concerns. An entry is recorded in the
  workspace entered, so a client's admin sees which MSSP analyst, of which
  organization, came in.
- **`GET /api/audit`**: admin only, the active workspace only, newest first,
  `before` paging, capped at 100.

## 4. The region guard

**One rule, in one module** (`auspex/tenancy/region.py`).
- `REGIONS = frozenset({"global", "ksa"})`; a new region is a code change.
- `may_process(workspace_region, processor_region)` is true only if the
  workspace is `global` or the two regions are equal.
- `ENGINE_REGION` is read into `Settings`. Unset means `global`, which fails
  safe (it serves no `ksa` workspace). An unknown value stops startup. It goes
  into `.env.example` and `docs/ENV_VARS.md` in the commit that creates it.

**The engine.** The two factories that build a workspace's engine client check
`may_process(auth.region, settings.engine_region)`:
`get_endpoint_resolver` (`auspex/routes/chat.py:298`) and
`get_summary_client_factory` (`auspex/routes/investigations.py:410`).
- **Chat:** a refused resolver carries the reason. The route answers it beside
  the "not configured" check, **before a session or message is stored**
  (B-008's rule). The answer names the regions and "the platform's engine",
  never a vendor (D-002).
- **The investigation summary:** 403 with the same reason.
- **What keeps working:** the shortcuts that need no engine. That is CVE lookup
  and definitions from our own KB, and an IOC check up to its third-party
  lookup.
- **Dev:** the dev switcher's endpoints count as the deployment's engine and
  inherit `ENGINE_REGION`.

**Third-party enrichment.**
- Every `Provider` subclass declares `region` in its own class body (all seven
  `global`). A structural test refuses one that only inherits a default.
- `EnrichmentService.enrich(observables, *, region)` takes the region as a
  required keyword and drops every provider the workspace's region forbids.
- With none left, the outcome says third-party lookups are not available in
  this workspace's region:
  - the IOC shortcut's answer (`chat.py:747`);
  - the agent's lookup tool result (`auspex/agent/capabilities.py:319`);
  - an investigation lookup (`investigations.py:358`), refused with the
    reason.
- Nothing is recorded as a verdict from a refused lookup.

**Structural pins.**
- `LLMClient.from_settings` is called only inside the guarded factories, plus
  an allowlist: the startup autoprobe and `scripts/llm_harness.py`. Both are
  deployment-level and send no tenant data.
- Every `enrich(` call passes `region=`.

**Not covered, and why.**
- The KB: our own OpenSearch, with in-process embeddings.
- Feed ingest and the retro-hunt sweep: public data in, nothing tenant-owned
  out.
- Per-workspace engines stay in ROADMAP's Later, so a `ksa` client on a
  `global` deployment has no co-analyst turns (D-061's bound).

## 5. Testing, review and scope

**Structural tests** read the app rather than a list someone must remember:
- every route on the `Admin` alias refuses an analyst and a viewer (403),
  found by walking `app.routes`;
- every non-GET `/api` route depends on `Analyst` or `Admin`, except a named
  allowlist: dev-login, switch, api-keys;
- no route takes a workspace, tenant or organization id from its path, query
  or body, except `/api/auth/switch`;
- every table carries `workspace_id` or is one of the three named exemptions;
- `audit_events` is never updated or deleted in `auspex/`;
- the region pins in §4.

**Cross-tenant tests**, on a fixture of one provider with two clients (one
`restricted`) and a direct organization:
- a client user cannot reach the sibling client or the provider's own
  workspace (switch, token, member API);
- an MSSP analyst without a membership cannot enter a client;
- a provider-wide grant reaches a client created after the grant, and not the
  restricted one;
- a removed membership ends access at the next request, and ends the open
  proposals stream;
- no one sets their own role or grants themselves provider-wide;
- explicit-wins precedence and the home-organization rule hold, including on a
  stray row written straight into `memberships`;
- a token minted for workspace A, used after switching to B, still sees only A;
- a foreign workspace and a missing one get the same 404 on switch.

**The migration** is tested on its own database, created by the test:
- the pre-S30 shape with data becomes users and memberships, ids kept;
- a duplicate email stops it, with a count and no email;
- a second run does nothing.

**The region guard:**
- a `ksa` workspace on a `global` engine:
  - its chat turn is refused with nothing stored;
  - its CVE and definition shortcuts still answer;
  - its lookups are refused;
  - its summary is refused;
- on a `ksa` engine its turns run;
- a `global` workspace is unaffected.

**Proof.**
- Every test fails first.
- Mutants on each guard: role, the membership re-check, the home-organization
  rule, the region rule, precedence, self-change.
- The full gate.
- Live checks through the rebuilt container: the CLI, a switch, `/me`.
- A fresh-agent adversarial review of tenancy and auth, and a fresh review of
  its fixes (SESSION-RULES.md).
- Then the promote, carrying S29's slate with S30.

**Out of S30.**

| What | Where it goes |
|---|---|
| Recording the approver's organization; the approval policy | S34 |
| Changing a live workspace's region | IDEAS |
| Postgres row-level security as a second wall | IDEAS |
| The pages | F4, F5 |
| Showing a client admin who *could* enter through a provider-wide grant | F5's members page (the audit trail shows who *did*) |

TD-001 stays a hard gate before Google sign-in.

## After execution (S30, 2026-10-15)

What the build added to, or refined in, the design above (rulings recorded in
D-068 and D-069; reviews in STATE.md's S30 section):
- **The engine check sits in the two route bodies** (`chat`, `render_summary`),
  not in the test-seam factories, so it holds when a test replaces the seam.
- **Membership writes hold the workspace row** (`FOR NO KEY UPDATE`) **and
  re-check, inside the transaction, that a person acting is still an admin
  there.** Without it two admins removing each other at once left zero admins
  (final review, reproduced 19/20). §3's "the API can never remove a
  workspace's last admin" is true since then.
- **`set-member` leaves an existing provider-wide grant unchanged** unless
  `--provider-wide` / `--no-provider-wide` is given.
- **`__deployment__` takes no membership**: every membership write refuses it
  by name.
- **A fifth CLI command, `rehome-person --email E --org O`**, recovers a person
  homed in the wrong organization (only while they hold no membership), audited
  as a ninth action, `person.rehome`. An admin can still create a person with
  any email over the API; limiting that is TD-059, a hard gate before Google
  sign-in. B-021 (fixed at S31, `b1fa61e`): the event showed the old
  organization's name to the new one's admins; it now records only `to`, and
  the CLI prints the old home to the operator.
- **`/api/audit`'s `before` must carry a UTC offset** (an offset-less value is
  a 422).
- **D-069 overturns §4's bound**: a `ksa` workspace will live only on a
  deployment that stores data in KSA (built in a later session).
