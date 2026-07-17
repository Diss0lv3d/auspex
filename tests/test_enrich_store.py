"""Enrichment persistence — S5, against live Postgres (compose dev DB).

Covers the upsert key (workspace, type, value), append-only verdict history,
"no signal ⇒ no verdict row", "skipped ⇒ not persisted at all", and D-008
workspace scoping. Each test provisions its own workspace and deletes it at
the end (cascades cover observables + verdicts).
"""

import asyncpg
import pytest

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
    return await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        name,
    )


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
