"""The typed, closed-vocabulary alert envelope — S10 (ADR 0006: code owns the
parse, no LLM). A multi-SIEM paste (CEF/LEEF/syslog/JSON) is normalized into
THIS shape; the additive scorer (scorer.py) reads only the envelope, never the
raw text. Keeping the envelope closed-vocab is what lets the score be a
deterministic function of parsed facts rather than of attacker-authored prose
(the alert paste is untrusted input — TD-013; parsing it to closed vocab is the
structural mitigation).

Everything here is a closed set or a normalized scalar. `severity` is one of five
levels or None (absent/undeterminable — which the DEFERRED rail treats as "no
data", never a defaulted LOW). `signals` is a closed tuple of named detections.
IOCs reuse the existing observable extractor. Nothing is free text the scorer
weights — free text lives only in `name`/`cmdline` for provenance/detail."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from auspex.classify.observables import Observable


class AlertFormat(StrEnum):
    """The multi-SIEM shapes the normalizer detects. `UNKNOWN` means detection
    failed — the scorer biases such an envelope to DEFERRED, never a LOW."""

    CEF = "cef"
    LEEF = "leef"
    SYSLOG = "syslog"
    JSON = "json"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    """Normalized severity vocabulary. Source formats carry wildly different
    scales (CEF 0-10, syslog PRI 0-7, JSON strings) — all map onto these five.
    Absence is represented by `severity=None` on the envelope, NOT by a level."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFORMATIONAL = "INFORMATIONAL"


class Signal(StrEnum):
    """Closed vocabulary of boolean detections the normalizer surfaces and the
    scorer weights. Detection (is it present?) is parse-time; weighting (what is
    it worth?) is the scorer's — the two never mix (ports SARA's `_add` signals,
    docs/probes/2026-07-18-sara-alert-triage-scorer.md)."""

    ENCODED_COMMAND = "encoded_command"  # -enc / base64 in a command line
    LOLBIN = "lolbin"  # living-off-the-land binary pattern
    SUSPICIOUS_PROCESS = "suspicious_process"  # known dual-use / attacker exe
    LOW_PREVALENCE = "low_prevalence"  # rare-in-environment flag


@dataclass(frozen=True)
class AlertEnvelope:
    """The normalized, closed-vocab result of parsing ONE alert paste. Every
    field is either a closed enum, a normalized scalar, or reused observables —
    the scorer consumes this and nothing else."""

    fmt: AlertFormat
    name: str | None = None  # alert name / signature (provenance + detail only)
    severity: Severity | None = None  # None = absent → "no data ≠ low risk"
    confidence: int | None = None  # 0-100 if the source carried one
    src: str | None = None  # source ip/host
    dst: str | None = None  # destination ip/host
    timestamp: str | None = None  # raw source timestamp (not reformatted)
    cmdline: str | None = None  # process command line, if any (detail)
    signals: tuple[Signal, ...] = ()
    iocs: tuple[Observable, ...] = ()
    mitre_techniques: tuple[str, ...] = ()  # T#### ids, upper-cased, de-duped
    mitre_tactics: tuple[str, ...] = ()  # TA#### ids
    # Whether ANY structured field was recovered. A paste we could not parse at
    # all (fmt=UNKNOWN, nothing extracted) must not read as a benign empty alert.
    parsed: bool = True
    # Parse notes for provenance (which keys mapped, what was skipped) — surfaced
    # in the triage detail, never scored.
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_severity(self) -> bool:
        return self.severity is not None

    @property
    def has_iocs(self) -> bool:
        return bool(self.iocs)

    @property
    def has_mitre(self) -> bool:
        return bool(self.mitre_techniques or self.mitre_tactics)
