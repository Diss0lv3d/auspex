"""UI shell smoke test (S3 step 5): served, on-brand, engine never named."""

import re

import pytest
from _fakes import FORBIDDEN_ENGINE_NAMES

_ASSET_PATHS = ("/css/chat.css", "/js/page-logic.js", "/js/chat.js")
_TIMELINE_ASSET_PATHS = ("/css/timeline.css", "/js/timeline-logic.js", "/js/timeline.js")


def _page(client) -> str:
    """The chat page as a browser gets it: the HTML and the files it loads
    (TD-045). The assertions below read this, so they also prove the files
    are served."""
    return "\n".join([client.get("/").text] + [client.get(p).text for p in _ASSET_PATHS])


def _timeline_page(client) -> str:
    """The timeline page as a browser gets it: the HTML and the files it loads
    (TD-051). Reading this also proves the files are served."""
    return "\n".join(
        [client.get("/timeline").text] + [client.get(p).text for p in _TIMELINE_ASSET_PATHS]
    )


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


def test_the_sign_in_is_kept_for_the_tab_only(client):
    """D-056: the token survives a reload in sessionStorage (never
    localStorage), is checked on load, and has a way out. Storage that throws
    must leave the page working, so the only storage calls are the three
    guarded helpers."""
    body = _page(client)
    assert "localStorage" not in body
    assert body.count("sessionStorage.") == 3
    for call in ("sessionStorage.getItem(TOKEN_KEY)", "sessionStorage.setItem(TOKEN_KEY, t)",
                 "sessionStorage.removeItem(TOKEN_KEY)"):
        assert f"try {{ {call}" in body or f"try {{ return {call}" in body, call
    assert "/api/auth/whoami" in body
    assert 'id="signout"' in body


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
    """F2 narrow pass: at 390 px the header took 132 px in two rows, and "Sign
    in", "Sign out", "Approvals · 1" and the status broke over two or three
    lines. Labels never wrap; below 600 px the tagline goes and the bars are
    tighter."""
    body = _page(client)
    assert "header button, #status { white-space: nowrap; }" in body
    narrow = body.split("@media (max-width: 599px) {", 1)[1].split("\n}", 1)[0]
    assert ".tag { display: none; }" in narrow
    assert "header, footer { padding: 10px 12px; }" in narrow


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
    ("/css/timeline.css", "text/css"),
    ("/js/timeline-logic.js", "text/javascript"),
    ("/js/timeline.js", "text/javascript"),
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
