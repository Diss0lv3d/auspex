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

_Below the S29 prompt is the **backend plan for the whole phase, S29–S40**:
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

1. **F3 must be closed.** STATE.md's Tracks table must show F3 as the front
   end's last closed session. If it doesn't, STOP: the collaborator may be
   working on `staging` (D-051, D-059). Run `git fetch` and read
   `origin/staging` before anything else, because her commits land there.
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
      proposal below is the answer to put to him. He ratifies it, changes it,
      or drops it.
   b. **The manifest contract, v1.** An integration is a typed, versioned
      manifest plus Python handlers (ADR 0007: the contract generates the
      config form, the action specs, the agent's tool text and the contract
      tests). Fields, versioning, and how a manifest action maps onto
      `ActionSpec` (`auspex/actions/types.py:164`) and passes `validate_spec`
      (`:239`).
   c. **Credential custody.** Edge-placed applications keep their credentials
      on the edge, and Auspex stores only a name. Cloud-placed ones (S40) need
      sealed secrets. No secret ever reaches an API response, a log, the page
      or the model.
   d. **Workspace roles.** `users.role` exists (`auspex/migrations.py:37`) and
      nothing reads it. Who may install integrations, configure applications
      and enroll runners (admin), and who works incidents (analyst). How the
      first admin of a workspace comes to exist.
   e. **A jobs queue.** D-001 promised "jobs via SKIP LOCKED" and none exists.
      Background work is plain asyncio tasks in the lifespan
      (`auspex/app.py:41-95`). Fetch schedules and runner work need a real
      queue: lease, retry, dead state.
   f. **TD-023 and TD-025 come out of Deferred for this phase.** Edit
      SESSION-RULES.md in its own commit. TD-025's own fix order applies: TTL
      first, grant-checked scope before the first third-party action. The
      idempotency key is needed the day an action reaches a network, and S33
      is that day.
   g. **The vocabulary**, fixed once (see the plan's "Words" below):
      integration, application, runner, alert, incident.
2. **QRadar CE, a reality probe (rule 4: probe the live thing first).** QRadar
   is the first SIEM (Burhan, 2026-10-14). Stand QRadar Community Edition up
   on the dev box as a KVM VM: an ISO plus a 3-month key from IBM's CE page,
   free and unsupported. **Check IBM's current requirements before
   downloading.** A 2024 IBM blog says 24 GB RAM, 250 GB disk and 6 cores. The
   dev box has 30 GB RAM, 24 cores and KVM, so the Auspex stack and the VM
   together are tight. The download can be export-restricted in some regions.
   Save the probe to `docs/probes/<date>-qradar-ce.md`. It must answer:
   - the version and the API version it serves; how an API token is created
     and sent;
   - the offense list, a single offense, and its fields and timestamps;
     paging and filtering;
   - how an offense is noted, assigned and closed (closing reasons), and
     **whether a closed offense can be reopened**. That decides whether
     closing is an undoable write (D-023);
   - how an offense's events and addresses are read, and what that costs
     (Ariel searches, if the API runs them that way);
   - **a repeatable recipe for a synthetic offense**: synthetic events sent
     to it that trip a rule. Every later QRadar session needs this. Synthetic
     data only, never a customer's.

   **If it can't run** (RAM, the download, the license), STOP, write a STATE.md
   blocker, and put it to Burhan: a bigger host, a rented VM (it costs money),
   or another first SIEM. No third attempt in the same session (thrash brake).
3. **Re-check this plan against the spec.** Adjust S30–S40's goals and exit
   criteria in this file, and F4–F9 in `NEXT-SESSION-FE.md` (you may edit the
   other track's plan here, because the phase is one plan). A change of
   order goes to Burhan.

**The runner proposal (goal 1a; Burhan's call):**
- **One integration format and one runner image, with two placements.**
  - **Edge runner.** The customer runs it inside their own network, as a
    container or a service on a VM. It connects **out** to Auspex over HTTPS,
    and nothing connects in: no inbound firewall rule and no VPN. It long-polls
    for jobs on the applications assigned to it, runs each command locally
    against the on-prem control (the QRadar console, a firewall, AD, an EDR
    manager), and posts the result back.
  - **Cloud runner.** The same image, run by Auspex in an isolated container,
    for controls the internet can reach (SaaS SIEM and EDR APIs). It comes
    later in the plan (S40), with sealed secrets.
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
    revocable, and scoped to one workspace and its assigned applications.
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
- **The dev topology mirrors a customer's.** The QRadar VM on Burhan's box
  stands in for "on-prem", and the edge runner (a compose service) reaches it
  the way a customer's would.

Candidates: none. S29 is goals 1–3. Ending early with the rituals done beats
starting S30's work.

Constraints: everything in `SESSION-RULES.md`.
- **No KSA-tenant or customer data in the dev stack, ever.** The dev engine
  processes in Singapore. QRadar's data is synthetic.
- Decisions get made once. If the spec needs to overturn a D-entry (D-023,
  D-024, D-037, D-039 are the likely ones), point at it and ask Burhan
  "overturn or drop?". Superseding is a new numbered entry.
- Do not start S30's work in S29, even where it looks small (scope lock).

---

## The integration phase — backend plan (S29–S40)

_Written 2026-10-14 (Burhan, planning window). **Scope lock: S29 works only on
the prompt above.** The sessions below are the plan, not S29's scope. Each
session-end writes the next session's prompt from its entry here, keeps this
section, and ticks the closed session._

### Words (S29 fixes them in a D-entry)

- **Integration**: a package a customer or Auspex writes. It is a typed,
  versioned manifest plus Python handlers, built with the Auspex SDK. Its
  commands are `test` (connectivity), `fetch` (bring alerts or incidents in)
  and `action` (do something, under D-023's contract).
- **Application**: an integration configured in one workspace, with its config
  values, its credentials' names, its placement (which runner), its fetch
  schedule, and its health.
- **Runner**: what executes an application's commands. One image, placed on a
  customer's network (edge) or in Auspex's cloud (S40).
- **Alert**: one item a fetch brought in, normalized through `AlertEnvelope`
  (`auspex/alerts/envelope.py:59`).
- **Incident**: the analyst's unit of work. It has a lifecycle, an assignee,
  an append-only event log, linked alerts, observables and proposals. This is
  not `investigations` (`auspex/migrations.py:204`), which is one pasted
  subject's ACH analysis.

### The order, both tracks (one session at a time, D-051)

| # | Session | Track | Depends on | Delivers |
|---|---|---|---|---|
| 0 | F3 | fe | — | in flight with the collaborator (D-059) |
| 1 | S29 | be | F3 closed | the S28 review, decisions and spec, the QRadar CE probe |
| 2 | S30 | be | S29 | jobs queue, roles, TD-025's first half |
| 3 | F4 | fe | S30 | one shell for every page, role-aware |
| 4 | S31 | be | S30 | the manifest contract, the SDK, a workspace registry |
| 5 | S32 | be | S31 | applications and the edge runner, "Test connection" end to end |
| 6 | F5 | fe | S32 | integrations, applications and runners admin pages |
| 7 | S33 | be | S32 | application actions through approvals, offered to the agent |
| 8 | S34 | be | S32 | fetch schedules, cursors, the alerts table |
| 9 | S35 | be | S33, S34 | QRadar on the edge runner, live |
| 10 | F6 | fe | S35 | the alerts queue |
| 11 | S36 | be | S35 | incidents: lifecycle, events, assignment, linking |
| 12 | F7 | fe | S36 | incidents list and detail |
| 13 | S37 | be | S36 | two-way sync with the SIEM, every write approved |
| 14 | S38 | be | S36 | the co-analyst on the incident |
| 15 | F8 | fe | S37, S38 | sync state and the co-analyst inside the incident |
| 16 | S39 | be | S37 | SLAs, metrics, closure feedback, the demo |
| 17 | F9 | fe | S39 | the dashboard, polish, Burhan's hands-on walk |
| 18 | S40 | be | S39 | after the path: cloud runner, sealed secrets, a second SIEM |

- **The focus follows the order.** Each session-end sets STATE.md's focus to
  the next session's track, so F3's session-end moves it to the backend.
- **Promote at the milestones:** S32 ("Test connection" end to end), S35
  (QRadar data in), S37 (the loop closed), and S39 (the phase's demo).

### Where the code stands (2026-10-14; re-verify before relying on it)

- **Actions** (`auspex/actions/`):
  - `EXECUTABLE_SYSTEMS = frozenset({"auspex"})` (`settlement.py:50`), checked
    only in `check_executable`. Widening it is code plus review (D-024).
  - There is one built-in action, `annotate_observable` (`builtin.py`).
  - The registry is in-process and workspace-blind (TD-023).
  - There is no idempotency key and no proposal TTL (TD-025).
- **Tenancy** (`auspex/auth.py:80`, `resolve_user`):
  - Every user belongs to one workspace, and dev logins all land in
    `default` (`auth.py:124`).
  - `users.role` is never read. There are no memberships.
- **Secrets.** Provider keys are env-only and deployment-wide
  (`auspex/config.py`). There is no per-workspace secret storage.
- **Background work** is asyncio tasks in the lifespan (`auspex/app.py:41-95`).
  There is no jobs table. `ingest_state` (`auspex/migrations.py:173`) is the
  pattern for a per-source cursor.
- **Schema**: one list, `SCHEMA_V0` (`auspex/migrations.py`). Every table
  carries `workspace_id` (D-008), and `tests/test_schema.py` enforces it.
- **Alerts** arrive only pasted into chat. `normalize` and `score_alert` live
  in `auspex/alerts/`.
- **Enrichment providers** (`auspex/enrich/providers/base.py:24`) are the
  nearest existing shape to an integration.
- **Compose** runs `app`, `postgres` and `opensearch`. There is no worker and
  no runner.

### Standing for every session in this phase

- **SESSION-RULES.md applies unchanged.** In particular, a change to the rail,
  an action, tenancy or the approvals state machine gets a read-only
  adversarial review by a fresh agent before the close.
- **CI stays hermetic.** QRadar is reached only through a fake built from
  recorded probe responses, never the live VM. Live checks are separate, and
  recorded in `docs/probes/`.
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

- [ ] **S29 — The S28 review, the phase's decisions and spec, and QRadar CE
  probed live.** (the prompt above)
  - **Exit criteria:**
    - The S28 review is recorded in `docs/probes/`. Each finding is either
      fixed with a test that failed first, or logged.
    - The spec is committed. The D-entries from goal 1 (a–g) are ratified by
      Burhan, or explicitly parked with his reason.
    - SESSION-RULES.md's Deferred list no longer holds TD-023 and TD-025, in
      its own commit.
    - QRadar CE answers its API on the dev box, with the probe saved and a
      synthetic-offense recipe that works twice in a row. **Or** a STATE.md
      blocker records why it can't, with Burhan's alternative.
    - The plan below, and F4–F9, are re-checked against the spec.

- [ ] **S30 — Foundations: a jobs queue, workspace roles, and TD-025's first
  half.**
  - **Depends on:** S29's D-entries (d, e, f).
  - **Goal:** the three things every later session stands on.
  - **Exit criteria:**
    - **The jobs queue.**
      - A `jobs` table, workspace-scoped (D-008). Claims use
        `FOR UPDATE SKIP LOCKED`, with a lease that expires, bounded retries
        with backoff, and a dead state.
      - A race test with two claimers proves exactly one claim.
      - Its worker starts in the lifespan beside the ingest task and is
        cancelled on shutdown.
    - **Roles, enforced.**
      - `users.role` takes S29's values. A `require_role` dependency sits
        beside `resolve_user`.
      - `GET /api/auth/me` returns the user, the workspace and the role.
        F4 needs it.
      - A structural test makes every admin route refuse an analyst, the way
        `tests/test_schema.py` enforces isolation.
    - **No route can change roles or workspaces it shouldn't.** No route lets
      anyone set their own role, or touch another workspace's users (the
      tenant-isolation invariant). The first-admin path is tested.
    - **TD-025, first half.**
      - Every execution attempt carries an idempotency key, handed to
        execute, undo and observe.
      - Pending proposals expire after a TTL. The new status goes into the
        one status-CHECK block, edited in place, and
        `test_startup_survives_every_status_a_proposal_can_be_in` passes.
    - An adversarial review covers tenancy and the approvals state machine.

- [ ] **S31 — The integration contract, the SDK, and a workspace registry.**
  - **Depends on:** S30, and S29's D-entries (b, g).
  - **Goal:** an integration is a typed, versioned manifest plus Python
    handlers, written with an in-repo SDK. A workspace knows which
    integrations it has. Nothing an integration ships runs in the app process.
  - **Exit criteria:**
    - **The manifest v1 types.** Identity and version; a config schema whose
      secret fields are marked; declared hosts; the commands `test`, `fetch`
      and `action`, each with typed params and an output schema. Actions carry
      D-023's risk, dry run and undo.
    - **`validate_manifest` refuses with exact reasons.** The tests are
      table-driven, one case per rule, including destructive-without-undo and
      an undeclared host.
    - **A manifest action maps onto `ActionSpec` and passes `validate_spec`**
      unchanged.
    - **The SDK** (a new package). Command decorators; a typed context; an
      HTTP client limited to the declared hosts; logs that redact secrets; and
      a local harness that runs a command against a recorded fixture. That
      harness is how a customer tests their integration before uploading it.
    - **The workspace registry.**
      - An admin registers an integration package.
      - Packages are content-hashed, like `spec_fingerprint`, so a changed
        package is a new version.
      - It answers TD-023's "which actions does this tenant have?".
    - **A reference integration passes the harness** (a mock HTTP service,
      used in tests).
    - **A structural test:** the app package never imports integration code.

- [ ] **S32 — Applications and the edge runner: "Test connection", end to
  end.**
  - **Depends on:** S31, and S29's D-entries (a, c).
  - **Goal:** an admin configures an application, assigns it to an edge
    runner, and "Test connection" runs through a real runner container.
  - **Exit criteria:**
    - **Applications.**
      - A table and API, admin only, with config validated against the
        manifest.
      - Credentials are custodied per S29 (the cloud stores names only).
      - No secret value appears in any API response or log. Tests scan both.
    - **Runner enrollment.** A one-time token becomes a runner credential,
      stored hashed, revocable, and scoped to one workspace.
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
      - A runner cannot claim another workspace's job.
      - A revoked runner is refused.
      - An expired lease can be re-claimed.
      - A result for a job the runner doesn't hold is refused.
    - An adversarial review covers tenancy and runner auth. **Promote.**

- [ ] **S33 — Application actions through the approvals path, offered to the
  agent.**
  - **Depends on:** S32.
  - **Goal:** an application's actions take the path that exists: proposal,
    approval, claim, a job on the runner, the result, then settle or undo.
  - **Exit criteria:**
    - **`EXECUTABLE_SYSTEMS` is widened by code and review (D-024).** An
      action is executable only on an enabled application, in the same
      workspace, whose runner is online. `check_executable` refuses the rest
      with a reason: runner offline, application disabled, or package version
      changed.
    - **Grant-checked scope (TD-025's second half, TD-023).** An action
      touches only what its application declares.
    - **A lost result never runs an action twice.** S30's key reaches the
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
      approved, runs on the runner, and is undone.
    - An adversarial review covers actions, the rail and tenancy.

- [ ] **S34 — Fetching: alerts from applications.**
  - **Depends on:** S32 (S33 is not needed).
  - **Goal:** fetch commands run on a schedule, and what they return lands as
    alerts.
  - **Exit criteria:**
    - **Schedules and cursors.**
      - Each application's fetch schedule runs as jobs (S30), bounded by plan
        limits (D-026: the plan is data, the limits are code).
      - Each application has a cursor (the `ingest_state` pattern) that
        advances only after a page is stored.
    - **The `alerts` table.**
      - It is unique on workspace, application and external id, so a
        re-fetch is a no-op.
      - The raw payload is size-capped. Alerts are normalized through
        `AlertEnvelope` and scored by `score_alert`.
      - A malformed item is quarantined. It never crashes the fetch.
    - **Observables.** Indicators are extracted from alerts and recorded.
      **Whether they are enriched with third parties is a decision beside
      D-039** (Burhan's call). It is off by default until he makes it.
    - **The alerts API** lists, filters, pages and gets alerts, scoped to the
      workspace.
    - **Tests.** A re-fetch is idempotent. The cursor resumes after a runner
      restart. The plan-limit cap holds. Bad items are quarantined.

- [ ] **S35 — QRadar, the first reference SIEM, on the edge runner, live.**
  - **Depends on:** S33, S34, and S29's probe.
  - **Goal:** QRadar CE's offenses arrive through an edge runner on the dev
    box, and the analyst can act back on QRadar.
  - **Exit criteria:**
    - **Built with the SDK only.** It is first-party, and it dogfoods "bring
      your own integration". Anything the SDK lacked is fixed in the SDK, not
      worked around in the integration.
    - **Every QRadar endpoint used is in a probe record.** Nothing is coded
      from memory.
    - **What it does.**
      - Test connection.
      - Fetch offenses, with the evidence S29 found affordable.
      - Actions: add a note, assign, and close with a closing reason.
      - Undo where QRadar allows it. **An irreversible external write (closing,
        if S29 found it can't be reopened) needs a decision beside D-023**
        (Burhan's call).
    - **CI uses a QRadar fake built from the recorded responses** (synthetic
      data).
    - **Live on the VM.**
      - A synthetic offense (S29's recipe) becomes an alert.
      - A note approved in Auspex appears in QRadar.
      - Recorded in `docs/probes/`. **Promote.**

- [ ] **S36 — Incidents.**
  - **Depends on:** S35.
  - **Goal:** the incident is the analyst's unit of work.
  - **Exit criteria:**
    - **The model.**
      - An `incidents` table plus an append-only incident event log.
      - Statuses and allowed transitions are owned by code, in one
        status-CHECK block, like proposals. A closure needs a reason.
      - Assignment goes only to members of the same workspace. Incidents
        carry severity and priority.
    - **Linking.**
      - A source-native incident (a QRadar offense) creates an incident
        directly.
      - Other alerts are grouped by a rule (a dedup key plus a time window),
        or by hand.
      - An alert links to at most one incident.
    - **Living Verdicts reach the incident.** A verdict flip or a retro-hunt
      match on a linked observable appends an incident event. This is the
      flagship's tie-in.
    - **The API.** List, filter, get, transition, assign, note and link, all
      scoped to the workspace. A read returns the allowed next transitions, so
      the page renders from the API and never copies the state machine.
    - **Tests.**
      - Every illegal transition is refused.
      - Two analysts racing one transition: exactly one wins (a conditional
        UPDATE).
      - Cross-workspace reads and assignments are refused.
      - QRadar-born alerts become incidents.
    - An adversarial review covers the state machine and tenancy.

- [ ] **S37 — Two-way sync with the SIEM, every write approved.**
  - **Depends on:** S36.
  - **Goal:** an incident and its source offense stay consistent, and nothing
    writes to the customer's SIEM without an approval.
  - **Exit criteria:**
    - **Outbound.** An incident change the source should know about (close,
      assign, note) proposes the matching application action. It runs only
      once it is approved (D-014).
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

- [ ] **S38 — The co-analyst on the incident.**
  - **Depends on:** S36 (S37 is helpful, not required).
  - **Goal:** the co-analyst works an incident. It reads the incident, triages
    it, and proposes actions inside it.
  - **Exit criteria:**
    - **An incident-scoped chat session**, with READ tools for the incident and
      its alerts. Tool results are data, unindexed (D-031).
    - **A decision beside D-037 clause 1 and D-039** (Burhan's call).
      - SIEM content is attacker-controlled, and here it reaches the agent
        path for the first time.
      - Which indicators in an incident count as supplied?
      - The bound is stated.
    - **Triage.** Where a verdict is code-decided (D-043's alert path), code
      decides it. The answer's contract is measured.
    - **Proposals.** Those filed in the turn are linked to the incident and
      appear in its event log.
    - **New directive text is measured into the rail.** Re-run TD-044's
      calibration; floors move only on that measurement. Any classifier,
      resolver or mode change is judged on batteries written blind
      (SESSION-RULES.md).
    - **Spend per incident**, from D-054's ledger.
    - **Live on a QRadar-born incident.** A triage, a proposed note, approval,
      and the note visible in QRadar.
    - An adversarial review covers the rail and actions.

- [ ] **S39 — SLAs, metrics, closure, and the phase's demo.**
  - **Depends on:** S37 (S38 for the demo's co-analyst step).
  - **Goal:** the incident path measures itself, and a closure teaches the
    platform something.
  - **Exit criteria:**
    - **SLAs.** A policy per severity (plan data, code limits, D-026). Time to
      acknowledge and time to resolve come from the event log. A breach
      becomes an event.
    - **The metrics API.** MTTA and MTTR; open incidents by severity, status
      and assignee; per application.
    - **Closure feedback.** A closure reason (true positive, false positive,
      benign) reaches the linked observables' verdicts as a D-entry decides.
      A closure is an analyst's judgement, not a provider's signal.
    - **`./scripts/demo.sh` walks the incident path end to end, hermetically**
      (the QRadar fake): an alert, an incident, the co-analyst, an approval,
      and a closure synced back.
    - **Promote:** the phase's demo.

- [ ] **S40 — After the path: the cloud runner, sealed secrets, and a second
  SIEM.**
  - **Depends on:** S39. **Burhan re-scopes it at S39's end.**
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
