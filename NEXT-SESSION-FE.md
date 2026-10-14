# NEXT-SESSION-FE — track: front end · session: F3

_Paste everything below the line into a fresh Claude Code window opened in
the Auspex repo (Burhan's clone: /home/burhan/auspex-new). **The front end is
the current focus** (Burhan, 2026-10-10: "before moving on with more backend
development we need to improve on the FE so lets shift our focus there and
pause BE for a bit")._

_**F3 is handed to a collaborator** (Burhan, 2026-10-13: "She owns F3 fully").
She runs it on her own machine under her own personal identity, and every F3
call is hers, new D-entries and `/promote` included (D-059). New here? Read
`HANDOFF.md` first._

---

SESSION F3 of Auspex, **front-end track** (D-051). The working dir must be the
Auspex repo: Burhan's /home/burhan/auspex-new, or a collaborator's own clone.
Run `/session-start fe F3` first (the full ritual). It reads `SESSION-RULES.md`
(standing rules for every track) and STATE.md.

**Who decides (D-059).** The human running F3 owns its calls. Where this
prompt, the rules or a command say "Burhan's call" or "ask Burhan", ask them.
Re-scoping the backend or bugs track stays Burhan's: flag it, don't do it.

**No local engine needed.** F3's default goal is page work and needs no LLM,
so the local-Ollama gate (`/session-start` 4b) is not a stop for F3. A chat
turn, if one is needed, uses the dev endpoint from `.env` and costs money.

Step 0 (do BEFORE new scope):

1. **One window at a time (D-051).** If anything moves that you did not move,
   check `ps` for a second `claude` in this directory and stop.
2. **If STATE.md says the promote slate is not empty, `/promote` it.** Read
   the diff, not the list. (At the handoff it held D-059 and the handoff docs:
   your first `/promote`, under your own account.)
3. **Use F2's page by hand first, and say what you saw.** Burhan handed F3 on
   before using it, so nobody has used these for real:
   - a chat survives a reload: the always-on sidebar, + New chat, reopening a
     chat (the "Reopened" divider, spend lines, proposal lines with Review);
   - the sign-in kept for the tab (D-056), and Sign out;
   - Review on a reopened proposal bringing back its card, and Undo from there;
   - the empty-answer note, errors in the server's own words, narration on its
     own line;
   - the page on a phone (the Chats button, the backdrop, Esc).

   That list outranks the goal below. What the session's owner names joins
   F3 only if they say so; the rest goes to IDEAS.md, or BUGS.md (`/bug`) if
   it is broken.

Goal (default): **the timeline page joins the chat page under D-057's policy**
(closes TD-051). Today `auspex/static/timeline.html` (280 lines) carries its
own inline `<style>` and `<script>`, four `onclick=` attributes, and builds its
cards as HTML strings into `innerHTML`, escaped by an `esc()` that does not
escape `'`, with inline `style="width:…"` attributes. All of that would be
blocked by a strict CSP. So:
- its CSS and script move into files on `auspex/routes/ui.py`'s allow-list,
  served no-cache, the way F2 moved the chat page's;
- the cards are built with elements and text (the chat page's `el` pattern),
  not HTML strings, and widths are set through the CSSOM;
- the handlers are listeners;
- `/timeline` carries the same policy as `/` (D-057), pinned by a test, and
  the "no CSP yet" test is replaced.

Design first (brainstorming): whether timeline's pure logic (its staleness
labels, its counts "at least N") moves into a tested module like
`js/page-logic.js`, and whether the two pages share helpers, are design
questions; ask. `tests/test_ui.py`'s timeline tests read the page's source;
they must read it as served, as the chat page's do (`_page(client)`). Live in a
real browser with **zero CSP violations**, against the rebuilt container.

Candidates. **Ask the session's owner at the start ritual. Do NOT start any
of these unasked:**
- **Analyst notes shown** (IDEAS, F2): `annotate_observable` writes
  `observable_notes` and nothing reads them back. Showing them on the
  timeline needs a read route (scoped to the workspace) — a design question.
  Handing them to the agent or the IOC check is rail-sensitive (new text the
  model reads): ask first.
- **TD-047:** every load of the chat page is four full responses (no 304s).
- **The stale proposal line** in a reopened turn after a door is used in the
  panel (STATE.md follow-up #20).
- **"[connection lost]"**, the last bracketed error copy on the chat page.
- **D-057's pins** (STATE.md follow-up #21): no test catches `style=` in the
  markup or in `chat.js`'s `innerHTML` templates.

Constraints: everything in `SESSION-RULES.md`, especially **The page** (the
logic module, D-053's subset, D-052's pacing, D-057's CSP) and **The output
rail**.
- The timeline page shows feed-derived text (sources, claims, checker names):
  it is text, never HTML, once it is rebuilt.
- A new external origin, or loosening the policy (`'unsafe-inline'`), is a
  D-entry, not an edit.
- Console-driven probes cannot reach the chat page's module-scoped names;
  drive the DOM (STATE.md follow-up #16).
- Live probes and pytest never run at the same time. A probe that files
  proposals rejects or undoes them; one that records observables deletes only
  what it created.

---

## After F3: the integration phase — front-end plan (F4–F9)

_Written 2026-10-14 by Burhan, in a planning window. **This is not F3's scope.**
F3 works only on the prompt above (scope lock); F3's owner does not need to
read past this line. **F3's session-end:** write F4's paste-ready prompt from
the F4 entry below, keep this whole section under it, tick F3, and set
STATE.md's focus to the backend, because S29 runs next (the order table)._

The phase builds alerts and incident management on applications. An
application is an integration a workspace has configured, and customers can
write their own integrations. The backend plan, with the full order across
both tracks, is in `NEXT-SESSION-BE.md` (S29–S40). **A front-end session
starts only after the backend sessions it depends on have closed.**

| # | Session | Depends on (backend) | Delivers |
|---|---|---|---|
| 3 | F4 | S30 (roles, `GET /api/auth/me`) | one shell for every page, role-aware |
| 6 | F5 | S31, S32 | integrations, applications and edge-runner admin pages |
| 10 | F6 | S34, S35 | the alerts queue, with QRadar alerts live |
| 12 | F7 | S36 | incidents: list and detail |
| 15 | F8 | S37, S38 | sync state, and the co-analyst inside the incident |
| 17 | F9 | S39 | the dashboard, polish, and Burhan's hands-on walk |

### Standing for every page in this phase

- **D-057's policy on every page.** No inline script or style, no `on…=`
  attributes, files served from `auspex/routes/ui.py`'s allow-list. A new
  external origin needs a D-entry. Verify in a real browser against the
  rebuilt container, with **zero CSP violations**, at phone width too.
- **Page logic lives in pure, tested modules**, the `js/page-logic.js` pattern
  run under Node inside the gate. The DOM wiring stays thin.
- **Anything a SIEM or an integration sent is attacker-controlled.** That
  includes alert names, raw payloads, offense notes, runner messages and
  manifest descriptions. It reaches the page as text, never HTML, and
  size-capped.
- **The server is the guard, and the page only reflects it.** An admin-only
  door is hidden from an analyst, and the server refuses it anyway; check
  both.
- **Secrets are write-only.** After a save, no secret value is in the DOM, in
  page state, or in any network response. Check it in the browser.
- **Specs over prompts.** Forms are generated from the manifest's typed
  contract, and the allowed incident transitions come from the API. The page
  never hand-writes a form per integration, and never keeps its own copy of
  the state machine.
- **Reuse the doors that exist.** That means F1's approvals doors (two clicks
  for runs) and the chat stream's rules (D-052 pacing, D-053's markdown
  subset). Do not copy them.
- **Brand (D-002).** The engine is "the platform's engine", and the co-analyst
  is never called a copilot. Customer-facing labels are Applications,
  Integrations, Edge runners, Alerts and Incidents.

### Sessions

- [ ] **F4 — One shell for every page, role-aware.**
  - **Depends on:** S30, and F3's design for the timeline page. Read F3's spec
    first, and build on its call about shared helpers.
  - **Goal:** chat, the timeline and the pages to come share one sign-in per
    tab (D-056), one navigation header, and one set of modules (the `el`
    builder, an API client that carries auth, the error copy).
  - **Exit criteria:**
    - You sign in once and move between chat and the timeline without signing
      in again. Today the timeline page has its own sign-in.
    - Shared modules are imported by every page and tested under Node.
      Nothing is duplicated between pages.
    - The navigation reads the role from `GET /api/auth/me`. An analyst sees
      no admin entries, and the server refuses them anyway (checked in the
      browser).
    - Every page carries D-057's policy, with zero violations live, at
      desktop and phone width.

- [ ] **F5 — Integrations, applications and edge runners (admin).**
  - **Depends on:** S31, S32.
  - **Goal:** an admin installs an integration, configures an application,
    enrolls an edge runner, and sees "Test connection" pass, all from the
    page.
  - **Exit criteria:**
    - **The catalogue** lists the workspace's integrations and their versions,
      with each manifest's commands, risks and declared hosts (as text).
    - **The application form is generated from the manifest's config schema**
      by a pure, tested function. Validation errors are shown in the server's
      own words.
    - **Secrets.** Secret fields are write-only, and after a save no value
      survives anywhere on the page (checked in the browser's network panel).
    - **Placement.** The picker lists the workspace's edge runners with their
      status.
    - **Test connection** runs through the dev edge runner, and shows pass or
      fail with the runner's message as text.
    - **Edge runners.**
      - Enrolling shows the one-time token once, then never again.
      - The page shows each runner's last heartbeat.
      - Revoke is a two-click door, F1's pattern.
    - Live end to end against the rebuilt container, as admin and as analyst.

- [ ] **F6 — The alerts queue.**
  - **Depends on:** S34, S35.
  - **Goal:** the analyst sees what the applications brought in, QRadar
    included, and can read any alert safely.
  - **Exit criteria:**
    - **The list.** Filters (application, severity, status, time) and paging
      are done by the API, never client-side over everything. Polling is
      bounded (TD-046's pattern).
    - **Alert detail.**
      - The normalized fields and the score.
      - Extracted observables, each linking to its timeline.
      - The raw payload as text, in a size-capped, collapsible block.
    - **A hostile alert fixture renders inert and bounded**, in a test and
      live. The fixture includes markup, `onerror`, RTL overrides and a 1 MB
      field.
    - **Live:** an alert born from a synthetic QRadar offense is visible,
      fetched through the edge runner.

- [ ] **F7 — Incidents: the list and the detail.**
  - **Depends on:** S36.
  - **Goal:** the incident page is where an analyst works.
  - **Exit criteria:**
    - **The list.** Filters by status, severity and assignee.
    - **The detail.**
      - Transition buttons only for what the API says is allowed.
      - Assign and unassign; notes as text.
      - The event timeline and the linked alerts.
      - Observables with their Living Verdicts, using the staleness labels
        from F3's timeline logic.
      - Proposals, with F1's approvals doors, reused.
    - **Create an incident** from alerts selected in F6's queue.
    - **A concurrent change** (two tabs) shows the server's refusal in its own
      words, then refreshes.
    - **Live:** walked end to end on a QRadar-born incident.

- [ ] **F8 — The incident and its source, and the co-analyst inside it.**
  - **Depends on:** S37, S38.
  - **Goal:** the analyst sees whether an incident agrees with its source
    offense, and works the incident with the co-analyst beside it.
  - **Exit criteria:**
    - **Sync state.** The linked source object, the last sync, and pending
      outbound proposals (such as "close in QRadar"), each with its doors.
    - **The co-analyst panel** is scoped to the incident. The chat stream's
      rules apply unchanged: D-052 pacing, D-053's subset, the rail.
    - **A proposal the co-analyst files** appears in the incident's timeline
      and the approvals panel.
    - **Spend per incident** is shown (D-054).
    - **Live:** approve the co-analyst's note, and it appears in QRadar.

- [ ] **F9 — The dashboard, polish, and Burhan's hands-on walk.**
  - **Depends on:** S39.
  - **Goal:** the phase is usable end to end, by hand.
  - **Exit criteria:**
    - **The dashboard.** MTTA and MTTR, open incidents by severity and
      status, and SLA breaches, all from the API. Charts are built as DOM or
      inline SVG, with no new external origin unless a D-entry allows one.
    - **Every new page** has empty, loading and error states, and works at
      phone width.
    - **Burhan walks the whole path by hand:** an offense in QRadar, an
      incident, the co-analyst, an approval, then closed in QRadar. What he
      sees goes to BUGS.md (`/bug`) or IDEAS.md (`/idea`).
