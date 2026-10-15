"""Falsification watchers — S15, against live Postgres (compose dev DB).

Covers the derivation vocabulary, registration inside the verdict transaction,
supersession, the ingest-side indexed join, the enrichment-side escalation
check, the honesty rail (a satisfied watcher NEVER writes a verdict), the
upgraded S14 re-open event, and D-008 tenancy on every read and write.

Zero LLM anywhere — the whole path is derivation, joins and events.

Each test provisions its own workspace and deletes it at the end (cascades cover
observables, verdicts, watchers, matches and flips).
"""

import asyncio

import pytest
from _tenancy import ensure_workspace

from auspex.classify.observables import Observable, ObservableType, observable_id
from auspex.db import create_pool
from auspex.enrich.store import persist_enrichment
from auspex.enrich.types import (
    EnrichmentOutcome,
    ObservableEnrichment,
    ProviderSignal,
    VerdictLabel,
)
from auspex.enrich.verdict import synthesize
from auspex.ingest.events import DocChange
from auspex.retrohunt import RetroHuntSink, list_matches
from auspex.retrohunt.store import _MATCHES_SQL, SWEEP_CHUNK
from auspex.watchers import (
    CHECKED_ON_ENRICHMENT,
    CHECKED_ON_INGEST,
    SATISFIED_BY_CHANGE,
    FanoutSink,
    WatcherKind,
    WatcherSink,
    check_documents,
    conditions_for,
    list_watchers,
)
from auspex.watchers.store import _CHECK_SQL

CVE_A = "CVE-2026-77001"
CVE_B = "CVE-2026-77002"
HASH_A = "a" * 64


def cve_obs(value: str) -> Observable:
    return Observable(
        type=ObservableType.CVE,
        value=value,
        obs_id=observable_id(ObservableType.CVE, value),
        defanged=False,
    )


def hash_obs(value: str) -> Observable:
    return Observable(
        type=ObservableType.SHA256,
        value=value,
        obs_id=observable_id(ObservableType.SHA256, value),
        defanged=False,
    )


def item(
    observable: Observable,
    label: VerdictLabel = VerdictLabel.SUSPICIOUS,
    provider: str = "TestProvider",
) -> ObservableEnrichment:
    return ObservableEnrichment(
        observable=observable,
        signals=(ProviderSignal(provider, label, 0.6, "seen", evidence={}),),
    )


def cve_item(value: str, label: VerdictLabel = VerdictLabel.SUSPICIOUS):
    return item(cve_obs(value), label)


@pytest.fixture
async def pool(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    yield pool
    await pool.close()


async def _workspace(pool, name: str):
    return await ensure_workspace(pool, name)


@pytest.fixture
async def workspace_id(pool):
    ws = await _workspace(pool, "t-watchers")
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


@pytest.fixture
async def other_workspace_id(pool):
    ws = await _workspace(pool, "t-watchers-other")
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


# -- the vocabulary ------------------------------------------------------------


def test_every_kind_is_owned_by_exactly_one_checker():
    """A registered watcher nobody evaluates is worse than no watcher: it reads
    as coverage. The partition is asserted, not documented."""
    all_kinds = set(WatcherKind)
    assert CHECKED_ON_INGEST | CHECKED_ON_ENRICHMENT == all_kinds
    assert not (CHECKED_ON_INGEST & CHECKED_ON_ENRICHMENT)
    # Every ingest-checked kind must be reachable from a real DocChange kind.
    assert set(SATISFIED_BY_CHANGE.values()) == CHECKED_ON_INGEST


def test_a_suspicious_cve_commits_to_kev_listing_and_its_record():
    obs = cve_obs(CVE_A)
    signals = (ProviderSignal("OTX", VerdictLabel.SUSPICIOUS, 0.6, "seen"),)
    verdict = synthesize(obs, signals)
    kinds = {c.kind for c in conditions_for(obs, verdict, signals)}
    assert kinds == {
        WatcherKind.KEV_LISTING,
        WatcherKind.RECORD_WITHDRAWN,
        WatcherKind.PROVIDER_ESCALATION,
    }


def test_a_malicious_cve_does_not_pretend_kev_would_falsify_it():
    """KEV AGREES with a malicious verdict. Registering a watcher for it would
    manufacture a self-check the platform does not actually perform — the count
    would look better and mean less."""
    obs = cve_obs(CVE_A)
    signals = (ProviderSignal("OTX", VerdictLabel.MALICIOUS, 0.9, "seen"),)
    verdict = synthesize(obs, signals)
    kinds = {c.kind for c in conditions_for(obs, verdict, signals)}
    assert WatcherKind.KEV_LISTING not in kinds
    assert WatcherKind.PROVIDER_ESCALATION not in kinds
    # The record can still be withdrawn — that falsifies the BASIS, not the label.
    assert kinds == {WatcherKind.RECORD_WITHDRAWN}


def test_a_non_cve_observable_gets_only_the_provider_claim():
    obs = hash_obs(HASH_A)
    signals = (ProviderSignal("ThreatFox", VerdictLabel.BENIGN, 0.4, "no data"),)
    verdict = synthesize(obs, signals)
    conditions = conditions_for(obs, verdict, signals)
    assert [c.kind for c in conditions] == [WatcherKind.PROVIDER_ESCALATION]
    # The claim is about the sources that ANSWERED, never about silence at large.
    assert "ThreatFox" in conditions[0].claim


def test_the_vocabulary_can_describe_the_s14_flip():
    """The S15 prompt's test of this vocabulary: S14's live flip was a
    `suspicious` CVE that became `malicious` after the CVE entered KEV. Both
    halves of what actually happened must be expressible as conditions the
    earlier verdict would have registered."""
    obs = cve_obs(CVE_A)
    signals = (ProviderSignal("OTX", VerdictLabel.SUSPICIOUS, 0.55, "seen"),)
    conditions = conditions_for(obs, synthesize(obs, signals), signals)
    by_kind = {c.kind: c for c in conditions}
    assert CVE_A in by_kind[WatcherKind.KEV_LISTING].claim
    assert "not known to be exploited" in by_kind[WatcherKind.KEV_LISTING].claim
    assert "suspicious" in by_kind[WatcherKind.PROVIDER_ESCALATION].claim


def test_the_package_imports_before_enrichment_does():
    """Caught by a probe script, not by this suite — which is the point.

    `auspex.watchers` needs enrichment's label vocabulary and `enrich.store`
    needs watchers to register conditions: a package-level cycle that resolves
    fine whenever `auspex.enrich` is imported first, as the app and every test
    here happen to do. `import auspex.watchers` on its own raised ImportError.

    Same class as S14's packaging defect — correct by accident of order rather
    than by construction — so it gets the same treatment: a subprocess with a
    clean interpreter, asserting the property directly instead of inheriting a
    lucky import order from whatever ran before it."""
    import subprocess  # noqa: S404 — fixed argv, no shell, no external input
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as elsewhere:
        for first in ("auspex.watchers", "auspex.watchers.store", "auspex.enrich"):
            proc = subprocess.run(  # noqa: S603 — argv is a literal list
                [sys.executable, "-c", f"import {first}"],
                capture_output=True,
                text=True,
                # Never the source root: running from there puts the tree on
                # sys.path and would hide exactly what this asserts.
                cwd=elsewhere,
                check=False,
            )
            assert proc.returncode == 0, f"import {first} failed:\n{proc.stderr}"


# -- registration --------------------------------------------------------------


async def test_writing_a_verdict_registers_its_falsifiers(pool, workspace_id):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    watchers = await list_watchers(pool, workspace_id=workspace_id)
    assert {w.kind for w in watchers} == {
        WatcherKind.KEV_LISTING.value,
        WatcherKind.RECORD_WITHDRAWN.value,
        WatcherKind.PROVIDER_ESCALATION.value,
    }
    assert all(w.status == "open" for w in watchers)
    assert all(w.verdict_label == "suspicious" for w in watchers)


async def test_watchers_are_written_in_the_verdict_transaction(pool, workspace_id):
    """A watcher that outlived a rolled-back verdict would be watching for a
    claim nobody made. Driven by making the flip writer raise mid-transaction."""
    from auspex.enrich import store as enrich_store

    async def boom(*a, **k):
        raise RuntimeError("provider blew up after the verdict insert")

    original = enrich_store.record_flip_if_changed
    enrich_store.record_flip_if_changed = boom
    try:
        with pytest.raises(RuntimeError):
            await persist_enrichment(
                pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),))
            )
    finally:
        enrich_store.record_flip_if_changed = original

    assert await pool.fetchval(
        "SELECT count(*) FROM verdicts WHERE workspace_id = $1", workspace_id
    ) == 0
    assert await list_watchers(pool, workspace_id=workspace_id) == []


async def test_a_new_verdict_supersedes_the_previous_verdicts_claims(pool, workspace_id):
    """Claims belong to a verdict. When the verdict is replaced its claims are
    SUPERSEDED, never deleted — 'we were watching for this and stopped' is how
    you find a question that was dropped instead of answered."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    first = {w.id for w in await list_watchers(pool, workspace_id=workspace_id)}
    await persist_enrichment(
        pool,
        workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.BENIGN),)),
    )
    everything = await list_watchers(pool, workspace_id=workspace_id, status=None)
    superseded = {w.id for w in everything if w.status == "superseded"}
    still_open = [w for w in everything if w.status == "open"]
    assert first <= superseded | {w.id for w in still_open if w.id in first}
    assert superseded, "the replaced verdict's claims must be retired"
    assert all(w.verdict_label == "benign" for w in still_open)


async def test_re_persisting_the_same_verdict_does_not_duplicate_claims(pool, workspace_id):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    open_now = await list_watchers(pool, workspace_id=workspace_id, status="open")
    assert len(open_now) == len({w.kind for w in open_now})
    # The trail keeps both generations: superseded is a record, not a delete.
    assert len(await list_watchers(pool, workspace_id=workspace_id, status=None)) == 6


# -- the ingest-side check (indexed join) --------------------------------------


async def test_a_kev_listing_satisfies_the_watcher_it_contradicts(pool, workspace_id):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await WatcherSink(pool).emit([DocChange(CVE_A, "kev", "kev-added")])

    everything = await list_watchers(pool, workspace_id=workspace_id, status=None)
    by_kind = {w.kind: w for w in everything}
    kev = by_kind[WatcherKind.KEV_LISTING.value]
    assert kev.status == "satisfied"
    assert kev.satisfied_by == CVE_A
    assert kev.satisfied_at is not None
    # Only the contradicted claim moves. The record was not withdrawn, and no
    # provider spoke, so those claims still stand.
    assert by_kind[WatcherKind.RECORD_WITHDRAWN.value].status == "open"
    assert by_kind[WatcherKind.PROVIDER_ESCALATION.value].status == "open"


async def test_a_withdrawal_satisfies_only_the_record_claim(pool, workspace_id):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await WatcherSink(pool).emit([DocChange(CVE_A, "nvd-delta", "deleted")])
    by_kind = {
        w.kind: w
        for w in await list_watchers(pool, workspace_id=workspace_id, status=None)
    }
    assert by_kind[WatcherKind.RECORD_WITHDRAWN.value].status == "satisfied"
    assert by_kind[WatcherKind.KEV_LISTING.value].status == "open"


async def test_a_satisfied_watcher_never_writes_a_verdict(pool, workspace_id):
    """The rail, and it matters MORE here than for a retro-hunt match: a fired
    watcher is the platform's own prediction coming true, which is the moment it
    would feel safest to skip the analyst."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    before = await pool.fetch(
        "SELECT id, label FROM verdicts WHERE workspace_id = $1 ORDER BY created_at",
        workspace_id,
    )
    await WatcherSink(pool).emit([DocChange(CVE_A, "kev", "kev-added")])
    after = await pool.fetch(
        "SELECT id, label FROM verdicts WHERE workspace_id = $1 ORDER BY created_at",
        workspace_id,
    )
    assert [(r["id"], r["label"]) for r in after] == [(r["id"], r["label"]) for r in before]
    assert await pool.fetchval(
        "SELECT count(*) FROM verdict_flips WHERE workspace_id = $1", workspace_id
    ) == 0


async def test_re_emitting_the_same_change_is_not_news_twice(pool, workspace_id):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    change = [DocChange(CVE_A, "kev", "kev-added")]
    await WatcherSink(pool).emit(change)
    satisfied_at = [
        w.satisfied_at
        for w in await list_watchers(pool, workspace_id=workspace_id, status="satisfied")
        if w.kind == WatcherKind.KEV_LISTING.value
    ][0]
    await WatcherSink(pool).emit(change)
    again = [
        w.satisfied_at
        for w in await list_watchers(pool, workspace_id=workspace_id, status="satisfied")
        if w.kind == WatcherKind.KEV_LISTING.value
    ][0]
    assert again == satisfied_at, "a re-read of the catalogue must not restamp it"


async def test_the_check_is_one_indexed_join_per_chunk(pool, workspace_id):
    """ROADMAP S15 constraint, same as S14: never a query per change. Counts
    round trips rather than trusting the loop's shape."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    calls = []
    real_acquire = pool.acquire

    class CountingPool:
        def __getattr__(self, name):
            return getattr(pool, name)

        def acquire(self, *a, **k):
            calls.append(1)
            return real_acquire(*a, **k)

    ids = [f"CVE-2026-{i:05d}" for i in range(SWEEP_CHUNK - 1)] + [CVE_A]
    hits = await check_documents(
        CountingPool(), doc_ids=ids, kind=WatcherKind.KEV_LISTING
    )
    assert len(calls) == 1
    assert [h.doc_id for h in hits if h.workspace_id == workspace_id] == [CVE_A]


PLAN_SEED_ROWS = 25_000  # the S14 crossover size, so the two plans are comparable


@pytest.fixture
async def seeded_watchers(pool, workspace_id):
    """A `watchers` table big enough for the planner's choice to be meaningful.

    Below the crossover a scan genuinely IS cheaper, and asserting otherwise
    tests Postgres's arithmetic rather than our query — the S15 Step-0 review
    caught S14's comment overclaiming exactly that. One observable per watcher,
    because the real table grows that way and a thousand watchers on one row
    would flatter the index.

    VACUUM after cleanup, not just ANALYZE: seeding and dropping 25k rows leaves
    the table bloated, and the planner costs a scan in PAGES (STATE.md host
    note)."""
    await pool.execute(
        """
        WITH obs AS (
            INSERT INTO observables (workspace_id, obs_id, type, value)
            SELECT $1, 'cve-wplan-' || i, 'cve', 'CVE-2018-' || lpad(i::text, 6, '0')
            FROM generate_series(1, $2) AS s(i)
            ON CONFLICT (workspace_id, type, value) DO NOTHING
            RETURNING id
        ), v AS (
            INSERT INTO verdicts (workspace_id, observable_id, label,
                confidence_at_write, half_life_days, floor, source)
            SELECT $1, obs.id, 'suspicious', 0.5, 365.0, 0.0, 'enrichment:seed'
            FROM obs RETURNING id, observable_id
        )
        INSERT INTO watchers (workspace_id, observable_id, verdict_id, kind, claim)
        SELECT $1, v.observable_id, v.id, 'kev_listing', 'seeded plan fixture'
        FROM v
        """,
        workspace_id,
        PLAN_SEED_ROWS,
    )
    await pool.execute("VACUUM (ANALYZE) watchers")
    await pool.execute("VACUUM (ANALYZE) observables")
    yield
    await pool.execute(
        "DELETE FROM observables WHERE workspace_id = $1 AND obs_id LIKE 'cve-wplan-%'",
        workspace_id,
    )
    await pool.execute("VACUUM (ANALYZE) watchers")
    await pool.execute("VACUUM (ANALYZE) observables")


async def test_the_check_query_plans_on_indexes_not_a_table_scan(
    pool, workspace_id, seeded_watchers
):
    """ROADMAP S15 constraint: "indexed join, never a scan per change", pinned
    at the shipped chunk size on a table where a scan would be a real cost.

    A watcher check that scans `watchers` would degrade with every verdict ever
    written — including the satisfied and superseded rows that accumulate
    forever and are never joined against, which is what the PARTIAL index on
    status='open' exists to skip. The plan is probed rather than assumed:
    docs/probes/2026-08-09-s15-watchers-explain.md."""
    ids = [f"CVE-2018-{i:06d}" for i in range(1, SWEEP_CHUNK + 1)]
    plan = "\n".join(
        r[0]
        for r in await pool.fetch(
            f"EXPLAIN {_CHECK_SQL}", ids, "cve", WatcherKind.KEV_LISTING.value
        )
    )
    # the changed doc ids drive the loop...
    assert "Function Scan on unnest" in plan, plan
    # ...each probes the observables index...
    assert "idx_observables_type_value" in plan, plan
    assert "Seq Scan on observables" not in plan, plan
    # ...and each match probes the PARTIAL watcher index, never the whole table
    assert "idx_watchers_open_obs_kind" in plan, plan
    assert "Seq Scan on watchers" not in plan, plan


@pytest.fixture
async def seeded_satisfied(pool, workspace_id):
    """Satisfied watchers and their re-open events, at a size where scanning
    would cost something. This is the population that grows WITHOUT BOUND — a
    satisfied watcher is never revisited and never deleted — so the read that
    derives a claim from it is the one that must not degrade over a workspace's
    lifetime."""
    await pool.execute(
        """
        WITH obs AS (
            INSERT INTO observables (workspace_id, obs_id, type, value)
            SELECT $1, 'cve-splan-' || i, 'cve', 'CVE-2017-' || lpad(i::text, 6, '0')
            FROM generate_series(1, $2) AS s(i)
            ON CONFLICT (workspace_id, type, value) DO NOTHING
            RETURNING id, value
        ), v AS (
            INSERT INTO verdicts (workspace_id, observable_id, label,
                confidence_at_write, half_life_days, floor, source)
            SELECT $1, obs.id, 'suspicious', 0.5, 365.0, 0.0, 'enrichment:seed'
            FROM obs RETURNING id, observable_id
        ), w AS (
            -- Chained through RETURNING, never re-read from `observables`: rows
            -- a data-modifying CTE inserts are invisible to the statement's own
            -- table scans, so a join here would silently seed nothing.
            INSERT INTO watchers (workspace_id, observable_id, verdict_id, kind,
                claim, status, satisfied_at, satisfied_by, satisfied_change_kind)
            SELECT $1, v.observable_id, v.id, 'kev_listing', 'seeded plan fixture',
                   'satisfied', clock_timestamp(), obs.value, 'kev-added'
            FROM v JOIN obs ON obs.id = v.observable_id
            RETURNING observable_id, satisfied_by
        )
        INSERT INTO retrohunt_matches (workspace_id, observable_id, doc_id, feed,
            change_kind, verdict_label)
        SELECT $1, w.observable_id, w.satisfied_by, 'kev', 'kev-added', 'suspicious'
        FROM w
        ON CONFLICT DO NOTHING
        """,
        workspace_id,
        PLAN_SEED_ROWS,
    )
    await pool.execute("VACUUM (ANALYZE) watchers")
    await pool.execute("VACUUM (ANALYZE) observables")
    await pool.execute("VACUUM (ANALYZE) retrohunt_matches")
    yield
    await pool.execute(
        "DELETE FROM observables WHERE workspace_id = $1 AND obs_id LIKE 'cve-splan-%'",
        workspace_id,
    )
    await pool.execute("VACUUM (ANALYZE) watchers")
    await pool.execute("VACUUM (ANALYZE) observables")
    await pool.execute("VACUUM (ANALYZE) retrohunt_matches")


async def test_deriving_the_claim_plans_on_the_satisfied_index(
    pool, workspace_id, seeded_satisfied
):
    """S16 Step 0 traded a written link for a derived one, and a derivation that
    scans is how a correctness fix becomes a performance defect. The claim is
    resolved per event on screen through the PARTIAL status='satisfied' index,
    never by reading the satisfied population."""
    # Same arguments the default lens passes: no `since`, no observable filter
    # (S16 added both to this one query rather than forking it).
    plan = "\n".join(
        r[0]
        for r in await pool.fetch(
            f"EXPLAIN {_MATCHES_SQL}", workspace_id, "open", 50, None, None
        )
    )
    assert "idx_watchers_satisfied_obs" in plan, plan
    assert "Seq Scan on watchers" not in plan, plan
    # The outer half is S14's and must stay indexed too.
    assert "idx_retrohunt_matches_ws_status" in plan, plan
    assert "Seq Scan on retrohunt_matches" not in plan, plan


# -- the enrichment-side check -------------------------------------------------


async def test_a_more_severe_label_satisfies_the_provider_claim(pool, workspace_id):
    """"No connected source rates this worse than suspicious" is falsified the
    moment one does."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(
        pool,
        workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
    )
    everything = await list_watchers(pool, workspace_id=workspace_id, status=None)
    escalations = [
        w for w in everything if w.kind == WatcherKind.PROVIDER_ESCALATION.value
    ]
    satisfied = [w for w in escalations if w.status == "satisfied"]
    assert len(satisfied) == 1, [w.status for w in escalations]
    assert satisfied[0].verdict_label == "suspicious"  # the claim that was wrong
    assert satisfied[0].satisfied_by.startswith("flip:")


async def test_a_de_escalation_falsifies_nothing_it_claimed(pool, workspace_id):
    """`suspicious → benign` disagrees with the old verdict but not with its
    CLAIM, which was only ever about nothing rating it WORSE. Severity, not
    inequality."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(
        pool,
        workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.BENIGN),)),
    )
    everything = await list_watchers(pool, workspace_id=workspace_id, status=None)
    escalations = [
        w for w in everything if w.kind == WatcherKind.PROVIDER_ESCALATION.value
    ]
    assert not [w for w in escalations if w.status == "satisfied"]
    assert {w.status for w in escalations} == {"open", "superseded"}


async def test_a_satisfied_claim_survives_the_verdict_that_replaced_it(pool, workspace_id):
    """Supersession must not erase a claim that was CONTRADICTED — that event is
    the whole point, and it happens in the same transaction that retires it."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(
        pool,
        workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
    )
    satisfied = await list_watchers(pool, workspace_id=workspace_id, status="satisfied")
    assert [w.kind for w in satisfied] == [WatcherKind.PROVIDER_ESCALATION.value]


# -- the upgraded re-open event ------------------------------------------------


async def test_a_satisfied_watcher_upgrades_the_s14_event(pool, workspace_id):
    """One fact, one event. The satisfied claim rides the retro-hunt match for
    the same doc instead of minting a second notification."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    matches = [
        m for m in await list_matches(pool, workspace_id=workspace_id) if m.doc_id == CVE_A
    ]
    assert len(matches) == 1
    assert matches[0].falsified_claim is not None
    assert "not known to be exploited" in matches[0].falsified_claim


async def test_a_match_without_a_registered_claim_says_so(pool, workspace_id):
    """A malicious CVE registers no KEV watcher, so a KEV listing still produces
    a re-open event — but it must not claim to have falsified anything."""
    await persist_enrichment(
        pool,
        workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
    )
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    matches = [
        m for m in await list_matches(pool, workspace_id=workspace_id) if m.doc_id == CVE_A
    ]
    assert len(matches) == 1
    assert matches[0].falsified_claim is None


async def test_the_link_survives_the_sinks_running_in_either_order(pool, workspace_id):
    """S16 Step 0. S15 wrote the link from the watcher side into the match row,
    so it only landed if the retro-hunt sink had already written that row —
    which was true of the order `FanoutSink` is constructed in and of nothing
    else. Executed then: reversing these two arguments dropped `falsifies`
    silently. The claim is derived now, so neither order is privileged."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await FanoutSink(WatcherSink(pool), RetroHuntSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    matches = [
        m for m in await list_matches(pool, workspace_id=workspace_id) if m.doc_id == CVE_A
    ]
    assert len(matches) == 1
    assert matches[0].falsified_claim is not None
    assert "not known to be exploited" in matches[0].falsified_claim


async def test_the_link_survives_a_sweep_that_failed_a_whole_cycle_earlier(
    pool, workspace_id
):
    """The same defect without any reordering, which is why the fix could not be
    "enforce the order". The retro-hunt sink is DESIGNED to swallow its failures
    so ingest outlives them, so the watcher can legitimately be satisfied in a
    cycle that recorded no match at all. S15 never retried the link — the next
    cycle found the watcher already satisfied and skipped it — so one survivable
    sweep failure erased the claim permanently."""

    class BrokenSweep:
        async def emit(self, changes):
            raise RuntimeError("sweep down")

    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await FanoutSink(BrokenSweep(), WatcherSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    assert not [m for m in await list_matches(pool, workspace_id=workspace_id)]

    # The next healthy cycle writes the match. The watcher was satisfied a cycle
    # ago and is never re-examined; the claim must still reach the analyst.
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    matches = [
        m for m in await list_matches(pool, workspace_id=workspace_id) if m.doc_id == CVE_A
    ]
    assert len(matches) == 1
    assert matches[0].falsified_claim is not None


async def test_two_verdicts_satisfied_by_one_doc_resolve_to_the_newest_claim(
    pool, workspace_id
):
    """The pairing is not unique over time: a later verdict registers its own
    watcher of the same kind, and a re-emitted change satisfies that one too.
    Deriving the claim must pick deterministically rather than return whichever
    row the planner reached first."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    # A later verdict with a different label — so its claim reads differently —
    # registers a fresh kev_listing watcher, which the same doc then satisfies.
    await persist_enrichment(
        pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.BENIGN),))
    )
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    satisfied = [
        w
        for w in await list_watchers(pool, workspace_id=workspace_id, status="satisfied")
        if w.kind == WatcherKind.KEV_LISTING.value
    ]
    assert len(satisfied) == 2  # both verdicts' claims were contradicted
    matches = [
        m for m in await list_matches(pool, workspace_id=workspace_id) if m.doc_id == CVE_A
    ]
    assert len(matches) == 1  # still ONE event for one fact
    assert "benign" in matches[0].falsified_claim  # the newest, every time


async def test_an_escalation_satisfaction_never_links_a_doc_event(pool, workspace_id):
    """`check_escalation` is satisfied by a flip, not by a document, so it must
    not be picked up by a re-open event that happens to touch the same
    observable. Its `satisfied_by` is a flip id and its change kind is NULL."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await persist_enrichment(
        pool,
        workspace_id,
        EnrichmentOutcome(items=(cve_item(CVE_A, VerdictLabel.MALICIOUS),)),
    )
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    row = await pool.fetchrow(
        "SELECT satisfied_by, satisfied_change_kind FROM watchers"
        " WHERE workspace_id = $1 AND kind = $2 AND status = 'satisfied'",
        workspace_id,
        WatcherKind.PROVIDER_ESCALATION.value,
    )
    assert row["satisfied_by"].startswith("flip:")
    assert row["satisfied_change_kind"] is None
    # The malicious verdict registered no kev_listing watcher, so this event has
    # no claim to carry — and must not borrow the escalation one.
    matches = [
        m for m in await list_matches(pool, workspace_id=workspace_id) if m.doc_id == CVE_A
    ]
    assert matches[0].falsified_claim is None


async def test_one_sink_failing_does_not_sink_the_other(pool, workspace_id):
    """Ingest survives its consumers, and so does each consumer."""

    class Broken:
        async def emit(self, changes):
            raise RuntimeError("consumer down")

    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await FanoutSink(Broken(), WatcherSink(pool)).emit(
        [DocChange(CVE_A, "kev", "kev-added")]
    )
    satisfied = await list_watchers(pool, workspace_id=workspace_id, status="satisfied")
    assert [w.kind for w in satisfied] == [WatcherKind.KEV_LISTING.value]


# -- tenancy (D-008) -----------------------------------------------------------


async def test_watchers_are_workspace_scoped(pool, workspace_id, other_workspace_id):
    for ws in (workspace_id, other_workspace_id):
        await persist_enrichment(pool, ws, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    mine = await list_watchers(pool, workspace_id=workspace_id)
    theirs = await list_watchers(pool, workspace_id=other_workspace_id)
    assert {w.id for w in mine}.isdisjoint({w.id for w in theirs})
    assert all(w.workspace_id == workspace_id for w in mine)


async def test_the_global_check_satisfies_each_tenants_own_watcher(
    pool, workspace_id, other_workspace_id
):
    """The join runs across workspaces (feeds are platform-global) exactly as
    the S14 sweep does. Each tenant's own claim must be the one that moves."""
    for ws in (workspace_id, other_workspace_id):
        await persist_enrichment(pool, ws, EnrichmentOutcome(items=(cve_item(CVE_A),)))
    await WatcherSink(pool).emit([DocChange(CVE_A, "kev", "kev-added")])
    for ws in (workspace_id, other_workspace_id):
        satisfied = await list_watchers(pool, workspace_id=ws, status="satisfied")
        assert [w.kind for w in satisfied] == [WatcherKind.KEV_LISTING.value]
        assert all(w.workspace_id == ws for w in satisfied)


async def test_concurrent_enrichments_register_one_set_of_claims(pool, workspace_id):
    """Same serialization the S15 Step-0 review pinned for flips: the
    observables row lock orders these, so two racing enrichments must not leave
    two open claims of one kind."""
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_A),)))
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
    open_now = await list_watchers(pool, workspace_id=workspace_id, status="open")
    assert len(open_now) == len({w.kind for w in open_now})


# -- the analyst surface -------------------------------------------------------

ROUTE_CVE = "CVE-2026-77009"
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
        ws,
        ROUTE_CVE,
    )
    yield ws
    await pool.execute(
        "DELETE FROM observables WHERE workspace_id = $1 AND type = 'cve' AND value = $2",
        ws,
        ROUTE_CVE,
    )


async def test_watchers_route_reports_claims_and_who_checks_them(pool, client, route_ws):
    await persist_enrichment(pool, route_ws, EnrichmentOutcome(items=(cve_item(ROUTE_CVE),)))
    resp = client.get("/api/watchers", headers=_hdr(client))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    mine = [w for w in body["watchers"] if w["observable"]["value"] == ROUTE_CVE]
    assert len(mine) == 3
    kev = [w for w in mine if w["kind"] == WatcherKind.KEV_LISTING.value][0]
    assert kev["status"] == "open"
    assert kev["checked_by"] == "ingest"
    assert kev["verdict"]["label"] == "suspicious"
    assert ROUTE_CVE in kev["claim"]
    escalation = [
        w for w in mine if w["kind"] == WatcherKind.PROVIDER_ESCALATION.value
    ][0]
    assert escalation["checked_by"] == "enrichment"
    assert set(body["kinds"]) == {k.value for k in WatcherKind}
    assert "never a re-classification" in body["note"]


async def test_watchers_route_shows_a_satisfied_claim_and_its_event(pool, client, route_ws):
    await persist_enrichment(pool, route_ws, EnrichmentOutcome(items=(cve_item(ROUTE_CVE),)))
    await FanoutSink(RetroHuntSink(pool), WatcherSink(pool)).emit(
        [DocChange(ROUTE_CVE, "kev", "kev-added")]
    )
    satisfied = [
        w
        for w in client.get(
            "/api/watchers", params={"status": "satisfied"}, headers=_hdr(client)
        ).json()["watchers"]
        if w["observable"]["value"] == ROUTE_CVE
    ]
    assert [w["kind"] for w in satisfied] == [WatcherKind.KEV_LISTING.value]
    assert satisfied[0]["satisfied_by"] == ROUTE_CVE
    assert satisfied[0]["satisfied_at"] is not None

    # The same fact, on the S14 surface, as an upgraded re-open event.
    match = [
        m
        for m in client.get("/api/retrohunt/matches", headers=_hdr(client)).json()["matches"]
        if m["trigger_doc"] == ROUTE_CVE
    ][0]
    assert match["action"] == "re-examine"
    assert "not known to be exploited" in match["falsifies"]


async def test_watchers_route_requires_a_token(client):
    assert client.get("/api/watchers").status_code == 401


async def test_watchers_route_never_shows_another_workspaces_claims(
    pool, client, route_ws, workspace_id
):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(cve_item(CVE_B),)))
    body = client.get(
        "/api/watchers", params={"status": "all", "limit": 200}, headers=_hdr(client)
    ).json()
    assert not [w for w in body["watchers"] if w["observable"]["value"] == CVE_B]
