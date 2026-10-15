# The integration phase — design (S29)

_Written 2026-10-14/15 in S29 (backend), from the plan Burhan wrote on
2026-10-14 (`NEXT-SESSION-BE.md`, S29–S41; `NEXT-SESSION-FE.md`, F4–F9).
Every decision below was put to Burhan one at a time and ratified by him; each
is a D-entry (D-060…D-067). This spec is what S30–S41 and F4–F9 build against.
It ships no code._

## What the phase is for

Burhan, 2026-10-14: "lets work on integrating a SIEM on the platform and build
the incident management platform but i believe in order to do that we first
need to build an application module which relies on the build your own
integration module". And: "My other concern is MSSP clients and their multi
tenancy problem". And: "Some security controls are on-prem only, how do you
propose to handle them considering we are a cloud based app".

- **Outcome.** Alerts and source cases from a customer's SIEM flow into Auspex;
  the analyst works them as **cases**, co-analyst included, and acts back on the
  SIEM only through approvals. It is built on **integrations** (a connector
  configured in a workspace), and customers and MSSPs can write their own
  **connectors**.
- **Who.** Direct customers, and MSSPs serving many clients. QRadar first.
- **Constraints.** Tenant isolation is an invariant. On-prem controls are
  reached with no inbound connection. No secret reaches an API response, a log,
  the page or the model. Customer code never runs on Auspex infrastructure in
  v1. KSA residency is enforced by code. Burhan's QRadar holds real data, so
  only a synthetic lab domain of it ever reaches the dev engine.

## D-060 — The words

| Word | Meaning |
|---|---|
| **Organization** | Who a customer is: `direct`, `provider` (an MSSP) or `client` (under one provider; may be `restricted`). It owns workspaces and holds no data itself. |
| **Workspace** | The isolation unit (D-008). Every data row belongs to exactly one. It carries a region. A provider has its own workspace. |
| **Membership** | A user's right to enter one workspace, with a role: `admin`, `analyst` or `viewer`. A provider-wide grant extends it to every unrestricted client. |
| **Connector** | A package a customer, an MSSP or Auspex writes with the SDK: a typed, versioned manifest plus Python handlers. Commands: `test`, `fetch`, `action`. |
| **Integration** | A connector configured in one workspace: config values, secret *names*, its Edge Agent, fetch schedule, health and, when shared, a routing map. |
| **Edge Agent / Cloud Agent** | What runs an integration's commands: one image, placed on a customer's or MSSP's network, or run by Auspex (S41). Code package `auspex/edge/`, kept apart from the co-analyst's `auspex/agent/`. |
| **Routing key / map / quarantine** | The item field that names its client (a QRadar domain); the provider's map from key to client workspace; where an unmapped item waits, in the provider's workspace. |
| **Alert** | One fetched item, normalized through `AlertEnvelope` (`auspex/alerts/envelope.py:59`), in exactly one workspace. |
| **Case** | The analyst's unit of work: lifecycle, assignee, an append-only event log, linked alerts, observables and proposals. "Incident" stays free for a SIEM's own word (a QRadar offense, a Sentinel incident). Not `investigations` (`auspex/migrations.py:204`), which is one pasted subject's ACH. |

User-visible copy uses these words; the brand rules (D-002) still apply.

## D-061 — Tenancy for MSSPs, and roles

**Organizations and workspaces.**
- `organizations(id, kind: direct|provider|client, parent_id, restricted)`; a
  `client` points to its provider. `workspaces.org_id`, `workspaces.region`.
- **A provider organization has its own workspace.** Its shared integrations,
  routing maps, quarantine and their jobs are ordinary rows there. So every data
  row keeps `workspace_id NOT NULL` (D-008 unchanged), and `tests/test_schema.py`
  names only two exemptions: `organizations`, and `users` once identity leaves
  the workspace (below). Memberships, agents, integrations and jobs all carry a
  `workspace_id`.

**Identity.** One user per person, with a home organization. Email is unique
across the deployment (case-folded). Today a user row belongs to a workspace
(`UNIQUE (workspace_id, email)`, `auspex/migrations.py:31-41`); S30 migrates
each row to a user plus a membership. TD-001 stays a hard gate before Google
sign-in. The `default` workspace and every dev login keep working;
`__deployment__` stays reserved (D-035).

**Memberships and roles.**
- `memberships(user_id, workspace_id, role)`, role `admin | analyst | viewer`:

  | role | enter | chat / triage / cases | propose | approve | configure |
  |---|---|---|---|---|---|
  | admin | yes | yes | yes | per policy | yes |
  | analyst | yes | yes | yes | per policy | no |
  | viewer | yes | read only | no | no | no |

- **Who may approve is not a role**: it is the workspace's approval policy (S34).
- **A membership's workspace must belong to the user's home organization, or to
  a client of it.** Code refuses anything else, so a client's user can never be
  added to a sibling client.
- **Explicit by default, plus an opt-in provider-wide grant.** A membership on
  the provider's own workspace may carry `provider_wide`; it then applies, with
  its role, in every current and future client workspace of that provider
  **except clients marked `restricted`** (a contract naming who may see that
  client).
- **One function computes the workspaces a person may enter**
  (`enterable_workspaces(user)`): explicit memberships ∪ provider-wide grants
  minus restricted clients. Every token mint and every cross-client view uses
  it, and nothing else decides it.

**Tokens and switching.** A token names one workspace (`wid`, today
`auspex/auth.py:53`), minted only for a workspace in that set. Switching mints a
new token and is audited. `resolve_user` (`auspex/auth.py:80`) re-checks the
membership on every request, so a removed membership ends access at the next
request, not at token expiry. **Nothing takes a workspace or tenant id from a
request body, a header or a query string.** `require_role` sits beside
`resolve_user`. `GET /api/auth/me` returns the user, the home organization, the
active workspace and role, and the switchable set (F4 needs it).

**Cross-client views** (an MSSP's "all my clients' cases") filter on
`workspace_id = ANY(<enterable_workspaces>)`, computed by code. A structural
test refuses any alert or case query that lacks a workspace filter.

**The co-analyst never mixes clients.** A chat session belongs to one
workspace: its context, tools, spend and residency are that workspace's, even
for an analyst who can enter several.

**Shared SIEMs.** A shared integration lives in the provider's workspace. Its
routing map (written by a provider admin) sends each fetched item to a client
workspace by its routing key. **An unmapped item is quarantined in the
provider's workspace and never lands in a guessed or default workspace.** An
action on a routed case goes back through the same shared integration, limited
to that item's routing key (S34).

**Approvals.** A per-client approval policy is data (which roles, in which
organization, may approve each risk level); D-024's claim path enforces it, and
the approver and their home organization are recorded (S34).

**Residency (a region guard, by code).**
- Each workspace carries a region (`global`, `ksa`, …). The deployment declares
  where its engine processes (`ENGINE_REGION`, born in S30 with `.env.example`
  and `docs/ENV_VARS.md`). Engines stay deployment-wide (D-005, D-035 stand).
- **A workspace whose region the engine may not serve gets no engine turn**,
  refused by code with the reason. The LLM-free paths (IOC check, CVE lookup,
  alerts, cases) still work.
- **The same guard covers third-party enrichment.** A lookup sends the
  indicator to the provider, which is tenant data leaving the region. Each
  enrichment provider declares its region in code (all `global` today), so a
  `ksa` workspace gets no third-party lookups until an in-region provider
  exists.
- Per-workspace engines stay in ROADMAP's Later ("KSA residency routing").

**Audit.** Every case event, approval and workspace switch records the acting
user and their home organization, so a client sees which MSSP analyst did what.

**Herd Immunity stays deferred.** Nothing here shares data across workspaces.

## D-062 — Where connector code runs: the Edge Agent and the Cloud Agent

- **One image, two placements.** The **Edge Agent** runs on the customer's or
  MSSP's network, as a container or a service. The **Cloud Agent** (S41) is the
  same image, run by Auspex, isolated (its own network, no database, limited
  egress), for internet-reachable controls, first-party connectors only.
- **Outbound only.** The agent long-polls Auspex over HTTPS for jobs and posts
  results back: no inbound firewall rule, no VPN. Long-poll rather than a
  WebSocket, because enterprise egress proxies pass plain HTTPS.
- **Trust.**
  - A one-time enrollment token becomes an agent credential, stored hashed (the
    `api_keys` pattern, `auspex/migrations.py:43`), revocable.
  - **An agent belongs to one workspace and serves only that workspace's
    integrations.** A shared SIEM's agent belongs to the provider's workspace;
    an agent at a client's site belongs to the client's workspace.
  - Its credential reaches only the edge API: claim its own jobs, post results,
    heartbeat, fetch packages. Nothing else.
- **Code.** Pulled from the catalogue by content hash by default; a local-install
  mode serves air-gapped sites. **Either way the agent runs a package only after
  its hash matches the one the job names**, so what was approved is byte-for-byte
  what runs. A customer-written connector runs only on that customer's own agent
  (v1; customer code on Auspex infrastructure needs per-tenant sandboxes and a
  later D-entry). S33 builds pull-by-hash; local install is built when the first
  air-gapped site needs it, logged as debt until then.
- **Each command** runs in a subprocess with a timeout. The SDK's HTTP client
  reaches only the connector's declared hosts. TLS is verified or pinned, never
  off.
- **Core code validates every result** against the command's output schema
  before anything stores it, shows it or hands it to the model (code over
  prompts).
- **Offline is a state.** Heartbeats drive health: online, stale, offline. An
  approved action whose agent is offline waits: `check_executable` refuses with
  "agent offline", and D-048's stale doors apply. A fetch resumes from its
  cursor.
- **Retries are safe.** Every job carries an idempotency key (TD-025), so a
  result lost on its way back never runs an action twice.
- **Residency.** Raw on-prem data and credentials stay on the edge; only what a
  command returns crosses, and a connector can redact first. D-061's region
  guard governs what happens to it after that.

## D-063 — Credential custody

- **Edge-placed secrets are names in Auspex.** An integration's config holds
  `secret:<name>`; the value lives on the agent's host (its secret file, mode
  0600, an env var, or a vault reference the agent resolves). Auspex never
  holds the value, encrypted or not. A missing secret fails "Test connection"
  with the secret's name and the agent's, never a value.
- **Cloud-placed secrets (S41)** are sealed in Auspex: envelope encryption under
  a master key from a documented env var, rotatable, write-only through the API.
- **No secret value ever reaches an API response, a log, the page or the
  model.** Tests scan responses and logs for it (S33).
- If a credential is pasted into a conversation, it is refused and rotation is
  requested (org rule).

## D-064 — The connector contract, v1

**Two ways to write one, one canonical form.** A connector is written
Python-first (SDK decorators: `@connector`, `@command`, `@action` with its risk,
dry run and undo, a typed config class with `Secret` and TLS fields) or as a
hand-written YAML manifest with Python handlers. `auspex-sdk build` turns
either into the same `manifest.json` plus the package and its content hash; for
YAML it checks that every handler named exists with matching parameters. **The
core reads only `manifest.json`, never YAML and never connector code** (a
structural test: the app package never imports connector code).

**The manifest.**
- **Identity:** `schema_version: 1`, `id` (`ibm.qradar`), semver `version`,
  name, description. **The package's content hash is its identity**: a changed
  package is a new version whatever its semver says. Whether a connector is
  first-party is set by the catalogue, never declared by the connector.
- **Config:** typed fields (string, integer, boolean, https URL, enum, `secret`
  (a name, D-063), `tls` (verify, or a pinned CA PEM or certificate SHA-256)).
  **TLS verification off is unrepresentable.**
- **Hosts:** declared host patterns templated from config (`{base_url}`).
- **Commands:**
  - `test` → `{ok, detail}`.
  - `fetch(cursor, limit)` → `{items, next_cursor}`. Each item: `external_id`,
    `kind` (`alert` or `source_case`), timestamps, the fields `AlertEnvelope`
    reads, a size-capped `raw`, and a `routing_key` (required when the
    connector declares that it serves many clients).
  - `actions[]`: a wire-safe name, a description, a risk (the `ToolLevel`
    vocabulary, D-023), primitive params (arrays wait for TD-023(d)), a
    **required** `dry_run`, an `undo` with `cannot_restore`, an output schema,
    and `targets` (the param that names the external item, used to limit a
    shared integration's action to its item's routing key, S34).
- **`validate_manifest` refuses with exact reasons**, table-driven tests, one
  per rule: destructive without undo, an undeclared host, TLS off, a missing
  dry run, a shared fetch without a routing key, a non-wire-safe name, an
  unknown field type.

**Mapping onto today's actions** (`ActionSpec`, `auspex/actions/types.py:164`;
`validate_spec`, `:239`).
- Each manifest action compiles to an `ActionSpec` whose `dry_run`, `execute`
  and `undo` are **distinct dispatcher callables** that send an agent job and
  await its validated result. `validate_spec` passes unchanged (it refuses a
  dry run that is an execute handler; distinct dispatchers are not).
- Wire names are prefixed per integration, so two QRadars in one workspace do
  not collide. `scope` names the integration.
- **The spec fingerprint (D-024) gains the connector id and package hash**, so
  an approval does not survive a code change. That closes D-024's stated gap
  ("a changed handler BODY behind identical declared facts") for connectors.
- A proposal's card comes from a `dry_run` job, so proposing a connector action
  needs its agent online; offline, the proposal is refused with the reason.
- **What the model reads is composed by code** from the manifest's typed fields
  and capped. Customer-written descriptions join the output rail's index;
  TD-044's calibration is re-run with them at S34, and a floor moves only on
  that measurement.

## D-065 — The jobs queue

- **Our own Postgres table, claimed with `FOR UPDATE SKIP LOCKED`** (D-001's
  promise), in settlement's style: conditional UPDATEs and claim tokens.
- `jobs(id, workspace_id, kind, integration_id, payload, idempotency_key,
  status: queued|claimed|done|failed|dead, attempts, max_attempts, run_after,
  lease_expires_at, claim_token, claimed_by, result, created_at, …)`, with the
  idempotency key unique per workspace.
- **Two kinds of claimer.** Edge Agents, over HTTP, claim only their own
  integrations' jobs. An in-app worker (started in the lifespan beside the
  ingest task, `auspex/app.py:41-95`, cancelled on shutdown) claims the rest:
  fetch schedules, retro-hunts, later SLA timers.
- **A lease that expires, bounded retries with backoff, a dead state.** A
  result for a job the claimer no longer holds (its token) is refused.
- **Fair across clients.** The claim order serves workspaces in turn, so one
  busy client cannot starve the others; a test proves it.

## D-066 — TD-023 and TD-025 leave Deferred, in TD-025's own order

- **S30:** roles are real (D-061), so `decided_by` can be enforced once S34's
  policy reads them.
- **S31:** pending proposals expire after a TTL (a new status, added to the one
  status-CHECK block in place;
  `test_startup_survives_every_status_a_proposal_can_be_in` passes); every
  execution attempt carries an idempotency key, handed to execute, undo and
  observe.
- **S32:** the catalogue answers TD-023's "which actions does this tenant have?"
  per workspace.
- **S34:** grant-checked scope before the first third-party action runs: an
  action touches only what its integration declares, and on a shared
  integration only its item's routing key. `EXECUTABLE_SYSTEMS`
  (`auspex/actions/settlement.py:50`) widens by code and review, as D-024
  itself requires.
- Still deferred: array params (TD-023(d)), until a real action needs one; the
  polled card stream (TD-046).
- SESSION-RULES.md's Deferred list loses both, in its own commit.

## D-067 — Live QRadar checks run on a synthetic-only lab domain

Burhan's QRadar holds real data (docs/probes/2026-10-14-qradar-reachability.md),
and the dev engine processes in Singapore. **The phase's live checks use a
QRadar domain that holds only the synthetic offenses S36's recipe creates, and
the Edge Agent's token is scoped to that domain alone**, so a fetch can only
return synthetic items, by QRadar's own permissions. It doubles as the MSSP
routing test (domain → workspace).
- **S36's Step 0 confirms Burhan's edition has domain management.** If it does
  not, the choice returns to him (a separate lab QRadar, or live checks that
  never send fetched content to an engine).
- Recorded responses for CI's QRadar fake are synthetic only, and record shapes,
  not values from the real domains.

## How it flows

**Fetch → alert → case.**
1. The worker's schedule enqueues a `fetch` job for an integration (bounded by
   the workspace's plan, D-026).
2. Its Edge Agent claims it, runs the connector's `fetch(cursor, limit)` against
   QRadar, and posts `{items, next_cursor}`.
3. Core validates the result against the output schema. An invalid page is
   refused and the job retries; a malformed item is quarantined, never a crash.
4. Each item is routed: a workspace integration's items stay in its workspace;
   a shared integration's items go where the routing map says, or to
   quarantine.
5. Items land as alerts, unique on (workspace, integration, external_id), so a
   re-fetch is a no-op; normalized through `AlertEnvelope`, scored by
   `score_alert`. The cursor advances only after the page is stored.
6. A source case (a QRadar offense) creates a case directly; other alerts group
   by rule or by hand (S37).

**Action → approval → result.**
1. The co-analyst (or an analyst) proposes a connector action in a case. Core
   sends a `dry_run` job; the agent returns what it would do; the card is
   compiled and frozen (D-024).
2. An approver allowed by the workspace's policy approves; D-024's claim path
   records them and their organization.
3. `check_executable` re-checks: integration enabled, agent online, package
   hash unchanged, the action within the integration's grants and the item's
   routing key.
4. An `execute` job with an idempotency key runs on the agent; the validated
   result settles the proposal; undo, observe and D-048's doors work as today.

## What fails, and what the analyst sees

| Situation | What happens |
|---|---|
| Agent offline | Health shows it; proposals refused with "agent offline"; approved actions wait (D-048's doors); fetches resume from the cursor |
| Lease expires mid-job | Another claim can take it; the idempotency key stops a second execution |
| Result fails its schema | Refused, the job retries, then dead; nothing stored or shown |
| Package hash mismatch | The agent refuses to run it and reports it |
| Secret missing on the edge | "Test connection" fails naming the secret and the agent |
| Unmapped routing key | Quarantined in the provider's workspace, visible to its admins |
| Region not served | The engine turn (or third-party lookup) is refused by code, with the reason |
| Membership removed | Access ends at the next request |

## Testing, across the phase

- **Every new table and route gets a cross-tenant test**; structural tests
  refuse a workspace id read from input, an unscoped alert or case query, and a
  new table that is neither workspace-scoped nor a named exemption.
- **Every claim is raced** (two claimers, exactly one winner), as D-024 and
  D-026 did.
- **CI is hermetic**: QRadar is reached only through a fake built from recorded,
  synthetic probe responses. Live checks are separate and recorded in
  `docs/probes/` with no secrets and no non-synthetic data.
- **A change to the rail, an action, tenancy or the approvals state machine gets
  a fresh-agent adversarial review before its session closes** (SESSION-RULES).

## What this supersedes

Nothing ratified. D-008 stands (the workspace is still the only isolation
unit). D-005 and D-035 stand (the engine stays deployment-wide; a guard is
added). D-024 is widened on its own terms (code and review). D-023's contract is
what a connector action compiles to.

## Open, and where it is answered

- QRadar's address, TLS certificate and unauthenticated API answer: the
  reachability probe, as soon as Burhan gives the address, before S33.
- Domain management on Burhan's QRadar edition: S36's Step 0.
- In-region enrichment providers for KSA workspaces: none today, so `ksa`
  workspaces get no third-party lookups (D-061).
- Local install for air-gapped sites: built with the first site that needs it.
