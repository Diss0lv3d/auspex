"""UI shell smoke test (S3 step 5): served, on-brand, engine never named."""

import re

import pytest
from _fakes import FORBIDDEN_ENGINE_NAMES

_ASSET_PATHS = (
    "/css/base.css", "/css/chat.css", "/js/dom.js", "/js/api.js", "/js/shell-logic.js",
    "/js/shell.js", "/js/page-logic.js", "/js/chat.js",
)
_TIMELINE_ASSET_PATHS = (
    "/css/base.css", "/css/timeline.css", "/js/dom.js", "/js/api.js", "/js/shell-logic.js",
    "/js/shell.js", "/js/timeline-logic.js", "/js/timeline.js",
)


def _served(client, path: str) -> str:
    """One file as the browser gets it. A page whose file does not load is
    broken however its text reads (F3 review, STATE.md follow-up #25)."""
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code)
    return resp.text


def _page(client) -> str:
    """The chat page as a browser gets it: the HTML and the files it loads
    (TD-045). The assertions below read this, so they also prove the files
    are served."""
    return "\n".join(_served(client, p) for p in ("/", *_ASSET_PATHS))


def _timeline_page(client) -> str:
    """The timeline page as a browser gets it: the HTML and the files it loads
    (TD-051, F4). Reading this also proves the files are served."""
    return "\n".join(_served(client, p) for p in ("/timeline", *_TIMELINE_ASSET_PATHS))


def test_index_served_dark_first_and_on_brand(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = _page(client)  # the palette lives in the stylesheet (TD-045)
    assert "Auspex" in body
    assert "the flock sees first" in body
    # dark-first palette present (Night bg + Aurora accent, CLAUDE.md D-002)
    assert "#0A0D12" in body
    assert "#4FF2C0" in body


def test_index_has_hidden_switcher_scaffolding(client):
    """The model switcher ships hidden with NO options in static HTML (populated
    only from /api/models when the server offers >1 endpoint)."""
    body = _page(client)
    assert 'id="endpoint"' in body and "hidden" in body
    assert "/api/models" in body  # populated after sign-in
    assert "<option" not in body  # no engine names baked into the static page


def test_index_never_names_the_engine(client):
    body = _page(client).lower()
    for name in FORBIDDEN_ENGINE_NAMES:
        assert name not in body, f"engine/provider name leaked into UI: {name!r}"


def test_timeline_page_served_on_brand(client):
    """S16 — the verdict timeline. Same dark-first palette, and Slate is the
    stale colour it is everywhere else (CLAUDE.md brand)."""
    resp = client.get("/timeline")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = _timeline_page(client)
    assert "#0A0D12" in body and "#4FF2C0" in body
    assert "#8B93A7" in body  # Slate — stale / lapsed
    assert "/api/timeline/digest" in body


def test_timeline_page_holds_no_decay_arithmetic_of_its_own(client):
    """The band vocabulary lives in one place (auspex/timeline/staleness.py).
    A page that recomputed staleness in JavaScript would be a second opinion
    about aging, and the two would drift the first time an edge moved."""
    body = _timeline_page(client)
    assert "half_life" not in body.replace("half_life_days", "")  # only the label
    assert "Math.pow" not in body and "**" not in body
    # It renders the server's answer, never its own.
    assert "v.staleness" in body


def test_timeline_page_never_states_a_count_it_cannot_back_up(client):
    """S17 Step 0. The digest banner used to render the arrival count as the
    total, so a page cut at 50 announced "50 went stale" when 32,930 had. Counts
    for a truncated list are stated as a floor, and each cut section says so."""
    body = _timeline_page(client)
    # the banner reads its counts through the helper that knows about the cut...
    assert 'count(d, "reopened")' in body
    assert "at least" in body
    # ...and no section renders a raw arrival length as a total any more.
    assert "${d.decayed.length}" not in body
    assert "${d.reopened.length}" not in body
    # the server's own flags are what it trusts, not a guess from array sizes
    assert "d.truncated" in body and "d.complete" in body
    # ...and a section the server cut says so under its rows (F3 review).
    assert "if (cut) out.push(" in body and "there are more" in body


def test_timeline_page_never_names_the_engine(client):
    body = _timeline_page(client).lower()
    for name in FORBIDDEN_ENGINE_NAMES:
        assert name not in body, f"engine/provider name leaked into UI: {name!r}"


def test_index_shows_each_tool_step_in_the_thinking_pane(client):
    """The agent path streams `tool` frames (D-031 decision 1: tool steps are
    narrated before the answer). A page that ignored them would show an answer
    built from lookups the analyst never saw happen. The step's STATUS is what
    is shown, because it is what actually ran (D-014)."""
    body = _page(client)
    assert '"tool" in ev' in body
    assert "ev.tool.status" in body
    # The server's line verbatim: re-rendering the arguments here ordered them
    # differently from what the output rail scanned (review of 1b86070).
    assert "ev.tool.call" in body and "ev.tool.arguments" not in body
    # The model's arguments are rendered as text, never parsed as markup.
    assert "innerHTML" not in body.split('"tool" in ev', 1)[1].split("else if", 1)[0]


def test_index_reasoning_appends_without_erasing_the_steps(client):
    """`textContent +=` on the Thinking pane rewrites it as one text node, which
    deletes every tool-step line already in it — the next reasoning delta after a
    tool step would erase the step."""
    body = _page(client)
    assert "ensureThink(wrap).textContent +=" not in body



def test_index_shows_a_proposal_outside_the_folded_thinking_pane(client):
    """D-045: the chat agent may propose an action. The step line sits in the
    Thinking pane, which folds when the answer starts — a decision waiting on
    the analyst must not fold away with it. Rendered as text, never markup."""
    body = _page(client)
    handler = body.split('"tool" in ev', 1)[1].split("else if", 1)[0]
    assert "ev.tool.proposal" in handler
    assert "wrap.appendChild(p)" in handler
    assert "innerHTML" not in handler


@pytest.mark.parametrize("path", ["/", "/timeline"])
def test_a_page_is_revalidated_on_every_load_so_a_deploy_reaches_the_browser(client, path):
    """B-003. Served with only `last-modified`, a page is cached on heuristic
    freshness: after a deploy, an open browser ran the old page (transferSize 0,
    none of the new code) — observed in F1. `no-cache` makes every load ask
    the server first."""
    resp = client.get(path)
    assert resp.status_code == 200
    assert "no-cache" in resp.headers.get("cache-control", "")


def test_index_has_the_approvals_panel_and_builds_it_without_markup(client):
    """The approvals panel (docs/superpowers/specs/2026-10-12-approvals-panel-
    design.md). A card carries the server's strings and the action's arguments,
    which came from a model's tool call, so everything in it is built from
    elements and text — never `innerHTML` past the fixed templates."""
    body = _page(client)
    assert 'id="approvals"' in body and 'id="approvals-panel"' in body
    panel_code = body.split("// <approvals-dom>", 1)[1].split("// </approvals-dom>", 1)[0]
    assert "doorsFor(" in panel_code and "/api/proposals" in panel_code
    assert "innerHTML" not in panel_code


def test_a_proposal_in_the_chat_opens_its_card_in_the_panel(client):
    body = _page(client)
    handler = body.split('"tool" in ev', 1)[1].split("else if", 1)[0]
    assert "openApprovals(ev.tool.proposal.id)" in handler


def test_index_lists_and_reopens_chats(client):
    """F2: the sidebar lists your chats and reopens one from its stored turns;
    the open chat's id lives in the hash; a reopened chat says what is not
    kept rather than showing an empty Thinking pane."""
    body = _page(client)
    assert 'id="chats"' in body and 'id="new-chat"' in body and 'id="chats-toggle"' in body
    assert '"/api/chat/sessions"' in body and '"/turns"' in body
    assert '"#chat="' in body
    assert "Reopened · answers and spend only; reasoning and tool steps aren't kept." in body
    assert "That chat is not available to you." in body
    chats_code = body.split("// <chats-dom>", 1)[1].split("// </chats-dom>", 1)[0]
    # floor: the extracted block is the real one
    assert "renderReopenedTurn(" in chats_code and "/turns" in chats_code
    assert "innerHTML" not in chats_code


def test_an_error_is_shown_in_the_servers_own_words(client):
    """S26's UX edge. The usage refusal, the leak stop and an endpoint failure
    each arrive as a full sentence that says what happened; the page used to
    call all three "[endpoint error]", and wrapped the HTTP refusals (the input
    rail's 400, the usage ceiling's 429) in square brackets."""
    body = _page(client)
    assert "[endpoint error]" not in body
    assert '"[" + detail + "]"' not in body
    assert "showError(wrap, ev.error)" in body


def test_the_page_asks_for_dark_scrollbars_and_controls(client):
    """F2 narrow pass: without `color-scheme: dark` the browser drew its light
    default scrollbar on Night (seen on the sidebar and the transcript)."""
    body = _page(client)
    root = body.split(":root {", 1)[1].split("}", 1)[0]
    assert "color-scheme: dark" in root


def test_the_header_keeps_its_labels_whole_on_a_phone(client):
    """F2 narrow pass, then F4's shared header: at 390 px the header took 132 px
    in two rows and broke its labels. Labels never wrap; below 600 px the
    tagline and the "signed in" status go first, and the workspace stays."""
    base = _served(client, "/css/base.css")
    assert "header button, header a, #status, .ws-label { white-space: nowrap; }" in base
    narrow = base.split("@media (max-width: 599px) {", 1)[1].split("\n}", 1)[0]
    assert ".tag { display: none; }" in narrow and "#status.ok { display: none; }" in narrow
    assert "header { padding: 10px 12px; gap: 8px; }" in narrow
    assert "#workspace { max-width: 100%; }" in narrow
    chat = _served(client, "/css/chat.css")
    assert "footer { padding: 10px 12px; }" in chat.split("@media (max-width: 599px) {", 1)[1]


def test_an_overlay_on_a_narrow_screen_has_a_backdrop_that_closes_it(client):
    """F2 narrow pass: below 900 px the chat list and the approvals panel sat
    over a live, undimmed chat that a tap outside did not close, both could be
    open at once, and at 390 px the 380 px panel left a 10 px sliver. One
    dimmed backdrop now closes either (so does Esc), the page logic keeps one
    open at a time, and the panel is full width on a phone."""
    body = _page(client)
    assert '<div id="scrim" hidden></div>' in body
    assert 'e.key === "Escape"' in body and '"dismiss"' in body
    assert "overlayAfter(" in client.get("/js/chat.js").text
    phone = body.split("@media (max-width: 420px) {", 1)[1].split("}", 1)[0]
    assert ".panel { width: 100vw;" in phone


@pytest.mark.parametrize("path,media", [
    ("/css/chat.css", "text/css"),
    ("/js/page-logic.js", "text/javascript"),
    ("/js/chat.js", "text/javascript"),
    ("/css/base.css", "text/css"), ("/js/shell.js", "text/javascript"),
    ("/css/timeline.css", "text/css"),
    ("/js/timeline-logic.js", "text/javascript"),
    ("/js/timeline.js", "text/javascript"),
    ("/js/shell-logic.js", "text/javascript"),
    ("/js/dom.js", "text/javascript"),
    ("/js/api.js", "text/javascript"),
])
def test_the_pages_files_are_served_fresh_with_their_types(client, path, media):
    """TD-045: the page's CSS and modules are files now. B-003 holds for them
    too: an open browser must not keep running an old module after a deploy."""
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(media)
    assert "no-cache" in resp.headers.get("cache-control", "")


@pytest.mark.parametrize(
    "path", ["/js/ui.py", "/js/..%2Fui.py", "/js/timeline.html", "/css/index.html"]
)
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
    assert '<link rel="stylesheet" href="/css/base.css" />' in html
    assert '<header id="shell">' in html


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
    assert '<link rel="stylesheet" href="/css/base.css" />' in html
    assert '<header id="shell">' in html
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


def test_a_throw_while_a_turn_ends_cannot_leave_the_composer_stuck(client):
    """R7, completed after F2's split review: send()'s finally painted the
    turn's ending before it re-enabled anything, so a throw in that paint left
    Send and the prompt disabled and the working line ticking. Everything that
    gives the analyst the composer back now comes first, and the paint is
    isolated."""
    js = client.get("/js/chat.js").text
    send = js.split("async function send()", 1)[1].split("\n}\n", 1)[0]
    ending = send.split("} finally {", 1)[1]
    first = next(ln.strip() for ln in ending.splitlines()
                 if ln.strip() and not ln.strip().startswith("//"))
    assert first == "busy = false;"
    paint_at = ending.index("paint(pacer.flush())")
    for reset in ("open = false", "clearInterval(ticker)",
                  '$("send").disabled = false', '$("prompt").disabled = false'):
        assert ending.index(reset) < paint_at, reset
    assert "try { paint(pacer.flush()); }" in ending


@pytest.mark.parametrize("path", ["/", "/timeline", "/css/chat.css", "/js/chat.js"])
def test_a_file_the_browser_already_holds_is_answered_304(client, path):
    """TD-047: `no-cache` makes every load ask (B-003), and FileResponse used
    to answer a matching ETag with the whole file again. It now says "you have
    it", with the headers a 200 would carry: a page's policy (D-057) included."""
    first = client.get(path)
    etag = first.headers["etag"]
    again = client.get(path, headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    assert "no-cache" in again.headers["cache-control"]
    if not path.startswith(("/css/", "/js/")):
        csp = first.headers["content-security-policy"]
        assert again.headers["content-security-policy"] == csp


def test_a_stale_or_absent_etag_gets_the_whole_file(client):
    for headers in ({"If-None-Match": '"not-this-one"'}, {}):
        resp = client.get("/js/chat.js", headers=headers)
        assert resp.status_code == 200 and resp.content, headers


def test_a_weak_or_listed_etag_still_matches(client):
    etag = client.get("/").headers["etag"]
    assert client.get("/", headers={"If-None-Match": f'"x", W/{etag}'}).status_code == 304


def test_the_timeline_page_has_no_sign_in_of_its_own(client):
    """F4: one sign-in per tab (D-056) serves every page. The timeline used to
    sign in on load as a pre-filled dev address; the shell owns sign-in now."""
    html = _served(client, "/timeline")
    js = _served(client, "/js/timeline.js")
    assert 'id="email"' not in html and "auspexdev.com" not in html
    assert "/api/auth/dev-login" not in js and "login(" not in js
    assert 'page: "timeline"' in js and "startShell(" in js


_PAGE_MODULES = ["/js/chat.js", "/js/timeline.js"]


@pytest.mark.parametrize("path", _PAGE_MODULES)
def test_no_page_carries_its_own_copy_of_a_shared_module(client, path):
    """F4's exit criterion: nothing duplicated between pages. The element
    factory, the sign-in's storage and the bearer header live once, in
    js/dom.js, js/shell.js and js/api.js, and every page imports them."""
    js = _served(client, path)
    assert "function el(" not in js and "const el =" not in js
    assert "sessionStorage" not in js and "localStorage" not in js
    assert "Authorization" not in js and "Bearer" not in js
    assert "fetch(" not in js
    assert 'from "./dom.js"' in js and 'from "./shell.js"' in js


def test_the_shell_keeps_the_sign_in_for_the_tab_only(client):
    """D-056, now the shell's: the token survives a reload in sessionStorage
    (never localStorage) and is checked on load against /me. Storage that
    throws must leave the page working, so the only storage calls are the three
    guarded helpers."""
    js = _served(client, "/js/shell.js")
    assert "localStorage" not in js
    assert js.count("sessionStorage.") == 3
    for call in ("sessionStorage.getItem(key)", "sessionStorage.setItem(key, value)",
                 "sessionStorage.removeItem(key)"):
        assert f"try {{ {call}" in js or f"try {{ return {call}" in js, call
    assert 'const TOKEN_KEY = "auspex.token";' in js
    assert '"/api/auth/me"' in js and 'id: "signout"' in js


def test_a_switch_reloads_the_page_without_its_hash(client):
    """D-070: a switch stores the new token and reloads, so nothing of the
    previous client survives in page state, and the hash goes, so no chat id of
    theirs reaches the next client. One switch at a time; storage that would
    not keep the token stops the reload rather than signing the tab out."""
    js = _served(client, "/js/shell.js")
    switch = js.split("async function switchTo()", 1)[1].split("\n  }\n", 1)[0]
    assert switch.index("picker.disabled = true") < switch.index('"/api/auth/switch"')
    assert "location.replace(afterSwitchUrl(location))" in switch
    kept = switch.index("stored(TOKEN_KEY) === r.body.access_token")
    assert kept < switch.index("location.replace(afterSwitchUrl(location))")
    assert "STORAGE_BLOCKED" in switch


def test_any_refusal_re_checks_access_through_me_once(client):
    """D-070: /me is the page's only judge of access. Any 403 asks it, one
    check at a time; a /me that refuses ends this tab's sign-in in the
    server's words; a role that changed reloads the page."""
    js = _served(client, "/js/shell.js")
    assert "onForbidden: recheck" in js
    check = js.split("function recheck()", 1)[1].split("\n  }\n", 1)[0]
    assert "if (!checking)" in check and '"/api/auth/me"' in check
    assert "end(r.detail)" in check and "roleChanged(me, r.body)" in check


@pytest.mark.parametrize("path", ["/js/shell.js", "/js/dom.js", "/js/api.js", "/js/shell-logic.js"])
def test_the_shared_modules_build_text_never_markup(client, path):
    js = _served(client, path)
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in js, sink


def test_a_sign_in_in_flight_is_not_started_twice(client):
    """F4 review: a double-click or Enter-then-click must not send two logins,
    run `ready` twice (two polls in chat) or let /me answers cross."""
    js = _served(client, "/js/shell.js")
    body = js.split("async function signIn(email)", 1)[1].split("\n  }\n", 1)[0]
    assert "if (signingIn) return;" in body
    assert body.index("if (signingIn) return;") < body.index('"/api/auth/dev-login"')
    assert "finally {" in body
    assert "signingIn = false" in body.split("finally {", 1)[1]


def test_the_timeline_tools_fit_a_phone(client):
    """F4 browser check at 390 px: the tools row overflowed the header by 25 px."""
    css = _served(client, "/css/timeline.css")
    phone = css.split("@media (max-width: 599px) {", 1)[1].split("\n}", 1)[0]
    tools = [ln for ln in phone.splitlines() if ".page-tools" in ln][0]
    field = [ln for ln in phone.splitlines() if "input.mono" in ln][0]
    assert "min-width: 0" in tools and "width: 0" in field
    assert "\na { color" not in css


def test_a_viewer_gets_no_composer_and_no_doors(client):
    """F4: a viewer may read but not ask the co-analyst (the server refuses even
    a shortcut question, probe item 4) nor decide a proposal. The page hides
    those doors and says why; the server's refusal is the guard."""
    js = _served(client, "/js/chat.js")
    ready = js.split("function ready(ctx)", 1)[1].split("\n}\n", 1)[0]
    assert "mayChange(me.workspace.role)" in ready
    assert '$("composer").hidden = true' in ready and "viewerNote(me)" in ready
    assert "doorsFor(p, me.workspace.role)" in js
    assert "Deciding needs the analyst or admin role." in js
    html = _served(client, "/")
    assert 'id="composer"' in html and 'id="role-note"' in html


def test_a_dropped_turn_says_so_in_a_sentence(client):
    """"[connection lost]" was the last bracketed error copy on the chat page."""
    body = _page(client)
    assert "[connection lost]" not in body
    assert "showError(wrap, CONNECTION_LOST)" in body


def test_the_switcher_waits_for_a_streaming_turn(client):
    """D-070: a switch reloads the page; mid-turn that would cut the turn, so
    the page holds the switcher still while it streams."""
    js = _served(client, "/js/chat.js")
    send = js.split("async function send()", 1)[1].split("\n}\n", 1)[0]
    assert "setBusy(true)" in send.split("try {", 1)[0]
    assert "setBusy(false)" in send.split("} finally {", 1)[1]


def test_a_refused_turn_is_shown_in_the_servers_words(client):
    """F4: the input rail's 400, residency's 403 and the usage ceiling's 429
    arrive as JSON before any stream; the page shows the server's sentence."""
    js = _served(client, "/js/chat.js")
    assert 'api.stream("/api/chat"' in js
    assert "showError(wrap, r.detail)" in js
