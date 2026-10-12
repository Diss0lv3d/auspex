# The chat page split into modules, then a CSP — design (F2, 2026-10-12)

_Approved by Burhan in F2. His calls: a logic module plus one DOM module (the
recommended shape, over splitting the DOM by concern or classic scripts); the
CSP in the same session as its own commit (recommended). Closes TD-045 and the
chat page's half of TD-051._

## Why

- **TD-045.** `auspex/static/index.html` is 1,151 lines: ~140 of CSS, ~70 of
  markup and ~930 of script in one inline `<script>`. Its pure logic is tested
  by regex-extracting the `// <page-logic>` block and running it through
  `new Function` (`tests/js/page_logic.test.mjs`), so the tests run a copy of the
  code in a different mode from the browser.
- **TD-051.** The page sends no Content-Security-Policy, and since D-056 the
  sign-in token sits in `sessionStorage`, readable by any script on the page. A
  useful CSP needs the script out of the page: an inline script needs
  `'unsafe-inline'` or a hash that every edit moves.

## What

### Files

| File | Holds | From |
|---|---|---|
| `auspex/static/js/page-logic.js` | the pure functions, each `export`ed | the `// <page-logic>` block, verbatim |
| `auspex/static/js/chat.js` | the DOM wiring; first line `import {…} from "./page-logic.js"` | the rest of the inline script, verbatim, its section markers (`// <chats-dom>`, `// <approvals-dom>`) kept |
| `auspex/static/css/chat.css` | every style rule | the `<style>` block, verbatim |
| `auspex/static/index.html` | the markup, `<link rel="stylesheet" href="/css/chat.css">`, `<script type="module" src="/js/chat.js"></script>` | — |

- `page-logic.js` stays pure: no DOM, no clock of its own (`now` is passed in).
  It exports every name `chat.js` uses, and nothing else is added to it.
- `chat.js` is a module, so it runs deferred and in strict mode, and its names
  are no longer globals. It loads where the inline script did (the end of the
  page), so nothing about load order changes.
- `timeline.html` is not touched.

### Serving (`auspex/routes/ui.py`)

- `GET /css/chat.css` → `text/css`.
- `GET /js/{name}` → `text/javascript`, for `name` in an allow-list of exactly
  `page-logic.js` and `chat.js`. Any other name, including a path trick such as
  `..%2Fui.py`, is a 404.
- All three with `Cache-Control: no-cache` (B-003: a deploy must reach an open
  browser, and the module graph is fetched again with the page).

### Packaging

- `pyproject.toml` package-data: `auspex = ["static/*.html", "static/css/*.css", "static/js/*.js"]`.
- The Dockerfile's deps-only skeleton makes `auspex/static/css` and
  `auspex/static/js` with a placeholder file in each, as it does for
  `static/placeholder.html`.

### Tests follow the code

- `tests/js/page_logic.test.mjs` imports from
  `../../auspex/static/js/page-logic.js` instead of the regex and
  `new Function`. Same tests and count (46); they now run the module the browser
  runs, in the same mode.
- `tests/test_page_logic.py` keeps running that file; its docstring points at
  the module.
- `tests/test_ui.py` reads the page **as served**: one helper fetches `/`,
  `/js/chat.js`, `/js/page-logic.js` and `/css/chat.css` and joins them, and
  the existing assertions read that. They keep their meaning and now also prove
  the routes serve the files.
- New:
  - each asset is served with its content type and `no-cache`;
  - an unknown name and a path trick under `/js/` are 404s;
  - `index.html` holds no inline `<script>` body, no `<style>` and no `on…=`
    attribute;
  - package-data declares the css and js globs, and the skeleton placeholds
    them (`tests/test_packaging.py`).

## The CSP (D-057), its own commit after the split is green

`GET /` is served with:

```
default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com;
font-src https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:;
object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
```

- No `'unsafe-inline'` anywhere: the markup has no `style=` or `on…=`
  attribute (checked), and the page sets styles through the CSSOM
  (`el.style.display = …`), which a CSP does not govern.
- Links in answers (D-053) are navigation, which `default-src` does not
  restrict; they open in a new tab with `noopener noreferrer` as before.
- `/timeline` gets no CSP: it still runs an inline script. TD-051 narrows to
  that page rather than closing.
- A test pins the header on `/` and its absence on `/timeline`.
- D-057 records the policy, why each directive, and the bound (the timeline
  page; style injection through a future `innerHTML` is still on D-053's rule).

## R7's guard, its own commit

`busy = false` moves first in `send()`'s `finally`, so a client-side throw in
the paint or cleanup there can never leave the composer stuck (the final review
of the reload work, parked as R7).

## Proof

- The full gate after each code commit.
- Live, in a real browser against the rebuilt container: sign in, send a
  shortcut turn (`check 8.8.8.8`, no engine call), open the chat list and the
  approvals panel, reload, reopen the chat. **Zero console errors and zero CSP
  violations** throughout (the console is read, not just the page). The assets
  are fetched with `no-cache`.
- Record: `docs/probes/2026-10-12-f2-page-split-csp.md`.

## Known cost

Functions in a module are not globals: live probes that drove the page from
the console through `busy`, `renderChats` or `openChat` (F2's Task 8 and the
fix wave did) can no longer reach them. Probes drive the page through its DOM
instead.

## Not in scope

- Splitting `chat.js` further by concern (Burhan: one DOM module).
- `timeline.html`'s split and CSP.
- Subresource integrity for Google Fonts.
