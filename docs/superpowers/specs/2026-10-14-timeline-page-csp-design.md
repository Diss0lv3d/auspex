# The timeline page under D-057's policy (F3, closes TD-051)

_Spec, 2026-10-14, session F3 (front end). Owner: Hunaiza (D-059). Approved
in conversation section by section; this file is the written record._

## Why

The chat page carries a strict Content-Security-Policy since F2 (D-057), and
the sign-in token sits in the tab's sessionStorage (D-056). `/timeline` sends
no policy at all (TD-051). Today `auspex/static/timeline.html` (280 lines)
holds its own inline `<style>` and `<script>`, four `onclick=` attributes, and
builds every card as an HTML string into `innerHTML`, escaped by an `esc()`
that does not escape `'`, with inline `style="…"` attributes. All of that is
feed-derived text (sources, claims, checker names, observable values) going
through string-built HTML, and all of it would be blocked by a strict policy.

## Goal

`/timeline` is served with exactly the chat page's policy (`_CHAT_CSP`), runs
with zero CSP violations in a real browser, and renders every piece of
feed-derived text as text, never as HTML.

## Decisions taken (Hunaiza, F3)

1. **The timeline's pure logic gets its own tested module**,
   `js/timeline-logic.js`, run under Node inside the pytest gate like
   `js/page-logic.js`. It is not added to `page-logic.js`.
2. **The two pages share nothing new.** `timeline.js` carries its own copy of
   the 5-line `el()` factory and `timeline.css` its own palette block. The chat
   page's files are not touched. Cost: about 15 duplicated lines.
3. **Behaviour is unchanged.** Same cards, copy, colours, auto sign-in on load
   and pre-filled dev email. This is a rebuild, not a redesign.

## Files

| File | Holds |
|---|---|
| `auspex/static/timeline.html` | Markup only: header, inputs, buttons, `<main>`. Links `/css/timeline.css` and `<script type="module" src="/js/timeline.js">`. No `<style>`, no inline script, no `on…=`, no `style=`. |
| `auspex/static/css/timeline.css` | Today's inline styles moved unchanged, plus utility classes for the spacing the inline `style="margin-top…"` / `font-size:16px` attributes gave. |
| `auspex/static/js/timeline-logic.js` | Pure exported functions, no DOM: `count(d, name)` ("at least N" for a list the server cut), `pct(x)` (0–100 clamp for a bar), the colour class for a claim status, and the digest banner's kind and sentence. |
| `auspex/static/js/timeline.js` | The DOM wiring: sign-in, `digest()`, `open_()`. Cards built with `el()` and text nodes; bar widths set through `element.style.width` (the CSSOM, which the policy allows); the observable links and the three buttons wired with `addEventListener`. No `innerHTML` anywhere. |
| `auspex/routes/ui.py` | `css/timeline.css`, `js/timeline-logic.js`, `js/timeline.js` added to `_ASSETS` (served `no-cache`). `/timeline` served with `_CHAT_CSP`. The comment saying `/timeline` has no policy is updated. |
| `pyproject.toml` package-data / Dockerfile | Checked: the new static files must ship in the built image (STATE.md follow-up #16). |

The pages still hold no decay arithmetic of their own: the band is the
server's `v.staleness`, and the page only renders it (S16).

## Tests

1. **Logic, under Node:** `tests/js/timeline_logic.test.mjs`, run from pytest
   the way `tests/test_page_logic.py` runs `page_logic.test.mjs` (named
   reporter, B-007). Covers `count` on an uncut and a cut list; `pct` at 0, 1,
   below 0 and above 1; each claim status's colour; every banner branch (quiet
   and trustworthy, quiet with a degraded checker, quiet with nothing watching,
   activity complete, activity cut). Each test fails before the code exists.
2. **Page, in `tests/test_ui.py`:**
   - The timeline tests read the page as served (markup plus its three files)
     through a `_timeline_page(client)` helper, as the chat tests use
     `_page(client)`. The S16/S17 promises keep their assertions: no decay
     arithmetic, counts through the helper that knows about the cut, the
     server's `truncated`/`complete` flags trusted, the engine never named.
   - The timeline markup holds no `<style>`, no inline script, no `on…=` and
     no `style=`.
   - `/timeline` carries the exact D-057 directives. This replaces
     `test_the_timeline_page_has_no_csp_yet`.
   - The three new files are served; names off the allow-list still 404.
   - `timeline.js` contains no `innerHTML`.
3. **Mutants** on each guard: e.g. drop the "at least", drop the CSP header,
   put an `innerHTML` back. Each must be caught.
4. **Full gate:** `./ci.sh`, README test count updated.

## Live check

Rebuild the app container. In a real browser at `/timeline`:
- zero CSP violations in the console;
- the digest renders, an observable's timeline opens from a link and from the
  input, Digest goes back, Sign in works;
- the decay bars show their widths;
- a feed string carrying `<img src=x onerror=…>` renders as literal text.

Evidence goes to `docs/probes/2026-10-14-f3-timeline-csp.md`.

## Out of scope

- Sharing helpers between the two pages (decision 2).
- The timeline reusing the chat page's stored sign-in.
- The pre-filled dev email in the timeline header: parked in IDEAS.md.
- Any change to `/api/timeline` or its payload.

## Done when

TD-051 is closed in TECHNICAL_DEBT.md, the full gate is green, and the live
check above is recorded.
