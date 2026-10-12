"""Enrichment core types — S5.

A `ProviderSignal` is ONE provider's read on ONE observable: a label, a
confidence, a one-line plain-text summary (user-facing, Auspex voice), and a
trimmed evidence dict (JSON-safe; this is what gets persisted — raw provider
bodies are unboundedly large, see docs/probes/2026-07-16-enrichment-providers.md).

"No data" is None, never a signal: an observable unknown to a provider is not
evidence of anything (hashlookup misses are not malice; GreyNoise "not observed"
is not innocence). Only actual provider statements become signals.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from auspex.classify.observables import Observable


class VerdictLabel(StrEnum):
    MALICIOUS = "malicious"
    SUSPICIOUS = "suspicious"
    BENIGN = "benign"
    UNKNOWN = "unknown"  # context-only signals (e.g. open ports) — never a claim


# Severity order for verdict synthesis: the worst credible signal wins.
SEVERITY: dict[VerdictLabel, int] = {
    VerdictLabel.MALICIOUS: 3,
    VerdictLabel.SUSPICIOUS: 2,
    VerdictLabel.BENIGN: 1,
    VerdictLabel.UNKNOWN: 0,
}


class ProviderError(Exception):
    """A provider call failed (network, 5xx, auth, rate limit).

    Distinct from "no data": failures feed the circuit breaker and the
    DEFERRED rail ("source unavailable"), never a verdict.
    """


class ProviderInputError(ProviderError):
    """The provider rejected OUR query (abuse.ch `invalid_*`, unknown
    query_status = contract drift). That is an input/contract problem on our
    side, not provider health — it surfaces in the trailer but MUST NOT feed
    the circuit breaker (probe contract: "a client bug, not provider-down").
    """


@dataclass(frozen=True)
class ProviderSignal:
    provider: str  # display name, e.g. "ThreatFox" (data source — not the engine)
    label: VerdictLabel
    confidence: float  # 0..1 (provider-mapped; see each provider module)
    summary: str  # one plain-text evidence line, user-facing
    evidence: dict = field(default_factory=dict)  # trimmed, JSON-safe


@dataclass(frozen=True)
class NetworkContext:
    """Who operates an address, as ONE provider reported it (B-001).

    A fact about the address, not a reputation. It is never a ProviderSignal:
    it is not synthesized into a verdict, never recorded as one, and so it can
    neither supersede nor flip what the workspace believes about an indicator.

    It exists because the platform used to fetch it and throw it away.
    AbuseIPDB names the network on every lookup; a low score returned None,
    the IOC check said "unknown to them", and a model asked to dig deeper,
    holding no tools and no owner, supplied one from memory — the wrong one
    (docs/probes/b1-b001/)."""

    provider: str  # display name, e.g. "AbuseIPDB" (data source — not the engine)
    summary: str  # one plain-text line, user-facing
    evidence: dict = field(default_factory=dict)  # trimmed, JSON-safe


# What one provider lookup may return: a reputation claim, the network it named,
# both, or nothing at all.
LookupResult = (
    ProviderSignal | NetworkContext | tuple[ProviderSignal | NetworkContext, ...] | None
)


def split_lookup(result: LookupResult) -> tuple[list[ProviderSignal], list[NetworkContext]]:
    """One lookup's result as (signals, network contexts), in the order given."""
    if result is None:
        return [], []
    parts = result if isinstance(result, tuple) else (result,)
    return (
        [p for p in parts if isinstance(p, ProviderSignal)],
        [p for p in parts if isinstance(p, NetworkContext)],
    )


@dataclass(frozen=True)
class ObservableEnrichment:
    """Everything enrichment produced for one observable this turn."""

    observable: Observable
    signals: tuple[ProviderSignal, ...] = ()
    skip_reason: str | None = None  # set ⇒ never sent to any provider
    # Providers that actually COMPLETED a lookup for this observable (returned
    # a signal or a clean no-data). Timeouts/errors/breaker-skips don't count —
    # the echo may only claim "unknown to them" about sources that answered.
    sources_answered: int = 0
    # B-001: who operates the address, per each source that said so. Kept
    # apart from `signals` on purpose — see NetworkContext.
    network: tuple[NetworkContext, ...] = ()


@dataclass(frozen=True)
class EnrichmentOutcome:
    items: tuple[ObservableEnrichment, ...]  # message order, one per observable
    provider_failures: dict[str, str] = field(default_factory=dict)  # name → reason

    @property
    def enriched(self) -> tuple[ObservableEnrichment, ...]:
        return tuple(item for item in self.items if item.skip_reason is None)
