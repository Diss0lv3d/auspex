"""UI shell smoke test (S3 step 5): served, on-brand, engine never named."""

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
