"""D-038 / TD-037: the platform probes its own configured endpoint, once per
fingerprint, in the background.

Before this, the only writer of the deployment scorecard was a developer running
`scripts/llm_harness.py`. Any other deployment read "unknown": two-pass on every
deep turn (D-036 made that survivable), and since D-037 no agent path at all.

Runs against the live dev DB like test_deployment_scorecard.py, under a
fingerprint no real endpoint has, with the probe and the client injected, so
nothing here reaches a network. It deletes exactly the rows it wrote.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import auspex.app as app_module
from auspex.app import create_app
from auspex.config import Settings
from auspex.db import create_pool
from auspex.llm.autoprobe import (
    REPROBE_CHECK_SECONDS,
    SCORECARD_MAX_AGE_SECONDS,
    autoprobe,
    ensure_deployment_scorecard,
    keep_scorecard_fresh,
)
from auspex.llm.capability import BASIC_CHAT_FAILED
from auspex.llm.scorecard import (
    CapabilityScorecard,
    load_deployment_scorecard,
    save_deployment_scorecard,
)

TEST_BASE = "https://d038-autoprobe.test/v1"
TEST_MODEL = "d038-model"


def _settings(**over) -> Settings:
    return Settings(llm_base_url=TEST_BASE, llm_model=TEST_MODEL, llm_api_key="", **over)


class _Client:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


class _Probe:
    """Counts probes; returns a scripted sequence of scorecards."""

    def __init__(self, *cards: CapabilityScorecard, gate: asyncio.Event | None = None):
        self.cards = list(cards)
        self.calls = 0
        self.gate = gate
        self.clients: list[_Client] = []

    def client_factory(self, settings):
        c = _Client()
        self.clients.append(c)
        return c

    async def __call__(self, client):
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        return self.cards.pop(0)


def _card(**over) -> CapabilityScorecard:
    base = {"base_url": TEST_BASE.rstrip("/"), "model": TEST_MODEL, "reachable": True,
            "native_reasoning": True, "native_tool_calling": True,
            "streaming_tool_deltas": True}
    return CapabilityScorecard(**{**base, **over})


@pytest.fixture
def pool(settings):
    """A fresh pool per test, on the test's own event loop, and every row these
    tests wrote removed afterwards."""

    async def make():
        return await create_pool(settings.database_url, retries=2, delay=0.5)

    async def cleanup(p):
        await p.execute("DELETE FROM llm_endpoint_scorecards WHERE base_url LIKE '%d038-%'")
        await p.close()

    loop = asyncio.new_event_loop()
    p = loop.run_until_complete(make())
    try:
        yield loop, p
    finally:
        loop.run_until_complete(cleanup(p))
        loop.close()


def _run(pool, coro_fn):
    loop, p = pool
    return loop.run_until_complete(coro_fn(p))


def test_an_unprobed_endpoint_is_probed_and_recorded_as_the_deployments(pool):
    probe = _Probe(_card())

    outcome = _run(pool, lambda p: ensure_deployment_scorecard(
        p, _settings(), probe=probe, client_factory=probe.client_factory))
    loaded = _run(pool, lambda p: load_deployment_scorecard(p, TEST_BASE, TEST_MODEL))

    assert outcome == "probed" and probe.calls == 1
    assert loaded is not None and loaded[1] == "native_tools"
    assert all(c.closed for c in probe.clients)


def test_a_known_endpoint_is_never_probed_again(pool):
    """Once per fingerprint: a restart must not spend the customer's inference
    re-measuring an endpoint that has not changed."""
    _run(pool, lambda p: save_deployment_scorecard(p, _card()))
    probe = _Probe(_card())

    outcome = _run(pool, lambda p: ensure_deployment_scorecard(
        p, _settings(), probe=probe, client_factory=probe.client_factory))

    assert (outcome, probe.calls) == ("known", 0)


def test_an_unconfigured_deployment_probes_nothing(pool):
    probe = _Probe()

    outcome = _run(pool, lambda p: ensure_deployment_scorecard(
        p, Settings(llm_base_url=""), probe=probe, client_factory=probe.client_factory))

    assert (outcome, probe.calls) == ("unconfigured", 0)


@pytest.mark.parametrize("card,outcome", [
    (_card(reachable=False, notes=["unreachable: transport: ConnectError"]), "unreachable"),
    (_card(native_tool_calling=False, notes=[BASIC_CHAT_FAILED]), "unusable"),
])
def test_a_probe_that_measured_nothing_is_not_recorded(pool, card, outcome):
    """A scale-to-zero endpoint asleep at startup, or a wrong key, measures
    nothing about the ENDPOINT. Recording it would pin plan_only for this
    fingerprint — and the key is not part of the fingerprint, so fixing the key
    and restarting would never re-probe."""
    probe = _Probe(card)

    result = _run(pool, lambda p: ensure_deployment_scorecard(
        p, _settings(), probe=probe, client_factory=probe.client_factory))
    loaded = _run(pool, lambda p: load_deployment_scorecard(p, TEST_BASE, TEST_MODEL))

    assert (result, loaded) == (outcome, None)


def test_two_starts_at_once_probe_the_endpoint_once(pool):
    """Several workers start together; the battery is ~15 requests of the
    customer's inference, and it is spent once."""
    gate = asyncio.Event()
    probe = _Probe(_card(), _card(), gate=gate)

    async def both(p):
        first = asyncio.ensure_future(ensure_deployment_scorecard(
            p, _settings(), probe=probe, client_factory=probe.client_factory))
        await asyncio.sleep(0.2)  # the first holds the lock, mid-probe
        try:
            # Without the lock the second caller would probe too and wait on
            # the same gate: bounded, so that FAILS here instead of hanging.
            second = await asyncio.wait_for(ensure_deployment_scorecard(
                p, _settings(), probe=probe, client_factory=probe.client_factory), timeout=5)
        finally:
            gate.set()  # always release the first, or its connection pins the pool
        return await first, second

    assert _run(pool, both) == ("probed", "busy")
    assert probe.calls == 1


def test_an_endpoint_asleep_at_startup_is_probed_when_it_wakes(pool):
    """Scale-to-zero is a normal state for a customer endpoint (2026-07-14
    probe). The background task retries on a schedule instead of leaving the
    deployment unknown until the next restart."""
    probe = _Probe(_card(reachable=False), _card(reachable=False), _card())
    slept: list[float] = []

    async def sleep(seconds):
        slept.append(seconds)

    async def attempt(p, s):
        return await ensure_deployment_scorecard(
            p, s, probe=probe, client_factory=probe.client_factory)

    outcome = _run(pool, lambda p: autoprobe(
        p, _settings(), attempt=attempt, sleep=sleep, delays=(1.0, 2.0, 3.0)))

    assert outcome == "probed" and probe.calls == 3
    assert slept == [1.0, 2.0]


def test_a_failing_attempt_never_takes_the_app_down():
    async def attempt(p, s):
        raise RuntimeError("database went away")

    async def sleep(seconds):
        pass

    outcome = asyncio.run(autoprobe(None, _settings(), attempt=attempt, sleep=sleep, delays=()))

    assert outcome == "error"


def test_the_app_starts_the_probe_only_when_switched_on(monkeypatch):
    """LLM_AUTOPROBE_ENABLED is the operator's say (D-005: the customer's
    inference) and the hermetic switch for tests (`auspex.devhost` pins it
    off, like INGEST_ENABLED)."""
    started: list[Settings] = []

    async def fake_keep_fresh(pool, settings, **kw):
        started.append(settings)

    monkeypatch.setattr(app_module, "keep_scorecard_fresh", fake_keep_fresh)
    for enabled in (True, False):
        with TestClient(create_app(_settings(llm_autoprobe_enabled=enabled))):
            pass

    assert [s.llm_autoprobe_enabled for s in started] == [True]


def test_host_test_runs_are_pinned_off():
    assert Settings().llm_autoprobe_enabled is False


# ── TD-041 (D-042): a measurement gets old, and the running app takes another ──


def _age_all(pool, seconds: float):
    """Backdate every row these tests wrote, as if probed `seconds` ago."""
    return _run(pool, lambda p: p.execute(
        "UPDATE llm_endpoint_scorecards"
        "   SET probed_at = now() - make_interval(secs => $1::double precision)"
        " WHERE base_url LIKE '%d038-%'", float(seconds)))


def test_an_old_measurement_is_taken_again_and_the_new_one_wins(pool):
    """TD-041: a provider can change a model under the same name, and the
    fingerprint cannot see it. Past SCORECARD_MAX_AGE_SECONDS the endpoint is
    measured again, and what it does NOW is what the route reads."""
    _run(pool, lambda p: save_deployment_scorecard(p, _card(native_reasoning=True)))
    _age_all(pool, SCORECARD_MAX_AGE_SECONDS + 3600)
    probe = _Probe(_card(native_reasoning=False))

    outcome = _run(pool, lambda p: ensure_deployment_scorecard(
        p, _settings(), probe=probe, client_factory=probe.client_factory))
    loaded = _run(pool, lambda p: load_deployment_scorecard(p, TEST_BASE, TEST_MODEL))

    assert (outcome, probe.calls) == ("reprobed", 1)
    assert loaded[0].native_reasoning is False


def test_a_measurement_younger_than_the_limit_is_not_taken_again(pool):
    _run(pool, lambda p: save_deployment_scorecard(p, _card()))
    _age_all(pool, SCORECARD_MAX_AGE_SECONDS - 3600)
    probe = _Probe(_card())

    outcome = _run(pool, lambda p: ensure_deployment_scorecard(
        p, _settings(), probe=probe, client_factory=probe.client_factory))

    assert (outcome, probe.calls) == ("known", 0)


def test_a_re_probe_that_measures_nothing_leaves_the_old_measurement_standing(pool):
    """An endpoint asleep at re-probe time says nothing about the endpoint. The
    old scorecard is still the best knowledge there is, and "unknown" would
    drop the deployment to two-pass and off the agent path."""
    _run(pool, lambda p: save_deployment_scorecard(p, _card()))
    _age_all(pool, SCORECARD_MAX_AGE_SECONDS + 3600)
    probe = _Probe(_card(reachable=False))

    outcome = _run(pool, lambda p: ensure_deployment_scorecard(
        p, _settings(), probe=probe, client_factory=probe.client_factory))
    loaded = _run(pool, lambda p: load_deployment_scorecard(p, TEST_BASE, TEST_MODEL))

    assert outcome == "unreachable"
    assert loaded is not None and loaded[1] == "native_tools"


def test_a_re_probe_that_finds_the_endpoint_changed_says_so(pool, caplog):
    """The rail's thinking floor (D-040) is calibrated per model and no probe
    re-calibrates it, so a changed endpoint has to be visible to a human."""
    _run(pool, lambda p: save_deployment_scorecard(p, _card()))
    _age_all(pool, SCORECARD_MAX_AGE_SECONDS + 3600)
    probe = _Probe(_card(native_tool_calling=False, streaming_tool_deltas=False))

    with caplog.at_level("WARNING", logger="auspex.llm.autoprobe"):
        _run(pool, lambda p: ensure_deployment_scorecard(
            p, _settings(), probe=probe, client_factory=probe.client_factory))

    warned = " ".join(r.getMessage() for r in caplog.records)
    assert "agent_mode: native_tools -> plan_only" in warned
    assert "native_tool_calling: True -> False" in warned and "D-040" in warned


def test_an_unchanged_endpoint_re_probes_quietly(pool, caplog):
    _run(pool, lambda p: save_deployment_scorecard(p, _card()))
    _age_all(pool, SCORECARD_MAX_AGE_SECONDS + 3600)
    probe = _Probe(_card())

    with caplog.at_level("WARNING", logger="auspex.llm.autoprobe"):
        outcome = _run(pool, lambda p: ensure_deployment_scorecard(
            p, _settings(), probe=probe, client_factory=probe.client_factory))

    assert outcome == "reprobed" and not caplog.records


def test_the_running_app_looks_again_on_a_schedule():
    """The startup cycle alone measured each fingerprint once, ever. The task
    the app runs repeats the look every REPROBE_CHECK_SECONDS until cancelled."""
    cycles: list[str] = []
    slept: list[float] = []

    async def cycle(p, s):
        cycles.append("look")
        return "known"

    async def sleep(seconds):
        slept.append(seconds)
        if len(slept) == 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(keep_scorecard_fresh(None, _settings(), cycle=cycle, sleep=sleep))

    assert cycles == ["look"] * 3
    assert slept == [REPROBE_CHECK_SECONDS] * 3
