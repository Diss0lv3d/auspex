"""Verdict timeline — S16, against live Postgres (compose dev DB).

Covers the staleness vocabulary (pure arithmetic, hermetic), the TD-020 answer
(an open claim on a decayed verdict), one observable's assembled history, the
"your past got re-scored" digest including verdicts that went stale by
themselves, the checker-health honesty the S16 Step-0 review found missing, and
D-008 tenancy on every read.

Zero LLM anywhere — the whole path is rows we already have plus the D-017 curve.
"""

from datetime import UTC, datetime, timedelta

import pytest

from auspex.checks import DEGRADED_AFTER, FailureCounter
from auspex.classify.observables import Observable, ObservableType, observable_id
from auspex.db import create_pool
from auspex.enrich.store import persist_enrichment
from auspex.enrich.types import (
    EnrichmentOutcome,
    ObservableEnrichment,
    ProviderSignal,
    VerdictLabel,
)
from auspex.enrich.verdict import effective_confidence
from auspex.ingest.events import DocChange
from auspex.retrohunt import RetroHuntSink
from auspex.timeline import (
    Staleness,
    Standing,
    band_for,
    confidence_now,
    decayed_since,
    digest,
    half_lives_elapsed,
    standing_for,
    timeline_for,
)
from auspex.timeline.staleness import (
    AGING_AT_HALF_LIVES,
    LAPSED_AT_HALF_LIVES,
    STALE_AT_HALF_LIVES,
)
from auspex.watchers import FanoutSink, WatcherSink

CVE_A = "CVE-2026-88001"
CVE_B = "CVE-2026-88002"

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def cve_obs(value: str) -> Observable:
    return Observable(
        type=ObservableType.CVE,
        value=value,
        obs_id=observable_id(ObservableType.CVE, value),
        defanged=False,
    )


def cve_item(value: str, label: VerdictLabel = VerdictLabel.SUSPICIOUS, conf: float = 0.6):
    return ObservableEnrichment(
        observable=cve_obs(value),
        signals=(ProviderSignal("TestProvider", label, conf, "seen", evidence={}),),
    )


@pytest.fixture
async def pool(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    yield pool
    await pool.close()


@pytest.fixture
async def workspace_id(pool):
    ws = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        "t-timeline",
    )
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


@pytest.fixture
async def other_workspace_id(pool):
    ws = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        "t-timeline-other",
    )
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


async def _age_verdicts(pool, workspace_id, value: str, *, days: float):
    """Move this observable's whole trail back in time. Decay is a function of
    the clock, so the only honest way to test it against real rows is to make
    the rows genuinely old."""
    await pool.execute(
        """
        UPDATE verdicts SET created_at = created_at - ($3 || ' days')::interval
        WHERE workspace_id = $1 AND observable_id = (
            SELECT id FROM observables
            WHERE workspace_id = $1 AND type = 'cve' AND value = $2
        )
        """,
        workspace_id,
        value,
        str(days),
    )


# -- the vocabulary (hermetic) -------------------------------------------------

BANDS = dict(confidence_at_write=0.8, floor=0.0, half_life_days=10.0)


@pytest.mark.parametrize(
    ("half_lives", "expected"),
    [
        (0.0, Staleness.FRESH),
        (AGING_AT_HALF_LIVES - 0.01, Staleness.FRESH),
        (AGING_AT_HALF_LIVES, Staleness.AGING),
        (STALE_AT_HALF_LIVES - 0.01, Staleness.AGING),
        (STALE_AT_HALF_LIVES, Staleness.STALE),
        (LAPSED_AT_HALF_LIVES - 0.01, Staleness.STALE),
        (LAPSED_AT_HALF_LIVES, Staleness.LAPSED),
        (12.0, Staleness.LAPSED),
    ],
)
def test_bands_are_edges_on_the_decay_curve(half_lives, expected):
    created = NOW - timedelta(days=half_lives * BANDS["half_life_days"])
    assert band_for(**BANDS, created_at=created, now=NOW) is expected


def test_a_band_means_the_same_thing_at_every_half_life():
    """The point of measuring in half-lives: a 14-day IP verdict and a 365-day
    hash verdict are the same amount of stale after the same number of them.
    Days would have needed a per-type table that drifts from HALF_LIFE_DAYS."""
    for half_life in (14.0, 30.0, 365.0):
        created = NOW - timedelta(days=STALE_AT_HALF_LIVES * half_life)
        band = band_for(
            confidence_at_write=0.8, floor=0.0, half_life_days=half_life,
            created_at=created, now=NOW,
        )
        assert band is Staleness.STALE


def test_a_floored_verdict_is_held_not_lapsed():
    """`floor >= confidence_at_write` is the writer saying this does not decay.
    Reporting it as lapsed after a decade would invert what the floor means —
    and the S7 floors (defanged input ⇒ at least suspicious) are exactly that."""
    band = band_for(
        confidence_at_write=0.5, floor=0.5, half_life_days=1.0,
        created_at=NOW - timedelta(days=4000), now=NOW,
    )
    assert band is Staleness.HELD


def test_a_verdict_from_the_future_is_not_fresher_than_new():
    """Clock skew between the writer and the reader must not produce a negative
    age (and, with an odd exponent, a confidence above what was written)."""
    future = NOW + timedelta(days=30)
    assert half_lives_elapsed(created_at=future, now=NOW, half_life_days=10.0) == 0.0
    assert band_for(**BANDS, created_at=future, now=NOW) is Staleness.FRESH
    assert confidence_now(**BANDS, created_at=future, now=NOW) == pytest.approx(0.8)


def test_confidence_now_is_the_s5_curve_and_not_a_second_opinion():
    """The whole module is a vocabulary FOR `effective_confidence`, never a
    reimplementation of it."""
    created = NOW - timedelta(days=25)
    assert confidence_now(**BANDS, created_at=created, now=NOW) == pytest.approx(
        effective_confidence(**BANDS, age_days=25.0)
    )
    # One half-life = half the decayable confidence, by construction.
    one = NOW - timedelta(days=BANDS["half_life_days"])
    assert confidence_now(**BANDS, created_at=one, now=NOW) == pytest.approx(0.4)


def test_standing_answers_td_020_without_touching_status():
    """An open claim on a decayed verdict is still OPEN — nobody contradicted
    it — but it is no longer load-bearing. Two questions, two fields; letting
    decay write to `status` would erase the difference between "never
    contradicted" and "contradicted"."""
    assert standing_for(Staleness.FRESH) is Standing.LOAD_BEARING
    assert standing_for(Staleness.AGING) is Standing.LOAD_BEARING
    assert standing_for(Staleness.STALE) is Standing.LAPSED
    assert standing_for(Staleness.LAPSED) is Standing.LAPSED
    assert standing_for(Staleness.HELD) is Standing.LOAD_BEARING


# -- one observable's life -----------------------------------------------------


async def test_the_trail_renders_newest_first_with_one_current_row(pool, workspace_id):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(
        pool, workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS, 0.9),)),
    )
    t = await timeline_for(pool, workspace_id=workspace_id, obs_id=cve_obs(CVE_A).obs_id)
    assert [v.label for v in t.trail] == ["malicious", "suspicious"]
    assert [v.current for v in t.trail] == [True, False]
    assert t.current.label == "malicious"
    # The flip S14 recorded is part of the same story.
    assert [(f.from_label, f.to_label) for f in t.flips] == [("suspicious", "malicious")]


async def test_the_trail_shows_decay_that_no_surface_has_ever_shown(pool, workspace_id):
    """`effective_confidence` has existed since S5 and been rendered nowhere."""
    await persist_enrichment(
        pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A, conf=0.8),))
    )
    # CVE half-life is 365 days; two of them.
    await _age_verdicts(pool, workspace_id, CVE_A, days=730)
    t = await timeline_for(pool, workspace_id=workspace_id, obs_id=cve_obs(CVE_A).obs_id)
    v = t.current
    assert v.confidence_at_write == pytest.approx(0.8)
    assert v.confidence_now == pytest.approx(0.2, abs=0.01)  # two half-lives
    assert v.half_lives_elapsed == pytest.approx(2.0, abs=0.01)
    # Two half-lives is `stale`, not `lapsed` — 75% of the claim is gone but
    # the band that says "this is not evidence any more" starts at three.
    assert v.staleness is Staleness.STALE
    # And the label is untouched: decay is about our confidence, not the CVE.
    assert v.label == "suspicious"


async def test_an_open_claim_on_a_decayed_verdict_is_lapsed_but_still_open(
    pool, workspace_id
):
    """TD-020, answered against real rows rather than in prose."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await _age_verdicts(pool, workspace_id, CVE_A, days=365 * 4)
    t = await timeline_for(pool, workspace_id=workspace_id, obs_id=cve_obs(CVE_A).obs_id)
    assert t.current.staleness is Staleness.LAPSED
    open_claims = [c for c in t.claims if c.watcher.status == "open"]
    assert open_claims, "the verdict registered claims"
    assert all(c.standing is Standing.LAPSED for c in open_claims)
    # Still OPEN — the platform committed to watching, and quietly stopping
    # would be the failure the feature exists to prevent.
    assert all(c.watcher.status == "open" for c in open_claims)


async def test_a_contradicted_claim_has_no_standing_question_left(pool, workspace_id):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    t = await timeline_for(pool, workspace_id=workspace_id, obs_id=cve_obs(CVE_A).obs_id)
    satisfied = [c for c in t.claims if c.watcher.status == "satisfied"]
    assert satisfied and all(c.standing is None for c in satisfied)
    # The re-open event rides along, carrying the claim it contradicted.
    assert len(t.matches) == 1
    assert t.matches[0].falsified_claim is not None


async def test_an_unseen_observable_has_no_timeline(pool, workspace_id):
    assert await timeline_for(
        pool, workspace_id=workspace_id, obs_id=cve_obs("CVE-2026-88999").obs_id
    ) is None


async def test_a_timeline_never_crosses_a_workspace(pool, workspace_id, other_workspace_id):
    await persist_enrichment(
        pool, other_workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),))
    )
    # Same observable VALUE, a different tenant: invisible, not merely filtered.
    assert await timeline_for(
        pool, workspace_id=workspace_id, obs_id=cve_obs(CVE_A).obs_id
    ) is None


# -- the digest ----------------------------------------------------------------


async def test_a_verdict_that_went_stale_by_itself_is_news(pool, workspace_id):
    """The only item in the digest nobody recorded: nothing happened, time
    passed. Written 1.6 half-lives ago, crossed into `stale` two days ago."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await _age_verdicts(pool, workspace_id, CVE_A, days=365 * STALE_AT_HALF_LIVES + 2)
    d = await digest(
        pool, workspace_id=workspace_id, since=datetime.now(UTC) - timedelta(days=7)
    )
    crossed = [x for x in d.decayed if x.value == CVE_A]
    assert len(crossed) == 1
    assert crossed[0].was is Staleness.AGING
    assert crossed[0].now is Staleness.STALE
    assert not d.quiet


async def test_a_verdict_that_crossed_nothing_is_not_news(pool, workspace_id):
    """Written this second: no edge crossed in the window, so it must not appear
    just because it exists."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    d = await digest(
        pool, workspace_id=workspace_id, since=datetime.now(UTC) - timedelta(days=7)
    )
    assert [x for x in d.decayed if x.value == CVE_A] == []


async def test_only_the_latest_verdict_can_go_stale(pool, workspace_id):
    """A superseded verdict decaying is not news — the belief it held was
    already replaced, and reporting it would double-count the observable."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await _age_verdicts(pool, workspace_id, CVE_A, days=365 * 2)
    await persist_enrichment(
        pool, workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
    )
    d = await decayed_since(
        pool, workspace_id=workspace_id,
        since=datetime.now(UTC) - timedelta(days=7), now=datetime.now(UTC),
    )
    assert [x for x in d if x.value == CVE_A] == []


async def test_the_digest_reuses_the_events_that_already_exist(pool, workspace_id):
    """D-020/D-021: no third notification shape. What lands here is the same
    match, the same flip and the same contradicted claim the other surfaces
    serve."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    await persist_enrichment(
        pool, workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
    )
    d = await digest(
        pool, workspace_id=workspace_id, since=datetime.now(UTC) - timedelta(days=1)
    )
    assert [m.value for m in d.matches] == [CVE_A]
    assert [(f.from_label, f.to_label) for f in d.flips] == [("suspicious", "malicious")]
    assert {w.kind for w in d.contradicted} == {"kev_listing", "provider_escalation"}
    assert not d.quiet


async def test_the_digest_never_crosses_a_workspace(pool, workspace_id, other_workspace_id):
    await persist_enrichment(
        pool, other_workspace_id, EnrichmentOutcome(items=(cve_item(CVE_B),))
    )
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(CVE_B, "kev", "kev-added")]
    )
    mine = await digest(
        pool, workspace_id=workspace_id, since=datetime.now(UTC) - timedelta(days=1)
    )
    assert mine.quiet
    theirs = await digest(
        pool, workspace_id=other_workspace_id, since=datetime.now(UTC) - timedelta(days=1)
    )
    assert not theirs.quiet


# -- "quiet" has to be earned (S16 Step 0's confirmed gap) ---------------------


def test_a_checker_is_degraded_only_after_consecutive_failures():
    c = FailureCounter("watchers")
    assert not c.status.degraded and not c.status.ever_succeeded
    for _ in range(DEGRADED_AFTER - 1):
        c.failed(RuntimeError("boom"))
    assert not c.status.degraded
    c.failed(RuntimeError("boom"))
    assert c.status.degraded
    assert c.status.consecutive_failures == DEGRADED_AFTER
    # The TYPE, never the message: an exception raised while checking a watcher
    # can carry an observable value (org data-handling rule).
    assert c.status.last_error == "RuntimeError"
    c.succeeded()
    assert not c.status.degraded and c.status.ever_succeeded
    assert c.status.last_error is None


async def test_a_dead_watcher_check_makes_a_quiet_digest_untrustworthy(pool, workspace_id):
    """The S16 Step-0 finding, closed. 50 consecutive failed checks used to
    produce a digest identical to 50 quiet ones."""

    class DeadCheck:
        async def emit(self, changes):
            raise RuntimeError("watcher check down")

    fanout = FanoutSink(DeadCheck())
    for _ in range(DEGRADED_AFTER):
        await fanout.emit([DocChange(CVE_A, "kev", "kev-added")])

    d = await digest(
        pool,
        workspace_id=workspace_id,
        since=datetime.now(UTC) - timedelta(days=7),
        checkers=fanout.health(),
    )
    assert d.quiet  # nothing to report...
    assert not d.trustworthy  # ...and that silence means nothing


async def test_a_healthy_checker_makes_quiet_mean_quiet(pool, workspace_id):
    fanout = FanoutSink(RetroHuntSink(pool), WatcherSink(pool))
    await fanout.emit([DocChange(CVE_A, "kev", "kev-added")])
    d = await digest(
        pool,
        workspace_id=workspace_id,
        since=datetime.now(UTC) - timedelta(days=7),
        checkers=fanout.health(),
    )
    assert d.quiet and d.trustworthy
    assert {c.name for c in d.checkers} == {"retrohunt", "watchers", "fanout"}


async def test_an_unknown_checker_roster_is_not_reassuring(pool, workspace_id):
    """Ingest disabled, or a process that has not started one: nothing was
    watching, so quiet is not evidence of quiet. The dangerous default here is
    'assume healthy', and it is not taken."""
    d = await digest(
        pool, workspace_id=workspace_id, since=datetime.now(UTC) - timedelta(days=7)
    )
    assert d.quiet and not d.trustworthy


def test_a_quiet_cycle_does_not_launder_a_broken_checker():
    """A checker that failed three times and then had nothing to do must not
    come back reading healthy — the quiet weeks are exactly when the digest is
    being trusted."""
    sink = WatcherSink(pool=None)
    sink._health.failed(RuntimeError("boom"))
    sink._health.failed(RuntimeError("boom"))
    sink._health.failed(RuntimeError("boom"))
    assert sink.health.degraded


async def test_a_cycle_with_no_relevant_changes_leaves_health_untouched(pool):
    """`upserted` is not a watcher trigger, so this cycle checks nothing —
    which is neither success nor failure."""
    sink = WatcherSink(pool)
    await sink.emit([DocChange(CVE_A, "nvd-delta", "upserted")])
    assert not sink.health.ever_succeeded
    assert sink.health.consecutive_failures == 0


# -- the analyst surface -------------------------------------------------------

ROUTE_CVE = "CVE-2026-88500"
ROUTE_EMAIL = "analyst@auspex.dev"


def _hdr(client) -> dict:
    token = client.post("/api/auth/dev-login", json={"email": ROUTE_EMAIL}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def route_ws(pool, client):
    ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = 'default'")
    assert ws is not None
    await pool.execute(
        "DELETE FROM observables WHERE workspace_id = $1 AND type = 'cve' AND value = $2",
        ws, ROUTE_CVE,
    )
    yield ws
    await pool.execute(
        "DELETE FROM observables WHERE workspace_id = $1 AND type = 'cve' AND value = $2",
        ws, ROUTE_CVE,
    )


async def test_the_timeline_route_renders_a_whole_life(pool, client, route_ws):
    await persist_enrichment(pool, route_ws, EnrichmentOutcome(items=(cve_item(ROUTE_CVE),)))
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(ROUTE_CVE, "kev", "kev-added")]
    )
    body = client.get(
        f"/api/timeline/{cve_obs(ROUTE_CVE).obs_id}", headers=_hdr(client)
    ).json()
    assert body["observable"]["value"] == ROUTE_CVE
    assert body["current"]["label"] == "suspicious"
    assert "confidence_now" in body["current"]
    assert body["current"]["staleness"] == "fresh"
    assert len(body["reopened_by"]) == 1
    assert body["reopened_by"][0]["falsifies"]
    assert any(c["status"] == "satisfied" for c in body["claims"])
    assert any(c["standing"] == "load_bearing" for c in body["claims"])
    # The vocabulary travels with the payload so no client invents its own.
    assert set(body["bands"]) == {"fresh", "aging", "stale", "lapsed", "held"}


async def test_the_digest_route_answers_and_states_its_own_reliability(
    pool, client, route_ws
):
    await persist_enrichment(pool, route_ws, EnrichmentOutcome(items=(cve_item(ROUTE_CVE),)))
    body = client.get("/api/timeline/digest", headers=_hdr(client)).json()
    assert "quiet" in body and "trustworthy" in body
    assert isinstance(body["checkers"], list)
    assert body["note"].startswith("Nothing on this surface has changed a verdict")


def test_digest_wins_the_route_match_against_an_observable_id(client):
    """`/digest` is declared before `/{obs_id}`; if that ever flips, this asks
    for a digest and gets a 404 for an observable named "digest"."""
    body = client.get("/api/timeline/digest", headers=_hdr(client))
    assert body.status_code == 200
    assert "checkers" in body.json()


def test_an_unknown_observable_is_404(client):
    resp = client.get("/api/timeline/cve-deadbeef", headers=_hdr(client))
    assert resp.status_code == 404


def test_timeline_routes_require_auth(client):
    assert client.get("/api/timeline/digest").status_code == 401
    assert client.get("/api/timeline/cve-deadbeef").status_code == 401


def test_the_digest_window_is_bounded(client):
    assert client.get(
        "/api/timeline/digest", params={"days": 0}, headers=_hdr(client)
    ).status_code == 422
    assert client.get(
        "/api/timeline/digest", params={"days": 10_000}, headers=_hdr(client)
    ).status_code == 422
