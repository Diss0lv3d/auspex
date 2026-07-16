"""Fan-out orchestration — S5: parallel submit-all, per-call timeouts, circuit
breaker, skip filters, per-turn cap, verdict synthesis, and the rendered echo.

Hermetic: scripted providers, no HTTP (the injected httpx client 500s if any
code path ever touches it — proving providers are the only network surface).
"""

import asyncio

import httpx
import pytest
from _fakes import FORBIDDEN_ENGINE_NAMES

from auspex.classify.observables import Observable, ObservableType, observable_id
from auspex.enrich.breaker import CircuitBreaker
from auspex.enrich.echo import render_ioc_answer
from auspex.enrich.fanout import BREAKER_OPEN_REASON
from auspex.enrich.filters import COMMON_DOMAIN_SKIP, PRIVATE_IP_SKIP, skip_reason
from auspex.enrich.providers.base import Provider
from auspex.enrich.service import CAP_SKIP, EnrichmentService
from auspex.enrich.types import ProviderError, ProviderSignal, VerdictLabel
from auspex.enrich.verdict import effective_confidence, synthesize

ALL_TYPES = frozenset(ObservableType)


def obs(type_: ObservableType, value: str, *, defanged: bool = False) -> Observable:
    return Observable(
        type=type_, value=value, obs_id=observable_id(type_, value), defanged=defanged
    )


def signal(provider: str, label=VerdictLabel.SUSPICIOUS, confidence=0.5) -> ProviderSignal:
    return ProviderSignal(
        provider=provider, label=label, confidence=confidence, summary=f"{provider} says {label}"
    )


class ScriptedProvider(Provider):
    def __init__(self, name, accepts=ALL_TYPES, *, result=None, error=None, delay=0.0):
        self.name = name
        self.accepts = accepts
        self.result = result
        self.error = error
        self.delay = delay
        self.calls: list[str] = []

    async def lookup(self, client, observable):
        self.calls.append(observable.value)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def poisoned_client():
    """Any real HTTP through the shared client is a test failure."""

    def explode(request):
        raise AssertionError(f"unexpected HTTP call: {request.url}")

    return httpx.AsyncClient(transport=httpx.MockTransport(explode))


def service(providers, *, client, cap=8, timeout=1.0, breakers=None) -> EnrichmentService:
    return EnrichmentService(
        providers, client=client, cap=cap, call_timeout=timeout, breakers=breakers
    )


# -- fan-out basics -----------------------------------------------------------


async def test_providers_only_see_types_they_accept(poisoned_client):
    ip_provider = ScriptedProvider("ips", frozenset({ObservableType.IPV4}), result=signal("ips"))
    hash_provider = ScriptedProvider(
        "hashes", frozenset({ObservableType.SHA256}), result=signal("hashes")
    )
    svc = service([ip_provider, hash_provider], client=poisoned_client)
    outcome = await svc.enrich((obs(ObservableType.IPV4, "1.2.3.4"),))
    assert ip_provider.calls == ["1.2.3.4"]
    assert hash_provider.calls == []
    assert [s.provider for s in outcome.items[0].signals] == ["ips"]
    assert outcome.provider_failures == {}  # hash provider wasn't needed — not reported


async def test_partial_results_survive_a_failing_provider(poisoned_client):
    good = ScriptedProvider("good", result=signal("good"))
    bad = ScriptedProvider("bad", error=ProviderError("bad: HTTP 503"))
    svc = service([good, bad], client=poisoned_client)
    outcome = await svc.enrich((obs(ObservableType.IPV4, "1.2.3.4"),))
    assert [s.provider for s in outcome.items[0].signals] == ["good"]
    assert outcome.provider_failures == {"bad": "unreachable or returned an error"}


async def test_slow_provider_times_out_without_sinking_the_turn(poisoned_client):
    fast = ScriptedProvider("fast", result=signal("fast"))
    slow = ScriptedProvider("slow", result=signal("slow"), delay=0.5)
    svc = service([fast, slow], client=poisoned_client, timeout=0.05)
    outcome = await svc.enrich((obs(ObservableType.IPV4, "1.2.3.4"),))
    assert [s.provider for s in outcome.items[0].signals] == ["fast"]
    assert "timed out" in outcome.provider_failures["slow"]


async def test_unexpected_provider_crash_degrades_gracefully(poisoned_client):
    good = ScriptedProvider("good", result=signal("good"))
    buggy = ScriptedProvider("buggy", error=KeyError("parser bug"))
    svc = service([good, buggy], client=poisoned_client)
    outcome = await svc.enrich((obs(ObservableType.IPV4, "1.2.3.4"),))
    assert [s.provider for s in outcome.items[0].signals] == ["good"]
    assert outcome.provider_failures["buggy"] == "unexpected error"


async def test_items_preserve_message_order(poisoned_client):
    svc = service([ScriptedProvider("p", result=signal("p"))], client=poisoned_client)
    observables = (
        obs(ObservableType.SHA256, "a" * 64),
        obs(ObservableType.IPV4, "1.2.3.4"),
        obs(ObservableType.DOMAIN, "evil.example"),
    )
    outcome = await svc.enrich(observables)
    assert tuple(i.observable for i in outcome.items) == observables


# -- circuit breaker ----------------------------------------------------------


def test_breaker_opens_after_threshold_and_half_opens_after_cooldown():
    now = [0.0]
    breaker = CircuitBreaker(threshold=3, cooldown_seconds=60, clock=lambda: now[0])
    assert breaker.state == "closed"
    for _ in range(2):
        breaker.record_failure()
    assert breaker.state == "closed"  # not yet
    breaker.record_failure()
    assert breaker.state == "open" and not breaker.allow()
    now[0] = 59.9
    assert breaker.state == "open"
    now[0] = 60.0
    assert breaker.state == "half_open" and breaker.allow()
    breaker.record_failure()  # half-open trial fails → re-open, fresh cooldown
    assert breaker.state == "open"
    now[0] = 120.0
    assert breaker.state == "half_open"
    breaker.record_success()  # trial succeeds → closed, count reset
    assert breaker.state == "closed"


async def test_open_breaker_skips_the_provider_and_says_so(poisoned_client):
    flaky = ScriptedProvider("flaky", error=ProviderError("flaky: HTTP 500"))
    steady = ScriptedProvider("steady", result=signal("steady"))
    now = [0.0]
    breakers = {
        "flaky": CircuitBreaker(threshold=3, cooldown_seconds=60, clock=lambda: now[0]),
        "steady": CircuitBreaker(),
    }
    svc = service([flaky, steady], client=poisoned_client, breakers=breakers)
    one_ip = (obs(ObservableType.IPV4, "1.2.3.4"),)

    for _ in range(3):  # three failing turns open the circuit
        await svc.enrich(one_ip)
    assert breakers["flaky"].state == "open"
    calls_before = len(flaky.calls)

    outcome = await svc.enrich(one_ip)  # 4th turn: flaky never contacted
    assert len(flaky.calls) == calls_before
    assert outcome.provider_failures["flaky"] == BREAKER_OPEN_REASON
    assert [s.provider for s in outcome.items[0].signals] == ["steady"]

    now[0] = 61.0  # cooldown over → half-open probe goes through
    flaky.error = None
    flaky.result = signal("flaky")
    outcome = await svc.enrich(one_ip)
    assert len(flaky.calls) == calls_before + 1
    assert breakers["flaky"].state == "closed"
    assert {s.provider for s in outcome.items[0].signals} == {"flaky", "steady"}


# -- skip filters (private/reserved IPs, ubiquitous domains) --------------------


def test_skip_reasons_cover_private_reserved_and_common():
    assert skip_reason(obs(ObservableType.IPV4, "10.0.0.1")) == PRIVATE_IP_SKIP
    assert skip_reason(obs(ObservableType.IPV4, "127.0.0.1")) == PRIVATE_IP_SKIP
    assert skip_reason(obs(ObservableType.IPV4, "192.0.2.1")) == PRIVATE_IP_SKIP  # TEST-NET
    assert skip_reason(obs(ObservableType.IPV6, "fe80::1")) == PRIVATE_IP_SKIP
    assert skip_reason(obs(ObservableType.IPV4, "185.220.101.34")) is None
    assert skip_reason(obs(ObservableType.DOMAIN, "google.com")) == COMMON_DOMAIN_SKIP
    assert skip_reason(obs(ObservableType.DOMAIN, "www.google.com")) == COMMON_DOMAIN_SKIP
    assert skip_reason(obs(ObservableType.DOMAIN, "evil.example")) is None
    # Defanged common domains are still skipped: the defang is signal (S7),
    # but the lookup answer would still be "Google is Google".
    assert skip_reason(obs(ObservableType.DOMAIN, "google.com", defanged=True)) is not None


async def test_skipped_observables_never_reach_providers(poisoned_client):
    provider = ScriptedProvider("p", result=signal("p"))
    svc = service([provider], client=poisoned_client)
    outcome = await svc.enrich(
        (
            obs(ObservableType.IPV4, "10.0.0.1"),
            obs(ObservableType.DOMAIN, "google.com"),
            obs(ObservableType.IPV4, "185.220.101.34"),
        )
    )
    assert provider.calls == ["185.220.101.34"]
    assert outcome.items[0].skip_reason == PRIVATE_IP_SKIP
    assert outcome.items[1].skip_reason == COMMON_DOMAIN_SKIP
    assert outcome.items[2].skip_reason is None


async def test_per_turn_cap_bounds_fanout_and_skips_dont_consume_it(poisoned_client):
    provider = ScriptedProvider("p", result=signal("p"))
    svc = service([provider], client=poisoned_client, cap=2)
    observables = (
        obs(ObservableType.IPV4, "10.0.0.1"),  # skipped: private — must not eat the cap
        obs(ObservableType.SHA256, "a" * 64),
        obs(ObservableType.SHA256, "b" * 64),
        obs(ObservableType.SHA256, "c" * 64),
    )
    outcome = await svc.enrich(observables)
    assert provider.calls == ["a" * 64, "b" * 64]
    assert outcome.items[3].skip_reason == CAP_SKIP


# -- verdict synthesis + decay ---------------------------------------------------


def test_worst_credible_signal_wins_the_label():
    o = obs(ObservableType.IPV4, "1.2.3.4")
    verdict = synthesize(
        o,
        (
            signal("a", VerdictLabel.BENIGN, 0.9),
            signal("b", VerdictLabel.MALICIOUS, 0.6),
            signal("c", VerdictLabel.SUSPICIOUS, 0.99),
        ),
    )
    assert verdict.label is VerdictLabel.MALICIOUS
    assert verdict.confidence_at_write == 0.6  # strongest signal OF THE WINNING LABEL
    assert verdict.source == "enrichment:a,b,c"


def test_no_signals_means_no_verdict_row():
    assert synthesize(obs(ObservableType.IPV4, "1.2.3.4"), ()) is None


def test_half_life_defaults_follow_observable_churn():
    ip = synthesize(obs(ObservableType.IPV4, "1.2.3.4"), (signal("p"),))
    sha = synthesize(obs(ObservableType.SHA256, "a" * 64), (signal("p"),))
    domain = synthesize(obs(ObservableType.DOMAIN, "evil.example"), (signal("p"),))
    assert ip.half_life_days == 14.0  # IPs churn in days
    assert domain.half_life_days == 30.0
    assert sha.half_life_days == 365.0  # a hash IS the artifact
    assert ip.floor == 0.0


def test_decay_curve_semantics_are_executable():
    at_write = effective_confidence(
        confidence_at_write=0.8, floor=0.0, half_life_days=14, age_days=0
    )
    one_half_life = effective_confidence(
        confidence_at_write=0.8, floor=0.0, half_life_days=14, age_days=14
    )
    ancient = effective_confidence(
        confidence_at_write=0.8, floor=0.2, half_life_days=14, age_days=1400
    )
    assert at_write == 0.8
    assert one_half_life == pytest.approx(0.4)
    assert ancient == pytest.approx(0.2)  # decays to the floor, never below


# -- rendered echo ----------------------------------------------------------------


def outcome_for_render():
    from auspex.enrich.types import EnrichmentOutcome, ObservableEnrichment

    return EnrichmentOutcome(
        items=(
            ObservableEnrichment(
                observable=obs(ObservableType.IPV4, "185.220.101.34"),
                signals=(
                    ProviderSignal(
                        "ThreatFox",
                        VerdictLabel.MALICIOUS,
                        0.75,
                        "known IOC: Cobalt Strike (botnet_cc), reporter confidence 75/100",
                    ),
                    ProviderSignal("InternetDB", VerdictLabel.UNKNOWN, 0.0, "open ports 443"),
                ),
            ),
            ObservableEnrichment(
                observable=obs(ObservableType.IPV4, "10.0.0.1"),
                skip_reason=PRIVATE_IP_SKIP,
            ),
            ObservableEnrichment(observable=obs(ObservableType.SHA256, "c" * 64)),
            ObservableEnrichment(observable=obs(ObservableType.EMAIL, "a@evil.example")),
        ),
        provider_failures={"GreyNoise": BREAKER_OPEN_REASON},
    )


COVERAGE = {ObservableType.IPV4: 3, ObservableType.SHA256: 2}  # email: no coverage


def test_render_reports_verdicts_skips_gaps_and_failures_honestly():
    text = render_ioc_answer(outcome_for_render(), COVERAGE)
    assert "Parsed 4 observables:" in text
    assert "verdict: malicious (confidence 0.75)" in text
    assert "ThreatFox: known IOC: Cobalt Strike" in text
    assert PRIVATE_IP_SKIP in text
    assert "no signal from 2 connected sources" in text  # sha: asked, nobody knew
    assert "no connected source covers this observable type" in text  # email
    assert "Sources unavailable this turn: GreyNoise" in text
    assert "185.220.101[.]34" not in text  # normalized forms only


def test_render_context_only_signals_do_not_claim_a_verdict():
    from auspex.enrich.types import EnrichmentOutcome, ObservableEnrichment

    outcome = EnrichmentOutcome(
        items=(
            ObservableEnrichment(
                observable=obs(ObservableType.IPV4, "8.8.8.8"),
                signals=(
                    ProviderSignal("InternetDB", VerdictLabel.UNKNOWN, 0.0, "open ports 53, 443"),
                ),
            ),
        ),
    )
    text = render_ioc_answer(outcome, COVERAGE)
    assert "no reputation verdict — context: InternetDB: open ports" in text
    assert "verdict: unknown" not in text


def test_render_never_names_the_engine_and_stays_plain_text():
    text = render_ioc_answer(outcome_for_render(), COVERAGE).lower()
    for name in [*FORBIDDEN_ENGINE_NAMES, "model"]:
        assert name not in text, f"{name!r} leaked into enriched copy"
    assert "`" not in text and "**" not in text  # UI renders plain text verbatim
