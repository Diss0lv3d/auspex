"""S12 /api/investigations — the zero-LLM ACH surface. Hermetic: the only
external system is the live dev Postgres (as for every route test); the one
lookup-execution test stubs the enrichment service on app.state. Created rows
are deleted in teardown (the conftest purge only cascades user-linked rows —
investigations hang off the workspace)."""

from uuid import uuid4

import asyncpg
import pytest

from auspex.enrich.types import (
    EnrichmentOutcome,
    ObservableEnrichment,
    ProviderSignal,
    VerdictLabel,
)

INV_EMAIL = "analyst@auspex.dev"  # in conftest TEST_EMAILS — purged at session end

ALERT_PASTE = (
    "CEF:0|Vendor|EDR|1.0|500|Beaconing detected|9|src=203.0.113.7 "
    "dst=evil-c2-server.biz cs1=powershell -enc SQBFAFgA "
    "fileHash=44d88612fea8a8f36de82e1278abb02f externalId=T1071"
)

EMAIL_PASTE = (
    'From: "PayPal Support" <security@paypa1.com>\n'
    "Reply-To: recover@account-verify.ru\n"
    "To: victim@acme.com\n"
    "Subject: verify your account\n"
    "Authentication-Results: mx.acme.com; spf=fail; dkim=fail; dmarc=fail\n"
    "Received: from mail.paypa1.com by mx.acme.com\n\n"
    "Click http://paypa1.com/verify within 24 hours."
)

_created: list[str] = []
_stub_values: list[tuple[str, str]] = []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(settings):
    """Delete investigations (cascades hypotheses + ach_evidence) and any
    stub-enriched observables (cascades their verdicts) this module created."""
    yield
    import asyncio

    async def _purge() -> None:
        conn = await asyncpg.connect(settings.database_url)
        try:
            if _created:
                await conn.execute(
                    "DELETE FROM investigations WHERE id = ANY($1::uuid[])", _created
                )
            # Scoped to the dev workspace (S12 verification finding 13: the
            # unscoped version cascaded OTHER workspaces' verdict history —
            # the D-017 trail — for any shared value). Stub lookups must use
            # test-unique values: within the shared 'default' workspace this
            # still deletes by value, so a stub on a real demo observable
            # would remove its genuine trail.
            for type_, value in _stub_values:
                await conn.execute(
                    """
                    DELETE FROM observables
                    WHERE type = $1 AND value = $2
                      AND workspace_id = (SELECT id FROM workspaces WHERE name = 'default')
                    """,
                    type_,
                    value,
                )
        finally:
            await conn.close()

    asyncio.run(_purge())


def _token(client) -> str:
    return client.post("/api/auth/dev-login", json={"email": INV_EMAIL}).json()["access_token"]


def _hdr(client) -> dict:
    return {"Authorization": f"Bearer {_token(client)}"}


def _create(client, message: str) -> dict:
    resp = client.post("/api/investigations", json={"message": message}, headers=_hdr(client))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    _created.append(body["investigation_id"])
    return body


def test_create_from_alert_paste_seeds_and_scores(client):
    body = _create(client, ALERT_PASTE)
    assert body["subject_kind"] == "alert"
    assert [h["key"] for h in body["hypotheses"]].count("true_positive") == 1
    assert len(body["hypotheses"]) == 4
    kinds = {e["kind"] for e in body["evidence"]}
    assert "alert_encoded_command" in kinds
    assert "alert_high_severity" in kinds
    # encoded command fits TP and TEST alike — both must be live
    surviving = [h["key"] for h in body["hypotheses"] if h["status"] == "surviving"]
    assert "true_positive" in surviving and "test_activity" in surviving
    # weights over surviving hypotheses sum to 1
    total = sum(h["weight"] for h in body["hypotheses"])
    assert total == pytest.approx(1.0, abs=1e-4)
    # the private TEST-NET src was skipped; domain + hash are ranked candidates
    ranked = body["next_lookups"]["ranked"]
    values = [r["value"] for r in ranked]
    assert "evil-c2-server.biz" in values
    assert "44d88612fea8a8f36de82e1278abb02f" in values
    assert "203.0.113.7" not in values
    # itemized gain math is exposed, ranked descending
    gains = [r["expected_gain_bits"] for r in ranked]
    assert gains == sorted(gains, reverse=True)
    assert all(r["outcomes"] for r in ranked)


def test_create_from_email_paste_victim_filters_candidates(client):
    body = _create(client, EMAIL_PASTE)
    assert body["subject_kind"] == "email"
    kinds = {e["kind"] for e in body["evidence"]}
    assert "email_auth_fail" in kinds
    assert "email_lookalike_domain" in kinds
    # the victim's own domain is neither an IOC in the snapshot nor a candidate
    snapshot_values = [o["value"] for o in body["subject"]["iocs"]]
    assert not any("acme.com" in v and "paypa1" not in v for v in snapshot_values)
    cand_values = [r["value"] for r in body["next_lookups"]["ranked"]]
    assert not any("acme.com" in v and "paypa1" not in v for v in cand_values)
    assert any("paypa1.com" in v for v in cand_values)


def test_create_rejects_unstructured_prose(client):
    resp = client.post(
        "/api/investigations",
        json={"message": "what do you make of this whole situation?"},
        headers=_hdr(client),
    )
    assert resp.status_code == 422
    assert "structured subject" in resp.json()["detail"]


def test_get_recomputes_identically(client):
    created = _create(client, ALERT_PASTE)
    got = client.get(
        f"/api/investigations/{created['investigation_id']}", headers=_hdr(client)
    )
    assert got.status_code == 200
    body = got.json()
    # scores/weights/plans recompute from stored inputs to the same values
    assert body["hypotheses"] == created["hypotheses"]
    assert body["next_lookups"] == created["next_lookups"]


def test_unknown_investigation_is_404(client):
    resp = client.get(f"/api/investigations/{uuid4()}", headers=_hdr(client))
    assert resp.status_code == 404


def test_lookup_503_when_enrichment_disabled(client):
    # the devhost pin runs the suite with ENRICHMENT_ENABLED=false — the route
    # must say so instead of pretending to look things up
    created = _create(client, ALERT_PASTE)
    resp = client.post(
        f"/api/investigations/{created['investigation_id']}/lookups",
        json={},
        headers=_hdr(client),
    )
    assert resp.status_code == 503


class _StubEnrichment:
    """Answers MALICIOUS for whatever observable the engine chose."""

    active = True

    async def enrich(self, observables):
        items = tuple(
            ObservableEnrichment(
                observable=o,
                signals=(
                    ProviderSignal(
                        provider="StubTI",
                        label=VerdictLabel.MALICIOUS,
                        confidence=0.9,
                        summary="listed as active C2",
                        evidence={},
                    ),
                ),
                skip_reason=None,
                sources_answered=1,
            )
            for o in observables
        )
        return EnrichmentOutcome(items=items, provider_failures={})


def test_run_lookup_executes_top_candidate_and_reassesses(client):
    created = _create(client, ALERT_PASTE)
    top = created["next_lookups"]["ranked"][0]
    # register cleanup BEFORE the request: a failing assert must not leave the
    # stub verdict row behind (S12 verification finding 13)
    _stub_values.append((top["type"], top["value"]))
    real = client.app.state.enrichment
    client.app.state.enrichment = _StubEnrichment()
    try:
        resp = client.post(
            f"/api/investigations/{created['investigation_id']}/lookups",
            json={},
            headers=_hdr(client),
        )
    finally:
        client.app.state.enrichment = real
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # the malicious answer landed as evidence tied to the chosen observable
    enr = [e for e in body["evidence"] if e["kind"] == "enrichment_malicious"]
    assert len(enr) == 1
    assert enr[0]["obs_id"] == top["obs_id"]
    # the answered observable is no longer a candidate
    assert top["obs_id"] not in [r["obs_id"] for r in body["next_lookups"]["ranked"]]
    # belief moved toward TRUE_POSITIVE and away from FALSE_POSITIVE
    def w(payload, key):
        return next(h["weight"] for h in payload["hypotheses"] if h["key"] == key)

    assert w(body, "true_positive") > w(created, "true_positive")
    assert w(body, "false_positive") < w(created, "false_positive")


def test_run_lookup_conflict_when_nothing_ranked(client):
    # an alert whose only observables are private/internal leaves no
    # candidates (the enrichment skip filter is candidate hygiene too).
    # NB an email can't easily produce this: the sender address survives the
    # victim filter BY DESIGN (S12 review B — the sender is the suspect).
    no_cand = "CEF:0|Vendor|FW|1.0|100|internal ping sweep|3|src=10.0.0.5 dst=10.0.0.9"
    created = _create(client, no_cand)
    assert created["next_lookups"]["ranked"] == []
    real = client.app.state.enrichment
    client.app.state.enrichment = _StubEnrichment()
    try:
        resp = client.post(
            f"/api/investigations/{created['investigation_id']}/lookups",
            json={},
            headers=_hdr(client),
        )
    finally:
        client.app.state.enrichment = real
    assert resp.status_code == 409
    assert "No lookup to run" in resp.json()["detail"]


def test_run_lookup_rejects_non_candidate_obs_id(client):
    created = _create(client, ALERT_PASTE)
    real = client.app.state.enrichment
    client.app.state.enrichment = _StubEnrichment()
    try:
        resp = client.post(
            f"/api/investigations/{created['investigation_id']}/lookups",
            json={"obs_id": "ipv4-deadbeef"},
            headers=_hdr(client),
        )
    finally:
        client.app.state.enrichment = real
    assert resp.status_code == 422
    assert "not among the current lookup candidates" in resp.json()["detail"]


def test_session_attachment_requires_ownership(client):
    resp = client.post(
        "/api/investigations",
        json={"message": ALERT_PASTE, "session_id": str(uuid4())},
        headers=_hdr(client),
    )
    assert resp.status_code == 404


# -- store-level regressions (S12 verification findings 2/4, 11/12, 14) --------


@pytest.fixture()
def store_pool(client):
    """The app's live pool (event loop owned by the TestClient lifespan)."""
    return client.app.state.pool


async def _scratch_workspace(conn) -> str:
    return await conn.fetchval(
        "INSERT INTO workspaces (name) VALUES ('test-ach-store') "
        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
    )


def test_store_roundtrip_preserves_hard_contradictions(client, settings):
    """S12 verification: credibility is a Postgres real (float32) — 0.7 came
    back 0.699999988 and silently failed the >= 0.7 hard-contradiction check,
    so the API served a different matrix than the fixture-pinned math. The
    load path now rounds to the 3dp _make writes."""
    import asyncio

    from auspex.ach import (
        Evidence,
        EvidenceKind,
        HypothesisKey,
        SubjectKind,
        score_matrix,
        seed_hypotheses,
    )
    from auspex.ach.store import create_investigation, load_investigation

    hyps = seed_hypotheses(SubjectKind.EMAIL)
    ev = tuple(
        Evidence(
            kind=EvidenceKind.EMAIL_SPOOF_INDICATOR,
            statement=f"spoof indicator {i}",
            credibility=0.7,  # the exact value float4 mangles
            cells={
                HypothesisKey.TRUE_POSITIVE: 2,
                HypothesisKey.FALSE_POSITIVE: -1,
                HypothesisKey.BENIGN_ACTIVITY: -2,
                HypothesisKey.TEST_ACTIVITY: 1,
            },
            source="test",
        )
        for i in range(3)
    )
    before = score_matrix(hyps, ev)

    async def _roundtrip():
        conn = await asyncpg.connect(settings.database_url)
        try:
            ws = await _scratch_workspace(conn)
        finally:
            await conn.close()
        pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
        try:
            inv_id = await create_investigation(
                pool,
                workspace_id=ws,
                subject_kind=SubjectKind.EMAIL,
                subject={},
                hypotheses=hyps,
                evidence=ev,
            )
            rec = await load_investigation(pool, workspace_id=ws, investigation_id=inv_id)
            async with pool.acquire() as c:
                await c.execute("DELETE FROM workspaces WHERE id = $1", ws)
            return rec
        finally:
            await pool.close()

    rec = asyncio.run(_roundtrip())
    assert all(e.credibility == 0.7 for e in rec.evidence)
    after = score_matrix(rec.hypotheses, rec.evidence)
    for b, a in zip(before.scores, after.scores, strict=True):
        assert b.hypothesis.key == a.hypothesis.key
        assert b.hard_contradictions == a.hard_contradictions
        assert b.status == a.status
        assert b.weight == pytest.approx(a.weight, abs=1e-6)


def test_store_tolerates_retired_evidence_kind_and_guards_ownership(client, settings):
    """(11/12) a kind retired from the vocabulary must not brick every load;
    (14) add_evidence must refuse a foreign-workspace investigation id."""
    import asyncio
    from uuid import uuid4

    from auspex.ach import Evidence, EvidenceKind, HypothesisKey, SubjectKind, seed_hypotheses
    from auspex.ach.store import add_evidence, create_investigation, load_investigation

    async def _run():
        conn = await asyncpg.connect(settings.database_url)
        try:
            ws = await _scratch_workspace(conn)
        finally:
            await conn.close()
        pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
        try:
            inv_id = await create_investigation(
                pool,
                workspace_id=ws,
                subject_kind=SubjectKind.ALERT,
                subject={},
                hypotheses=seed_hypotheses(SubjectKind.ALERT),
                evidence=(
                    Evidence(
                        kind=EvidenceKind.ALERT_LOLBIN,
                        statement="kept row",
                        credibility=0.8,
                        cells={k: 0 for k in HypothesisKey},
                        source="test",
                    ),
                ),
            )
            async with pool.acquire() as c:
                await c.execute(
                    """
                    INSERT INTO ach_evidence
                        (workspace_id, investigation_id, kind, statement,
                         credibility, cells, source)
                    VALUES ($1, $2, 'retired_kind_from_v0', 'old row', 0.5, '{}', 'test')
                    """,
                    ws,
                    inv_id,
                )
            rec = await load_investigation(pool, workspace_id=ws, investigation_id=inv_id)
            foreign_error = None
            try:
                await add_evidence(
                    pool,
                    workspace_id=uuid4(),  # not the owning workspace
                    investigation_id=inv_id,
                    evidence=rec.evidence[:1],
                )
            except LookupError as err:
                foreign_error = err
            async with pool.acquire() as c:
                await c.execute("DELETE FROM workspaces WHERE id = $1", ws)
            return rec, foreign_error
        finally:
            await pool.close()

    rec, foreign_error = asyncio.run(_run())
    assert [e.statement for e in rec.evidence] == ["kept row"]  # retired row skipped
    assert isinstance(foreign_error, LookupError)


class _DeadEnrichment:
    """No provider completes anything — outage shape."""

    active = True

    async def enrich(self, observables):
        items = tuple(
            ObservableEnrichment(
                observable=o, signals=(), skip_reason=None, sources_answered=0
            )
            for o in observables
        )
        return EnrichmentOutcome(
            items=items, provider_failures={"StubTI": "unreachable or returned an error"}
        )


def test_uncompleted_lookup_reports_not_completed_and_keeps_the_candidate(client):
    # S12 verification finding 15: a lookup no provider completed must not
    # return a byte-identical 200 that reads as progress.
    created = _create(client, ALERT_PASTE)
    top = created["next_lookups"]["ranked"][0]
    real = client.app.state.enrichment
    client.app.state.enrichment = _DeadEnrichment()
    try:
        resp = client.post(
            f"/api/investigations/{created['investigation_id']}/lookups",
            json={},
            headers=_hdr(client),
        )
    finally:
        client.app.state.enrichment = real
    assert resp.status_code == 200
    body = resp.json()
    assert body["lookup_status"]["status"] == "not_completed"
    assert body["lookup_status"]["obs_id"] == top["obs_id"]
    assert body["lookup_status"]["provider_failures"] == 1
    # the candidate honestly remains for a later retry
    assert top["obs_id"] in [r["obs_id"] for r in body["next_lookups"]["ranked"]]


def test_completed_lookup_reports_completed(client):
    created = _create(client, ALERT_PASTE)
    top = created["next_lookups"]["ranked"][0]
    _stub_values.append((top["type"], top["value"]))
    real = client.app.state.enrichment
    client.app.state.enrichment = _StubEnrichment()
    try:
        resp = client.post(
            f"/api/investigations/{created['investigation_id']}/lookups",
            json={},
            headers=_hdr(client),
        )
    finally:
        client.app.state.enrichment = real
    assert resp.json()["lookup_status"]["status"] == "completed"
