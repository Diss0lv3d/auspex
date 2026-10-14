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
at his request. **Scope lock: S29 works only on the prompt above.** The
sessions below are the plan, not S29's scope. Each session-end writes the next
session's prompt from its entry here, keeps this section, and ticks the closed
session._

### Words (S29 fixes them in a D-entry)

- **Organization**: who a customer is.
  - A direct customer is one organization.
  - An MSSP is a provider organization whose clients are client
    organizations.
  - An organization owns workspaces, and holds no data itself.
- **Workspace**: the isolation unit (D-008). Every data row belongs to exactly
  one.
- **Membership**: a user's right to enter one workspace, with a role.
- **Integration**: a package a customer, an MSSP or Auspex writes. It is a
  typed, versioned manifest plus Python handlers, built with the Auspex SDK.
  Its commands are `test` (connectivity), `fetch` (bring alerts or incidents
  in) and `action` (do something, under D-023's contract).
- **Application**: an integration configured for one owner, either a
  workspace or (for a shared SIEM) a provider organization. It carries config
  values, its credentials' names, its placement, its fetch schedule, its
  health, and, when shared, a routing map.
- **Runner**: what executes an application's commands. One image, placed on a
  customer's or MSSP's network (edge) or in Auspex's cloud (S41).
- **Alert**: one item a fetch brought in, normalized through `AlertEnvelope`
  (`auspex/alerts/envelope.py:59`), in exactly one workspace.
- **Incident**: the analyst's unit of work. It has a lifecycle, an assignee,
  an append-only event log, linked alerts, observables and proposals. This is
  not `investigations` (`auspex/migrations.py:204`), which is one pasted
  subject's ACH analysis.

### The order, both tracks (one session at a time, D-051)

| # | Session | Track | Depends on | Delivers |
|---|---|---|---|---|
| 0 | F3 | fe | — | closed 2026-10-14 by the collaborator (D-059); its PR `f3-timeline-csp` → `staging` is merged before S29 |
| 1 | S29 | be | F3 closed | the S28 review, decisions and spec, where the QRadar lives |
| 2 | S30 | be | S29 | MSSP tenancy: organizations, memberships, roles, one workspace per token |
| 3 | F4 | fe | S30 | one shell for every page, role-aware, a workspace switcher |
| 4 | S31 | be | S30 | jobs queue, TD-025's first half |
| 5 | S32 | be | S31 | the manifest contract, the SDK, the catalogues |
| 6 | S33 | be | S32 | applications and the edge runner, "Test connection" end to end |
| 7 | S34 | be | S33 | application actions through approvals and per-client policy |
| 8 | F5 | fe | S34 | integrations, applications, runners and approval policy admin |
| 9 | S35 | be | S33 | fetch schedules, cursors, alerts, routing for shared SIEMs |
| 10 | S36 | be | S34, S35 | QRadar on the edge runner, live |
| 11 | F6 | fe | S36 | the alerts queue, the quarantine and the routing map |
| 12 | S37 | be | S36 | incidents: lifecycle, events, assignment, linking |
| 13 | F7 | fe | S37 | incidents list and detail, across clients for an MSSP |
| 14 | S38 | be | S37 | two-way sync with the SIEM, every write approved |
| 15 | S39 | be | S37 | the co-analyst on the incident |
| 16 | F8 | fe | S38, S39 | sync state and the co-analyst inside the incident |
| 17 | S40 | be | S38 | SLAs, metrics per client and for the MSSP, closure, the demo |
| 18 | F9 | fe | S40 | the dashboard, polish, Burhan's hands-on walk |
| 19 | S41 | be | S40 | after the path: cloud runner, sealed secrets, a second SIEM |

- **The focus follows the order.** Each session-end sets STATE.md's focus to
  the next session's track, so F3's session-end moves it to the backend.
- **Promote at the milestones:** S30 (tenancy), S33 ("Test connection" end to
  end), S36 (QRadar data in), S38 (the loop closed), and S40 (the phase's
  demo).

### Where the code stands (2026-10-14; re-verify before relying on it)

- **Actions** (`auspex/actions/`):
  - `EXECUTABLE_SYSTEMS = frozenset({"auspex"})` (`settlement.py:50`), checked
    only in `check_executable`. Widening it is code plus review (D-024).
  - There is one built-in action, `annotate_observable` (`builtin.py`).
  - The registry is in-process and workspace-blind (TD-023).
  - There is no idempotency key and no proposal TTL (TD-025).
- **Tenancy** (`auspex/auth.py`):
  - A user row belongs to one workspace (`users.workspace_id` NOT NULL,
    `UNIQUE (workspace_id, email)`, `auspex/migrations.py:31-41`), and dev
    logins all land in `default` (`get_or_create_user`, `auth.py:124`).
  - The JWT carries one `wid` (`auth.py:48`), and `resolve_user` (`:80`) is
    the single chokepoint.
  - `users.role` is never read. There are no organizations and no
    memberships.
- **Secrets.** Provider keys are env-only and deployment-wide
  (`auspex/config.py`). There is no per-workspace secret storage.
- **Background work** is asyncio tasks in the lifespan (`auspex/app.py:41-95`).
  There is no jobs table. `ingest_state` (`auspex/migrations.py:173`) is the
  pattern for a per-source cursor.
- **Schema**: one list, `SCHEMA_V0` (`auspex/migrations.py`). Every table
  carries `workspace_id` (D-008), and `tests/test_schema.py` enforces it.
  Organization-level tables (provider applications, routing maps) are the
  first that would not. That exemption is a decision, and the test must name
  each exempt table.
- **Alerts** arrive only pasted into chat. `normalize` and `score_alert` live
  in `auspex/alerts/`.
- **Enrichment providers** (`auspex/enrich/providers/base.py:24`) are the
  nearest existing shape to an integration.
- **Compose** runs `app`, `postgres` and `opensearch`. There is no worker and
  no runner.

### Standing for every session in this phase

- **SESSION-RULES.md applies unchanged.** In particular, a change to the rail,
  an action, tenancy or the approvals state machine gets a read-only
  adversarial review by a fresh agent before the close. In this phase that is
  nearly every session.
- **Tenant isolation is an invariant** (org policy). No route takes a
  workspace or tenant id from input. A cross-client view is computed from
  memberships by code. Every new table and route gets a cross-tenant test.
- **CI stays hermetic.** QRadar is reached only through a fake built from
  recorded probe responses, never the live machine. Live checks are separate,
  and recorded in `docs/probes/` with no secrets and no non-synthetic data.
- **Anything a SIEM sends is attacker-controlled.** It reaches the model only
  through the data channel, under the input guard (D-027). It reaches the
  page only as text.
- **Every write to a customer system goes through an approval** (D-014,
  D-024). There is no auto-run, whatever a fetch says.
- **Specs over prompts.** The manifest generates forms, action specs, the
  agent's tool text and contract tests. Nothing is written twice by hand.
- New package → `pyproject.toml` and the Dockerfile skeleton. New env var →
  `.env.example` and `docs/ENV_VARS.md` at birth.

### Sessions

- [ ] **S29 — The S28 review, the phase's decisions and spec, and where the
  QRadar lives.** (the prompt above)
  - **Exit criteria:**
    - The S28 review is recorded in `docs/probes/`. Each finding is either
      fixed with a test that failed first, or logged.
    - The spec is committed. The D-entries from goal 1 (a–g) are ratified by
      Burhan, or explicitly parked with his reason. Decision 1d (MSSP
      tenancy) is not parked, because S30 builds on it.
    - SESSION-RULES.md's Deferred list no longer holds TD-023 and TD-025, in
      its own commit.
    - The QRadar reachability probe is saved: address, TLS, and Burhan's
      answer on its data. No credential appears anywhere in the repo.
    - The plan below, and F4–F9, are re-checked against the spec.

- [ ] **S30 — Tenancy for MSSPs: organizations, memberships, roles, one
  workspace per token.**
  - **Depends on:** S29's decision 1d.
  - **Goal:** an MSSP analyst can enter the client workspaces they are
    assigned to, one at a time. A client's users see only their own. Every
    query is still scoped to one workspace.
  - **Exit criteria:**
    - **The model.**
      - `organizations` (direct, provider, client, where a client points to
        its provider) and `workspaces.org_id`.
      - `memberships` (user × workspace × role).
      - One user per person, and the identity question settled (TD-001's
        hard gate stays in force for Google sign-in).
      - Existing rows migrate. The `default` workspace and every dev login
        keep working, and `__deployment__` stays reserved (D-035).
    - **Tokens and switching.**
      - A token names one workspace, and is minted only for a membership the
        user holds.
      - A switch route mints a new token, and the switch is audited.
      - `GET /api/auth/me` returns the user, their organization, the active
        workspace, its role, and the workspaces they may switch to. F4 needs
        it.
    - **Roles, enforced.** A `require_role` dependency sits beside
      `resolve_user`, with the role read from the membership.
    - **Structural tests.**
      - Every admin route refuses an analyst.
      - No route reads a workspace id from input.
      - Every new table is workspace-scoped, or a named, decided exemption.
    - **Cross-tenant tests.**
      - A client user cannot reach a sibling client's workspace, nor the
        provider's own.
      - An MSSP analyst without a membership cannot enter a client.
      - A removed membership ends access at the next request, not when the
        token expires.
      - No route lets anyone set their own role.
    - An adversarial review covers tenancy and auth. **Promote.**

- [ ] **S31 — A jobs queue, and TD-025's first half.**
  - **Depends on:** S30, and S29's decisions 1e and 1f.
  - **Goal:** the background machinery every later session stands on.
  - **Exit criteria:**
    - **The jobs queue.**
      - A `jobs` table, workspace-scoped. Claims use
        `FOR UPDATE SKIP LOCKED`, with a lease that expires, bounded retries
        with backoff, and a dead state.
      - A race test with two claimers proves exactly one claim.
      - Its worker starts in the lifespan beside the ingest task and is
        cancelled on shutdown.
    - **One client cannot starve the rest.** The claim order keeps one busy
      workspace from crowding out the others, and a test proves it.
    - **TD-025, first half.**
      - Every execution attempt carries an idempotency key, handed to
        execute, undo and observe.
      - Pending proposals expire after a TTL. The new status goes into the
        one status-CHECK block, edited in place, and
        `test_startup_survives_every_status_a_proposal_can_be_in` passes.
    - An adversarial review covers the approvals state machine.

- [ ] **S32 — The integration contract, the SDK, and the catalogues.**
  - **Depends on:** S31, and S29's decisions 1b and 1g.
  - **Goal:** an integration is a typed, versioned manifest plus Python
    handlers, written with an in-repo SDK. A workspace, and an MSSP for all
    of its clients, knows which integrations it has. Nothing an integration
    ships runs in the app process.
  - **Exit criteria:**
    - **The manifest v1 types.**
      - Identity and version.
      - A config schema whose secret fields are marked, and TLS settings that
        can pin a CA or certificate (S29's reachability probe).
      - Declared hosts.
      - The commands `test`, `fetch` and `action`, each with typed params
        and an output schema. Actions carry D-023's risk, dry run and undo.
      - For a fetch that serves many clients, the field that routes an item.
    - **`validate_manifest` refuses with exact reasons.** The tests are
      table-driven, one case per rule, including destructive-without-undo, an
      undeclared host, and TLS verification turned off without a pin.
    - **A manifest action maps onto `ActionSpec` and passes `validate_spec`**
      unchanged.
    - **The SDK** (a new package). Command decorators; a typed context; an
      HTTP client limited to the declared hosts; logs that redact secrets; and
      a local harness that runs a command against a recorded fixture. That
      harness is how a customer tests their integration before uploading it.
    - **The catalogues.**
      - An admin registers an integration package, in a workspace, or in a
        provider organization to share with all of its clients.
      - Packages are content-hashed, like `spec_fingerprint`, so a changed
        package is a new version.
      - They answer TD-023's "which actions does this tenant have?".
    - **A reference integration passes the harness** (a mock HTTP service,
      used in tests).
    - **A structural test:** the app package never imports integration code.

- [ ] **S33 — Applications and the edge runner: "Test connection", end to
  end.**
  - **Depends on:** S32, and S29's decisions 1a and 1c.
  - **Goal:** an admin configures an application, assigns it to an edge
    runner, and "Test connection" runs through a real runner container.
  - **Exit criteria:**
    - **Applications.**
      - A table and API, admin only, with config validated against the
        manifest.
      - The owner is a workspace, or a provider organization for a shared
        SIEM.
      - Credentials are custodied per S29 (the cloud stores names only).
      - No secret value appears in any API response or log. Tests scan both.
    - **Runner enrollment.** A one-time token becomes a runner credential,
      stored hashed, revocable, and scoped to one owner.
    - **The runner API.**
      - A runner can claim jobs only for its own applications, post results,
        and send heartbeats.
      - Core code validates each result against the output schema before
        storing it.
    - **The runner image.** A new package and Dockerfile, and a compose
      service under a dev profile. Its env vars are in `.env.example` and
      `docs/ENV_VARS.md`.
    - **"Test connection" runs end to end** through the container against the
      reference integration. Heartbeats drive the application's health:
      online, stale, offline.
    - **Tests.**
      - A runner cannot claim another owner's job.
      - A revoked runner is refused.
      - An expired lease can be re-claimed.
      - A result for a job the runner doesn't hold is refused.
      - A client's admin cannot see or touch the provider's applications.
    - **Burhan's QRadar credentials** can be saved now, into the edge runner's
      secret file. The full QRadar API probe then runs at the next session's
      Step 0.
    - An adversarial review covers tenancy and runner auth. **Promote.**

- [ ] **S34 — Application actions through approvals, per-client policy, and
  the agent.**
  - **Depends on:** S33.
  - **Goal:** an application's actions take the path that exists: proposal,
    approval, claim, a job on the runner, the result, then settle or undo.
    Each client's approval policy decides who may approve.
  - **Exit criteria:**
    - **`EXECUTABLE_SYSTEMS` is widened by code and review (D-024).**
      - An action is executable only on an enabled application the
        incident's workspace may use, whose runner is online.
      - `check_executable` refuses the rest with a reason: runner offline,
        application disabled, package version changed, or approver not
        allowed by policy.
    - **Grant-checked scope (TD-025's second half, TD-023).**
      - An action touches only what its application declares.
      - On a shared application, an action touches only the item's own
        routing key (its QRadar domain, say).
    - **The per-client approval policy.**
      - It is data per workspace: which roles, in which organization, may
        approve each risk level.
      - D-024's claim path enforces it, and the approver and their
        organization are recorded.
    - **A lost result never runs an action twice.** S31's key reaches the
      handler. A test drops the result, has the job re-claimed, and proves
      one execution.
    - **Every door works on an application action:** undo, observe, abandon,
      keep, withdraw, and D-048's stale doors.
    - **The agent is offered application actions on the chat agent path**
      (D-045).
      - Their tool text is composed by code from the manifest's typed fields,
        and capped.
      - Customer-written text joins the rail's index. Re-run TD-044's
        calibration with it, and move a floor only on that measurement.
    - **Live:** a chat turn proposes a reference-integration action. It is
      approved under the policy, runs on the runner, and is undone.
    - An adversarial review covers actions, the rail and tenancy.

- [ ] **S35 — Fetching: alerts from applications, and routing for shared
  SIEMs.**
  - **Depends on:** S33 (S34 is not needed).
  - **Goal:** fetch commands run on a schedule, and what they return lands as
    alerts, each in exactly one workspace.
  - **Exit criteria:**
    - **Schedules and cursors.**
      - Each application's fetch schedule runs as jobs (S31), bounded by plan
        limits per client (D-026: the plan is data, the limits are code).
      - Each application has a cursor (the `ingest_state` pattern) that
        advances only after a page is stored.
    - **Routing.**
      - A shared application's items go to the workspace its routing map
        names.
      - **An unmapped item is quarantined at the provider level. It never
        lands in a default or guessed workspace.** Tested per case: mapped,
        unmapped, a mapping removed mid-fetch, two maps naming the same key.
    - **The `alerts` table.**
      - It is unique on workspace, application and external id, so a
        re-fetch is a no-op.
      - The raw payload is size-capped. Alerts are normalized through
        `AlertEnvelope` and scored by `score_alert`.
      - A malformed item is quarantined. It never crashes the fetch.
    - **Observables.** Indicators are extracted from alerts and recorded in
      the alert's own workspace. **Whether they are enriched with third
      parties is a decision beside D-039** (Burhan's call). It is off by
      default until he makes it.
    - **The alerts API** lists, filters, pages and gets alerts. Its
      cross-client queue for an MSSP is built from memberships.
    - **Tests.** A re-fetch is idempotent. The cursor resumes after a runner
      restart. The plan-limit cap holds. Bad items are quarantined. A
      cross-tenant read is refused.
    - An adversarial review covers tenancy and routing.

- [ ] **S36 — QRadar, the first reference SIEM, on the edge runner, live.**
  - **Depends on:** S34 and S35, plus Burhan's QRadar credentials (saved per
    S33, never in the chat).
  - **Step 0, if not already done:** the full QRadar API probe, saved to
    `docs/probes/`. It must answer:
    - the API version and how a token is sent;
    - the offense list, a single offense, and its fields and timestamps;
      paging and filtering;
    - **domains and tenants**: whether they are configured, and how an offense
      names its domain (the routing key for an MSSP);
    - how an offense is noted, assigned and closed (closing reasons), and
      **whether a closed offense can be reopened**. That decides whether
      closing is an undoable write (D-023);
    - how an offense's events and addresses are read, and what that costs;
    - **a repeatable recipe for a synthetic offense**: synthetic events sent
      to it that trip a rule. It must work twice in a row.
  - **Goal:** QRadar's offenses arrive through an edge runner, routed to the
    right workspace, and the analyst can act back on QRadar.
  - **Exit criteria:**
    - **Built with the SDK only.** It is first-party, and it dogfoods "bring
      your own integration". Anything the SDK lacked is fixed in the SDK, not
      worked around in the integration.
    - **Every QRadar endpoint used is in a probe record.** Nothing is coded
      from memory.
    - **What it does.**
      - Test connection.
      - Fetch offenses, with the evidence the probe found affordable. When
        domains are configured, an offense routes by its domain (S35's map).
      - Actions: add a note, assign, and close with a closing reason.
      - Undo where QRadar allows it. **An irreversible external write
        (closing, if it can't be reopened) needs a decision beside D-023**
        (Burhan's call).
    - **CI uses a QRadar fake built from the recorded responses** (synthetic
      data).
    - **Live on Burhan's QRadar.**
      - A synthetic offense becomes an alert in the right workspace.
      - A note approved in Auspex appears in QRadar.
      - Recorded in `docs/probes/`. **Promote.**

- [ ] **S37 — Incidents.**
  - **Depends on:** S36.
  - **Goal:** the incident is the analyst's unit of work.
  - **Exit criteria:**
    - **The model.**
      - An `incidents` table plus an append-only incident event log. Each
        event records the actor and the actor's home organization.
      - Statuses and allowed transitions are owned by code, in one
        status-CHECK block, like proposals. A closure needs a reason.
      - Assignment goes only to users with a membership in the incident's
        workspace. Incidents carry severity and priority.
    - **Linking.**
      - A source-native incident (a QRadar offense) creates an incident
        directly.
      - Other alerts are grouped by a rule (a dedup key plus a time window),
        or by hand.
      - An alert links to at most one incident, and only in its own
        workspace.
    - **Living Verdicts reach the incident.** A verdict flip or a retro-hunt
      match on a linked observable appends an incident event. This is the
      flagship's tie-in.
    - **The API.**
      - List, filter, get, transition, assign, note and link, all scoped to
        the workspace.
      - An MSSP's cross-client list is built from memberships.
      - A read returns the allowed next transitions, so the page renders
        from the API and never copies the state machine.
    - **Tests.**
      - Every illegal transition is refused.
      - Two analysts racing one transition: exactly one wins (a conditional
        UPDATE).
      - Cross-workspace reads, links and assignments are refused.
      - QRadar-born alerts become incidents.
    - An adversarial review covers the state machine and tenancy.

- [ ] **S38 — Two-way sync with the SIEM, every write approved.**
  - **Depends on:** S37.
  - **Goal:** an incident and its source offense stay consistent, and nothing
    writes to the customer's SIEM without an approval under the client's
    policy.
  - **Exit criteria:**
    - **Outbound.** An incident change the source should know about (close,
      assign, note) proposes the matching application action. It runs only
      once it is approved (D-014, S34's policy).
    - **Inbound.** A change made in QRadar (closed, reassigned) reaches the
      incident on the next fetch, as a "changed in source" event.
    - **A conflict rule, decided and test-pinned.** For example, a SIEM
      closure never silently overwrites a reopen in Auspex; both are recorded.
    - **No echo loop.** Auspex's own change, coming back on the next fetch, is
      recognised. Test-pinned.
    - **Live.**
      - Close in Auspex, approve, and the offense is closed in QRadar.
      - Close in QRadar, and the incident shows it.
    - An adversarial review covers actions. **Promote.**

- [ ] **S39 — The co-analyst on the incident.**
  - **Depends on:** S37 (S38 is helpful, not required).
  - **Goal:** the co-analyst works an incident. It reads the incident, triages
    it, and proposes actions inside it, never seeing another client.
  - **Exit criteria:**
    - **An incident-scoped chat session**, in the incident's workspace, with
      READ tools for the incident and its alerts. Tool results are data,
      unindexed (D-031). No tool reaches another workspace, and a test proves
      it for a user who holds both memberships.
    - **A decision beside D-037 clause 1 and D-039** (Burhan's call).
      - SIEM content is attacker-controlled, and here it reaches the agent
        path for the first time.
      - Which indicators in an incident count as supplied?
      - The bound is stated.
    - **Residency.** A workspace whose region forbids the configured engine
      gets no turn, refused by code (S29's decision 1d).
    - **Triage.** Where a verdict is code-decided (D-043's alert path), code
      decides it. The answer's contract is measured.
    - **Proposals.** Those filed in the turn are linked to the incident and
      appear in its event log.
    - **New directive text is measured into the rail.** Re-run TD-044's
      calibration; floors move only on that measurement. Any classifier,
      resolver or mode change is judged on batteries written blind
      (SESSION-RULES.md).
    - **Spend per incident and per client**, from D-054's ledger.
    - **Live on a QRadar-born incident** (lab data only). A triage, a
      proposed note, approval, and the note visible in QRadar.
    - An adversarial review covers the rail, actions and tenancy.

- [ ] **S40 — SLAs, metrics per client and for the MSSP, closure, and the
  phase's demo.**
  - **Depends on:** S38 (S39 for the demo's co-analyst step).
  - **Goal:** the incident path measures itself, per client and across an
    MSSP's clients, and a closure teaches the platform something.
  - **Exit criteria:**
    - **SLAs.** A policy per client workspace and severity (plan data, code
      limits, D-026). Time to acknowledge and time to resolve come from the
      event log. A breach becomes an event.
    - **The metrics API.**
      - MTTA and MTTR; open incidents by severity, status and assignee; per
        application.
      - Per client, plus an MSSP rollup built from memberships.
    - **Closure feedback.** A closure reason (true positive, false positive,
      benign) reaches the linked observables' verdicts as a D-entry decides.
      A closure is an analyst's judgement, not a provider's signal, and it
      stays in its own workspace.
    - **`./scripts/demo.sh` walks the incident path end to end, hermetically**
      (the QRadar fake): an MSSP with two clients, an offense routed to one
      of them, an incident, the co-analyst, an approval, and a closure synced
      back.
    - **Promote:** the phase's demo.

- [ ] **S41 — After the path: the cloud runner, sealed secrets, and a second
  SIEM.**
  - **Depends on:** S40. **Burhan re-scopes it at S40's end.**
  - **Goal:** Auspex runs first-party integrations for internet-reachable
    controls itself, and a second SIEM proves the contract generalizes.
  - **Exit criteria:**
    - **Sealed secrets for cloud-placed applications.** Envelope encryption,
      with a master key from a documented env var. Keys rotate, and a secret
      is never logged and never returned.
    - **The cloud runner.** The same image, isolated: its own network, no
      database, limited egress. It runs first-party integrations only.
    - **A second SIEM** (Elastic Security, Sentinel, or Burhan's pick), built
      with the same SDK and no core change. Any core change it needs is logged
      as a contract bug.
    - Customer code on Auspex infrastructure stays out, unless a new D-entry
      brings it in.
