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
    """A provider call failed (network, 5xx, auth, rate limit, contract break).

    Distinct from "no data": failures feed the circuit breaker and the
    DEFERRED rail ("source unavailable"), never a verdict.
    """


@dataclass(frozen=True)
class ProviderSignal:
    provider: str  # display name, e.g. "ThreatFox" (data source — not the engine)
    label: VerdictLabel
    confidence: float  # 0..1 (provider-mapped; see each provider module)
    summary: str  # one plain-text evidence line, user-facing
    evidence: dict = field(default_factory=dict)  # trimmed, JSON-safe


@dataclass(frozen=True)
class ObservableEnrichment:
    """Everything enrichment produced for one observable this turn."""

    observable: Observable
    signals: tuple[ProviderSignal, ...] = ()
    skip_reason: str | None = None  # set ⇒ never sent to any provider


@dataclass(frozen=True)
class EnrichmentOutcome:
    items: tuple[ObservableEnrichment, ...]  # message order, one per observable
    provider_failures: dict[str, str] = field(default_factory=dict)  # name → reason

    @property
    def enriched(self) -> tuple[ObservableEnrichment, ...]:
        return tuple(item for item in self.items if item.skip_reason is None)
