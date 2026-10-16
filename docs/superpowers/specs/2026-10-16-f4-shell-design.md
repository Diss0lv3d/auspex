# One shell for every page, role-aware, with a workspace switcher (F4)

_Spec, 2026-10-16, session F4 (front end). Owner: Burhan. Approved in
conversation section by section; this file is the written record. Reality it
codes against: docs/probes/2026-10-16-f4-s30-routes.md (S30's `/me` and switch,
probed as every D-061 role)._

## Why

S30 made Auspex multi-tenant: a person may enter several workspaces, with a
role in each, and one token is one workspace (D-061, D-068). The pages know
none of it. The chat page and the timeline each carry their own sign-in, their
own `el()`, their own palette and their own `fetch` with a bearer header (F3
kept them apart on purpose, its decision 2). The timeline still signs in on
load as a pre-filled dev address. No page shows which workspace it is in, no
page can switch, and no page hides a door the active role cannot use.

## Goal

Chat, the timeline and every page to come share one sign-in per tab (D-056),
one header and one set of modules. The header reads `GET /api/auth/me`, shows
the active client on every page, and switches between the workspaces `/me`
lists. A switch leaves nothing of the previous client on screen, in page state
or in a request. Doors follow the active role, and the server refuses them
anyway. The exit criteria are the plan's F4 entry (`NEXT-SESSION-FE.md`).

## Decisions taken (Burhan, F4)

1. **Candidates in scope:** the `"[connection lost]"` copy, TD-047 (304s), the
   stale proposal line (STATE.md follow-up #20), and F2's page with live turns
   (#26). Analyst notes stay out.
2. **A switch reloads the page.** The new token is stored, the hash is dropped,
   and the page reloads, so the browser discards every variable, timer, poll
   and in-flight request of the previous client. Switching is disabled while a
   turn streams.
3. **The first admin entry is a read-only Members page** (`/members`, from
   `GET /api/workspace/members`). F5 adds its doors.
4. **The switcher is a native `<select>`**; a person with one workspace sees a
   label instead. (Refinement while writing: each option names the
   organization itself, not an `<optgroup>` heading, because a closed select
   shows only the chosen option's text and the active organization must stay
   visible.)
5. **Approach: a shared header module in each page** — every page's markup has
   one `<header id="shell">`, filled by `js/shell.js`. Rejected: a single-page
   app (a restructure the reload makes unnecessary, and it fights the per-page
   allow-list and CSP); the header markup copied into each page (duplication,
   against the exit criteria).

**Proposed D-070** (written to DECISIONS.md when this ships): _the page's
tenancy rules._ A switch reloads the page without its hash; `GET /api/auth/me`
is the page's only judge of access (any 403 re-checks it; a `/me` that refuses
signs the tab out with the server's sentence); the page never computes the
switchable set and never sends a workspace id except to the switch.

## Files

| File | Holds |
|---|---|
| `auspex/static/css/base.css` | **New.** One palette (D-002, plus the timeline's `--line`/`--edge`), the fonts, `color-scheme: dark`, inputs, buttons, selects, `[hidden]`, the shared header, the nav, the switcher, the status line. `chat.css` and `timeline.css` keep only their own rules. |
| `auspex/static/js/dom.js` | **New.** `$(id)` and the one `el(tag, props = {}, children = [])`: props are DOM properties, a string child is a text node, `null`/`undefined`/`false` children are skipped (the timeline's version; chat's calls already fit it). |
| `auspex/static/js/shell-logic.js` | **New, pure.** See "The shared logic". |
| `auspex/static/js/api.js` | **New.** `createApi({ fetch, token, onForbidden, onExpired })` → `get(path)`, `post(path, body)`, each answering `{ ok, status, body, detail }`, and `stream(path, body)` answering the raw `Response` for SSE after the same status handling. The bearer header is set here and nowhere else. A 401 calls `onExpired`; a 403 calls `onForbidden`; a network failure answers status `0`. `fetch` is injected, so Node tests drive it. |
| `auspex/static/js/shell.js` | **New, DOM.** `startShell({ page, ready, signedOut })` → `{ api, setBusy }`. Owns the token (`auspex.token`, unchanged, so a tab signed in before F4 stays signed in) and a one-time notice (`auspex.notice`) — the only `sessionStorage` user, through guarded helpers; sign-in, sign-out, the switch, the `/me` re-check. Builds the header around the page's own controls: `[.page-lead] mark nav [.page-tools] spacer workspace session`. |
| `auspex/static/index.html`, `js/chat.js`, `css/chat.css` | The header becomes `<header id="shell">` holding only the page's controls (`.page-lead`: Chats; `.page-tools`: Approvals, the endpoint select). The email, Sign in, Sign out and status leave the markup. `chat.js` imports `dom.js`, `api.js`, `shell.js`; its own `el`, token helpers, `authed`, the proposals `api()` and every `Authorization` header go. Role-aware composer and doors (below). |
| `auspex/static/timeline.html`, `js/timeline.js`, `css/timeline.css` | The header becomes `<header id="shell">` with `.page-tools`: the observable input, Open timeline, Digest. **Its own sign-in, the pre-filled address and the auto-login on load go.** Signed out, `<main>` says "Sign in to see the digest." |
| `auspex/static/members.html`, `js/members.js` | **New.** Read-only: each member's display name (or email), email, home organization, role, and a "provider-wide" tag, all as text. Empty → "No members." A refusal → the server's words. |
| `auspex/routes/ui.py` | `/members` served with `_CHAT_CSP`; `css/base.css`, `js/dom.js`, `js/api.js`, `js/shell.js`, `js/shell-logic.js`, `js/members.js` on the allow-list; **304s** for every page and file (TD-047, below). |
| `pyproject.toml`, `Dockerfile` | Checked: package-data globs `static/*.html`, `static/css/*.css`, `static/js/*.js`, and the Dockerfile's skeleton already has those directories; the new files need no change there, which the built image proves. |

## The shared logic (`js/shell-logic.js`, pure)

- `navEntries(me, page)` → Chat (`/`), Timeline (`/timeline`), and Members
  (`/members`) **only when the active role is `admin`**; the current page is
  marked.
- `workspaceLabel(ws)` → `"<org> · <kind> · <role>"`, with `" / <workspace>"`
  after the organization when the two names differ, and `" · <region>"` when
  the region is not `global`. The active workspace's organization kind comes
  from its own entry in `me.workspaces` (the probe: `me.workspace.organization`
  is a bare name, the entries carry `{id, name, kind}`).
- `switchOptions(me)` → one `{ id, text, selected }` per `me.workspaces` entry,
  **in the server's order, never filtered, never added to**; one entry means a
  label, not a select.
- `mayChange(role)` → `analyst` or `admin`. `isAdmin(role)`.
- **The one error copy.** `errorText(status, body)`: a string `detail` is
  shown as given (the server's own sentence); a non-string `detail` (the 422's
  array, which echoes the input) → "The request was not valid."; no body →
  `The request failed (<status>).`; status `0` → "Couldn't reach the server.".
  `CONNECTION_LOST` = "The connection dropped before this turn finished.
  Reopen the chat to see what was kept." `EXPIRED` = "Your sign-in expired.
  Sign in again."
- `viewerNote(me)` → "You are a viewer in `<workspace>`: you can read here;
  asking the co-analyst and deciding proposals need the analyst or admin role."
- `afterSwitchUrl(loc)` → `pathname + search`, the hash dropped.

Additions elsewhere: `doorsFor(p, role)` in `page-logic.js` returns no doors
when `!mayChange(role)`; `proposalLine(p, now)` holds the reopened proposal
line's words (taken out of `reopenedTurnPlan`, which calls it); `labelClass`
in `timeline-logic.js` (F3 minors, below).

## Behaviour

- **Load.** A stored token → `GET /api/auth/me` (it replaces `/whoami`). 200 →
  the signed-in header, then the page's `ready({ me, api })`. 401 → token
  forgotten, signed out, with `EXPIRED` in the header. 403 → lost access
  (below). A network failure → the
  header says so and keeps the token.
- **Signed out.** The header shows the dev email field and Sign in, and any
  one-time notice (then clears it). Each page shows its own signed-out state:
  chat's welcome; "Sign in to see the digest."; "Sign in to see this
  workspace's members." **Sign in** → dev login → store the token → `/me` →
  `ready`, in place (there is no previous client to clear).
- **Switch.** The select (and Sign out) is disabled while the page says it is
  busy (`setBusy`, chat's streaming turn). A change → `POST /api/auth/switch`.
  200 → store the new token, `location.replace(afterSwitchUrl(location))`: the
  page reloads, without `#chat=…`. A refusal → `errorText` in the header
  status, the select back on the active workspace, `/me` re-read (a 404 means
  the set changed since it was read).
- **Lost access.** Any 403 through `api` → the shell re-checks `/me`, one check
  in flight at a time. `/me` 200 → it was a role refusal; the caller shows the
  server's words where the action was (the chat error, a door's note, the
  Members page). `/me` 401/403 → forget the token, keep the server's sentence
  (or `EXPIRED`) as the one-time notice, reload. A 401 anywhere → the same,
  with `EXPIRED`.
- **Roles.**
  - Chat, viewer: no composer and no New chat; the footer shows `viewerNote`.
    The approvals panel lists the queue with no doors and says "Deciding needs
    the analyst or admin role." Chats list as today (a viewer has none).
  - Members: the nav entry shows for an admin only. Opened directly by anyone
    else, the page shows the server's 403 sentence.
  - The timeline is read-only for every role.
- **The active client is always visible**, at phone width too: below 600 px the
  tagline and the "signed in" status give way first, never the switcher.
- **Residency.** A deep turn the server refuses for residency is a 403 with a
  JSON `detail` before any stream; chat shows it through `errorText`, in the
  server's words.

## The candidates

1. **TD-047.** `ui.py` stats the file first, so the `FileResponse`'s ETag is
   known before answering. A request whose `If-None-Match` matches gets a
   **304** carrying the ETag, `Cache-Control: no-cache` and, for a page, its
   CSP; anything else gets the full 200 as today. Closes TD-047.
2. **`"[connection lost]"`** → `CONNECTION_LOST`.
3. **The stale proposal line (#20).** A reopened turn's proposal line carries
   its proposal id. Whenever the panel records a fresh row (after a door is
   used; after Review fetches a decided proposal), every line with that id is
   rewritten from `proposalLine(fresh, now)`.
4. **F2's page with live turns** (#26), after the build, in headless Chromium:
   an agent turn that files a note proposal; the chat reopened; Review →
   approve → Undo in the panel, the reopened line following each step (#20,
   live); the usage ceiling's 429 (the counter trick: no engine call) and the
   ksa residency 403, each in the server's words; narration on its own line on
   an agent turn with a lookup. The empty-answer note cannot be produced on
   demand: shown if a turn lands one, otherwise recorded as not reached (Node
   pins `noAnswerNote`). Budget ≤ ~10 engine calls; proposals rejected or
   undone, and only the probe's own observables deleted.

## F3's deferred minors (STATE.md follow-up #25)

- `timeline.js` is pinned to the null-safe `conf`/`pct`: no `.toFixed(` in it.
- `obsLink`'s own click listener is pinned (the assertion reads that
  function's body, not the file).
- The served-page helpers (`_page`, `_timeline_page`, and the new
  `_members_page`) assert every file answers 200.
- The `"**"` assertion scans the timeline's JavaScript only.
- A feed label's pill class goes through `labelClass(label)`: one of the known
  classes, anything else `slate`; a label with spaces adds no classes.

## Tests

Each fails before its code exists.

1. **Node** (each file run from pytest with the named reporter, B-007, and a
   pass-count floor):
   - `tests/js/shell_logic.test.mjs`: nav per role (admin sees Members; analyst
     and viewer do not; the current page marked); `switchOptions` keeps the
     server's order and length; `workspaceLabel` (kind from the entry, the
     region suffix only off `global`, the workspace name only when it differs);
     `mayChange`; `errorText` for a string, an array (input never echoed), no
     body, status 0; `viewerNote`; `afterSwitchUrl` drops the hash.
   - `tests/js/api.test.mjs`: the bearer header; `{ ok, status, body, detail }`;
     a 403 calls `onForbidden`, a 401 `onExpired`; a network failure is status
     0; no token → no `Authorization` header.
   - `tests/js/dom.test.mjs`: `el` with a stub document — props assigned,
     strings passed as text, absent children skipped.
   - Additions: `doorsFor(p, "viewer")` is empty for every status;
     `proposalLine`; `labelClass`.
2. **`tests/test_ui.py`:**
   - All three pages: `<header id="shell">`, `base.css` linked, the page module
     loaded; no `<style>`, inline script, `on…=` or `style=`; the same CSP.
   - **Nothing duplicated:** no page module (`chat.js`, `timeline.js`,
     `members.js`) defines `el(`, touches `sessionStorage`, or writes
     `Authorization`; `shell.js` holds the only storage calls, each guarded
     (D-056's pin moves here).
   - The timeline holds no sign-in of its own: no email input, no address, no
     `/api/auth/dev-login`.
   - 304: a repeat request with the ETag → 304, empty body, `no-cache`, and the
     CSP on a page; a different ETag → 200. Off the allow-list still 404s.
   - The Members page builds member text as text (no `innerHTML`).
   - Existing pins updated where code moved (e.g. `/api/auth/whoami` → `/me`).
3. **Mutants** on each guard, each caught: Members for an analyst; the hash
   kept by a switch; no reload after a switch; doors for a viewer; a 304 for a
   different ETag; a 403 without the re-check; `errorText` echoing a 422's
   input; `switchOptions` filtering an entry.
4. **Full gate** `./ci.sh`; README test count updated.
5. **A read-only adversarial review by a fresh agent** (most capable model)
   before the close: the page now carries the workspace token across a switch
   (SESSION-RULES.md, tenancy). Its fixes get their own review.

## Live check

Rebuild the app container. `f4-live-*` organizations seeded with the tenancy
CLI and deleted in the same command. Headless Chromium, recording every request
with its headers after each switch.

- **MSSP analyst, provider-wide; bank (global) and telco (ksa):** in bank, a
  shortcut question (no engine), the approvals panel, the timeline digest.
  Switch to telco: no bank chat entry, transcript or card on screen; this tab's
  `sessionStorage` holds only the telco token; the URL has no hash; **every
  request after the switch carries the telco token and no bank chat id.** A deep
  turn in telco shows the residency sentence.
- **Client viewer:** no composer, no doors, no Members. A `POST /api/chat` from
  the console with the tab's own token → 403 (the server refuses anyway).
- **Client analyst:** no Members entry; `/members` opened directly → the
  server's 403 sentence.
- **Client admin:** the Members list.
- **A membership removed while the page is open:** the next poll → signed out,
  with "You no longer have access to this workspace."
- **Every page at 1280 px and 390 px:** zero CSP violations; screenshots.
- Then F2's live walk (candidate 4).

Evidence: `docs/probes/2026-10-16-f4-shell-live.md`.

## Out of scope

- Any API change. The server's rules are as probed: a viewer cannot send even
  a shortcut question (the role dependency runs first), `restricted` is
  CLI-only (F5 note), the switch answer names no organization.
- Membership doors (F5), the audit page, analyst notes.
- The approvals stream (`/api/proposals/stream`): the page still polls
  (TD-046).
- Several tabs in several clients at once: each tab holds its own token
  (D-056), which already allows it; nothing synchronises them.

## Done when

The plan's F4 exit criteria hold live, TD-047 is closed in TECHNICAL_DEBT.md,
D-070 is in DECISIONS.md, the full gate is green, the review's findings are
fixed or logged, and the live check above is recorded.
