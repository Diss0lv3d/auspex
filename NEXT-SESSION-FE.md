# NEXT-SESSION-FE — track: front end · session: F4

_Paste everything below the first line of dashes into a fresh Claude Code
window opened in the Auspex repo. **S30 closed 2026-10-15** (MSSP tenancy,
`GET /api/auth/me`, the switch), so **F4 is next in the order table and the
focus** (STATE.md). F3 closed 2026-10-14 (the collaborator Hunaiza, D-059); its
spec is the base F4 builds on._

_Below the F4 prompt is **Burhan's front-end plan for the whole phase,
F4–F9**. `/session-end` writes the next prompt from its entry, keeps the plan
section, and ticks the session it closed._

---

SESSION F4 of Auspex, **front-end track** (D-051). The working dir must be the
Auspex repo. Run `/session-start fe F4` first (the full ritual). It reads
`SESSION-RULES.md` (standing rules for every track) and STATE.md.

**Who decides.** Burhan, unless STATE.md says F4 was handed to a collaborator
(D-059); then its calls are theirs, and re-scoping other tracks stays Burhan's.

Step 0 (do BEFORE new scope):

1. **S30 must be closed.** STATE.md's Tracks table must show S30 as the
   backend's last closed session. If it doesn't, STOP: F4 reads S30's
   `GET /api/auth/me` and its workspace-switch route.
2. **One window at a time (D-051), across both machines.** `git fetch` and
   read `origin/staging` first; if anything moves that you did not move,
   check `ps` for a second `claude` in this directory and stop.
3. **If STATE.md says the promote slate is not empty, `/promote` it.** Read
   the diff, not the list.
4. **Probe S30's routes before coding against them** (CLAUDE.md rule 4):
   `GET /api/auth/me` and the workspace switch, as an MSSP analyst (explicit
   memberships, and a provider-wide grant with a `restricted` client), a client
   admin, a client analyst and a viewer (D-061). Save it to `docs/probes/`.
   What S30 shipped, to probe rather than trust (docs/probes/2026-10-15-s30-tenancy-live.md
   is S30's own run):
   - **Set the people up with the CLI** (organizations are CLI-only, D-068):
     `docker compose exec app python -m auspex.tenancy create-org | create-client
     | set-member | set-restricted | list`. A dev login provisions an unknown
     email as an analyst in `default` and lands a known one in its home
     organization's first workspace.
   - `GET /api/auth/me` → `user`, `organization`, `workspace` (id, name,
     region, role, organization), `workspaces[]` (id, name, region, role, `via`
     membership|provider_wide, organization {id, name, kind}), home first.
   - `POST /api/auth/switch {workspace_id}` → a new `access_token` and the
     workspace; a login session only (an API key is a 403); a foreign and a
     missing workspace are the same 404; a malformed id is a 422. The old token
     stays valid for its own workspace.
   - A viewer's write is a 403 ("This needs the analyst or admin role in this
     workspace."); a removed membership is a 403 at the next request ("You no
     longer have access to this workspace.") and ends the approvals stream with
     an `error` frame; a residency refusal is a 403 before any stream starts.

Goal: **F4 — one shell for every page, role-aware, with a workspace switcher**
(the plan's F4 entry below is the contract: its exit criteria are the done
line).
- Read F3's spec first:
  docs/superpowers/specs/2026-10-14-timeline-page-csp-design.md. F3 kept the
  two pages separate on purpose (its decision 2: each page its own `el()` and
  palette). **F4 is where they are shared**: one `el` builder, one API client
  that carries auth, one error copy, one stylesheet base, each a pure tested
  module where it has logic, imported by every page.
- The timeline page loses its own sign-in (and its pre-filled dev email): one
  sign-in per tab (D-056) serves every page.
- **Fix F3's deferred minors in the shared modules** (STATE.md follow-up #25):
  pin the pages to the null-safe `conf`/`pct`, pin the link listeners, check
  status codes in the served-page test helpers.

Design first (brainstorming): the shape of the shared modules and the shell,
and how a switch clears page state, are design questions; ask.

Candidates. **Ask at the start ritual. Do NOT start any of these unasked:**
- **F2's page with live turns** (STATE.md follow-up #26): Review/Undo on a
  reopened proposal, the empty-answer note, server errors, narration on its
  own line. F3 walked the rest without a turn.
- **TD-047:** every page load is a full response per file (no 304s); the
  shell adds files.
- **The stale proposal line** in a reopened turn after a door is used in the
  panel (STATE.md follow-up #20).
- **"[connection lost]"**, the last bracketed error copy on the chat page.
- **Analyst notes shown** (IDEAS, F2): a read route scoped to the workspace —
  a design question; handing them to the agent is rail-sensitive.

Constraints: everything in `SESSION-RULES.md`, especially **The page**, and
the plan's "Standing for every page in this phase" below.
- The page never sends a workspace id the server would trust; the active
  workspace lives in the token.
- Live with two clients in a real browser against the rebuilt container:
  zero CSP violations, at desktop and phone width.
- Live probes and pytest never run at the same time. A probe that seeds rows
  deletes only what it created, in the same command.

---

## The integration phase — front-end plan (F4–F9)

_Written 2026-10-14 by Burhan, in a planning window; MSSP tenancy was added the
same day. **Re-checked at S29 against the phase's spec**
(docs/superpowers/specs/2026-10-15-integration-phase-design.md, D-060…D-067):
the words changed (D-060) and F4, F5 and F6 gained what the spec decided; the
order did not change. Each front-end session-end writes the next prompt from
its entry below._

The phase builds alerts and case management on integrations. A **connector** is
the package a customer, an MSSP or Auspex writes; an **integration** is a
connector configured in one workspace (an MSSP's shared SIEM lives in the
MSSP's own workspace). An **Edge Agent** runs an integration's commands on the
customer's network. An MSSP's analysts work many client workspaces, one at a
time, and a client's users see only their own. The backend plan, with the full
order across both tracks, is in `NEXT-SESSION-BE.md` (S29–S41). **A front-end
session starts only after the backend sessions it depends on have closed.**

| # | Session | Depends on (backend) | Delivers |
|---|---|---|---|
| 3 | F4 | S30 (tenancy, `GET /api/auth/me`) | one shell for every page, role-aware, a workspace switcher |
| 8 | F5 | S32, S33, S34 | connectors, integrations, Edge Agents, memberships and approval-policy admin |
| 11 | F6 | S35, S36 | the alerts queue, the quarantine and the routing map |
| 13 | F7 | S37 | cases: list and detail, across clients for an MSSP |
| 16 | F8 | S38, S39 | sync state, and the co-analyst inside the case |
| 18 | F9 | S40 | the dashboard, polish, and Burhan's hands-on walk |

### Standing for every page in this phase

- **D-057's policy on every page.** No inline script or style, no `on…=`
  attributes, files served from `auspex/routes/ui.py`'s allow-list. A new
  external origin needs a D-entry. Verify in a real browser against the
  rebuilt container, with **zero CSP violations**, at phone width too.
- **Page logic lives in pure, tested modules**, the `js/page-logic.js` pattern
  run under Node inside the gate. The DOM wiring stays thin.
- **Anything a SIEM, a connector or an agent sent is attacker-controlled.**
  That includes alert names, raw payloads, offense notes, agent messages and
  manifest descriptions. It reaches the page as text, never HTML, and
  size-capped.
- **The server is the guard, and the page only reflects it.**
  - An admin-only door is hidden from an analyst and a viewer, and the server
    refuses it anyway; check both.
  - A `viewer` sees no door that changes anything.
  - The page never sends a workspace id the server would trust. The active
    workspace lives in the token.
- **Which client you are in is always visible.** The active workspace and its
  organization show on every page. Switching clients reloads everything the
  page holds, so nothing from the last client stays on screen: lists, the
  open chat, the approvals panel.
- **Secrets are names (D-063).** An Edge Agent's secret value is never typed
  into Auspex: the form takes the secret's name, and the page says where the
  value goes (the agent's host). Cloud Agent secrets (S41) are write-only:
  after a save, no value is in the DOM, page state or any response.
- **Specs over prompts.** Forms are generated from the manifest's typed
  contract (D-064), and the allowed case transitions come from the API. The
  page never hand-writes a form per connector, and never keeps its own copy of
  the state machine.
- **Reuse the doors that exist.** F1's approvals doors (two clicks for runs)
  and the chat stream's rules (D-052 pacing, D-053's markdown subset). Do not
  copy them.
- **Brand (D-002, D-060).** The engine is "the platform's engine", and the
  co-analyst is never called a copilot. Customer-facing labels are Connectors,
  Integrations, Edge Agents, Alerts, Cases and Clients.

### Sessions

- [ ] **F4 — One shell for every page, role-aware, with a workspace
  switcher.**
  - **Depends on:** S30, and F3's design for the timeline page. Read F3's spec
    first, and build on its call about shared helpers.
  - **Goal:** chat, the timeline and the pages to come share one sign-in per
    tab (D-056), one navigation header, and one set of modules (the `el`
    builder, an API client that carries auth, the error copy). An MSSP
    analyst switches between the client workspaces they may enter.
  - **Exit criteria:**
    - You sign in once and move between chat and the timeline without signing
      in again. Today the timeline page has its own sign-in.
    - Shared modules are imported by every page and tested under Node.
      Nothing is duplicated between pages.
    - **The navigation reads `GET /api/auth/me`.** An analyst sees no admin
      entries and a viewer no changing doors, and the server refuses them
      anyway (checked in the browser).
    - **The switcher.**
      - It lists exactly the switchable set `GET /api/auth/me` returns (D-061:
        explicit memberships plus provider-wide grants, minus restricted
        clients). The page never computes it.
      - Switching swaps the tab's token through S30's route and clears
        everything the page held: the chat list, the open chat, the approvals
        panel.
      - The active client is visible on every page.
      - **Live with two clients:** after a switch, nothing from the first
        client is on screen, in page state, or in a request.
    - **A refused engine turn for residency** (D-061) is shown in the server's
      words.
    - Every page carries D-057's policy, with zero violations live, at
      desktop and phone width.

- [ ] **F5 — Connectors, integrations, Edge Agents, memberships and approval
  policy (admin).**
  - **Depends on:** S32, S33, S34.
  - **Goal:** an admin registers a connector, configures an integration,
    enrolls an Edge Agent, sees "Test connection" pass, manages who may enter
    which workspace, and sets who may approve what, all from the page.
  - **Exit criteria:**
    - **The catalogue** lists the connectors and versions available to the
      workspace (and, if S32's decision allows, those an MSSP offers its
      clients). Each shows its manifest's commands, risks and declared hosts
      as text.
    - **The integration form is generated from the manifest's config schema**
      by a pure, tested function, TLS pinning included. Validation errors are
      shown in the server's own words.
    - **Secrets are names (D-063).** A secret field takes a name, and the page
      says the value goes on the Edge Agent's host. "Test connection" naming a
      missing secret shows which secret and which agent.
    - **Where it lives.** The integration lives in the active workspace; an
      MSSP admin configures a shared SIEM from the provider's own workspace.
      The agent picker lists that workspace's Edge Agents with their status.
    - **Test connection** runs through the dev Edge Agent and shows pass or
      fail with the agent's message as text.
    - **Edge Agents.** Enrolling shows the one-time token once, then never
      again. Each agent's last heartbeat is shown. Revoke is a two-click door,
      F1's pattern.
    - **Memberships (D-061).** An admin manages memberships and roles in their
      workspace. A provider admin grants and removes provider-wide access and
      marks a client `restricted`. Every refusal is the server's.
      _S30 note: the API exists (`GET|POST /api/workspace/members`,
      `PATCH|DELETE /api/workspace/members/{user_id}`, `GET /api/audit`, all
      admin, active workspace only), but **`restricted` is CLI-only** (D-068
      call 1): a page control for it needs a backend route first — Burhan's
      call before F5._
    - **The approval policy** for each client workspace (S34) can be read and
      edited by an admin who may edit it, and only by them.
    - Live end to end against the rebuilt container, as an MSSP admin, a
      client admin, an analyst and a viewer.

- [ ] **F6 — The alerts queue, the quarantine and the routing map.**
  - **Depends on:** S35, S36.
  - **Goal:** the analyst sees what the integrations brought in, QRadar
    included, and can read any alert safely. An MSSP admin sees what a shared
    SIEM could not route, and maps it.
  - **Exit criteria:**
    - **The list.** Filters (integration, severity, status, time) and paging
      are done by the API, never client-side over everything; polling is
      bounded (TD-046's pattern). For an MSSP analyst, an "all my clients" view
      built by the server, each row naming its client.
    - **Alert detail.** The normalized fields and the score; extracted
      observables, each linking to its timeline; the raw payload as text, in a
      size-capped, collapsible block.
    - **A hostile alert fixture renders inert and bounded**, in a test and
      live: markup, `onerror`, RTL overrides and a 1 MB field.
    - **The quarantine and the routing map** live in the provider's workspace
      (MSSP admin only): unmapped items listed with their routing key (a
      QRadar domain), mapping a key to a client workspace routes the next
      fetch, and a client's users never see the quarantine.
    - **Live:** an alert born from a synthetic offense in the lab domain
      (D-067) is visible in the right client, fetched through the Edge Agent.

- [ ] **F7 — Cases: the list and the detail.**
  - **Depends on:** S37.
  - **Goal:** the case page is where an analyst works, in one client or across
    an MSSP's clients.
  - **Exit criteria:**
    - **The list.** Filters by status, severity, assignee and, for an MSSP
      analyst, client. The cross-client list comes from the server; the page
      never stitches clients together.
    - **The detail.** Transition buttons only for what the API says is
      allowed; assign and unassign, to people who may enter that workspace
      only; notes as text; the event timeline, naming each actor and their
      organization; the linked alerts; observables with their Living Verdicts,
      using the staleness labels from F3's timeline logic; proposals, with F1's
      approvals doors reused, showing who may approve under the client's
      policy.
    - **Create a case** from alerts selected in F6's queue.
    - **A concurrent change** (two tabs) shows the server's refusal in its own
      words, then refreshes.
    - **Opening another client's case** from the cross-client list switches
      the workspace first (F4's switcher), visibly.
    - **Live:** walked end to end on a QRadar-born case from the lab domain.

- [ ] **F8 — The case and its source, and the co-analyst inside it.**
  - **Depends on:** S38, S39.
  - **Goal:** the analyst sees whether a case agrees with its source offense,
    and works the case with the co-analyst beside it.
  - **Exit criteria:**
    - **Sync state.** The linked source object, the last sync, and pending
      outbound proposals (such as "close in QRadar"), each with its doors.
    - **The co-analyst panel** is scoped to the case and its client. The chat
      stream's rules apply unchanged: D-052 pacing, D-053's subset, the rail.
    - **A proposal the co-analyst files** appears in the case's timeline and
      the approvals panel.
    - **Spend per case** is shown (D-054).
    - **Residency.** A turn the server refuses for residency says so, in the
      server's words.
    - **Live:** approve the co-analyst's note, and it appears in QRadar (lab
      domain).

- [ ] **F9 — The dashboard, polish, and Burhan's hands-on walk.**
  - **Depends on:** S40.
  - **Goal:** the phase is usable end to end, by hand, as an MSSP and as a
    client.
  - **Exit criteria:**
    - **The dashboard.** MTTA and MTTR, open cases by severity and status, and
      SLA breaches, all from the API; per client, plus the MSSP rollup for a
      provider's analysts; charts built as DOM or inline SVG, with no new
      external origin unless a D-entry allows one.
    - **Every new page** has empty, loading and error states, and works at
      phone width.
    - **Burhan walks the whole path by hand.** As an MSSP analyst: a synthetic
      offense in the lab domain, routed to a client, a case, the co-analyst,
      an approval, then closed in QRadar. Then as that client's user, who sees
      only their own. What he sees goes to BUGS.md (`/bug`) or IDEAS.md
      (`/idea`).
