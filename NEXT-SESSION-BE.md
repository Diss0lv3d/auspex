# NEXT-SESSION-BE — track: backend · session: S29

_Paste everything below the first line of dashes into a fresh Claude Code
window opened in /home/burhan/auspex-new. **S29 opens the integration phase**
(Burhan, 2026-10-14: "lets work on integrating a SIEM on the platform and build
the incident management platform but i believe in order to do that we first
need to build an application module which relies on the build your own
integration module"). **Start it only after F3 has closed.** F3 is out with the
collaborator (D-059), and one session at a time spans both machines (D-051)._

_(S29 was re-scoped on 2026-10-14, in a planning window with no session id. Its
old goals wait in STATE.md: TD-036 is follow-up #3 and TD-044 is follow-up #4.
The review of S28's code stays as Step 0.)_

_Below the S29 prompt is the **backend plan for the whole phase, S29–S41**:
each session's goal, what it depends on, and its exit criteria. The front-end
half (F4–F9) is in `NEXT-SESSION-FE.md`, after F3. **`/session-end` writes the
next session's prompt from its entry in the plan, keeps the plan section, and
ticks the session it closed.** A change to the plan's order is Burhan's call._

---

SESSION S29 of Auspex, **backend track** (D-051). The working dir must be
/home/burhan/auspex-new. Run `/session-start be S29` first (the full ritual).
It reads `SESSION-RULES.md` (standing rules for every track) and STATE.md.

**S29 ships decisions, a spec and probes. No feature code.** Probe scripts
live under `docs/probes/`, as usual.

Step 0 (do BEFORE new scope):

1. **F3 must be closed and merged.** F3 closed 2026-10-14, and its work
   (with its session-end docs) is the PR from `f3-timeline-csp` into
   `staging`. Review and merge that PR first; until then, STATE.md on
   `staging` still shows F3 in flight. Run `git fetch` and read
   `origin/staging` before anything else (D-051, D-059).
2. **If STATE.md says the promote slate is not empty, `/promote` it.** Read the
   diff, not the list.
3. **An adversarial second-pass review of S28's own code.** Every integration
   action will run through this code, so it is read before anything is built on
   it. Each change was mutant-checked or battery-judged by its author, but
   nobody else has read it adversarially. Read and attack:
   - D-046: `_on_offer`, `_dispatch_within_budget` and the last-call notice
     (`auspex/agent/loop.py`), and the budget declaration
     (`auspex/agent/capabilities.py`). Check `run` and `run_stream` parity,
     and what a call refused for budget looks like on the page;
   - D-048: `run_stale_approval`, the shared `_run_claimed`, `withdraw`, and
     the queue's new clause (`auspex/actions/settlement.py`), plus the two
     routes. Check against every claim-token and `resolved_by` rule;
   - D-049: `record` in `enrich_observable` and the route's lambda. What gets
     written, for which workspace, and what the model is told on failure.
     (B2 has since added the `reputation: unknown` lines to the same payload,
     `fce2f55` and `58b45e4`; read the current version);
   - D-047: `_IDENTITY_RE` (`auspex/classify/classifier.py`);
   - D-050: `_NOTE_ASK_RE`, `_NOTE_REQUEST_RE`, the shortcut veto, and the
     `action_request` contract;
   - `e2af082`: JSON alert name precedence and the new keys;
   - the review fixes `831dedc` and `3a09fcd`.

   Same discipline as before: reproduce by execution first, fix with a test
   that fails pre-fix, and record what you clear in a probe record.

Goal (three items, in order):

1. **Design the integration phase, and put its decisions to Burhan.**
   Brainstorm first. The spec goes to
   `docs/superpowers/specs/<date>-integration-phase-design.md`. Inputs: the
   plan below, the incident-management line in IDEAS.md, and the code as it
   stands (the map under "Where the code stands" below; re-verify every
   citation before relying on it). Each decision becomes a D-entry once Burhan
   ratifies it:
   a. **Where integration code runs: the runner, and its two placements.**
      Burhan asked: "Some security controls are on-prem only, how do you
      propose to handle them considering we are a cloud based app". The
      runner proposal below is the answer to put to him. He ratifies it,
      changes it, or drops it.
   b. **The manifest contract, v1.** An integration is a typed, versioned
      manifest plus Python handlers (ADR 0007: the contract generates the
      config form, the action specs, the agent's tool text and the contract
      tests). Fields, versioning, and how a manifest action maps onto
      `ActionSpec` (`auspex/actions/types.py:164`) and passes `validate_spec`
      (`:239`).
   c. **Credential custody.** Edge-placed applications keep their credentials
      on the edge, and Auspex stores only a name. Cloud-placed ones (S41) need
      sealed secrets. No secret ever reaches an API response, a log, the page
      or the model.
   d. **Tenancy for MSSPs, and roles.** Burhan, 2026-10-14: "My other concern
      is MSSP clients and their multi tenancy problem". The MSSP proposal below
      is the answer to put to him. It decides where a role lives (on a
      membership, not on the user), so it must be ratified before S30 builds
      anything.
   e. **A jobs queue.** D-001 promised "jobs via SKIP LOCKED" and none exists.
      Background work is plain asyncio tasks in the lifespan
      (`auspex/app.py:41-95`). Fetch schedules and runner work need a real
      queue: lease, retry, dead state.
   f. **TD-023 and TD-025 come out of Deferred for this phase.** Edit
      SESSION-RULES.md in its own commit. TD-025's own fix order applies: TTL
      first, grant-checked scope before the first third-party action. The
      idempotency key is needed the day an action reaches a network, and S34
      is that day.
   g. **The vocabulary**, fixed once (see the plan's "Words" below):
      organization, workspace, membership, integration, application, runner,
      alert, incident.
2. **Where the QRadar lives (no credentials needed).** QRadar is the first SIEM,
   and Burhan already runs one on another machine (2026-10-14). He shares its
   credentials later, once the application module exists.
   - **Credentials never go into the chat**, and never into a probe record or
     a commit. They go into the gitignored `.env` under a documented name, or
     into the edge runner's own secret file once S33 exists. If a token is
     pasted into a conversation anyway, refuse to use it and ask Burhan to
     rotate it (org policy).
   - **Without credentials, probe and save to
     `docs/probes/<date>-qradar-reachability.md`:**
     - its address and port, and whether it is reachable from where the dev
       edge runner will run;
     - its TLS certificate. A self-signed certificate is the common case on an
       on-prem console. The runner then needs a pinned CA or certificate from
       the application's config, **never a silent "don't verify"**. That is an
       input to goal 1b;
     - whatever the API tells an unauthenticated caller (for example, its
       version).
   - **Ask Burhan what data it holds.** Lab or synthetic data only can reach
     the dev engine, which processes in Singapore. Any customer data, KSA data
     above all, never can. Record his answer in the probe.
   - **The full API probe** waits for the token. It runs at the first session's
     Step 0 after Burhan saves the token, and at the latest at S36's Step 0.
     The list it must answer is in S36's entry below.
3. **Re-check this plan against the spec.** Adjust S30–S41's goals and exit
   criteria in this file, and F4–F9 in `NEXT-SESSION-FE.md` (you may edit the
   other track's plan here, because the phase is one plan). A change of
   order goes to Burhan.

**The runner proposal (goal 1a; Burhan's call):**
- **One integration format and one runner image, with two placements.**
  - **Edge runner.** The customer (or their MSSP) runs it inside the network
    that holds the control, as a container or a service on a VM. It connects
    **out** to Auspex over HTTPS, and nothing connects in: no inbound firewall
    rule and no VPN. It long-polls for jobs on the applications assigned to it,
    runs each command locally against the on-prem control (the QRadar
    console, a firewall, AD, an EDR manager), and posts the result back.
  - **Cloud runner.** The same image, run by Auspex in an isolated container,
    for controls the internet can reach (SaaS SIEM and EDR APIs). It comes
    later in the plan (S41), with sealed secrets.
- **Who writes the code that runs where (v1).** A customer-written integration
  runs only on that customer's own edge runner: their code, on their
  infrastructure. Auspex-hosted runners run only first-party integrations
  Auspex has reviewed. Running customer code on Auspex infrastructure needs
  per-tenant sandboxes, and is a later D-entry, not v1. This is what keeps the
  tenant-isolation invariant intact without building a sandbox platform first.
- **Credentials.** An edge holds its own credentials, in its local secret file
  or vault, and Auspex stores only the secret's name. On-prem credentials never
  leave the customer's network.
- **What the core trusts.**
  - A runner enrolls with a one-time token. It then holds a runner credential,
    stored hashed (the `api_keys` pattern, `auspex/migrations.py:43`),
    revocable, and scoped to one owner (a workspace, or an MSSP's provider
    organization) and the applications assigned to it.
  - It can claim only its own jobs, and it can call no other API.
  - Core code validates every result against the command's output schema
    before anything is stored, shown or handed to the model (code over
    prompts).
- **Offline is a state, not an error.** Heartbeats drive the application's
  health. An approved action whose runner is offline waits: `check_executable`
  refuses with "runner offline", and D-048's stale doors apply. A fetch
  resumes from its cursor.
- **Retries are safe.** Every job carries an idempotency key (TD-025), so a
  result lost on its way back never runs an action twice.
- **Residency.** Raw on-prem data and credentials stay on the edge. Only what a
  fetch returns crosses to the cloud, and the integration can filter or redact
  before it does. Org policy on KSA-tenant data applies to whatever crosses.
- **The dev topology mirrors a customer's.** Burhan's QRadar, on another
  machine, stands in for "on-prem", and the edge runner reaches it over the
  network the way a customer's would.

**The MSSP proposal (goal 1d; Burhan's call):**
- **The workspace stays the isolation unit.** Every data row keeps its
  `workspace_id` (D-008, unchanged). An organization does not hold data. It
  only decides who may enter which workspace.
- **Organizations own workspaces.**
  - A direct customer is one organization with its workspace(s).
  - An MSSP is a **provider** organization. Each of its clients is a
    **client** organization, under that provider, with its own workspace(s).
- **Memberships carry the role.**
  - A user has one home organization, and a membership in each workspace they
    may enter. The role lives on the membership, not on `users.role`.
  - An MSSP assigns its analysts to client workspaces by membership. A
    client's own users get memberships only in their own organization's
    workspaces.
  - Identity becomes one user per person. Today the same email can exist once
    per workspace (`UNIQUE (workspace_id, email)`, `auspex/migrations.py:39`),
    and OAuth matches on email (TD-001, a hard gate before Google sign-in).
- **One workspace per token, minted only for a membership the user holds.**
  The JWT already carries one `wid` (`auspex/auth.py:48`). Switching client
  means minting a new token, and the switch is audited. Nothing takes a
  workspace or tenant id from a request body, a header or a query string
  (org invariant).
- **Cross-client views are computed from memberships, never unscoped.** The
  MSSP's "all my clients' incidents" queue filters on
  `workspace_id = ANY(<the caller's membership workspaces>)`, where code
  builds that list from memberships and never from input. A structural test
  refuses any alert or incident query that lacks a workspace filter.
- **The co-analyst never mixes clients.** A chat session belongs to one
  workspace. Its context, tools, spend and engine are that workspace's, even
  for an MSSP analyst who can enter both.
- **Shared SIEMs: one application, many clients.**
  - MSSPs often run one multi-tenant SIEM. QRadar has domains for this, and
    other SIEMs have their own equivalents.
  - Such an application belongs to the provider organization. A routing map,
    written by an MSSP admin, sends each item to a client workspace (for
    example, QRadar domain → workspace).
  - **An item with no mapping is quarantined at the provider level. It never
    lands in a guessed or default workspace.**
  - An action on a routed incident goes back through the same shared
    application, limited to that item's domain.
- **Who approves on whose systems is a per-client policy.** For example,
  MSSP analysts propose, and a destructive action on a client's own systems
  needs a client approver unless the contract says otherwise. The policy is
  data, and the gate is code: D-024's claim path reads it.
- **Residency per client.** A workspace carries its region. A KSA client's
  workspace never sends data to an engine or a runner outside KSA. Code
  refuses it; no prompt is involved. Engines are deployment-wide today
  (D-005). S29 decides whether the engine becomes per-workspace in this phase,
  or keeps that guard and defers the rest ("KSA residency routing" is in
  ROADMAP.md's Later).
- **Audit.** Every incident event and approval records the acting user and
  their home organization, so a client sees which MSSP analyst did what.
- **Herd Immunity stays deferred.** An MSSP's clients would be its natural
  first flock (k≥3), but nothing in this design shares data across
  workspaces until its own D-entry.

Candidates: none. S29 is goals 1–3. Ending early with the rituals done beats
starting S30's work.

Constraints: everything in `SESSION-RULES.md`.
- **No KSA-tenant or customer data in the dev stack, ever.** The dev engine
  processes in Singapore. What reaches it from QRadar is lab or synthetic data
  only (goal 2's answer).
- Decisions get made once. If the spec needs to overturn a D-entry (D-005,
  D-008, D-023, D-024, D-037 and D-039 are the likely ones), point at it and
  ask Burhan "overturn or drop?". Superseding is a new numbered entry.
- Do not start S30's work in S29, even where it looks small (scope lock).

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
| 2 | S30 | be | S29 | MSSP tenancy: organizations, provider workspaces, memberships, roles, one workspace per token, the region guard |
| 3 | F4 | fe | S30 | one shell for every page, role-aware, a workspace switcher |
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

### Where the code stands (2026-10-15; re-verify before relying on it)

- **Actions** (`auspex/actions/`):
  - `EXECUTABLE_SYSTEMS = frozenset({"auspex"})` (`settlement.py:50`), checked
    only in `check_executable`. Widening it is code plus review (D-024, D-066).
  - One built-in action, `annotate_observable` (`builtin.py`). `ActionSpec` is
    `types.py:164`, `validate_spec` `:239`.
  - The registry is in-process and workspace-blind (TD-023). No idempotency key
    and no proposal TTL (TD-025). Both left Deferred at S29 (D-066).
- **Tenancy** (`auspex/auth.py`):
  - A user row belongs to one workspace (`users.workspace_id` NOT NULL,
    `UNIQUE (workspace_id, email)`, `auspex/migrations.py:31-41`); dev logins
    all land in `default` (`get_or_create_user`, `auth.py:124`).
  - The JWT carries one `wid` (`auth.py:53`); `resolve_user` (`:80`) is the
    single chokepoint. `users.role` is never read. No organizations, no
    memberships.
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
- **Open bugs that touch this phase** (BUGS.md): B-010 (three classify rules
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

- [ ] **S30 — Tenancy for MSSPs: organizations, provider workspaces,
  memberships, roles, one workspace per token, and the region guard.**
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
