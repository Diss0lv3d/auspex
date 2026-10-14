# The timeline page under D-057's policy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/timeline` is served with the chat page's strict CSP (D-057), runs with zero CSP violations, and renders all feed text as text (closes TD-051).

**Architecture:** The 280-line `timeline.html` splits into markup, `css/timeline.css`, a pure tested `js/timeline-logic.js`, and a DOM module `js/timeline.js` that builds cards with an `el()` factory and listeners. `auspex/routes/ui.py` serves the three files from its allow-list and sends `_CHAT_CSP` on `/timeline`.

**Tech Stack:** FastAPI `FileResponse`, plain ES modules, Node's built-in test runner run from pytest, pytest + FastAPI test client.

**Spec:** `docs/superpowers/specs/2026-10-14-timeline-page-csp-design.md`

## Global Constraints

- The policy is exactly `_CHAT_CSP` in `auspex/routes/ui.py`; no `'unsafe-inline'`, no new origin (either is a D-entry, not an edit).
- No `innerHTML`, no `<style>`, no inline `<script>`, no `on…=` and no `style=` anywhere in the timeline's markup or modules.
- Feed-derived text (observable values, sources, claims, checker names, triggers, notes) reaches the page only as text nodes or `textContent`.
- The chat page's files (`index.html`, `css/chat.css`, `js/chat.js`, `js/page-logic.js`) are not touched.
- Behaviour and copy unchanged: same cards, wording, colours, auto sign-in on load, pre-filled dev email.
- The page holds no decay arithmetic: the band is the server's `v.staleness`; no `Math.pow`, no `**`, no `half_life` other than `half_life_days` anywhere in the served page (S16 test).
- The engine is never named in any served file (D-002, `FORBIDDEN_ENGINE_NAMES`).
- One concern per commit, `feat|fix|chore|docs|test(scope): summary`, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit locally; **never push** (Hunaiza asks for the PR herself).
- Run pytest from `.venv` with deps up: `source .venv/bin/activate && docker compose up -d --wait postgres opensearch`.
- Every test-adding commit updates the README's single test count (`tests/test_docs.py::test_the_readme_states_one_current_test_count`).

## Review Focus

1. A verdict whose `confidence_at_write`/`confidence_now` is null: today `.toFixed` throws and the whole timeline says "no timeline for that id"; expected: the card renders with "—" and an empty bar (Task 1 `conf`/`pct` tests).
2. Feed text carrying markup (`<img src=x onerror=…>`) or a `'` in an observable id: expected to render literally and the link still opens the right timeline (Task 2 no-`innerHTML` pin; Task 4 live check).
3. A checker list that is empty vs. degraded: the banner must say "nothing was watching" vs. "a checker is degraded" exactly as today (Task 1 banner tests).
4. A list the server cut: banner and section must state a floor ("at least N", "showing the first N — there are more"), never a total (Task 1 `count` tests; Task 2 S17 test kept).
5. Browser blocks something the tests cannot see (a stray inline style, a font origin): expected zero console CSP violations (Task 4 live check).

---

### Task 1: The timeline's pure logic, tested under Node

**Files:**
- Create: `auspex/static/js/timeline-logic.js`
- Create: `tests/js/timeline_logic.test.mjs`
- Create: `tests/test_timeline_logic.py`
- Modify: `README.md` (test count, two places)

**Interfaces:**
- Produces (exported from `timeline-logic.js`):
  - `count(d, name) -> string` — `"N"`, or `"at least N"` when `d.truncated` includes `name`
  - `pct(x) -> number` — 0..100 integer; non-finite input → 0
  - `conf(x) -> string` — `x.toFixed(2)`; non-finite → `"—"`
  - `claimStatusClass(status) -> "malicious" | "slate" | "benign"`
  - `standingClass(standing) -> "slate" | "fresh"`
  - `digestBanner(d) -> { kind: "ok" | "warn", text: string }`

- [ ] **Step 1: Write the failing Node tests** — `tests/js/timeline_logic.test.mjs`:

```js
// The timeline page's pure logic (S16, S17), run under Node's built-in test
// runner: no dependencies, no browser. It imports the module the page itself
// imports. tests/test_timeline_logic.py runs this file inside the pytest gate.
//
//   node --test tests/js/timeline_logic.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  count, pct, conf, claimStatusClass, standingClass, digestBanner,
} from "../../auspex/static/js/timeline-logic.js";

const rows = (n) => Array.from({ length: n }, () => ({}));
const digest = (over = {}) => ({
  quiet: false, trustworthy: true, complete: true, limit: 50,
  checkers: [{ name: "retrohunt", degraded: false }], truncated: [],
  reopened: [], flipped: [], contradicted: [], decayed: [], ...over,
});

test("a list the server did not cut is stated as its length", () => {
  assert.equal(count(digest({ decayed: rows(3) }), "decayed"), "3");
});

test("a list the server cut is stated as a floor, never a total (S17)", () => {
  assert.equal(count(digest({ decayed: rows(50), truncated: ["decayed"] }), "decayed"), "at least 50");
});

test("a cut on one list does not make another list a floor", () => {
  const d = digest({ decayed: rows(50), reopened: rows(2), truncated: ["decayed"] });
  assert.equal(count(d, "reopened"), "2");
});

test("pct turns a confidence into a bar width, clamped to 0..100", () => {
  assert.equal(pct(0), 0);
  assert.equal(pct(1), 100);
  assert.equal(pct(0.456), 46);
  assert.equal(pct(-0.2), 0);
  assert.equal(pct(1.7), 100);
});

test("a missing confidence is an empty bar, not NaN", () => {
  for (const x of [null, undefined, NaN, "0.5"]) assert.equal(pct(x), 0, String(x));
});

test("conf shows a confidence to two places", () => {
  assert.equal(conf(0.5), "0.50");
  assert.equal(conf(0), "0.00");
});

test("a missing confidence reads as a dash instead of throwing", () => {
  for (const x of [null, undefined, NaN]) assert.equal(conf(x), "—", String(x));
});

test("a claim's status picks its colour", () => {
  assert.equal(claimStatusClass("satisfied"), "malicious");
  assert.equal(claimStatusClass("superseded"), "slate");
  assert.equal(claimStatusClass("registered"), "benign");
});

test("a lapsed standing is slate, anything else fresh", () => {
  assert.equal(standingClass("lapsed"), "slate");
  assert.equal(standingClass("standing"), "fresh");
});

test("a quiet week is reassuring only when everything was watching", () => {
  assert.deepEqual(digestBanner(digest({ quiet: true, trustworthy: true })), {
    kind: "ok",
    text: "Nothing re-scored your past this week — and everything that would have noticed was running.",
  });
});

test("a quiet week with a degraded checker is not evidence", () => {
  const d = digest({ quiet: true, trustworthy: false, checkers: [{ name: "retrohunt", degraded: true }] });
  assert.deepEqual(digestBanner(d), {
    kind: "warn",
    text: "Nothing to report, but this silence is not evidence: a checker is degraded.",
  });
});

test("a quiet week with nothing watching says so", () => {
  const d = digest({ quiet: true, trustworthy: false, checkers: [] });
  assert.deepEqual(digestBanner(d), {
    kind: "warn",
    text: "Nothing to report, but this silence is not evidence: nothing was watching.",
  });
});

test("an active week counts each list", () => {
  const d = digest({ reopened: rows(1), flipped: rows(2), contradicted: rows(3), decayed: rows(4) });
  assert.deepEqual(digestBanner(d), {
    kind: "warn",
    text: "Your past got re-scored. 1 re-opened · 2 changed label · 3 claims contradicted · 4 went stale.",
  });
});

test("an active week the server cut states floors and says how to see the rest", () => {
  const d = digest({ complete: false, decayed: rows(50), truncated: ["decayed"] });
  assert.deepEqual(digestBanner(d), {
    kind: "warn",
    text: "Your past got re-scored. 0 re-opened · 0 changed label · 0 claims contradicted · at least 50 went stale."
      + " Showing the first 50 of each — widen the page to see the rest.",
  });
});
```

- [ ] **Step 2: Write the pytest runner** — `tests/test_timeline_logic.py`:

```python
"""The timeline page's pure logic (S16, S17), inside the gate.

Its behavioural tests are JavaScript, under Node's built-in test runner:
tests/js/timeline_logic.test.mjs. This runs that file, so `./ci.sh` (D-028)
covers it, exactly as tests/test_page_logic.py does for the chat page.

Node missing is a FAILURE, not a skip.
"""

import shutil
import subprocess
from pathlib import Path

NODE_TESTS = Path(__file__).parent / "js" / "timeline_logic.test.mjs"


def test_the_timeline_pages_logic_passes_its_node_tests():
    node = shutil.which("node")
    assert node, "Node is required to run the page's logic tests (tests/js/)"
    # The reporter is named so the floor below finds "ℹ pass" on any Node (B-007).
    run = subprocess.run(  # noqa: S603 — argv is node, flags and our own test file
        [node, "--test", "--test-reporter=spec", str(NODE_TESTS)],
        capture_output=True, text=True, timeout=60,
    )
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
    # A file that defined no tests also exits 0. The floor is the count this
    # file holds today; it only ever goes up.
    passed = [line for line in run.stdout.splitlines() if line.startswith("ℹ pass ")]
    assert passed and int(passed[0].split()[-1]) >= 14, run.stdout[-2000:]
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_timeline_logic.py -q`
Expected: FAIL — Node reports `Cannot find module …/timeline-logic.js`.

- [ ] **Step 4: Write the module** — `auspex/static/js/timeline-logic.js`:

```js
// The timeline page's pure logic (S16, S17): no DOM, imported by the page
// (js/timeline.js) and by tests/js/timeline_logic.test.mjs. The page holds no
// decay arithmetic: a band is the server's `staleness`, rendered as given.

// A count the page is allowed to state. `truncated` names the lists the server
// cut at `limit`, and for those the length of what arrived is a floor, not a
// total — "50 went stale" when 32,930 did is a wrong answer, not a short one.
export function count(d, name) {
  const n = d[name].length;
  return d.truncated.includes(name) ? `at least ${n}` : `${n}`;
}

// A confidence as a bar width. A missing one is an empty bar, not "NaN%".
export function pct(x) {
  return Number.isFinite(x) ? Math.max(0, Math.min(100, Math.round(x * 100))) : 0;
}

// A confidence as written on the card. A missing one is a dash, not a throw
// that would take the whole timeline down with it.
export function conf(x) {
  return Number.isFinite(x) ? x.toFixed(2) : "—";
}

export function claimStatusClass(status) {
  if (status === "satisfied") return "malicious";
  if (status === "superseded") return "slate";
  return "benign";
}

export function standingClass(standing) {
  return standing === "lapsed" ? "slate" : "fresh";
}

// The reassuring version is only rendered when it can be believed.
export function digestBanner(d) {
  if (d.quiet) {
    if (d.trustworthy) {
      return {
        kind: "ok",
        text: "Nothing re-scored your past this week — and everything that would have noticed was running.",
      };
    }
    const why = d.checkers.length ? "a checker is degraded" : "nothing was watching";
    return { kind: "warn", text: `Nothing to report, but this silence is not evidence: ${why}.` };
  }
  const counts = `${count(d, "reopened")} re-opened · ${count(d, "flipped")} changed label · `
    + `${count(d, "contradicted")} claims contradicted · ${count(d, "decayed")} went stale.`;
  const cut = d.complete ? "" : ` Showing the first ${d.limit} of each — widen the page to see the rest.`;
  return { kind: "warn", text: `Your past got re-scored. ${counts}${cut}` };
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_timeline_logic.py -q && node --test --test-reporter=spec tests/js/timeline_logic.test.mjs | grep "ℹ pass"`
Expected: `1 passed`; `ℹ pass 14`.

- [ ] **Step 6: Mutants.** One at a time, each must make Step 5 fail, then revert:
  - `count`: return `${n}` unconditionally.
  - `pct`: drop the `Number.isFinite` guard.
  - `digestBanner`: swap the two `why` strings.

- [ ] **Step 7: Update the README count.** Run `.venv/bin/pytest --collect-only -q | tail -1` and replace the single count in `README.md` (both places, e.g. `1385 tests` → the collected number) with `sed -i 's/1385 tests/<N> tests/g' README.md`.

- [ ] **Step 8: Commit**

```bash
git add auspex/static/js/timeline-logic.js tests/js/timeline_logic.test.mjs tests/test_timeline_logic.py README.md
git commit -m "feat(timeline): the page's pure logic in a tested module (F3, TD-051)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The page split — markup, stylesheet and a DOM module with no HTML strings

**Files:**
- Create: `auspex/static/css/timeline.css`
- Create: `auspex/static/js/timeline.js`
- Modify: `auspex/static/timeline.html` (whole file → markup only)
- Modify: `auspex/routes/ui.py:40-46` (`_ASSETS`)
- Modify: `tests/test_ui.py` (timeline tests read the page as served; new pins)
- Modify: `README.md` (test count)

**Interfaces:**
- Consumes: `count`, `pct`, `conf`, `claimStatusClass`, `standingClass`, `digestBanner` from Task 1 (`count` is used by `digestBanner` only; `timeline.js` imports the other five).
- Produces: served paths `/css/timeline.css`, `/js/timeline-logic.js`, `/js/timeline.js`; test helper `_timeline_page(client) -> str`.

- [ ] **Step 1: Write the failing tests** in `tests/test_ui.py`.

Add near `_ASSET_PATHS` at the top:

```python
_TIMELINE_ASSET_PATHS = ("/css/timeline.css", "/js/timeline-logic.js", "/js/timeline.js")


def _timeline_page(client) -> str:
    """The timeline page as a browser gets it: the HTML and the files it loads
    (TD-051). Reading this also proves the files are served."""
    return "\n".join(
        [client.get("/timeline").text] + [client.get(p).text for p in _TIMELINE_ASSET_PATHS]
    )
```

In the four existing timeline tests (`test_timeline_page_served_on_brand`, `…holds_no_decay_arithmetic_of_its_own`, `…never_states_a_count_it_cannot_back_up`, `…never_names_the_engine`), replace each `body = resp.text` / `client.get("/timeline").text` with `_timeline_page(client)` (keep `.lower()` in the engine test). Their assertions stay as they are.

Extend the served-files test's parametrize list with:

```python
    ("/css/timeline.css", "text/css"),
    ("/js/timeline-logic.js", "text/javascript"),
    ("/js/timeline.js", "text/javascript"),
```

Add after `test_the_page_holds_no_inline_script_or_style`:

```python
def test_the_timeline_page_holds_no_inline_script_or_style(client):
    """TD-051: what D-057's policy depends on, for /timeline. An inline script,
    a style block, an `on…=` handler or a `style=` attribute would be blocked in
    the browser while every other test here stayed green."""
    html = client.get("/timeline").text
    assert "<style" not in html
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) is None
    assert re.search(r"\son[a-z]+\s*=", html) is None
    assert re.search(r"\sstyle\s*=", html) is None
    assert '<link rel="stylesheet" href="/css/timeline.css" />' in html
    assert '<script type="module" src="/js/timeline.js"></script>' in html


def test_the_timeline_page_builds_feed_text_as_text(client):
    """TD-051: sources, claims and checker names are feed-derived. The page
    builds elements and text nodes, never HTML strings, so none of it can
    become markup, and widths go through the CSSOM, which the policy allows."""
    js = client.get("/js/timeline.js").text + client.get("/js/timeline-logic.js").text
    assert "innerHTML" not in js and "outerHTML" not in js
    assert "insertAdjacentHTML" not in js and "document.write" not in js
    assert "setAttribute(\"style\"" not in js
    assert "addEventListener(\"click\"" in js
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_ui.py -q -k "timeline or served_fresh"`
Expected: FAIL — `/css/timeline.css` etc. return 404; the inline-script test finds `<style`.

- [ ] **Step 3: Put the files on the allow-list** — `auspex/routes/ui.py`, extend `_ASSETS` and its comment:

```python
# TD-045, TD-051: each page's own files, by name. An allow-list, so no name a
# request can make reaches anything else on disk.
_ASSETS = {
    "css/chat.css": ("text/css", _STATIC / "css" / "chat.css"),
    "js/page-logic.js": ("text/javascript", _STATIC / "js" / "page-logic.js"),
    "js/chat.js": ("text/javascript", _STATIC / "js" / "chat.js"),
    "css/timeline.css": ("text/css", _STATIC / "css" / "timeline.css"),
    "js/timeline-logic.js": ("text/javascript", _STATIC / "js" / "timeline-logic.js"),
    "js/timeline.js": ("text/javascript", _STATIC / "js" / "timeline.js"),
}
```

- [ ] **Step 4: Create `auspex/static/css/timeline.css`** — lines 11–84 of today's `timeline.html` (the body of its `<style>` block) moved verbatim, then append:

```css
/* What the inline style="…" attributes gave, as classes (TD-051: the policy
   blocks inline styles). Bar widths are set through the CSSOM instead. */
.mt6 { margin-top: 6px; }
.mt8 { margin-top: 8px; }
.mb8 { margin-bottom: 8px; }
.mono.big { font-size: 16px; }
```

- [ ] **Step 5: Replace `auspex/static/timeline.html`** with markup only:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Auspex — verdict timeline</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="/css/timeline.css" />
  <script type="module" src="/js/timeline.js"></script>
</head>
<body>
  <header>
    <span class="mark">auspex<span class="dot">.</span></span>
    <span class="tag">the flock sees first</span>
    <span class="spacer"></span>
    <input id="email" value="burhan@auspexdev.com" />
    <button id="login">Sign in</button>
    <input id="obs" class="mono" placeholder="obs id, e.g. cve-1a2b3c4d" />
    <button id="go" class="ghost">Open timeline</button>
    <button id="back" class="ghost">Digest</button>
    <span id="status"></span>
  </header>
  <main id="main"></main>
</body>
</html>
```

- [ ] **Step 6: Create `auspex/static/js/timeline.js`:**

```js
// The timeline page's DOM wiring (S16). Its pure logic is ./timeline-logic.js;
// this builds elements from it and talks to the API. Feed text (observable
// values, sources, claims, checker names) is always text, never HTML: the page
// runs under D-057's policy (TD-051).
import { pct, conf, claimStatusClass, standingClass, digestBanner } from "./timeline-logic.js";

const $ = (id) => document.getElementById(id);
let TOKEN = null;
const when = (iso) => new Date(iso).toLocaleString();

// The element factory: props are DOM properties, and a string child is
// appended as a text node. Nothing here parses HTML. An absent child (null,
// undefined, false) is skipped, so a card can hold an optional line in place.
function el(tag, props = {}, children = []) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  e.append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  return e;
}
const span = (className, text = "") => el("span", { className }, [String(text ?? "")]);
const pill = (cls, text) => span(`pill ${cls ?? ""}`, text);
const spacer = () => span("spacer");

// A decay bar: its width through the CSSOM, which the policy allows.
function bar(className, width) {
  const b = el("div", { className });
  b.style.width = `${width}%`;
  return b;
}

// An observable that opens its own timeline. The id travels in the closure,
// never through markup, so no character in it can break out.
function obsLink(o) {
  const a = el("a", { className: "mono", href: "#" }, [o.value]);
  a.addEventListener("click", (e) => { e.preventDefault(); open_(o.obs_id); });
  return a;
}

function setStatus(msg, err) { $("status").textContent = msg; $("status").className = err ? "err" : ""; }

async function api(path) {
  const r = await fetch(path, { headers: { Authorization: `Bearer ${TOKEN}` } });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

async function login() {
  const r = await fetch("/api/auth/dev-login", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: $("email").value }),
  });
  if (!r.ok) return setStatus("sign-in failed", true);
  TOKEN = (await r.json()).access_token;
  setStatus("signed in");
  digest();
}

// A verdict card: the label, both confidences, and the gap between them.
function verdictCard(v, inTrail) {
  const band = v.staleness;
  return el("div", { className: `card${inTrail && v.current ? " current" : ""}` }, [
    el("div", { className: "row" }, [
      pill(v.label, v.label), pill(band, band),
      span("small muted", v.current ? "current" : "superseded"),
      spacer(), span("small muted", when(v.created_at)),
    ]),
    el("div", { className: "decay" }, [
      el("div", { className: "track" }, [
        bar("written", pct(v.confidence_at_write)),
        bar(`now ${band}-f`, pct(v.confidence_now)),
      ]),
      el("div", { className: "legend" }, [
        el("span", {}, ["asserted ", span("mono", conf(v.confidence_at_write))]),
        el("span", {}, ["still stands ", span("mono", conf(v.confidence_now))]),
        span("", `${v.half_lives_elapsed} half-lives (${v.half_life_days}d)`),
      ]),
    ]),
    el("div", { className: "small muted mono mt8" }, [v.source]),
  ]);
}

function claimCard(c) {
  return el("div", { className: "card" }, [
    el("div", { className: "row" }, [
      pill(claimStatusClass(c.status), c.status),
      c.standing ? pill(standingClass(c.standing), c.standing) : null,
      span("mono small muted", c.kind),
      spacer(),
      span("small muted", c.satisfied_at ? "contradicted " + when(c.satisfied_at) : "registered " + when(c.created_at)),
    ]),
    el("div", { className: "mt6" }, [c.claim]),
    c.satisfied_by ? el("div", { className: "small muted mono mt6" }, [`by ${c.satisfied_by}`]) : null,
  ]);
}

function section(title, items, render, cut) {
  const out = [el("h2", {}, [title])];
  if (items.length) out.push(...items.map(render));
  else out.push(el("div", { className: "card empty" }, ["nothing"]));
  // `cut` is the server saying this list had more rows than the page asked for
  // (S17 Step 0). Rendering the page size as though it were the total is the
  // same dishonesty as rendering an unexplained empty list, which the banner
  // above already refuses.
  if (cut) out.push(el("div", { className: "card empty" }, [`showing the first ${items.length} — there are more`]));
  return out;
}

async function digest() {
  try {
    const d = await api("/api/timeline/digest?days=7");
    const banner = digestBanner(d);
    const checkers = d.checkers.length
      ? d.checkers.map((c) => pill(c.degraded ? "malicious" : "benign", `${c.name}${c.degraded ? " degraded" : ""}`))
      : [pill("slate", "no checkers running")];
    $("main").replaceChildren(
      el("div", { className: `banner ${banner.kind}` }, [banner.text]),
      el("div", { className: "row small muted mb8" }, ["checking: ", ...checkers]),
      ...section("New intel re-opened", d.reopened, (m) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [
          obsLink(m.observable),
          pill(m.verdict_label_at_match || "unknown", m.verdict_label_at_match || "no verdict"),
          spacer(), span("small muted", when(m.created_at)),
        ]),
        m.falsifies ? el("div", { className: "small mt6" }, [
          span("muted", "contradicts a claim this verdict made:"), ` ${m.falsifies}`,
        ]) : null,
      ]), d.truncated.includes("reopened")),
      ...section("Labels that actually changed", d.flipped, (f) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [
          obsLink(f.observable), pill(f.from_label, f.from_label), "→", pill(f.to_label, f.to_label),
          spacer(), span("small muted mono", f.trigger),
        ]),
      ]), d.truncated.includes("flipped")),
      ...section("Claims that stopped being true", d.contradicted, (c) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [obsLink(c.observable), span("mono small muted", c.kind)]),
        el("div", { className: "mt6" }, [c.claim]),
      ]), d.truncated.includes("contradicted")),
      ...section("Went stale on their own", d.decayed, (x) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [
          obsLink(x.observable), pill(x.label, x.label), pill(x.was, x.was), "→", pill(x.now, x.now),
          spacer(), span("small muted", `${conf(x.confidence_at_write)} → ${conf(x.confidence_now)}`),
        ]),
      ]), d.truncated.includes("decayed")),
    );
    setStatus(`digest · ${d.quiet ? "quiet" : "activity"}`);
  } catch (e) { setStatus("digest failed — sign in first", true); }
}

async function open_(obsId) {
  $("obs").value = obsId;
  try {
    const t = await api(`/api/timeline/${encodeURIComponent(obsId)}`);
    $("main").replaceChildren(
      el("div", { className: "row" }, [span("mono big", t.observable.value), pill("slate", t.observable.type)]),
      el("div", { className: "small muted mt6" }, [t.note]),
      el("h2", {}, ["Now"]),
      t.current ? verdictCard(t.current, false) : el("div", { className: "card empty" }, ["never enriched"]),
      ...section("What would prove it wrong", t.claims, claimCard),
      ...section("What re-opened it", t.reopened_by, (m) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [
          span("mono", m.trigger_doc), pill("slate", m.change_kind),
          spacer(), span("small muted", when(m.created_at)),
        ]),
        el("div", { className: "small muted mt6" }, [m.note]),
        m.falsifies ? el("div", { className: "small mt6" }, [`falsifies: ${m.falsifies}`]) : null,
      ])),
      ...section("When the label changed", t.flips, (f) => el("div", { className: "card" }, [
        el("div", { className: "row" }, [
          pill(f.from_label, f.from_label), "→", pill(f.to_label, f.to_label),
          span("mono small muted", f.trigger), spacer(), span("small muted", when(f.created_at)),
        ]),
      ])),
      el("h2", {}, ["The whole trail"]),
      el("div", { className: "trail" }, t.trail.map((v) => verdictCard(v, true))),
    );
    setStatus(`timeline · ${t.trail.length} verdicts`);
  } catch (e) { setStatus("no timeline for that id", true); }
}

$("login").addEventListener("click", login);
$("go").addEventListener("click", () => open_($("obs").value.trim()));
$("back").addEventListener("click", digest);
login();
```

Check the S16 pins still hold on the served page: `v.staleness` present; `count(d, "reopened")`, `at least`, `d.truncated`, `d.complete` present (in `timeline-logic.js`); no `Math.pow`, no `**`, no `half_life` except `half_life_days` (`half_lives_elapsed` does not contain `half_life`).

- [ ] **Step 7: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_ui.py tests/test_timeline_logic.py -q`
Expected: all pass.

- [ ] **Step 8: Mutants.** One at a time, each must fail Step 7, then revert:
  - put `style="margin-top:6px"` back on any element in `timeline.html`;
  - in `timeline.js`, replace one `[c.claim]` child with `$("main").innerHTML = c.claim`;
  - remove `"js/timeline.js"` from `_ASSETS`.

- [ ] **Step 9: Update the README count** as in Task 1 Step 7 (collected number, both places).

- [ ] **Step 10: Commit**

```bash
git add auspex/static/timeline.html auspex/static/css/timeline.css auspex/static/js/timeline.js auspex/routes/ui.py tests/test_ui.py README.md
git commit -m "feat(timeline): markup, a stylesheet and a DOM module with no HTML strings (TD-051)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `/timeline` carries D-057's policy

**Files:**
- Modify: `auspex/routes/ui.py:25-27` (comment), `:65-70` (`timeline()`)
- Modify: `tests/test_ui.py` (replace `test_the_timeline_page_has_no_csp_yet`)

**Interfaces:**
- Consumes: `_CHAT_CSP` (unchanged), the split page from Task 2.

- [ ] **Step 1: Replace the "no CSP yet" test** in `tests/test_ui.py` with:

```python
@pytest.mark.parametrize("path", ["/", "/timeline"])
def test_each_page_is_served_with_the_same_strict_policy(client, path):
    """D-057 on both pages (TD-051 closed). Both hold the sign-in token, so
    both run only their own scripts and talk only to their own origin."""
    csp = client.get(path).headers.get("content-security-policy", "")
    assert csp == client.get("/").headers["content-security-policy"]
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";") if d.strip())
    assert directives["script-src"] == "'self'"
    assert directives["connect-src"] == "'self'"
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_ui.py -q -k same_strict_policy`
Expected: `[/timeline]` FAILS (empty header); `[/]` passes.

- [ ] **Step 3: Send the policy** — in `auspex/routes/ui.py`:

Comment above `_CHAT_CSP` becomes:

```python
# D-057: each page runs only its own scripts and talks only to its own origin;
# TD-045 (chat) and TD-051 (timeline) moved every script and style rule out of
# the pages to make that possible without 'unsafe-inline'.
```

`timeline()` returns:

```python
    return FileResponse(
        _TIMELINE, media_type="text/html",
        headers={**_REVALIDATE, "Content-Security-Policy": _CHAT_CSP},
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_ui.py -q`
Expected: all pass.

- [ ] **Step 5: Mutant:** remove the header from `timeline()` → Step 4 must fail; revert.

- [ ] **Step 6: Update the README count** (the parametrized test adds one net test) as in Task 1 Step 7.

- [ ] **Step 7: Commit**

```bash
git add auspex/routes/ui.py tests/test_ui.py README.md
git commit -m "feat(ui): /timeline carries D-057's policy (closes TD-051)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Full gate, local deploy, live check, records

**Files:**
- Create: `docs/probes/2026-10-14-f3-timeline-csp.md`
- Modify: `TECHNICAL_DEBT.md` (TD-051 closed)

- [ ] **Step 1: Full gate.** `./ci.sh > /tmp/claude-1000/ci.log 2>&1; echo "exit $?"` (never piped into `tail`). Expected `exit 0`, `CI green.` It also rebuilds and restarts the local app container with the change.

- [ ] **Step 2: Live check in a real browser** against `http://localhost:8000/timeline` (headless Chromium via Playwright, or by hand):
  - console shows zero `Content-Security-Policy` violations;
  - the digest renders with its banner, checker pills and sections;
  - an observable link opens its timeline; the input + Open timeline does too; Digest goes back; Sign in works;
  - decay bars show their widths;
  - nothing in the rendered page became markup: `document.querySelectorAll("main img, main script, main iframe").length` is `0` on the digest and on an opened timeline. (No feed row is created to inject markup — probe residue is expensive; the no-`innerHTML` pin from Task 2 is the guarantee, this is the live confirmation.)

- [ ] **Step 3: Record it** in `docs/probes/2026-10-14-f3-timeline-csp.md`: what was checked, the console output, screenshots' paths (copied from `.playwright-mcp/` if used).

- [ ] **Step 4: Close TD-051** in `TECHNICAL_DEBT.md`: mark it **Closed (F3)**, naming the three files, the policy test, and the probe record.

- [ ] **Step 5: Commit** (local only — Hunaiza checks the running container, then asks for the PR):

```bash
git add docs/probes/2026-10-14-f3-timeline-csp.md TECHNICAL_DEBT.md
git commit -m "docs(td): TD-051 closed — /timeline under D-057, checked live (F3)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
