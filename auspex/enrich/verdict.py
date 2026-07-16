"""Verdict synthesis + decay-curve parameters — S5, the first Living Verdicts
brick (D-017 documents the field semantics).

Combining rule (v1, deliberately simple): the worst credible signal wins the
label; confidence is the strongest confidence among signals carrying that
label. Cross-provider agreement boosting is parked in IDEAS.md. The defanged
verdict FLOOR (defanged input ⇒ at least suspicious) is S7 scope — the
`Observable.defanged` flag already travels with the observable.

Decay: verdicts age. Effective confidence at time t is
    floor + (confidence_at_write - floor) * 2^(-(t - created_at) / half_life)
Half-life defaults encode how fast each observable class churns: IPs get
reassigned in days; domains/URLs get cleaned or parked in weeks; a hash IS the
artifact — a malicious file never becomes less malicious, it only becomes less
*relevant*, slowly.
"""

from dataclasses import dataclass

from auspex.classify.observables import Observable, ObservableType
from auspex.enrich.types import SEVERITY, ProviderSignal, VerdictLabel

HALF_LIFE_DAYS: dict[ObservableType, float] = {
    ObservableType.IPV4: 14.0,
    ObservableType.IPV6: 14.0,
    ObservableType.DOMAIN: 30.0,
    ObservableType.URL: 30.0,
    ObservableType.EMAIL: 30.0,
    ObservableType.SHA256: 365.0,
    ObservableType.SHA1: 365.0,
    ObservableType.MD5: 365.0,
    ObservableType.CVE: 365.0,  # no CVE provider yet (KB lands S6); future-proof default
}

ENRICHMENT_FLOOR = 0.0  # S5 enrichment verdicts may fully decay; S7 adds floors


@dataclass(frozen=True)
class Verdict:
    label: VerdictLabel
    confidence_at_write: float  # 0..1
    half_life_days: float
    floor: float
    source: str  # e.g. "enrichment:OTX,ThreatFox" — the writers, auditably


def effective_confidence(
    *, confidence_at_write: float, floor: float, half_life_days: float, age_days: float
) -> float:
    """The D-017 decay curve, executable. Nothing reads it until S7 renders
    stale verdicts — it lives here so the semantics are pinned by a test, not
    only by prose in DECISIONS.md."""
    return floor + (confidence_at_write - floor) * 2 ** (-age_days / half_life_days)


def synthesize(observable: Observable, signals: tuple[ProviderSignal, ...]) -> Verdict | None:
    """One verdict from this turn's signals, or None when nothing was said
    (an unknown observable gets no verdict row — there is nothing to decay)."""
    if not signals:
        return None
    label = max((s.label for s in signals), key=lambda lb: SEVERITY[lb])
    confidence = max((s.confidence for s in signals if s.label is label), default=0.0)
    contributors = sorted({s.provider for s in signals})
    return Verdict(
        label=label,
        confidence_at_write=round(min(max(confidence, 0.0), 1.0), 3),
        half_life_days=HALF_LIFE_DAYS[observable.type],
        floor=ENRICHMENT_FLOOR,
        source="enrichment:" + ",".join(contributors),
    )
