# The Chat Page Split, Then a CSP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The chat page's CSS, pure logic and DOM wiring live in their own files, served fresh from an allow-list, and the page carries a strict Content-Security-Policy.

**Architecture:** A one-off script cuts `auspex/static/index.html` at its existing markers into `css/chat.css`, `js/page-logic.js` (each top-level name `export`ed) and `js/chat.js` (an ES module importing the names it uses), leaving the markup. `auspex/routes/ui.py` serves exactly those three files `no-cache`; the tests read the page as served and import the logic module. Then the chat page gets a strict CSP (D-057), and R7's `busy` guard moves first in `send()`'s `finally`.

**Tech Stack:** FastAPI (`FileResponse`), plain ES modules, pytest, Node's test runner.

**Spec:** `docs/superpowers/specs/2026-10-12-page-split-csp-design.md` (approved by Burhan, F2).

## Global Constraints

- The move is verbatim: no logic changes inside the moved code, only `export`/`import` lines, a 4-space dedent, and the logic block's stale two-line header comment replaced.
- Served paths, exactly: `/css/chat.css` (`text/css`), `/js/page-logic.js` and `/js/chat.js` (`text/javascript`), each `Cache-Control: no-cache`; any other name under `/css/` or `/js/` is a 404.
- `index.html` loads them with `<link rel="stylesheet" href="/css/chat.css" />` and `<script type="module" src="/js/chat.js"></script>`; no inline `<script>` body, no `<style>`, no `on…=` attribute.
- The CSP on `/`, exactly: `default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`. No `'unsafe-inline'`, no `'unsafe-eval'`. `/timeline` gets none.
- `timeline.html` is not touched.
- One concern per commit; never amend. Trailers: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01DhCqy11iYBpKh8zJKuC2bP`. README count in both places on every test-adding commit (`.venv/bin/pytest --collect-only -q | tail -1`).
- Do not edit code while `./ci.sh` runs; no pytest during live checks.

## Review Focus

1. **A strict-mode difference in the moved DOM code** (module scripts are strict): an assignment to an undeclared name, or a name the DOM code used from the logic block but the import missed, throws at load and leaves a dead page. Pinned: Task 1 Step 6 parses both modules with Node and imports the logic module; Task 1 Step 9 loads the page in a browser with zero console errors.
2. **A stale cached module after a deploy** (B-003 again, for the new files): pinned by Task 1's `no-cache` test on each asset.
3. **A path trick reaching a file outside the allow-list**: pinned by Task 1's 404 tests.
4. **The CSP blocking something the page needs** (Google Fonts, the SSE fetch, a style set by script): pinned by Task 4's live run reading the console for violations.
5. **A later edit re-inlining a script or handler** (which the CSP would then silently block in the browser): pinned by Task 1's no-inline test.

---

### Task 1: Split the page into a stylesheet, a logic module and a DOM module

**Files:**
- Create: `auspex/static/css/chat.css`, `auspex/static/js/page-logic.js`, `auspex/static/js/chat.js` (by the script in Step 3)
- Modify: `auspex/static/index.html` (by the script), `auspex/routes/ui.py`, `pyproject.toml:45`, `Dockerfile:13,22`, `tests/js/page_logic.test.mjs:1-23`, `tests/test_ui.py`, `tests/test_packaging.py`, `tests/test_page_logic.py:1-9`, `README.md`

**Interfaces:**
- Produces: the three served files; `_page(client)` in `tests/test_ui.py` (the HTML plus the three files, joined); `_ASSETS` in `auspex/routes/ui.py`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_ui.py`, add `import re` to the imports, then add right after the imports:

```python
_ASSET_PATHS = ("/css/chat.css", "/js/page-logic.js", "/js/chat.js")


def _page(client) -> str:
    """The chat page as a browser gets it: the HTML and the files it loads
    (TD-045). The assertions below read this, so they also prove the files
    are served."""
    return "\n".join([client.get("/").text] + [client.get(p).text for p in _ASSET_PATHS])
```

and append:

```python
@pytest.mark.parametrize("path,media", [
    ("/css/chat.css", "text/css"),
    ("/js/page-logic.js", "text/javascript"),
    ("/js/chat.js", "text/javascript"),
])
def test_the_pages_files_are_served_fresh_with_their_types(client, path, media):
    """TD-045: the page's CSS and modules are files now. B-003 holds for them
    too: an open browser must not keep running an old module after a deploy."""
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(media)
    assert "no-cache" in resp.headers.get("cache-control", "")


@pytest.mark.parametrize("path", ["/js/ui.py", "/js/..%2Fui.py", "/js/timeline.html", "/css/index.html"])
def test_only_the_pages_own_files_are_served(client, path):
    assert client.get(path).status_code == 404


def test_the_page_holds_no_inline_script_or_style(client):
    """TD-045, and what D-057's CSP depends on: a script or style written into
    the page, or an `on…=` handler, would be blocked by the policy in the
    browser while every test here stayed green."""
    html = client.get("/").text
    assert "<style" not in html
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) is None
    assert re.search(r"\son[a-z]+\s*=", html) is None
    assert '<link rel="stylesheet" href="/css/chat.css" />' in html
    assert '<script type="module" src="/js/chat.js"></script>' in html
```

In `tests/test_packaging.py` append:

```python
def test_the_pages_files_are_packaged():
    """TD-045: the chat page's CSS and modules ship in the wheel, and the
    deps-only skeleton satisfies their globs the way it does static/*.html."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert '"static/css/*.css"' in pyproject and '"static/js/*.js"' in pyproject
    skeleton = (REPO_ROOT / "Dockerfile").read_text().split("# App layer")[0]
    assert "auspex/static/css/placeholder.css" in skeleton
    assert "auspex/static/js/placeholder.js" in skeleton
```

- [ ] **Step 2: Run them to see them fail.**

Run: `.venv/bin/pytest tests/test_ui.py tests/test_packaging.py -q -k "served_fresh or own_files or no_inline or packaged"`
Expected: FAIL — the asset GETs 404 (no route), the page has `<style>`, pyproject lacks the globs. (`/js/ui.py` etc. already 404 and pass; that is expected.)

- [ ] **Step 3: Cut the page with the script** (run once, from the repo root):

```bash
python3 - <<'EOF'
import re
from pathlib import Path

static = Path("auspex/static")
lines = (static / "index.html").read_text().split("\n")

def find(text):
    hits = [i for i, l in enumerate(lines) if l.strip() == text]
    assert len(hits) == 1, (text, hits)
    return hits[0]

style_open, style_close = find("<style>"), find("</style>")
script_open, script_close = find("<script>"), find("</script>")
logic_open, logic_close = find("// <page-logic>"), find("// </page-logic>")
assert style_open < style_close < script_open < logic_open < logic_close < script_close
assert script_open + 1 == logic_open

def dedent(block):
    for l in block:
        assert l == "" or l.startswith("    "), repr(l)
    return "\n".join(l[4:] for l in block).strip("\n") + "\n"

# the logic: the stale header comment goes, every top-level name is exported
logic = lines[logic_open + 1:logic_close]
assert logic[0].strip().startswith("// Pure: no DOM") and logic[1].strip().startswith("// block under Node")
logic = logic[2:]
decl = re.compile(r"^    (?:async )?(?:function\*? (\w+)|const (\w+)|let (\w+)|class (\w+))")
names, exported = [], []
for l in logic:
    m = decl.match(l)
    if m:
        names.append(next(g for g in m.groups() if g))
        l = "    export " + l[4:]
    exported.append(l)
logic_js = ("// The chat page's pure logic (D-052): no DOM, no clock of its own. The page\n"
            "// imports it (js/chat.js) and tests/js/page_logic.test.mjs imports it under\n"
            "// Node, so what is tested is the module the browser runs.\n\n" + dedent(exported))

dom = dedent(lines[logic_close + 1:script_close])
used = [n for n in names if re.search(r"(?<![\w.$])" + re.escape(n) + r"\b", dom)]
imports, row = [], "  "
for n in used:
    piece = n + ", "
    if len(row) + len(piece) > 92:
        imports.append(row.rstrip())
        row = "  "
    row += piece
imports.append(row.rstrip())
chat_js = ("// The chat page's DOM wiring. Its pure logic is ./page-logic.js; this builds\n"
           "// elements from it and talks to the API. Model and tool text are always text,\n"
           "// never HTML (D-053).\n"
           "import {\n" + "\n".join(imports) + "\n} from \"./page-logic.js\";\n\n" + dom)

(static / "css").mkdir(exist_ok=True)
(static / "js").mkdir(exist_ok=True)
(static / "css" / "chat.css").write_text(dedent(lines[style_open + 1:style_close]))
(static / "js" / "page-logic.js").write_text(logic_js)
(static / "js" / "chat.js").write_text(chat_js)
html = (lines[:style_open] + ['  <link rel="stylesheet" href="/css/chat.css" />']
        + lines[style_close + 1:script_open]
        + ['  <script type="module" src="/js/chat.js"></script>'] + lines[script_close + 1:])
(static / "index.html").write_text("\n".join(html))
print(len(names), "exported;", len(used), "imported:", ", ".join(used))
EOF
wc -l auspex/static/index.html auspex/static/css/chat.css auspex/static/js/*.js
```

Expected: `35 exported; N imported: …`; `index.html` about 120 lines.

- [ ] **Step 4: Serve the files.** In `auspex/routes/ui.py`, change the import line to `from fastapi import APIRouter, HTTPException` and add after `_REVALIDATE`:

```python
# TD-045: the chat page's own files, by name. An allow-list, so no name a
# request can make reaches anything else on disk.
_ASSETS = {
    "css/chat.css": ("text/css", _STATIC / "css" / "chat.css"),
    "js/page-logic.js": ("text/javascript", _STATIC / "js" / "page-logic.js"),
    "js/chat.js": ("text/javascript", _STATIC / "js" / "chat.js"),
}


def _asset(key: str) -> FileResponse:
    entry = _ASSETS.get(key)
    if entry is None:
        raise HTTPException(status_code=404, detail="Not Found")
    media_type, path = entry
    return FileResponse(path, media_type=media_type, headers=_REVALIDATE)
```

and at the end of the file:

```python
@router.get("/css/{name}", include_in_schema=False)
async def stylesheet(name: str) -> FileResponse:
    return _asset(f"css/{name}")


@router.get("/js/{name}", include_in_schema=False)
async def script(name: str) -> FileResponse:
    return _asset(f"js/{name}")
```

Update the module docstring's first paragraph: "Serves the chat page (its markup, plus its CSS and two ES modules from an allow-list, TD-045) and the timeline page."

- [ ] **Step 5: Package them.** `pyproject.toml` line 45 becomes `auspex = ["static/*.html", "static/css/*.css", "static/js/*.js"]`. In the Dockerfile skeleton, line 13's `auspex/static` becomes `auspex/static auspex/static/css auspex/static/js`, and line 22's `auspex/static/placeholder.html server.py` becomes `auspex/static/placeholder.html auspex/static/css/placeholder.css auspex/static/js/placeholder.js server.py`.

- [ ] **Step 6: Point the Node tests at the module, and check both modules parse.** In `tests/js/page_logic.test.mjs`, replace lines 1–23 (the comment, the `readFileSync` import, `html`, `block`, its assert and the `new Function` destructuring) with:

```js
// The chat page's pure logic (D-052), run under Node's built-in test runner:
// no dependencies, no browser. It imports auspex/static/js/page-logic.js, the
// module the page itself imports, so what is tested is what the page runs.
// tests/test_page_logic.py runs this file inside the pytest gate.
//
//   node --test tests/js/page_logic.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createPacer, indicatorText, markdownNodes,
  doorsFor, statusText, undoText, undoLineFor, askedText, mergeQueue, armDoor, confirmable,
  spendText, chatSpendText, chatIdFromHash, relativeTime, chatListLabel, ledgerSpendText, endingText, reopenedTurnPlan,
  noAnswerNote, overlayAfter,
} from "../../auspex/static/js/page-logic.js";
```

(keep every line after the old line 23 as it is). In `tests/test_page_logic.py`, change the docstring's first sentence to "The chat page's pure logic (D-052), inside the gate." and "The logic is JavaScript in auspex/static/index.html" to "The logic is JavaScript in auspex/static/js/page-logic.js". Then:

Run: `node --test --test-reporter=spec tests/js/page_logic.test.mjs 2>&1 | grep -E "^ℹ (pass|fail)"` → `ℹ pass 46`, `ℹ fail 0`.
Run: `node --check auspex/static/js/chat.js && node --check auspex/static/js/page-logic.js && node --input-type=module -e "import('./auspex/static/js/page-logic.js').then(m => console.log(Object.keys(m).length, 'exports'))"` → no error, `35 exports`.

- [ ] **Step 7: Make the existing UI tests read the page as served.** In `tests/test_ui.py`:
  - every `client.get("/").text` becomes `_page(client)` (ten places, one of them `.lower()`);
  - in `test_index_served_dark_first_and_on_brand`, `body = resp.text` becomes `body = _page(client)` (the palette is in the CSS now);
  - in `test_the_header_keeps_its_labels_whole_on_a_phone`, the split `.split("\n    }", 1)` becomes `.split("\n}", 1)` (the CSS is dedented);
  - in `test_an_overlay_on_a_narrow_screen_has_a_backdrop_that_closes_it`, `assert "overlayAfter(" in body.split("// </page-logic>", 1)[1]` becomes `assert "overlayAfter(" in client.get("/js/chat.js").text`.

Run: `.venv/bin/pytest tests/test_ui.py tests/test_page_logic.py tests/test_packaging.py -q` → all pass.

- [ ] **Step 8: README count, ruff, full gate.** `.venv/bin/pytest --collect-only -q | tail -1` → expect 1357 (9 new); update both README places. `.venv/bin/ruff check auspex tests`. Then `./ci.sh > <scratchpad>/ci-split.log 2>&1; echo $?` → `0`.

- [ ] **Step 9: Live, zero console errors.** The gate rebuilt the app. In headless Chromium at `http://localhost:8000/`: the console holds only the known `favicon.ico` 404; sign in as `fe-probe-split@auspex.dev`; send `check 8.8.8.8` (no engine call); open and close the chat list (at 390 px) and the approvals panel; reload — the chat comes back under the divider; the network panel shows `/css/chat.css`, `/js/chat.js`, `/js/page-logic.js` with `cache-control: no-cache`. Delete the probe user afterwards.

- [ ] **Step 10: Commit.**

```bash
git add auspex/static/index.html auspex/static/css/chat.css auspex/static/js/page-logic.js auspex/static/js/chat.js \
        auspex/routes/ui.py pyproject.toml Dockerfile tests/js/page_logic.test.mjs tests/test_page_logic.py \
        tests/test_ui.py tests/test_packaging.py README.md
git commit   # subject: refactor(page): the chat page is markup, a stylesheet, a logic module and a DOM module, served fresh (TD-045) (1357 tests)
```

---

### Task 2: The chat page carries a strict CSP (D-057)

**Files:**
- Modify: `DECISIONS.md` (append D-057), `auspex/routes/ui.py`, `tests/test_ui.py`, `TECHNICAL_DEBT.md` (TD-051), `README.md`

**Interfaces:**
- Consumes: Task 1's `index()` route and `_REVALIDATE`.
- Produces: `_CHAT_CSP` in `auspex/routes/ui.py`.

- [ ] **Step 1: Record D-057** (append to `DECISIONS.md`) and commit it alone:

```markdown

## D-057 — The chat page carries a strict Content-Security-Policy (2026-10-12, F2)

**Context.** D-056 keeps the sign-in token in the tab's `sessionStorage`, where
any script running on the page can read it, and the page sent no CSP (TD-051).
TD-045's split moved every script and style rule out of the page, so a policy
needs neither `'unsafe-inline'` nor a hash per edit.

**Decision (Burhan's call; the recommended option).** `GET /` is served with
`default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com;
font-src https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:;
object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`.
- Scripts only from the page's own origin: an injected `<script>` or `on…=`
  does not run.
- Fetches only to the platform: an injected script that did run could not send
  the token anywhere else.
- No framing, no `<base>`, no form posts, no plugins.
- The page's styles set through the CSSOM (`el.style.display`) are not governed
  by a CSP; the markup has no `style=` attribute.
- Links in answers (D-053) are navigation, which this does not restrict.

**Bounds, stated.** `/timeline` has no CSP yet: it still runs an inline script
(TD-051 narrows to it). A new external origin (a CDN, an analytics host) needs
a D-entry, not an edit to the header.
```

- [ ] **Step 2: Write the failing tests** (append to `tests/test_ui.py`):

```python
def test_the_chat_page_is_served_with_a_strict_content_security_policy(client):
    """D-057: the sign-in token sits in sessionStorage (D-056), so the page
    runs only its own scripts and talks only to its own origin."""
    csp = client.get("/").headers.get("content-security-policy", "")
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";") if d.strip())
    assert directives["default-src"] == "'self'"
    assert directives["script-src"] == "'self'"
    assert directives["connect-src"] == "'self'"
    assert directives["style-src"] == "'self' https://fonts.googleapis.com"
    assert directives["font-src"] == "https://fonts.gstatic.com"
    for d in ("object-src", "base-uri", "form-action", "frame-ancestors"):
        assert directives[d] == "'none'", d
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp


def test_the_timeline_page_has_no_csp_yet(client):
    """TD-051's remainder: timeline.html still runs an inline script, which the
    chat page's policy would block."""
    assert "content-security-policy" not in client.get("/timeline").headers
```

Run: `.venv/bin/pytest tests/test_ui.py -q -k "content_security or no_csp_yet"` → the first FAILS (`KeyError: 'default-src'`), the second passes (expected).

- [ ] **Step 3: Send the header.** In `auspex/routes/ui.py`, after `_REVALIDATE`:

```python
# D-057: the chat page runs only its own scripts and talks only to its own
# origin; TD-045 moved every script and style rule out of it to make that
# possible without 'unsafe-inline'. /timeline has no policy yet (TD-051).
_CHAT_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "connect-src 'self'",
    "img-src 'self' data:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
])
```

and `index()` returns `FileResponse(_INDEX, media_type="text/html", headers={**_REVALIDATE, "Content-Security-Policy": _CHAT_CSP})`.

Run: `.venv/bin/pytest tests/test_ui.py -q` → all pass.

- [ ] **Step 4: Narrow TD-051.** Retitle it `## TD-051 (F2) — the timeline page sends no Content-Security-Policy` and add, after its title, a line: `**Narrowed (F2, D-057):** the chat page carries a strict CSP since the split (TD-045). What remains is /timeline, which still runs an inline script with \`onclick\` attributes.` Commit separately.

- [ ] **Step 5: README count (+2 → 1359), full gate, commit** the route + tests + README as one commit: `feat(ui): the chat page carries a strict Content-Security-Policy (D-057) (1359 tests)`.

---

### Task 3: A throw while a turn ends cannot leave the composer busy (R7)

**Files:**
- Modify: `auspex/static/js/chat.js` (`send()`'s `finally`), `tests/test_ui.py`, `README.md`

- [ ] **Step 1: Failing test** (append to `tests/test_ui.py`):

```python
def test_a_throw_while_a_turn_ends_cannot_leave_the_composer_busy(client):
    """R7 (F2's final review): `busy` was cleared at the end of send()'s finally,
    after the paint and the cleanup, so a throw there left the composer stuck
    and every chat switch refused. It is cleared first."""
    js = client.get("/js/chat.js").text
    ending = js.split("async function send()", 1)[1].split("} finally {", 1)[1]
    assert ending.lstrip().startswith("busy = false;")
```

Run it → FAIL.

- [ ] **Step 2: Move it.** In `send()`'s `finally`, the first line becomes `busy = false;`, and the later `busy = false; loadChats();` becomes `loadChats();`.

- [ ] **Step 3:** `.venv/bin/pytest tests/test_ui.py -q` → pass; README count (+1 → 1360); commit `fix(page): send() clears busy first, so a throw while a turn ends cannot leave the composer stuck (R7) (1360 tests)`.

---

### Task 4: Rules, debt and the live proof

**Files:**
- Modify: `SESSION-RULES.md` ("The page"), `TECHNICAL_DEBT.md` (TD-045)
- Create: `docs/probes/2026-10-12-f2-page-split-csp.md`

- [ ] **Step 1: SESSION-RULES** — in "The page": "writes them with `textContent`/`append` (`auspex/static/index.html`)" → "(`auspex/static/js/chat.js`)"; the bullet "**The page's logic lives in its `// <page-logic>` block**: pure functions, run under Node by `tests/js/page_logic.test.mjs` inside the pytest gate." → "**The page's logic lives in `auspex/static/js/page-logic.js`**: pure, exported functions, imported by the page (`js/chat.js`) and by `tests/js/page_logic.test.mjs` under Node inside the pytest gate."; and add a bullet: "**The chat page carries a strict CSP (D-057).** No inline script or style and no `on…=` in its markup; a new external origin needs a D-entry." Commit.

- [ ] **Step 2: TD-045** — add a `**Closed (F2):**` line naming the split commit. Commit.

- [ ] **Step 3: Full gate**, then live in headless Chromium against the rebuilt container: sign in as `fe-probe-csp@auspex.dev`, `check 8.8.8.8`, open the chat list and the approvals panel at 390 px, reload, reopen the chat, then at 1280 px. Read the console after each step: **no CSP violation** ("Refused to …") and no error besides `favicon.ico`. Check the response headers of `/` carry the policy. Delete the probe user.

- [ ] **Step 4: Record** what was run and seen in `docs/probes/2026-10-12-f2-page-split-csp.md` (incl. the known cost: the page's functions are module-scoped, so console-driven probes now drive the DOM). Commit.
