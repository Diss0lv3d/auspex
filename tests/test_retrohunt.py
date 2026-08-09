"""Retro-hunt — S14, against live Postgres (compose dev DB).

Covers the sweep's indexed join and what it matches, the honesty rail (a match
NEVER writes a verdict), idempotent re-emission, the sink's trigger filter and
failure posture, verdict-flip provenance, and D-008 tenancy on every read/write.
Zero LLM anywhere: this is ingest/join/event code.

Each test provisions its own workspace and deletes it at the end (cascades cover
observables, verdicts, retrohunt_matches and verdict_flips).
"""

import asyncio

import asyncpg
import pytest

from auspex.classify.observables import Observable, ObservableType, observable_id
from auspex.db import create_pool
from auspex.enrich.store import persist_enrichment
from auspex.enrich.types import (
    EnrichmentOutcome,
    ObservableEnrichment,
    ProviderSignal,
    VerdictLabel,
)
from auspex.ingest.events import DocChange
from auspex.retrohunt import (
    RetroHuntSink,
    list_flips,
    list_matches,
    mark_reviewed,
    record_matches,
    sweep,
)
from auspex.retrohunt.flips import latest_verdict
from auspex.retrohunt.store import _SWEEP_SQL, SWEEP_CHUNK, normalize_doc_ids

CVE_A = "CVE-2026-58644"
CVE_B = "CVE-2026-11111"


def cve_obs(value: str) -> Observable:
    return Observable(
        type=ObservableType.CVE,
        value=value,
        obs_id=observable_id(ObservableType.CVE, value),
        defanged=False,
    )


def cve_item(value: str, label: VerdictLabel = VerdictLabel.SUSPICIOUS) -> ObservableEnrichment:
    return ObservableEnrichment(
        observable=cve_obs(value),
        signals=(ProviderSignal("TestProvider", label, 0.6, "seen", evidence={}),),
    )


@pytest.fixture
async def pool(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    yield pool
    await pool.close()


async def _workspace(pool, name: str):
    return await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        name,
    )


@pytest.fixture
async def workspace_id(pool):
    ws = await _workspace(pool, "t-retrohunt")
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


@pytest.fixture
async def other_workspace_id(pool):
    ws = await _workspace(pool, "t-retrohunt-other")
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


# -- the sweep -----------------------------------------------------------------


async def test_sweep_finds_a_historical_observable_with_its_settled_verdict(
    pool, workspace_id
):
    """The core claim of S14: intel landing today finds what we settled earlier."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    hits = await sweep(pool, doc_ids=[CVE_A], feed="kev", change_kind="kev-added")
    mine = [h for h in hits if h.workspace_id == workspace_id]
    assert len(mine) == 1
    hit = mine[0]
    assert hit.value == CVE_A
    assert hit.doc_id == CVE_A
    assert hit.obs_id == observable_id(ObservableType.CVE, CVE_A)
    assert hit.verdict_label == "suspicious"
    assert hit.settled is True
    assert hit.feed == "kev" and hit.change_kind == "kev-added"


async def test_sweep_returns_the_latest_verdict_not_the_first(pool, workspace_id):
    """`verdicts` is append-only, so "the verdict" is the newest row — a sweep
    that reported the first one would tell the analyst about a belief the
    platform had already replaced."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(
        pool,
        workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
    )
    hits = [
        h
        for h in await sweep(pool, doc_ids=[CVE_A], feed="kev", change_kind="kev-added")
        if h.workspace_id == workspace_id
    ]
    assert len(hits) == 1
    assert hits[0].verdict_label == "malicious"


async def test_sweep_reports_an_unsettled_observable_too(pool, workspace_id):
    """An observable seen but never enriched to a verdict is still worth telling
    someone about: they pasted it once and it is now known-exploited."""
    await pool.execute(
        "INSERT INTO observables (workspace_id, obs_id, type, value) VALUES ($1,$2,$3,$4)",
        workspace_id,
        observable_id(ObservableType.CVE, CVE_A),
        "cve",
        CVE_A,
    )
    hits = [
        h
        for h in await sweep(pool, doc_ids=[CVE_A], feed="kev", change_kind="kev-added")
        if h.workspace_id == workspace_id
    ]
    assert len(hits) == 1
    assert hits[0].settled is False
    assert hits[0].verdict_label is None


async def test_sweep_matches_nothing_when_the_workspace_never_saw_the_cve(
    pool, workspace_id
):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    hits = await sweep(pool, doc_ids=[CVE_B], feed="kev", change_kind="kev-added")
    assert [h for h in hits if h.workspace_id == workspace_id] == []


async def test_sweep_normalizes_doc_id_case(pool, workspace_id):
    """Every writer upper-cases CVE ids today (kb/seed.py, kev.py, the S4
    classifier). The sweep normalizes anyway so the join can compare exactly and
    keep the index — `UPPER(o.value)` would throw it away."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    hits = [
        h
        for h in await sweep(
            pool, doc_ids=[CVE_A.lower()], feed="kev", change_kind="kev-added"
        )
        if h.workspace_id == workspace_id
    ]
    assert len(hits) == 1


def test_normalize_doc_ids_dedups_and_drops_blanks():
    assert normalize_doc_ids([CVE_A, CVE_A.lower(), " ", "", CVE_B]) == [CVE_B, CVE_A]


async def test_sweep_chunks_a_batch_larger_than_the_chunk_size(pool, workspace_id):
    """A KEV first-run refresh can carry ~1,600 ids (S8 review). Chunking must
    not lose hits that fall in a later chunk."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    padding = [f"CVE-2026-{i:05d}" for i in range(SWEEP_CHUNK + 10)]
    hits = [
        h
        for h in await sweep(
            pool, doc_ids=[*padding, CVE_A], feed="kev", change_kind="kev-added"
        )
        if h.workspace_id == workspace_id
    ]
    assert len(hits) == 1 and hits[0].value == CVE_A


# -- re-open events (the honesty rail) -----------------------------------------


async def test_a_match_records_the_event_and_never_writes_a_verdict(pool, workspace_id):
    """D-017's rail, held by code rather than by prose: a retro-hunt match is a
    reason to re-examine. If a sweep could flip a label, the calendar (or CISA's
    publishing schedule) would be changing verdicts instead of evidence."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    before = await pool.fetch(
        "SELECT id, label FROM verdicts WHERE workspace_id = $1 ORDER BY created_at",
        workspace_id,
    )
    hits = [
        h
        for h in await sweep(pool, doc_ids=[CVE_A], feed="kev", change_kind="kev-added")
        if h.workspace_id == workspace_id
    ]
    assert await record_matches(pool, hits) == 1

    after = await pool.fetch(
        "SELECT id, label FROM verdicts WHERE workspace_id = $1 ORDER BY created_at",
        workspace_id,
    )
    assert [(r["id"], r["label"]) for r in after] == [(r["id"], r["label"]) for r in before]
    assert await pool.fetchval(
        "SELECT count(*) FROM verdict_flips WHERE workspace_id = $1", workspace_id
    ) == 0

    matches = await list_matches(pool, workspace_id=workspace_id)
    assert len(matches) == 1
    assert matches[0].status == "open"
    assert matches[0].verdict_label == "suspicious"  # as it stood AT MATCH TIME
    assert matches[0].doc_id == CVE_A


async def test_re_emitting_the_same_change_is_not_news_twice(pool, workspace_id):
    """The KEV first-run refresh re-emits every held id on a fresh volume, and a
    catalogue re-read repeats ids — an analyst must not see the same event grow
    a duplicate every cycle."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    hits = await sweep(pool, doc_ids=[CVE_A], feed="kev", change_kind="kev-added")
    assert await record_matches(pool, hits) == 1
    assert await record_matches(pool, hits) == 0  # idempotent
    assert len(await list_matches(pool, workspace_id=workspace_id)) == 1


async def test_a_different_change_kind_on_the_same_doc_is_a_separate_event(
    pool, workspace_id
):
    """"Now known-exploited" and "NVD rejected this CVE" are different news about
    the same doc, so the natural key includes change_kind."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    added = await sweep(pool, doc_ids=[CVE_A], feed="kev", change_kind="kev-added")
    deleted = await sweep(pool, doc_ids=[CVE_A], feed="kev", change_kind="deleted")
    assert await record_matches(pool, added) == 1
    assert await record_matches(pool, deleted) == 1
    assert len(await list_matches(pool, workspace_id=workspace_id)) == 2


async def test_matches_are_workspace_scoped_in_both_directions(
    pool, workspace_id, other_workspace_id
):
    """D-008. Both workspaces saw the same CVE; one sweep finds both, and each
    workspace's reads show only its own event."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(
        pool, other_workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),))
    )
    hits = await sweep(pool, doc_ids=[CVE_A], feed="kev", change_kind="kev-added")
    swept = {h.workspace_id for h in hits}
    assert {workspace_id, other_workspace_id} <= swept  # one query, both tenants
    await record_matches(pool, hits)

    mine = await list_matches(pool, workspace_id=workspace_id)
    theirs = await list_matches(pool, workspace_id=other_workspace_id)
    assert len(mine) == 1 and len(theirs) == 1
    assert mine[0].id != theirs[0].id
    # neither can acknowledge the other's event
    assert await mark_reviewed(pool, workspace_id=workspace_id, match_id=theirs[0].id) is False
    assert await mark_reviewed(pool, workspace_id=workspace_id, match_id=mine[0].id) is True
    assert (await list_matches(pool, workspace_id=workspace_id, status="open")) == []


# -- the sink ------------------------------------------------------------------


async def test_sink_sweeps_only_material_change_kinds(pool, workspace_id):
    """`upserted` is ~770 docs/day of NVD re-scores and reworded descriptions
    (STATE.md). Waking an analyst for those would train them to ignore the
    surface that exists to be trusted."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    sink = RetroHuntSink(pool)

    await sink.emit([DocChange(CVE_A, "nvd-delta", "upserted")])
    assert await list_matches(pool, workspace_id=workspace_id) == []

    await sink.emit([DocChange(CVE_A, "kev", "kev-added")])
    matches = await list_matches(pool, workspace_id=workspace_id)
    assert len(matches) == 1 and matches[0].change_kind == "kev-added"


async def test_sink_groups_a_mixed_batch_into_one_sweep_per_feed_and_kind(
    pool, workspace_id
):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_B),)))
    sink = RetroHuntSink(pool)
    await sink.emit(
        [
            DocChange(CVE_A, "kev", "kev-added"),
            DocChange(CVE_B, "kev", "kev-added"),
            DocChange("CVE-2026-99999", "nvd-delta", "upserted"),  # filtered out
        ]
    )
    matches = await list_matches(pool, workspace_id=workspace_id)
    assert {m.doc_id for m in matches} == {CVE_A, CVE_B}


async def test_sink_survives_a_sweep_failure(pool, workspace_id):
    """Ingest outlives retro-hunt failures: intel landing in the KB is the more
    important job, and a missed batch is re-swept when the doc changes again. A
    raise here would kill an ingest cycle."""

    class Boom:
        def acquire(self, *a, **k):
            raise asyncpg.PostgresError("boom")

        async def fetch(self, *a, **k):
            raise asyncpg.PostgresError("boom")

    await RetroHuntSink(Boom()).emit([DocChange(CVE_A, "kev", "kev-added")])  # no raise


async def test_sink_never_touches_the_database_for_a_non_material_batch(pool):
    """An empty or all-filtered batch must not even acquire a connection — the
    NVD delta feed emits one of these every cycle."""

    class Forbidden:
        def acquire(self, *a, **k):
            raise AssertionError("no query should run for a non-material batch")

    sink = RetroHuntSink(Forbidden())
    await sink.emit([])
    await sink.emit([DocChange(CVE_A, "nvd-delta", "upserted")])


# -- verdict flips -------------------------------------------------------------


async def test_a_changed_label_records_a_flip_with_provenance(pool, workspace_id):
    """The D-017 trail's first automated writer."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(
        pool,
        workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
    )
    flips = await list_flips(pool, workspace_id=workspace_id)
    assert len(flips) == 1
    assert flips[0].from_label == "suspicious" and flips[0].to_label == "malicious"
    assert flips[0].trigger == "enrichment"  # no retro-hunt match explains it
    assert flips[0].match_id is None
    assert flips[0].value == CVE_A


async def test_a_first_ever_verdict_is_not_a_flip(pool, workspace_id):
    """No previous belief means nothing changed its mind. A new malicious
    observable is triage; a benign one turning malicious is news."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    assert await list_flips(pool, workspace_id=workspace_id) == []


async def test_re_enrichment_with_the_same_label_is_not_a_flip(pool, workspace_id):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    assert await pool.fetchval(
        "SELECT count(*) FROM verdicts WHERE workspace_id = $1", workspace_id
    ) == 2  # the append-only trail still grew
    assert await list_flips(pool, workspace_id=workspace_id) == []


async def test_a_flip_after_a_retrohunt_match_names_the_doc_that_prompted_it(
    pool, workspace_id
):
    """The full S14 loop: intel lands → sweep matches a settled observable →
    an analyst re-enriches → the label changes → the flip names the CVE that
    caused anyone to look again."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await RetroHuntSink(pool).emit([DocChange(CVE_A, "kev", "kev-added")])
    match = (await list_matches(pool, workspace_id=workspace_id))[0]

    await persist_enrichment(
        pool,
        workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
    )
    flips = await list_flips(pool, workspace_id=workspace_id)
    assert len(flips) == 1
    assert flips[0].trigger == f"retrohunt:{CVE_A}"
    assert flips[0].match_id == match.id
    # and the match stays OPEN: a flip is the strongest sign the ask was worth
    # making, so it is never closed on the analyst's behalf
    assert (await list_matches(pool, workspace_id=workspace_id))[0].status == "open"


async def test_flip_rows_carry_both_verdict_ids(pool, workspace_id):
    """A flip must be reconstructible from the trail it describes."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(
        pool,
        workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.BENIGN),)),
    )
    row = await pool.fetchrow(
        "SELECT from_verdict_id, to_verdict_id FROM verdict_flips WHERE workspace_id = $1",
        workspace_id,
    )
    verdicts = await pool.fetch(
        "SELECT id, label FROM verdicts WHERE workspace_id = $1 ORDER BY created_at",
        workspace_id,
    )
    assert row["from_verdict_id"] == verdicts[0]["id"]
    assert row["to_verdict_id"] == verdicts[-1]["id"]


async def test_concurrent_enrichments_of_one_observable_record_exactly_one_flip(
    pool, workspace_id
):
    """S15 Step 0, concurrency angle. `latest_verdict` reads the trail and the
    verdict insert follows it with no FOR UPDATE in between — the shape the S13
    review found broken in `add_evidence`. It is safe HERE only because the
    `observables` upsert already holds that row's lock to commit, so the two
    transactions cannot interleave. Pinning it: without that lock both runs read
    `benign` and record the same flip twice."""
    await persist_enrichment(
        pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.BENIGN),))
    )
    await asyncio.gather(
        persist_enrichment(
            pool,
            workspace_id,
            EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
        ),
        persist_enrichment(
            pool,
            workspace_id,
            EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
        ),
    )
    flips = await list_flips(pool, workspace_id=workspace_id)
    assert [(f.from_label, f.to_label) for f in flips] == [("benign", "malicious")]


async def test_the_trail_orders_by_write_time_not_by_transaction_start(
    pool, workspace_id
):
    """S15 Step 0, the executed defect. `created_at DEFAULT now()` is
    transaction_timestamp — fixed at a transaction's FIRST statement. A
    transaction that starts earlier, blocks on the shared observable's row lock,
    and commits LAST wrote the newest belief but carried the OLDEST stamp, so
    `latest_verdict` (and the sweep, which reads the trail the same way)
    reported a superseded label as current.

    Reproduced here in the shape production produces it: B's first statement is
    an unrelated observable — exactly what persist_enrichment does when a turn
    carries more than one, since it sorts by (type, value) before writing."""
    await persist_enrichment(
        pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.BENIGN),))
    )
    conn_b = await pool.acquire()
    tx_b = conn_b.transaction()
    await tx_b.start()
    try:
        # B begins on an unrelated row. Under now() its clock stops here.
        await conn_b.fetchval(
            "INSERT INTO observables (workspace_id, obs_id, type, value)"
            " VALUES ($1, $2, 'cve', $3)"
            " ON CONFLICT (workspace_id, type, value) DO UPDATE SET last_seen = now()"
            " RETURNING id",
            workspace_id,
            observable_id(ObservableType.CVE, CVE_B),
            CVE_B,
        )
        # A starts later and commits first: 'malicious' is now the trail's head.
        await persist_enrichment(
            pool,
            workspace_id,
            EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
        )
        # B reaches the shared observable and writes the newest belief last.
        row_id = await conn_b.fetchval(
            "INSERT INTO observables (workspace_id, obs_id, type, value)"
            " VALUES ($1, $2, 'cve', $3)"
            " ON CONFLICT (workspace_id, type, value) DO UPDATE SET last_seen = now()"
            " RETURNING id",
            workspace_id,
            observable_id(ObservableType.CVE, CVE_A),
            CVE_A,
        )
        new_id = await conn_b.fetchval(
            "INSERT INTO verdicts (workspace_id, observable_id, label,"
            " confidence_at_write, half_life_days, floor, source, details)"
            " VALUES ($1, $2, 'suspicious', 0.5, 365.0, 0.1, 'enrichment:Test', '{}')"
            " RETURNING id",
            workspace_id,
            row_id,
        )
        await tx_b.commit()
    except BaseException:  # pragma: no cover — a failing assert must not leak the tx
        await tx_b.rollback()
        raise
    finally:
        await pool.release(conn_b)

    async with pool.acquire() as conn:
        current = await latest_verdict(
            conn, workspace_id=workspace_id, observable_id=row_id
        )
    assert current["id"] == new_id, "the trail's head is not the last belief written"
    assert current["label"] == "suspicious"
    hits = [
        h
        for h in await sweep(pool, doc_ids=[CVE_A], feed="kev", change_kind="kev-added")
        if h.workspace_id == workspace_id
    ]
    assert [h.verdict_label for h in hits] == ["suspicious"]


async def test_flips_are_workspace_scoped(pool, workspace_id, other_workspace_id):
    for ws in (workspace_id, other_workspace_id):
        await persist_enrichment(pool, ws, EnrichmentOutcome(items=(cve_item(CVE_A),)))
        await persist_enrichment(
            pool, ws, EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),))
        )
    mine = await list_flips(pool, workspace_id=workspace_id)
    theirs = await list_flips(pool, workspace_id=other_workspace_id)
    assert len(mine) == 1 and len(theirs) == 1
    assert mine[0].id != theirs[0].id


# -- the analyst surface -------------------------------------------------------

ROUTE_CVE = "CVE-2026-90001"
ROUTE_EMAIL = "analyst@auspex.dev"  # provisioned into the 'default' workspace


def _hdr(client) -> dict:
    token = client.post("/api/auth/dev-login", json={"email": ROUTE_EMAIL}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def route_ws(pool, client):
    """The dev-login workspace. Its genuine rows must survive, so cleanup is
    scoped to this test CVE only (cascades cover matches and flips)."""
    ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = 'default'")
    assert ws is not None, "dev-login should have provisioned the default workspace"
    await pool.execute(
        "DELETE FROM observables WHERE workspace_id = $1 AND type = 'cve' AND value = $2",
        ws,
        ROUTE_CVE,
    )
    yield ws
    await pool.execute(
        "DELETE FROM observables WHERE workspace_id = $1 AND type = 'cve' AND value = $2",
        ws,
        ROUTE_CVE,
    )


async def test_matches_route_reports_the_event_and_the_honesty_rail(
    pool, client, route_ws
):
    await persist_enrichment(pool, route_ws, EnrichmentOutcome(items=(cve_item(ROUTE_CVE),)))
    await RetroHuntSink(pool).emit([DocChange(ROUTE_CVE, "kev", "kev-added")])

    resp = client.get("/api/retrohunt/matches", headers=_hdr(client))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    mine = [m for m in body["matches"] if m["trigger_doc"] == ROUTE_CVE]
    assert len(mine) == 1
    m = mine[0]
    assert m["observable"]["value"] == ROUTE_CVE
    assert m["verdict_label_at_match"] == "suspicious"
    assert m["settled"] is True
    assert m["status"] == "open"
    assert m["action"] == "re-examine"  # stated in the payload, not just the docs
    assert "no verdict has been changed" in m["note"].lower()
    assert body["status_filter"] == "open"
    # the filter is named, so "no events" can't be confused with "we swept nothing"
    assert set(body["sweeps_on"]) == {"kev-added", "deleted"}


async def test_ack_moves_a_match_out_of_the_open_list(pool, client, route_ws):
    await persist_enrichment(pool, route_ws, EnrichmentOutcome(items=(cve_item(ROUTE_CVE),)))
    await RetroHuntSink(pool).emit([DocChange(ROUTE_CVE, "kev", "kev-added")])
    match_id = [
        m["match_id"]
        for m in client.get("/api/retrohunt/matches", headers=_hdr(client)).json()["matches"]
        if m["trigger_doc"] == ROUTE_CVE
    ][0]

    ack = client.post(f"/api/retrohunt/matches/{match_id}/ack", headers=_hdr(client))
    assert ack.status_code == 200
    assert ack.json() == {"match_id": match_id, "status": "reviewed"}

    still_open = client.get("/api/retrohunt/matches", headers=_hdr(client)).json()["matches"]
    assert [m for m in still_open if m["trigger_doc"] == ROUTE_CVE] == []
    reviewed = client.get(
        "/api/retrohunt/matches", params={"status": "reviewed"}, headers=_hdr(client)
    ).json()["matches"]
    assert [m["match_id"] for m in reviewed if m["trigger_doc"] == ROUTE_CVE] == [match_id]

    # acknowledging twice is an honest 404, not a silent success
    assert client.post(
        f"/api/retrohunt/matches/{match_id}/ack", headers=_hdr(client)
    ).status_code == 404


async def test_ack_of_an_unknown_match_is_404(client):
    resp = client.post(
        "/api/retrohunt/matches/00000000-0000-4000-8000-000000000000/ack",
        headers=_hdr(client),
    )
    assert resp.status_code == 404


async def test_flips_route_reports_provenance(pool, client, route_ws):
    await persist_enrichment(pool, route_ws, EnrichmentOutcome(items=(cve_item(ROUTE_CVE),)))
    await RetroHuntSink(pool).emit([DocChange(ROUTE_CVE, "kev", "kev-added")])
    await persist_enrichment(
        pool,
        route_ws,
        EnrichmentOutcome(items=(cve_item(ROUTE_CVE, VerdictLabel.MALICIOUS),)),
    )
    body = client.get("/api/retrohunt/flips", headers=_hdr(client)).json()
    mine = [f for f in body["flips"] if f["observable"]["value"] == ROUTE_CVE]
    assert len(mine) == 1
    assert mine[0]["from_label"] == "suspicious"
    assert mine[0]["to_label"] == "malicious"
    assert mine[0]["trigger"] == f"retrohunt:{ROUTE_CVE}"
    assert mine[0]["match_id"] is not None


def test_retrohunt_routes_require_auth(client):
    assert client.get("/api/retrohunt/matches").status_code == 401
    assert client.get("/api/retrohunt/flips").status_code == 401
    assert client.post(
        "/api/retrohunt/matches/00000000-0000-4000-8000-000000000000/ack"
    ).status_code == 401


def test_matches_route_rejects_an_unknown_status_filter(client):
    resp = client.get(
        "/api/retrohunt/matches", params={"status": "banana"}, headers=_hdr(client)
    )
    assert resp.status_code == 422


# -- the query plan (ROADMAP S14 constraint) ------------------------------------


PLAN_SEED_ROWS = 25_000  # above the measured 20k crossover for a 50-id batch


@pytest.fixture
async def seeded_observables(pool, workspace_id):
    """A table big enough for the planner's choice to be meaningful. Below the
    crossover a scan genuinely IS cheaper and asserting otherwise would be
    testing Postgres's arithmetic, not our query. Re-ANALYZEs after cleanup so
    the shared dev DB is left as we found it."""
    await pool.execute(
        """
        INSERT INTO observables (workspace_id, obs_id, type, value)
        SELECT $1, 'cve-plan-' || i, 'cve', 'CVE-2019-' || lpad(i::text, 6, '0')
        FROM generate_series(1, $2) AS s(i)
        ON CONFLICT (workspace_id, type, value) DO NOTHING
        """,
        workspace_id,
        PLAN_SEED_ROWS,
    )
    # VACUUM, not just ANALYZE: seeding and dropping 25k rows leaves the table
    # bloated (measured: 25k dead tuples in 358 pages behind 10 live rows), and
    # the planner costs a scan in PAGES — so bloat, not the query, decided the
    # plan and this test failed for a reason that had nothing to do with the
    # code under test. Compacting first makes the assertion about the query.
    await pool.execute("VACUUM (ANALYZE) observables")
    yield
    await pool.execute(
        "DELETE FROM observables WHERE workspace_id = $1 AND obs_id LIKE 'cve-plan-%'",
        workspace_id,
    )
    await pool.execute("VACUUM (ANALYZE) observables")


async def test_sweep_plan_is_an_indexed_join_not_a_table_scan(
    pool, workspace_id, seeded_observables
):
    """The ROADMAP S14 constraint, pinned: "indexed join, never scan".

    A real regression, not a formality — the first version of this sweep planned
    as `Seq Scan on observables ... Rows Removed by Filter: 19760`, which EXPLAIN
    caught and review did not (docs/probes/2026-08-09-s14-retrohunt-explain.md).
    A scan means every KEV release reads every observable the platform ever
    recorded.

    Asserted at the SHIPPED chunk size, because that bound is what holds the
    plan (see the companion test below). The crossover only moves in the index's
    favour as the table grows, so holding at 25k rows means holding above it."""
    ids = [f"CVE-2019-{i:06d}" for i in range(1, SWEEP_CHUNK + 1)]
    plan = "\n".join(r[0] for r in await pool.fetch(f"EXPLAIN {_SWEEP_SQL}", ids, "cve"))
    # the changed doc ids drive the loop...
    assert "Function Scan on unnest" in plan, plan
    # ...and each one descends the index instead of the table being read whole
    assert "idx_observables_type_value" in plan, plan
    assert "Seq Scan on observables" not in plan, plan
    # NB: no assertion on the verdicts LATERAL. `verdicts` holds one row in this
    # test, where a scan+sort genuinely IS the cheaper plan; asserting otherwise
    # would test Postgres's arithmetic rather than our query. The probe shows it
    # taking idx_verdicts_ws_obs at 22k verdict rows.


async def test_an_unchunked_batch_would_scan_which_is_why_the_chunk_exists(
    pool, workspace_id, seeded_observables
):
    """The bound is the load-bearing decision, so pin what it buys.

    Ten times the shipped chunk on the same table drops the planner to a whole-
    table read — the ROADMAP-forbidden shape. Corrects the first reading of this
    EXPLAIN, which credited the join formulation: rewriting the query did not fix
    the scan (measured, the array spelling actually holds the index to a LARGER
    batch than the join). Chunking fixed it."""
    unchunked = [f"CVE-2019-{i:06d}" for i in range(1, SWEEP_CHUNK * 10 + 1)]
    plan = "\n".join(
        r[0] for r in await pool.fetch(f"EXPLAIN {_SWEEP_SQL}", unchunked, "cve")
    )
    assert "Seq Scan on observables" in plan, plan
    # and the shipped path never sends a batch that big
    assert SWEEP_CHUNK <= 50


async def test_a_full_sweep_chunk_is_one_query(pool, workspace_id):
    """The batching promise: a KEV release costs one query per SWEEP_CHUNK ids,
    never one per changed doc."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    calls: list[int] = []
    real_acquire = pool.acquire

    class CountingPool:
        def acquire(self, *a, **k):
            calls.append(1)
            return real_acquire(*a, **k)

    ids = [f"CVE-2026-{i:05d}" for i in range(SWEEP_CHUNK - 1)] + [CVE_A]
    hits = await sweep(CountingPool(), doc_ids=ids, feed="kev", change_kind="kev-added")
    assert len(calls) == 1  # SWEEP_CHUNK ids ⇒ exactly one round trip
    assert [h.value for h in hits if h.workspace_id == workspace_id] == [CVE_A]


async def test_the_scheduler_is_wired_to_the_retrohunt_sink(pool, settings):
    """S7 built the seam and defaulted it to NullSink; S14's job was to attach a
    consumer. Everything else in this file would pass with the sink unwired —
    the sweep would simply never run in production."""
    from auspex.ingest import IngestScheduler, NullSink

    class FakeKB:
        active = False

    scheduler = IngestScheduler.from_settings(settings, FakeKB(), pool)
    try:
        assert isinstance(scheduler._sink, RetroHuntSink)
        assert not isinstance(scheduler._sink, NullSink)
    finally:
        await scheduler.aclose()
