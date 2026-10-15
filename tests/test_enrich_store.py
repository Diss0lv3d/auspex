"""Enrichment persistence — S5, against live Postgres (compose dev DB).

Covers the upsert key (workspace, type, value), append-only verdict history,
"no signal ⇒ no verdict row", "skipped ⇒ not persisted at all", and D-008
workspace scoping. Each test provisions its own workspace and deletes it at
the end (cascades cover observables + verdicts).
"""

import asyncpg
import pytest
from _tenancy import ensure_workspace

from auspex.classify.observables import Observable, ObservableType, observable_id
from auspex.db import create_pool
from auspex.enrich.filters import PRIVATE_IP_SKIP
from auspex.enrich.store import persist_enrichment
from auspex.enrich.types import (
    EnrichmentOutcome,
    ObservableEnrichment,
    ProviderSignal,
    VerdictLabel,
)


def obs(type_: ObservableType, value: str) -> Observable:
    return Observable(type=type_, value=value, obs_id=observable_id(type_, value), defanged=False)


def malicious_item(value: str = "203.0.113.7") -> ObservableEnrichment:
    return ObservableEnrichment(
        observable=obs(ObservableType.IPV4, value),
        signals=(
            ProviderSignal(
                "ThreatFox",
                VerdictLabel.MALICIOUS,
                0.75,
                "known IOC: Cobalt Strike",
                evidence={"malware": "Cobalt Strike"},
            ),
        ),
    )


@pytest.fixture
async def pool(client, settings):
    pool = await create_pool(settings.database_url, retries=2, delay=0.5)
    yield pool
    await pool.close()


async def _get_or_create_workspace(pool, name: str):
    """Upsert-get: a leaked row from a crashed earlier run must not lock every
    later run out via the UNIQUE(name) index (S5 review finding)."""
    return await ensure_workspace(pool, name)


@pytest.fixture
async def workspace_id(pool):
    ws = await _get_or_create_workspace(pool, "t-enrich")
    yield ws
    await pool.execute("DELETE FROM workspaces WHERE id = $1", ws)


async def test_persist_writes_observable_and_verdict_with_decay_fields(pool, workspace_id):
    written = await persist_enrichment(
        pool, workspace_id, EnrichmentOutcome(items=(malicious_item(),))
    )
    assert written == 1
    row = await pool.fetchrow(
        """
        SELECT o.obs_id, o.type, o.value, v.label, v.confidence_at_write,
               v.half_life_days, v.floor, v.source, v.details
        FROM observables o JOIN verdicts v ON v.observable_id = o.id
        WHERE o.workspace_id = $1
        """,
        workspace_id,
    )
    assert row["type"] == "ipv4" and row["value"] == "203.0.113.7"
    assert row["obs_id"] == observable_id(ObservableType.IPV4, "203.0.113.7")
    assert row["label"] == "malicious"
    assert row["confidence_at_write"] == pytest.approx(0.75)
    assert row["half_life_days"] == 14.0  # D-017 default for IPs
    assert row["floor"] == 0.0
    assert row["source"] == "enrichment:ThreatFox"
    assert "Cobalt Strike" in row["details"]


async def test_reseeing_a_value_bumps_last_seen_and_appends_a_verdict(pool, workspace_id):
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(malicious_item(),)))
    first = await pool.fetchrow(
        "SELECT id, first_seen, last_seen FROM observables WHERE workspace_id = $1", workspace_id
    )
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(malicious_item(),)))
    rows = await pool.fetch(
        "SELECT id, first_seen, last_seen FROM observables WHERE workspace_id = $1", workspace_id
    )
    assert len(rows) == 1 and rows[0]["id"] == first["id"]  # upsert, not duplicate
    assert rows[0]["first_seen"] == first["first_seen"]
    assert rows[0]["last_seen"] > first["last_seen"]
    verdict_count = await pool.fetchval(
        "SELECT count(*) FROM verdicts WHERE workspace_id = $1", workspace_id
    )
    assert verdict_count == 2  # append-only history (Living Verdicts substrate)


async def test_no_signals_records_the_observable_but_no_verdict(pool, workspace_id):
    quiet = ObservableEnrichment(observable=obs(ObservableType.SHA256, "c" * 64))
    written = await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(quiet,)))
    assert written == 0
    counts = await pool.fetchrow(
        "SELECT (SELECT count(*) FROM observables WHERE workspace_id = $1) AS obs,"
        " (SELECT count(*) FROM verdicts WHERE workspace_id = $1) AS verdicts",
        workspace_id,
    )
    assert counts["obs"] == 1 and counts["verdicts"] == 0


async def test_skipped_observables_are_not_persisted(pool, workspace_id):
    skipped = ObservableEnrichment(
        observable=obs(ObservableType.IPV4, "10.0.0.1"), skip_reason=PRIVATE_IP_SKIP
    )
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(skipped,)))
    count = await pool.fetchval(
        "SELECT count(*) FROM observables WHERE workspace_id = $1", workspace_id
    )
    assert count == 0  # a row would imply an enrichment attempt that never happened


async def test_workspace_scoping_keeps_same_value_in_separate_rows(pool, workspace_id):
    other = await _get_or_create_workspace(pool, "t-enrich-other")
    try:
        for ws in (workspace_id, other):
            await persist_enrichment(pool, ws, EnrichmentOutcome(items=(malicious_item(),)))
        rows = await pool.fetch("SELECT workspace_id FROM observables WHERE value = '203.0.113.7'")
        assert {r["workspace_id"] for r in rows} == {workspace_id, other}
        cross = await pool.fetchval("SELECT count(*) FROM verdicts WHERE workspace_id = $1", other)
        assert cross == 1  # D-008: each workspace sees exactly its own verdict
    finally:
        await pool.execute("DELETE FROM workspaces WHERE id = $1", other)


async def test_persist_is_atomic_per_turn(pool, workspace_id, monkeypatch):
    """A failed verdict insert anywhere in the outcome rolls the whole turn
    back. synthesize() clamps its inputs, so the invalid verdict is injected
    below that sanitization to force the DB CHECK to fire mid-transaction."""
    from auspex.enrich import store as store_module
    from auspex.enrich.verdict import Verdict

    real_synthesize = store_module.synthesize

    def poisoned_synthesize(observable, signals):
        verdict = real_synthesize(observable, signals)
        if verdict is not None and observable.value == "198.51.100.9":
            return Verdict(
                label=verdict.label,
                confidence_at_write=5.0,  # violates the CHECK
                half_life_days=verdict.half_life_days,
                floor=verdict.floor,
                source=verdict.source,
            )
        return verdict

    monkeypatch.setattr(store_module, "synthesize", poisoned_synthesize)
    bad = malicious_item("198.51.100.9")
    with pytest.raises(asyncpg.CheckViolationError):
        await persist_enrichment(
            pool, workspace_id, EnrichmentOutcome(items=(malicious_item(), bad))
        )
    counts = await pool.fetchrow(
        "SELECT (SELECT count(*) FROM observables WHERE workspace_id = $1) AS obs,"
        " (SELECT count(*) FROM verdicts WHERE workspace_id = $1) AS verdicts",
        workspace_id,
    )
    assert counts["obs"] == 0 and counts["verdicts"] == 0


def context_only_item(value: str = "203.0.113.7") -> ObservableEnrichment:
    """InternetDB's open ports: exposure, not reputation (VerdictLabel.UNKNOWN
    at confidence 0.0). It is also what a lookup returns for most live IPs while
    the reputation sources are silent or down."""
    return ObservableEnrichment(
        observable=obs(ObservableType.IPV4, value),
        signals=(
            ProviderSignal("InternetDB", VerdictLabel.UNKNOWN, 0.0, "open ports 80", evidence={}),
        ),
    )


@pytest.mark.parametrize(
    "known", [VerdictLabel.MALICIOUS, VerdictLabel.SUSPICIOUS, VerdictLabel.BENIGN]
)
async def test_a_context_only_lookup_leaves_a_known_verdict_standing(pool, workspace_id, known):
    """S29 review of D-049, reproduced live. A lookup that only found context
    (or ran while ThreatFox was down) wrote an `unknown` verdict over the
    stored one: malicious → unknown, with a flip and the old verdict's watchers
    retired. D-055 states the opposite, "today it keeps its verdict and
    decays", and D-017 changes labels on new evidence, which silence is not.
    Every agent lookup records since D-049, so this reached every chat turn."""
    first = malicious_item()
    first = ObservableEnrichment(
        observable=first.observable,
        signals=(ProviderSignal("ThreatFox", known, 0.75, "seen", evidence={}),),
    )
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(first,)))

    written = await persist_enrichment(
        pool, workspace_id, EnrichmentOutcome(items=(context_only_item(),))
    )

    assert written == 0
    labels = await pool.fetch(
        "SELECT label FROM verdicts WHERE workspace_id = $1 ORDER BY created_at", workspace_id
    )
    assert [r["label"] for r in labels] == [known.value]
    assert await pool.fetchval(
        "SELECT count(*) FROM verdict_flips WHERE workspace_id = $1", workspace_id
    ) == 0
    assert await pool.fetchval(
        "SELECT last_seen > first_seen FROM observables WHERE workspace_id = $1", workspace_id
    )  # the sighting itself is still recorded


async def test_a_first_context_only_lookup_still_records_unknown(pool, workspace_id):
    """What D-055 kept: an address with no earlier belief gets its `unknown`
    row, so a later malicious answer is a flip the timeline can show. Only an
    `unknown` that would REPLACE a known label is dropped."""
    written = await persist_enrichment(
        pool, workspace_id, EnrichmentOutcome(items=(context_only_item(),))
    )
    assert written == 1
    await persist_enrichment(pool, workspace_id, EnrichmentOutcome(items=(malicious_item(),)))
    assert await pool.fetchval(
        "SELECT from_label || '>' || to_label FROM verdict_flips WHERE workspace_id = $1",
        workspace_id,
    ) == "unknown>malicious"
