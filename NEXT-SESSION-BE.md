# NEXT-SESSION-BE — track: backend · session: S31

_Paste everything below the first line of dashes into a fresh Claude Code
window opened in /home/burhan/auspex-new. **S31 builds the jobs queue and
TD-025's first half (D-065, D-066).** **F4 closed 2026-10-16** (one shell for
every page, D-070), so S31 is next in the order table and **the focus**
(STATE.md). Promote #37 shipped F4, so the slate is empty. S30 closed
2026-10-15 (MSSP tenancy)._

_Below the S31 prompt is the **backend plan for the whole phase, S29–S41**.
**`/session-end` writes the next session's prompt from its entry in the plan,
keeps the plan section, and ticks the session it closed.** A change to the
plan's order is Burhan's call._

---

SESSION S31 of Auspex, **backend track** (D-051). The working dir must be
/home/burhan/auspex-new. Run `/session-start be S31` first (the full ritual).
It reads `SESSION-RULES.md` (standing rules for every track, including the
**Tenancy** section S30 added) and STATE.md.

Step 0 (do BEFORE new scope):

1. **One window at a time (D-051, D-059).** `git fetch` and read
   `origin/staging` first. If anything moves that you did not move, check `ps`
   for a second `claude` in this directory and stop.
2. **If STATE.md says the promote slate is not empty, `/promote` it.** Read
   the diff, not the list.
3. **B-021, unless BUGS.md says B3 fixed it** (Burhan, 2026-10-15: "promote
   now, fix next session"). `rehome-person` records the OLD organization's name
   in the NEW organization's audit trail, which that organization's admins read
   (`auspex/tenancy/admin.py:402-404`; the test that pins the leak is
   `tests/test_tenancy_cli.py:136`). Fix it as BUGS.md sketches: the event keeps
   only `to`; the old name goes to the operator's CLI output. In the same lines:
   a second concurrent rehome answers `NotFound` (lock `users` alone, then read
   the organization's name), and `admin.py`'s docstring overclaims the
   workspace lock (`provision_dev_user` takes none). Test first; a fresh-agent
   review (a tenancy change, SESSION-RULES.md); `fixed <commit> (S31)` in
   BUGS.md.
4. **D-069's build: ask Burhan where it goes** before anything else of it.
   Proposed: here, as Step 0 — the deployment declares its storage region (an
   env var born with it, in `.env.example` and `docs/ENV_VARS.md`), and the CLI's
   `create-org` / `create-client` refuse a `ksa` workspace unless that region is
   `ksa`. If he places it elsewhere, write that into STATE.md and the target
   prompt and move on.
5. **Read D-065 and D-066, and the spec's sections on them, before any code**
   (docs/superpowers/specs/2026-10-15-integration-phase-design.md). They are the
   contract; re-debating one is "overturn or drop?" to Burhan.
6. **Probe reality first (CLAUDE.md rule 4).** Save to
   `docs/probes/<date>-s31-jobs-baseline.md`:
   - the live `proposals` schema and its status CHECK block
     (`auspex/migrations.py`), and every claim/finish path in
     `auspex/actions/settlement.py` by `file:line` (D-041, D-048: claim tokens,
     `claimed_at`, the stale doors);
   - the lifespan's background tasks (`auspex/app.py`) and the `ingest_state`
     cursor pattern;
   - what an execution attempt hands `execute` / `undo` / `observe` today.

Goal: **S31, the plan's entry below, is the contract: its exit criteria are
the done line.** In short: a workspace-scoped `jobs` table claimed with
`FOR UPDATE SKIP LOCKED` (lease, bounded retries with backoff, a dead state, an
idempotency key unique per workspace, claim tokens, a claim that takes a scope),
a race test, fairness across workspaces, the in-app worker in the lifespan;
then TD-025's first half: an idempotency key on every execution attempt, and a
TTL on pending proposals (a new status in the one CHECK block). An adversarial
review of the approvals state machine.

**Design first, then a plan.** Brainstorm with Burhan, one question at a time,
then write `docs/superpowers/plans/<date>-s31-jobs.md` and ask how to execute
it. Questions D-065/D-066 leave to S31:
- the TTL's length (a code constant, D-026) and what an expired proposal says
  on its card and in the approvals list;
- the retry cap, the backoff curve and the lease length;
- the claim's scope shape, so S33's Edge Agents reuse it over HTTP;
- which job kind S31 runs at all (the proposal-expiry sweep is the obvious
  first), since connectors arrive at S32.

Candidates: none. Ending early with the rituals done beats starting S32's
work.

Constraints: everything in `SESSION-RULES.md`, and the plan's "Standing for
every session in this phase" below.
- `jobs` carries `workspace_id` (D-008); it is not an exemption. Every new
  table and route gets a cross-tenant test (`tests/_tenancy.py`).
- Any new status goes into the ONE `proposals_status_check` block, edited in
  place, and `test_startup_survives_every_status_a_proposal_can_be_in` passes.
- **An approvals-state-machine change gets a fresh-agent adversarial review
  before the close, and so do the review's fixes** (SESSION-RULES.md).
- Run pytest only when no live probe is running.
- Do not start S32's work in S31 (scope lock).

---

## The integration phase — backend plan (S29–S41)

_Written 2026-10-14 (Burhan, planning window); MSSP tenancy added the same day
at his request. **Re-checked at S29 against the phase's spec**
(docs/superpowers/specs/2026-10-15-integration-phase-design.md) and its
D-entries, D-060…D-067: the words changed (D-060), and S30, S32, S33, S35 and
S36 gained what the spec decided. The order did not change. Each session-end
writes the next session's prompt from its entry here, keeps this section, and
ticks the closed session._

### Words (D-060; the full table is in the spec)

- **Organization** (direct, provider, client; a client may be `restricted`)
  owns **workspaces**; a provider has its own workspace. Every data row belongs
  to exactly one workspace (D-008).
- **Membership**: a user's right to enter one workspace, as `admin`, `analyst`
  or `viewer`; a provider-wide grant reaches every unrestricted client.
- **Connector**: the package (manifest plus Python handlers, built with the
  SDK). **Integration**: a connector configured in one workspace.
- **Edge Agent / Cloud Agent**: what runs an integration's commands
  (`auspex/edge/`, apart from the co-analyst's `auspex/agent/`).
- **Routing key / map / quarantine**, **alert**, and **case** (the analyst's
  unit of work; "incident" stays the SIEM's own word).

### The order, both tracks (one session at a time, D-051)

| # | Session | Track | Depends on | Delivers |
|---|---|---|---|---|
| 0 | F3 | fe | — | closed 2026-10-14 by the collaborator (D-059); its PR #34 merged at S29 |
| 1 | S29 | be | F3 closed | closed: the S28 review, the spec and D-060…D-067 |
| 2 | S30 | be | S29 | closed 2026-10-15: MSSP tenancy (D-061, D-068); D-069 decided, built later |
| 3 | F4 | fe | S30 | closed 2026-10-16: one shell for every page, role-aware, a workspace switcher (D-070) |
| 4 | S31 | be | S30 | the jobs queue, TD-025's first half |
| 5 | S32 | be | S31 | the connector contract, the SDK (Python and YAML), the catalogue |
| 6 | S33 | be | S32 | integrations and the Edge Agent, "Test connection" end to end |
| 7 | S34 | be | S33 | integration actions through approvals and per-client policy |
| 8 | F5 | fe | S34 | connectors, integrations, Edge Agents, memberships and approval policy admin |
| 9 | S35 | be | S33 | fetch schedules, cursors, alerts, routing for shared SIEMs |
| 10 | S36 | be | S34, S35 | QRadar on the Edge Agent, live on the lab domain |
| 11 | F6 | fe | S36 | the alerts queue, the quarantine and the routing map |
| 12 | S37 | be | S36 | cases: lifecycle, events, assignment, linking |
| 13 | F7 | fe | S37 | cases list and detail, across clients for an MSSP |
| 14 | S38 | be | S37 | two-way sync with the SIEM, every write approved |
| 15 | S39 | be | S37 | the co-analyst on the case |
| 16 | F8 | fe | S38, S39 | sync state and the co-analyst inside the case |
| 17 | S40 | be | S38 | SLAs, metrics per client and for the MSSP, closure, the demo |
| 18 | F9 | fe | S40 | the dashboard, polish, Burhan's hands-on walk |
| 19 | S41 | be | S40 | after the path: the Cloud Agent, sealed secrets, a second SIEM |

- **The focus follows the order.** Each session-end sets STATE.md's focus to
  the next session's track.
- **Promote at the milestones:** S30 (tenancy), S33 ("Test connection" end to
  end), S36 (QRadar data in), S38 (the loop closed), and S40 (the phase's
  demo).

### Where the code stands (2026-10-15, after S30; re-verify before relying on it)

- **Actions** (`auspex/actions/`):
  - `EXECUTABLE_SYSTEMS = frozenset({"auspex"})` (`settlement.py:50`), checked
    only in `check_executable`. Widening it is code plus review (D-024, D-066).
  - One built-in action, `annotate_observable` (`builtin.py`). `ActionSpec` is
    `types.py:164`, `validate_spec` `:239`.
  - The registry is in-process and workspace-blind (TD-023). No idempotency key
    and no proposal TTL (TD-025). Both left Deferred at S29 (D-066).
- **Tenancy** (`auspex/tenancy/`, `auspex/auth.py`; built at S30, D-061/D-068):
  - organizations (`direct|provider|client`, `restricted`), memberships with
    `admin|analyst|viewer` and `provider_wide`, `users.home_org_id`,
    `workspaces.region`; `audit_events` (append-only). Schema-test exemptions:
    `workspaces`, `organizations`, `users`.
  - `enterable_workspaces` (`access.py`) is re-checked by `resolve_user` on
    every request; `require_role` aliases `AnyRole` / `Analyst` / `Admin`;
    `POST /api/auth/switch`, `GET /api/auth/me`; the membership API and
    `GET /api/audit` (`auspex/routes/workspace.py`); the CLI
    `python -m auspex.tenancy`; the region guard (`ENGINE_REGION`, `region.py`).
  - Every write already needs `Analyst` or `Admin` (pinned by
    `tests/test_tenancy_roles.py`); a new route inherits that check.
- **Secrets.** Provider keys are env-only and deployment-wide
  (`auspex/config.py`). No per-workspace secret storage.
- **Background work** is asyncio tasks in the lifespan (`auspex/app.py:41-95`);
  no jobs table. `ingest_state` (`auspex/migrations.py:173`) is the pattern for
  a per-source cursor.
- **Schema**: one list, `SCHEMA_V0` (`auspex/migrations.py`). Every table
  carries `workspace_id` (D-008), enforced by `tests/test_schema.py`. D-061
  names its only exemptions: `organizations`, and `users` once identity leaves
  the workspace.
- **Alerts** arrive only pasted into chat (`normalize`, `score_alert` in
  `auspex/alerts/`). **Enrichment providers** (`auspex/enrich/providers/base.py:24`)
  are the nearest existing shape to a connector.
- **Compose** runs `app`, `postgres` and `opensearch`. No worker, no agent.
- **Open bugs that touch this phase** (BUGS.md): B-021 (a rehome names the
  old organization to the new one's admins; S31's Step 0), B-010 (three classify rules
  still backtrack on crafted input), B-015/B-020 (what the agent says it
  recorded), B-017 (a malformed tool name from the endpoint crashes a turn),
  B-018 (a URL's credentials are kept).

### Standing for every session in this phase

- **SESSION-RULES.md applies unchanged.** A change to the rail, an action,
  tenancy or the approvals state machine gets a read-only adversarial review by
  a fresh agent before the close. In this phase that is nearly every session.
  At S29 the review of the review's own fixes found two more defects: review
  the fixes too.
- **Tenant isolation is an invariant** (org policy, D-061). No route takes a
  workspace or tenant id from input. Cross-client views use
  `enterable_workspaces`. Every new table and route gets a cross-tenant test.
- **Residency is code** (D-061): an engine turn or a third-party lookup the
  workspace's region forbids is refused.
- **CI stays hermetic.** QRadar is reached only through a fake built from
  synthetic recorded responses (D-067). Live checks are separate, on the lab
  domain, and recorded in `docs/probes/` with no secrets and no real data.
- **Anything a SIEM or a connector sends is attacker-controlled.** It reaches
  the model only through the data channel, under the input guard (D-027), and
  the page only as text.
- **Every write to a customer system goes through an approval** (D-014,
  D-024). No auto-run, whatever a fetch says.
- **Specs over prompts.** The manifest generates forms, action specs, the
  agent's tool text and contract tests (D-064). Nothing is written twice.
- New package → `pyproject.toml` and the Dockerfile skeleton. New env var →
  `.env.example` and `docs/ENV_VARS.md` at birth.

### Sessions

- [x] **S29 — The S28 review, the phase's decisions and spec, and where the
  QRadar lives.** Closed 2026-10-15. The review: 21 findings, 7 fixed (two HIGH),
  13 logged, the fixes reviewed in turn (docs/probes/2026-10-14-s29-s28-code-review.md).
  The spec and D-060…D-067, every decision Burhan's. TD-023/TD-025 out of
  Deferred. QRadar: real data (hence D-067); its address is still to come.

- [x] **S30 — Tenancy for MSSPs: organizations, provider workspaces,
  memberships, roles, one workspace per token, and the region guard.**
  Closed 2026-10-15. Built to the S30 design (D-068), every exit criterion met;
  the final adversarial review's fixes reviewed in turn; B-021 open (S31 Step 0);
  D-069 decided (a ksa workspace only on a KSA-storage deployment), built later.
  - **Depends on:** D-061 (spec, D-061).
  - **Goal:** an MSSP analyst enters the client workspaces they may, one at a
    time; a client's users see only their own; every query is still scoped to
    one workspace; residency is refused by code.
  - **Exit criteria:**
    - **The model.**
      - `organizations` (direct, provider, client with its provider, and
        `restricted`); `workspaces.org_id` and `workspaces.region`; **each
        provider organization has its own workspace**.
      - `memberships` (user × workspace × role `admin|analyst|viewer`, and
        `provider_wide` on a provider-workspace membership).
      - One user per person, with a home organization, email unique across the
        deployment (TD-001's hard gate stays for Google sign-in).
      - Existing rows migrate. `default` and every dev login keep working;
        `__deployment__` stays reserved (D-035).
    - **`enterable_workspaces(user)`**, one function: explicit memberships ∪
      provider-wide grants, minus restricted clients. Code refuses a membership
      outside the user's home organization or its clients.
    - **Tokens and switching.** A token names one workspace, minted only for an
      enterable one. A switch route mints a new token, audited.
      `resolve_user` re-checks the membership on every request.
      `GET /api/auth/me` returns the user, their organization, the active
      workspace and role, and the switchable set (F4 needs it).
    - **Roles, enforced.** `require_role` beside `resolve_user`.
    - **The region guard.** `ENGINE_REGION` (in `.env.example` and
      `docs/ENV_VARS.md`). An engine turn for a workspace whose region the
      engine may not serve is refused by code with the reason; each enrichment
      provider declares its region in code (all `global`), and a third-party
      lookup the workspace's region forbids is refused too. LLM-free paths
      still work.
    - **Structural tests.** Every admin route refuses an analyst and a viewer.
      No route reads a workspace id from input. Every table is
      workspace-scoped, or one of the two named exemptions.
    - **Cross-tenant tests.** A client user cannot reach a sibling client's
      workspace, nor the provider's own. An MSSP analyst without a membership
      cannot enter a client. A provider-wide grant reaches a new client but not
      a restricted one. A removed membership ends access at the next request.
      No route lets anyone set their own role or grant themselves
      provider-wide.
    - An adversarial review covers tenancy and auth. **Promote.**

- [ ] **S31 — A jobs queue, and TD-025's first half.**
  - **Depends on:** S30, D-065, D-066.
  - **Goal:** the background machinery every later session stands on.
  - **Exit criteria:**
    - **The jobs queue (D-065).**
      - A `jobs` table, workspace-scoped, claimed with `FOR UPDATE SKIP
        LOCKED`: a lease that expires, bounded retries with backoff, a dead
        state, an idempotency key unique per workspace, claim tokens.
      - The claim takes a scope (a workspace and, for an agent, its
        integrations), so S33's Edge Agents reuse it over HTTP.
      - A race test with two claimers proves exactly one claim. A result for a
        job the claimer no longer holds is refused.
      - The in-app worker starts in the lifespan beside the ingest task and is
        cancelled on shutdown.
    - **One client cannot starve the rest.** The claim order serves workspaces
      in turn, and a test proves it.
    - **TD-025, first half (D-066).**
      - Every execution attempt carries an idempotency key, handed to execute,
        undo and observe.
      - Pending proposals expire after a TTL. The new status goes into the one
        status-CHECK block, edited in place, and
        `test_startup_survives_every_status_a_proposal_can_be_in` passes.
    - An adversarial review covers the approvals state machine.

- [ ] **S32 — The connector contract, the SDK, and the catalogue.**
  - **Depends on:** S31, D-060, D-064.
  - **Goal:** a connector is a typed, versioned manifest plus Python handlers,
    written Python-first or in YAML, and both build to one canonical
    `manifest.json`. A workspace knows which connectors it has. Nothing a
    connector ships runs in the app process.
  - **Exit criteria:**
    - **The manifest v1 types** (D-064): identity; typed config with `secret`
      (a name) and `tls` (verify or a pin; off is unrepresentable); declared
      hosts; `test`, `fetch` and `actions[]` with typed params, output schemas,
      risk, a required dry run, undo with `cannot_restore`, `targets`; the
      routing key for a shared fetch.
    - **`validate_manifest` refuses with exact reasons**, table-driven, one
      case per rule (destructive without undo, an undeclared host, TLS off, a
      missing dry run, a shared fetch without a routing key, a bad name, an
      unknown type).
    - **A manifest action compiles to an `ActionSpec`** with distinct
      dispatcher callables and passes `validate_spec` unchanged; wire names are
      prefixed per integration; **the spec fingerprint includes the connector
      id and package hash.**
    - **The SDK** (a new package): decorators, a typed context, an HTTP client
      limited to declared hosts with TLS pinning, logs that redact secrets, and
      a local harness that runs a command against a recorded fixture.
      **`auspex-sdk build` turns Python or YAML into the same manifest**; for
      YAML it checks each named handler exists with matching parameters. A test
      builds the reference connector both ways and gets the same manifest.
    - **The catalogue.** An admin registers a package in a workspace,
      content-hashed; first-party is set by the catalogue. It answers TD-023's
      "which actions does this tenant have?". **Whether and how a provider
      offers its connectors to its clients' workspaces is S32's to propose and
      Burhan's to decide** (a package is code, not tenant data; which catalogue
      lists it is still tenancy).
    - **A reference connector passes the harness** (a mock HTTP service).
    - **Structural tests:** the app package never imports connector code; the
      core never reads YAML.

- [ ] **S33 — Integrations and the Edge Agent: "Test connection", end to
  end.**
  - **Depends on:** S32, D-062, D-063.
  - **Step 0:** if Burhan has given the QRadar's address, run the reachability,
    TLS and unauthenticated-API probes into
    docs/probes/2026-10-14-qradar-reachability.md before any agent code.
  - **Goal:** an admin configures an integration, enrolls an Edge Agent, and
    "Test connection" runs through a real agent container.
  - **Exit criteria:**
    - **Integrations.** A table and API, admin only, config validated against
      the manifest, secret fields stored as names only (D-063). An integration
      lives in one workspace (a shared SIEM's in the provider's).
    - **Edge Agent enrollment.** A one-time token becomes an agent credential,
      stored hashed, revocable, belonging to one workspace.
    - **The edge API.** An agent claims only its own integrations' jobs
      (S31's claim), posts results, heartbeats, and fetches packages **by
      hash**, verifying the hash before running. Core validates each result
      against the output schema before storing it.
    - **The agent image.** A new package `auspex/edge/`, a Dockerfile, a
      compose service under a dev profile; each command in a subprocess with a
      timeout. Env vars in `.env.example` and `docs/ENV_VARS.md`. The
      local-install mode is logged as debt (D-062).
    - **"Test connection" runs end to end** through the container against the
      reference connector. Heartbeats drive health: online, stale, offline. A
      missing secret fails naming the secret and the agent.
    - **Tests.** An agent cannot claim another workspace's job. A revoked agent
      is refused. An expired lease can be re-claimed. A result for a job the
      agent doesn't hold is refused. A hash mismatch is refused. No secret
      value appears in any response or log (scanned). A client admin cannot see
      or touch the provider workspace's integrations.
    - **Burhan's QRadar token** can be saved now, in the agent host's secret
      file, scoped to the lab domain (D-067); never in the chat or the repo.
    - An adversarial review covers tenancy and agent auth. **Promote.**

- [ ] **S34 — Integration actions through approvals, per-client policy, and
  the co-analyst.**
  - **Depends on:** S33, D-064, D-066.
  - **Goal:** an integration's actions take the path that exists: proposal (its
    card from a dry-run job), approval, claim, a job on the agent, the result,
    then settle or undo. Each client's approval policy decides who may approve.
  - **Exit criteria:**
    - **`EXECUTABLE_SYSTEMS` is widened by code and review (D-024).**
      `check_executable` refuses with a reason: agent offline, integration
      disabled, package hash changed, outside the integration's grants, outside
      the item's routing key, or approver not allowed by policy.
    - **Grant-checked scope (TD-025's second half, TD-023).** An action touches
      only what its integration declares; on a shared integration, only its
      item's routing key (`targets`).
    - **The per-client approval policy** is data per workspace (which roles, in
      which organization, may approve each risk level). D-024's claim path
      enforces it, and records the approver and their organization.
    - **A lost result never runs an action twice.** S31's key reaches the
      handler; a test drops the result, has the job re-claimed, and proves one
      execution.
    - **Every door works on an integration action:** undo, observe, abandon,
      keep, withdraw, and D-048's stale doors. Proposing needs the agent online
      (the dry run); offline is refused with the reason.
    - **The co-analyst is offered integration actions on the agent path**
      (D-045): tool text composed by code from the manifest's typed fields and
      capped. Customer-written text joins the rail's index; TD-044's
      calibration is re-run with it, and a floor moves only on that
      measurement.
    - **Live:** a chat turn proposes a reference-connector action; it is
      approved under the policy, runs on the agent, and is undone.
    - An adversarial review covers actions, the rail and tenancy.

- [ ] **S35 — Fetching: alerts from integrations, and routing for shared
  SIEMs.**
  - **Depends on:** S33 (S34 is not needed).
  - **Goal:** fetch commands run on a schedule, and what they return lands as
    alerts, each in exactly one workspace.
  - **Exit criteria:**
    - **Schedules and cursors.** Each integration's fetch schedule runs as jobs
      (S31), bounded by plan limits per client (D-026). Each integration has a
      cursor (the `ingest_state` pattern) that advances only after a page is
      stored.
    - **Routing.** A shared integration (in the provider's workspace) sends
      each item to the workspace its routing map names. **An unmapped item is
      quarantined in the provider's workspace and never lands in a default or
      guessed one.** Tested per case: mapped, unmapped, a mapping removed
      mid-fetch, two maps naming the same key.
    - **The `alerts` table.** Unique on workspace, integration and external id,
      so a re-fetch is a no-op. The raw payload is size-capped. Normalized
      through `AlertEnvelope`, scored by `score_alert`. A malformed item is
      quarantined, never a crash.
    - **Observables** are extracted and recorded in the alert's own workspace.
      **Whether they are enriched with third parties is a decision beside
      D-039, under D-061's region guard** (Burhan's call); off by default until
      he makes it.
    - **The alerts API** lists, filters, pages and gets alerts; the
      cross-client queue uses `enterable_workspaces`.
    - **Tests.** A re-fetch is idempotent. The cursor resumes after an agent
      restart. The plan-limit cap holds. Bad items are quarantined. A
      cross-tenant read is refused.
    - An adversarial review covers tenancy and routing.

- [ ] **S36 — QRadar, the first reference SIEM, on the Edge Agent, live on the
  lab domain.**
  - **Depends on:** S34 and S35, plus Burhan's QRadar token, saved per S33,
    scoped to the lab domain (D-067), never in the chat.
  - **Step 0:**
    - **Confirm Burhan's edition has domain management**, and that the lab
      domain exists with nothing but synthetic data. If it has no domain
      management, STOP: the choice returns to Burhan (D-067).
    - **The full QRadar API probe**, saved to `docs/probes/`, recording shapes
      and field names, never real values. It must answer: the API version and
      how a token is sent; the offense list, a single offense, its fields and
      timestamps, paging and filtering; **domains**: how an offense names its
      domain (the routing key); how an offense is noted, assigned and closed
      (closing reasons), and **whether a closed offense can be reopened**
      (whether closing is an undoable write, D-023); how its events and
      addresses are read, and what that costs; **a repeatable recipe for a
      synthetic offense** in the lab domain, working twice in a row.
  - **Goal:** QRadar's offenses arrive through an Edge Agent, routed to the
    right workspace, and the analyst can act back on QRadar.
  - **Exit criteria:**
    - **Built with the SDK only**, first-party, dogfooding "bring your own
      connector". Anything the SDK lacked is fixed in the SDK.
    - **Every QRadar endpoint used is in a probe record.** Nothing coded from
      memory.
    - **What it does.** Test connection; fetch offenses with the evidence the
      probe found affordable, routed by domain where configured; actions: add
      a note, assign, close with a closing reason; undo where QRadar allows.
      **An irreversible external write (closing, if it can't be reopened)
      needs a decision beside D-023** (Burhan's call).
    - **CI uses a QRadar fake built from synthetic recorded responses.**
    - **Live, on the lab domain only:** a synthetic offense becomes an alert in
      the right workspace; a note approved in Auspex appears in QRadar.
      Recorded in `docs/probes/`. **Promote.**

- [ ] **S37 — Cases.**
  - **Depends on:** S36.
  - **Goal:** the case is the analyst's unit of work.
  - **Exit criteria:**
    - **The model.** A `cases` table plus an append-only case event log, each
      event recording the actor and their home organization. Statuses and
      allowed transitions owned by code in one status-CHECK block; a closure
      needs a reason. Assignment only to users who may enter the case's
      workspace. Severity and priority.
    - **Linking.** A source case (a QRadar offense) creates a case directly.
      Other alerts group by a rule (a dedup key plus a time window) or by hand.
      An alert links to at most one case, only in its own workspace.
    - **Living Verdicts reach the case.** A verdict flip or a retro-hunt match
      on a linked observable appends a case event (the flagship's tie-in).
    - **The API.** List, filter, get, transition, assign, note and link, all
      scoped to the workspace; the cross-client list uses
      `enterable_workspaces`; a read returns the allowed next transitions, so
      the page never copies the state machine.
    - **Tests.** Every illegal transition is refused. Two analysts racing one
      transition: exactly one wins. Cross-workspace reads, links and
      assignments are refused. QRadar-born alerts become cases.
    - An adversarial review covers the state machine and tenancy.

- [ ] **S38 — Two-way sync with the SIEM, every write approved.**
  - **Depends on:** S37.
  - **Goal:** a case and its source offense stay consistent, and nothing writes
    to the customer's SIEM without an approval under the client's policy.
  - **Exit criteria:**
    - **Outbound.** A case change the source should know (close, assign, note)
      proposes the matching integration action; it runs only once approved.
    - **Inbound.** A change made in QRadar reaches the case on the next fetch,
      as a "changed in source" event.
    - **A conflict rule, decided and test-pinned** (a SIEM closure never
      silently overwrites a reopen in Auspex; both are recorded).
    - **No echo loop.** Auspex's own change coming back is recognised;
      test-pinned.
    - **Live, on the lab domain:** close in Auspex, approve, and the offense
      closes in QRadar; close in QRadar, and the case shows it.
    - An adversarial review covers actions. **Promote.**

- [ ] **S39 — The co-analyst on the case.**
  - **Depends on:** S37 (S38 helps, not required).
  - **Goal:** the co-analyst works a case: reads it, triages it, proposes
    actions inside it, never seeing another client.
  - **Exit criteria:**
    - **A case-scoped chat session** in the case's workspace, with READ tools
      for the case and its alerts. Tool results are data, unindexed (D-031). No
      tool reaches another workspace; a test proves it for a user who can enter
      both.
    - **A decision beside D-037 clause 1 and D-039** (Burhan's call): SIEM
      content reaches the agent path for the first time; which indicators in a
      case count as supplied; the bound stated.
    - **Residency.** A workspace whose region forbids the engine gets no turn,
      refused by code (D-061).
    - **Triage.** Where a verdict is code-decided (D-043's alert path), code
      decides it; the answer's contract is measured.
    - **Proposals** filed in the turn are linked to the case and appear in its
      event log.
    - **New directive text is measured into the rail** (TD-044); any
      classifier, resolver or mode change is judged on blind batteries.
    - **Spend per case and per client**, from D-054's ledger.
    - **Live on a QRadar-born case from the lab domain:** a triage, a proposed
      note, approval, the note visible in QRadar.
    - An adversarial review covers the rail, actions and tenancy.

- [ ] **S40 — SLAs, metrics per client and for the MSSP, closure, and the
  phase's demo.**
  - **Depends on:** S38 (S39 for the demo's co-analyst step).
  - **Goal:** the case path measures itself, per client and across an MSSP's
    clients, and a closure teaches the platform something.
  - **Exit criteria:**
    - **SLAs.** A policy per client workspace and severity (plan data, code
      limits, D-026). Time to acknowledge and to resolve from the event log; a
      breach becomes an event.
    - **The metrics API.** MTTA and MTTR; open cases by severity, status and
      assignee; per integration; per client, plus an MSSP rollup from
      `enterable_workspaces`.
    - **Closure feedback.** A closure reason (true positive, false positive,
      benign) reaches the linked observables' verdicts as a D-entry decides. A
      closure is an analyst's judgement, not a provider's signal, and stays in
      its own workspace.
    - **`./scripts/demo.sh` walks the case path end to end, hermetically** (the
      QRadar fake): an MSSP with two clients, an offense routed to one, a case,
      the co-analyst, an approval, and a closure synced back.
    - **Promote:** the phase's demo.

- [ ] **S41 — After the path: the Cloud Agent, sealed secrets, and a second
  SIEM.**
  - **Depends on:** S40. **Burhan re-scopes it at S40's end.**
  - **Goal:** Auspex runs first-party connectors for internet-reachable
    controls itself, and a second SIEM proves the contract generalizes.
  - **Exit criteria:**
    - **Sealed secrets for Cloud Agent integrations (D-063).** Envelope
      encryption under a master key from a documented env var; rotation; never
      logged, never returned.
    - **The Cloud Agent (D-062).** The same image, isolated: its own network,
      no database, limited egress, first-party connectors only.
    - **A second SIEM** (Elastic Security, Sentinel, or Burhan's pick), built
      with the same SDK and no core change. Any core change it needs is logged
      as a contract bug.
    - Customer code on Auspex infrastructure stays out unless a new D-entry
      brings it in.
