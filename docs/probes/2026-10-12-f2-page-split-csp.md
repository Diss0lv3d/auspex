# F2 — the chat page split (TD-045) and its CSP (D-057), live

_2026-10-12, headless Chromium (Playwright) against the container rebuilt by
`./ci.sh` at `b57f667` (exit 0, 1360 passed). No inference: one shortcut turn
per probe user. Users `fe-probe-split@` and `fe-probe-csp@auspex.dev`, deleted
after; one inserted `annotate_observable` proposal, rejected through the panel
and deleted._

## What changed

- `e99302d` — `index.html` (62 lines of markup) loads `css/chat.css` and the ES
  module `js/chat.js`, which imports 18 of `js/page-logic.js`'s 35 exports. The
  three files are served from an allow-list, `no-cache`; anything else under
  `/css/` or `/js/` is a 404. The Node tests import the module.
- `0aac79e` — `GET /` carries D-057's policy; `/timeline` none (TD-051).
- `d4daa62` — `send()` clears `busy` first in its `finally` (R7).

## After the split (at `e99302d`, before the CSP)

At 1280 px: signed in; `check 8.8.8.8` answered with "Answered without the
engine"; the chat list showed it; the body's background computed to
`rgb(10, 13, 18)` (the stylesheet applied). Fetched from the page:

| Path | Status | Content-Type | Cache-Control |
|---|---|---|---|
| `/css/chat.css` | 200 | `text/css; charset=utf-8` | `no-cache` |
| `/js/chat.js` | 200 | `text/javascript; charset=utf-8` | `no-cache` |
| `/js/page-logic.js` | 200 | `text/javascript; charset=utf-8` | `no-cache` |

At 390 px, driven through the DOM: the Chats button opened the list over the
backdrop, a tap on the backdrop closed it, Approvals opened, Esc closed it.
A reload kept the sign-in and reopened the chat under the divider, with the
sidebar's current entry "check 8.8.8.8". Console: only the known
`favicon.ico` 404.

## Under the CSP (at `b57f667`)

- `GET /` answered `Content-Security-Policy: default-src 'self'; script-src
  'self'; style-src 'self' https://fonts.googleapis.com; font-src
  https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:;
  object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`.
- Inter and Space Grotesk loaded (`document.fonts`), the stylesheet applied,
  the module ran.
- At 390 px: the chat list opened and the backdrop closed it; Approvals opened
  with the inserted card (1 card); Esc closed it; a reload reopened the chat,
  whose turn showed `Proposal: Attach a note to ipv4 185.220.101.9: csp probe ·
  Waiting for your approval [Review]`; Review opened the panel at that card,
  highlighted, doors Approve and Reject; **Reject** (a POST under
  `connect-src 'self'`) answered "Rejected", and the row read `rejected`.
- At 1280 px: the chat list on (`display: flex`), the backdrop `display: none`,
  the open panel making room (`padding-right: 380px`), and the point at the
  centre of Send hit `send`.
- **Console: no entry at all during this run** — no CSP violation ("Refused
  to …"), no error.

## Known cost

`js/chat.js` is a module, so its functions and `busy` are not globals. Probes
that drove the page from the console through `busy`, `renderChats` or
`openChat` (F2's reload probe and its fix wave did) now drive the DOM instead,
as this one does.
