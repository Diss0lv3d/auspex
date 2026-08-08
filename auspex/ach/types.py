"""Typed, closed-vocabulary core of the ACH engine — S12 (D-019: the matrix is
code, the vocabularies are closed, the tables are tested constants).

An investigation holds N competing hypotheses about ONE subject (an alert or an
email). Evidence items score FOR or AGAINST each hypothesis through a cell
vector; the matrix layer (matrix.py) ranks hypotheses by LEAST weighted
inconsistency (Heuer: disconfirmation is diagnostic, confirmation is cheap) and
the gain layer (gain.py) picks the next lookup by expected information gain.
Nothing in this package calls a model — the model may later PROPOSE hypotheses
or evidence through a contract; it never decides a cell, a weight, a status, or
the next lookup (ADR 0006, the SARA lesson: its prompt-only ACH was structurally
discarded by its own output template, docs/probes/2026-08-08-sara-ach-analogues.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class SubjectKind(StrEnum):
    """What kind of thing the investigation is about. Closed: each kind has a
    deterministic parser (S10 alerts, S11 emails) and a hypothesis catalog."""

    ALERT = "alert"
    EMAIL = "email"


class HypothesisKey(StrEnum):
    """The four standard competing explanations (ROADMAP S12). Keys are stable
    identifiers shared across subject kinds; the analyst-facing wording is
    per-kind (HYPOTHESIS_CATALOG)."""

    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"
    BENIGN_ACTIVITY = "benign_activity"
    TEST_ACTIVITY = "test_activity"


@dataclass(frozen=True)
class Hypothesis:
    """One candidate explanation. `label` is the subject-kind-specific analyst
    wording; identity is `key`."""

    key: HypothesisKey
    label: str


# Per-kind analyst wording. Seeding is deterministic (D-019): every new
# investigation starts with the full catalog for its subject kind — ACH's whole
# point is that the unflattering alternatives are always on the table.
HYPOTHESIS_CATALOG: Mapping[SubjectKind, tuple[Hypothesis, ...]] = MappingProxyType(
    {
        SubjectKind.ALERT: (
            Hypothesis(
                HypothesisKey.TRUE_POSITIVE,
                "True positive — the alert reflects real malicious activity",
            ),
            Hypothesis(
                HypothesisKey.FALSE_POSITIVE,
                "False positive — the detection logic misfired on innocuous telemetry",
            ),
            Hypothesis(
                HypothesisKey.BENIGN_ACTIVITY,
                "Benign activity — real but authorized/administrative action "
                "matching the signature",
            ),
            Hypothesis(
                HypothesisKey.TEST_ACTIVITY,
                "Authorized test — red team, pentest, or detection-engineering exercise",
            ),
        ),
        SubjectKind.EMAIL: (
            Hypothesis(
                HypothesisKey.TRUE_POSITIVE,
                "Genuine phishing — a real credential-harvest or fraud attempt",
            ),
            Hypothesis(
                HypothesisKey.FALSE_POSITIVE,
                "Reporting error — the message is ordinary and was flagged in error",
            ),
            Hypothesis(
                HypothesisKey.BENIGN_ACTIVITY,
                "Legitimate message — unusual but explainable features "
                "(ESP mediation, forwarding, marketing tooling)",
            ),
            Hypothesis(
                HypothesisKey.TEST_ACTIVITY,
                "Phishing simulation — an authorized security-awareness exercise",
            ),
        ),
    }
)


def seed_hypotheses(kind: SubjectKind) -> tuple[Hypothesis, ...]:
    """The deterministic starting hypothesis set for a subject kind."""
    return HYPOTHESIS_CATALOG[kind]


class EvidenceKind(StrEnum):
    """Closed vocabulary of deterministic evidence. Each kind maps to ONE cell
    vector in evidence.py — detection lives in the source layers (S5/S10/S11),
    the ACH direction table lives here-adjacent, weighting stays out of both
    (the S10 signal/scorer split, applied a third time)."""

    # from the S5 enrichment fan-out (per provider signal; NO_SIGNAL = a
    # COMPLETED lookup that no answering source had a claim about)
    ENRICHMENT_MALICIOUS = "enrichment_malicious"
    ENRICHMENT_SUSPICIOUS = "enrichment_suspicious"
    ENRICHMENT_BENIGN = "enrichment_benign"
    ENRICHMENT_NO_SIGNAL = "enrichment_no_signal"
    # from the S10 alert envelope
    ALERT_ENCODED_COMMAND = "alert_encoded_command"
    ALERT_LOLBIN = "alert_lolbin"
    ALERT_SUSPICIOUS_PROCESS = "alert_suspicious_process"
    ALERT_LOW_PREVALENCE = "alert_low_prevalence"
    ALERT_HIGH_SEVERITY = "alert_high_severity"
    ALERT_MITRE_MAPPED = "alert_mitre_mapped"
    # from the S11 phishing findings
    EMAIL_AUTH_FAIL = "email_auth_fail"
    EMAIL_AUTH_PASS = "email_auth_pass"  # noqa: S105 — an evidence kind, not a secret
    EMAIL_SPOOF_INDICATOR = "email_spoof_indicator"
    EMAIL_LOOKALIKE_DOMAIN = "email_lookalike_domain"
    EMAIL_HEADER_ANOMALY = "email_header_anomaly"


# A cell is the evidence item's bearing on ONE hypothesis:
#   +2 strongly consistent · +1 consistent · 0 neutral · −1 inconsistent ·
#   −2 strongly inconsistent · None = NOT AVAILABLE for that hypothesis.
# None is excluded from all scoring — absence of evidence is not evidence
# (the enrich/types.py:8-11 doctrine, structural since S5).
Cell = int | None

CELL_MIN, CELL_MAX = -2, 2


@dataclass(frozen=True)
class Evidence:
    """One scored piece of evidence — never an opaque flag. `credibility` is
    how much this item can move the matrix (0..1, source-dependent: a
    gateway-stamped auth result outranks a vendor severity claim); `cells`
    holds the per-hypothesis bearing; `source` is provenance
    ("alert:signal", "phishing:finding", "enrichment:OTX"); `obs_id` links
    enrichment evidence back to the observable it covers (candidate
    exclusion in gain.py).

    `evidence_id` is the ach_evidence row uuid — None on freshly-adapted
    evidence, filled by the store on load. It is the STABLE identity a
    citation stands on (S13): row uuids never change and never renumber when
    a retired-kind sibling is skipped, unlike a load index."""

    kind: EvidenceKind
    statement: str
    credibility: float
    cells: Mapping[HypothesisKey, Cell]
    source: str
    obs_id: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    evidence_id: str | None = None
