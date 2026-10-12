"""UI shell smoke test (S3 step 5): served, on-brand, engine never named."""

import pytest
from _fakes import FORBIDDEN_ENGINE_NAMES


def test_index_served_dark_first_and_on_brand(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "Auspex" in body
    assert "the flock sees first" in body
    # dark-first palette present (Night bg + Aurora accent, CLAUDE.md D-002)
    assert "#0A0D12" in body
    assert "#4FF2C0" in body


def test_index_has_hidden_switcher_scaffolding(client):
    """The model switcher ships hidden with NO options in static HTML (populated
    only from /api/models when the server offers >1 endpoint)."""
    body = client.get("/").text
    assert 'id="endpoint"' in body and "hidden" in body
    assert "/api/models" in body  # populated after sign-in
    assert "<option" not in body  # no engine names baked into the static page


def test_index_never_names_the_engine(client):
    body = client.get("/").text.lower()
    for name in FORBIDDEN_ENGINE_NAMES:
        assert name not in body, f"engine/provider name leaked into UI: {name!r}"


def test_timeline_page_served_on_brand(client):
    """S16 — the verdict timeline. Same dark-first palette, and Slate is the
    stale colour it is everywhere else (CLAUDE.md brand)."""
    resp = client.get("/timeline")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "#0A0D12" in body and "#4FF2C0" in body
    assert "#8B93A7" in body  # Slate — stale / lapsed
    assert "/api/timeline/digest" in body


def test_timeline_page_holds_no_decay_arithmetic_of_its_own(client):
    """The band vocabulary lives in one place (auspex/timeline/staleness.py).
    A page that recomputed staleness in JavaScript would be a second opinion
    about aging, and the two would drift the first time an edge moved."""
    body = client.get("/timeline").text
    assert "half_life" not in body.replace("half_life_days", "")  # only the label
    assert "Math.pow" not in body and "**" not in body
    # It renders the server's answer, never its own.
    assert "v.staleness" in body


def test_timeline_page_never_states_a_count_it_cannot_back_up(client):
    """S17 Step 0. The digest banner used to render the arrival count as the
    total, so a page cut at 50 announced "50 went stale" when 32,930 had. Counts
    for a truncated list are stated as a floor, and each cut section says so."""
    body = client.get("/timeline").text
    # the banner reads its counts through the helper that knows about the cut...
    assert 'count(d, "reopened")' in body
    assert "at least" in body
    # ...and no section renders a raw arrival length as a total any more.
    assert "${d.decayed.length}" not in body
    assert "${d.reopened.length}" not in body
    # the server's own flags are what it trusts, not a guess from array sizes
    assert "d.truncated" in body and "d.complete" in body


def test_timeline_page_never_names_the_engine(client):
    body = client.get("/timeline").text.lower()
    for name in FORBIDDEN_ENGINE_NAMES:
        assert name not in body, f"engine/provider name leaked into UI: {name!r}"


def test_index_shows_each_tool_step_in_the_thinking_pane(client):
    """The agent path streams `tool` frames (D-031 decision 1: tool steps are
    narrated before the answer). A page that ignored them would show an answer
    built from lookups the analyst never saw happen. The step's STATUS is what
    is shown, because it is what actually ran (D-014)."""
    body = client.get("/").text
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
    body = client.get("/").text
    assert "ensureThink(wrap).textContent +=" not in body



def test_index_shows_a_proposal_outside_the_folded_thinking_pane(client):
    """D-045: the chat agent may propose an action. The step line sits in the
    Thinking pane, which folds when the answer starts — a decision waiting on
    the analyst must not fold away with it. Rendered as text, never markup."""
    body = client.get("/").text
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
    body = client.get("/").text
    assert 'id="approvals"' in body and 'id="approvals-panel"' in body
    panel_code = body.split("// <approvals-dom>", 1)[1].split("// </approvals-dom>", 1)[0]
    assert "doorsFor(" in panel_code and "/api/proposals" in panel_code
    assert "innerHTML" not in panel_code


def test_a_proposal_in_the_chat_opens_its_card_in_the_panel(client):
    body = client.get("/").text
    handler = body.split('"tool" in ev', 1)[1].split("else if", 1)[0]
    assert "openApprovals(ev.tool.proposal.id)" in handler


def test_the_sign_in_is_kept_for_the_tab_only(client):
    """D-056: the token survives a reload in sessionStorage (never
    localStorage), is checked on load, and has a way out. Storage that throws
    must leave the page working, so the only storage calls are the three
    guarded helpers."""
    body = client.get("/").text
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
    body = client.get("/").text
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
    body = client.get("/").text
    assert "[endpoint error]" not in body
    assert '"[" + detail + "]"' not in body
    assert "showError(wrap, ev.error)" in body


def test_the_page_asks_for_dark_scrollbars_and_controls(client):
    """F2 narrow pass: without `color-scheme: dark` the browser drew its light
    default scrollbar on Night (seen on the sidebar and the transcript)."""
    body = client.get("/").text
    root = body.split(":root {", 1)[1].split("}", 1)[0]
    assert "color-scheme: dark" in root


def test_the_header_keeps_its_labels_whole_on_a_phone(client):
    """F2 narrow pass: at 390 px the header took 132 px in two rows, and "Sign
    in", "Sign out", "Approvals · 1" and the status broke over two or three
    lines. Labels never wrap; below 600 px the tagline goes and the bars are
    tighter."""
    body = client.get("/").text
    assert "header button, #status { white-space: nowrap; }" in body
    narrow = body.split("@media (max-width: 599px) {", 1)[1].split("\n    }", 1)[0]
    assert ".tag { display: none; }" in narrow
    assert "header, footer { padding: 10px 12px; }" in narrow
