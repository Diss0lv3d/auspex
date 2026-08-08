"""Evidence adapters + the curated cell tables — S12 (D-019).

The three deterministic layers Auspex already owns become ACH evidence here:
S5 enrichment signals, S10 alert envelopes, S11 phishing findings. Each closed
source vocabulary maps to an EvidenceKind, and each EvidenceKind carries ONE
per-hypothesis cell vector in `_CELLS` — a doctrine table in the SARA sense
(docs/probes/2026-08-08-sara-ach-analogues.md §4): a code constant, extended
via PR with a fixture test, never an env var and never model output.

The vectors are analyst priors, and the honest ones are deliberately
non-obvious: an encoded PowerShell command is strongly consistent with BOTH a
real attack and a red-team exercise; a lookalike domain is the hallmark of BOTH
genuine phishing and an authorized simulation. That shared consistency is not a
weakness — it is exactly what makes the info-gain layer (gain.py) prefer the
lookup that can split TP from TEST, instead of piling on confirmation.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from auspex.ach.types import Cell, Evidence, EvidenceKind, HypothesisKey
from auspex.alerts.envelope import AlertEnvelope, Severity, Signal
from auspex.enrich.types import ObservableEnrichment, VerdictLabel
from auspex.phishing.envelope import EmailEnvelope, FindingType
from auspex.phishing.verdict import PhishingVerdict

_TP = HypothesisKey.TRUE_POSITIVE
_FP = HypothesisKey.FALSE_POSITIVE
_BEN = HypothesisKey.BENIGN_ACTIVITY
_TEST = HypothesisKey.TEST_ACTIVITY


def _vec(tp: Cell, fp: Cell, benign: Cell, test: Cell) -> Mapping[HypothesisKey, Cell]:
    return MappingProxyType({_TP: tp, _FP: fp, _BEN: benign, _TEST: test})


# EvidenceKind → (TP, FP, BENIGN, TEST). Every kind covers all four hypotheses;
# None cells are reserved for future kinds that genuinely cannot speak to a
# hypothesis, not for hedging.
_CELLS: Mapping[EvidenceKind, Mapping[HypothesisKey, Cell]] = MappingProxyType(
    {
        # Third-party TI on the exact observable. Malicious strongly supports a
        # real attack and strongly contradicts misfire/authorized-admin; only
        # mildly contradicts TEST (red teams occasionally reuse known-bad
        # tooling, but simulation infra is rarely feed-listed). A benign read
        # is weak disconfirmation of attack — attackers abuse benign infra.
        EvidenceKind.ENRICHMENT_MALICIOUS: _vec(+2, -2, -2, -1),
        EvidenceKind.ENRICHMENT_SUSPICIOUS: _vec(+1, -1, -1, 0),
        EvidenceKind.ENRICHMENT_BENIGN: _vec(-1, +1, +1, 0),
        # S10 alert signals. Encoded commands are the classic move of attackers
        # AND red teams — deliberately consistent with both; admins rarely -enc.
        EvidenceKind.ALERT_ENCODED_COMMAND: _vec(+2, -1, -2, +2),
        # LOLBins are dual-use: genuine admin use is common → BENIGN neutral.
        EvidenceKind.ALERT_LOLBIN: _vec(+1, -1, 0, +1),
        EvidenceKind.ALERT_SUSPICIOUS_PROCESS: _vec(+1, 0, -1, +1),
        # A rare binary: attacks and test drops are rare; routine admin isn't.
        EvidenceKind.ALERT_LOW_PREVALENCE: _vec(+1, 0, -1, +1),
        # The vendor's own severity claim — direction only; the adapter caps
        # its credibility (a claim, not an observation).
        EvidenceKind.ALERT_HIGH_SEVERITY: _vec(+1, 0, -1, 0),
        EvidenceKind.ALERT_MITRE_MAPPED: _vec(+1, -1, -1, +1),
        # S11 phishing findings. Auth failures: spoofed phish fails auth;
        # legitimate mail rarely fails everything; simulations usually send
        # from infrastructure they control or allow-list → TEST neutral.
        EvidenceKind.EMAIL_AUTH_FAIL: _vec(+2, -1, -2, 0),
        # Positive, gateway-stamped auth evidence (post-S12-review _auth: body
        # prose and relay passes can no longer manufacture this kind).
        EvidenceKind.EMAIL_AUTH_PASS: _vec(-1, +1, +2, 0),
        EvidenceKind.EMAIL_SPOOF_INDICATOR: _vec(+2, -1, -2, +1),
        # Lookalike domains: the hallmark of real phish AND simulations — the
        # canonical TP/TEST non-discriminator that enrichment must split.
        EvidenceKind.EMAIL_LOOKALIKE_DOMAIN: _vec(+2, -2, -2, +2),
        EvidenceKind.EMAIL_HEADER_ANOMALY: _vec(+1, 0, -1, 0),
    }
)


def cells_for(kind: EvidenceKind) -> Mapping[HypothesisKey, Cell]:
    """The curated cell vector for an evidence kind."""
    return _CELLS[kind]


def _make(
    kind: EvidenceKind,
    statement: str,
    credibility: float,
    source: str,
    obs_id: str | None = None,
) -> Evidence:
    return Evidence(
        kind=kind,
        statement=statement,
        credibility=round(min(max(credibility, 0.0), 1.0), 3),
        cells=cells_for(kind),
        source=source,
        obs_id=obs_id,
    )


# ── S10 alerts ────────────────────────────────────────────────────────────────

_ALERT_SIGNAL_KINDS: Mapping[Signal, EvidenceKind] = MappingProxyType(
    {
        Signal.ENCODED_COMMAND: EvidenceKind.ALERT_ENCODED_COMMAND,
        Signal.LOLBIN: EvidenceKind.ALERT_LOLBIN,
        Signal.SUSPICIOUS_PROCESS: EvidenceKind.ALERT_SUSPICIOUS_PROCESS,
        Signal.LOW_PREVALENCE: EvidenceKind.ALERT_LOW_PREVALENCE,
    }
)

# Content-anchored detections (the normalizer saw the actual command line /
# process fields) outrank claims the alert merely asserts about itself.
_ALERT_SIGNAL_CREDIBILITY = 0.8
_ALERT_SEVERITY_CREDIBILITY = 0.5  # the vendor says so — a claim, not an observation
_ALERT_MITRE_CREDIBILITY = 0.6  # an ID field in the alert, spoofable by the source


def evidence_from_alert(env: AlertEnvelope) -> tuple[Evidence, ...]:
    """Deterministic ACH evidence from a parsed alert envelope. An unparsed
    envelope yields NO evidence (all hypotheses stay live at uniform weight —
    the ACH mirror of the S10 unparsed-always-defers rail)."""
    if not env.parsed:
        return ()
    out: list[Evidence] = []
    for sig in env.signals:
        kind = _ALERT_SIGNAL_KINDS.get(sig)
        if kind is None:  # a future Signal member without a vector: skip, never guess
            continue
        out.append(
            _make(
                kind,
                f"Alert telemetry carries the {sig.value} signal",
                _ALERT_SIGNAL_CREDIBILITY,
                "alert:signal",
            )
        )
    if env.severity in (Severity.HIGH, Severity.CRITICAL):
        out.append(
            _make(
                EvidenceKind.ALERT_HIGH_SEVERITY,
                f"Source rates the alert {env.severity.value}",
                _ALERT_SEVERITY_CREDIBILITY,
                "alert:severity",
            )
        )
    if env.mitre_techniques or env.mitre_tactics:
        refs = ", ".join((*env.mitre_tactics, *env.mitre_techniques)[:4])
        out.append(
            _make(
                EvidenceKind.ALERT_MITRE_MAPPED,
                f"Alert maps to ATT&CK ({refs})",
                _ALERT_MITRE_CREDIBILITY,
                "alert:mitre",
            )
        )
    return tuple(out)


# ── S11 phishing ─────────────────────────────────────────────────────────────

_FINDING_KINDS: Mapping[FindingType, EvidenceKind] = MappingProxyType(
    {
        FindingType.SPF_FAIL: EvidenceKind.EMAIL_AUTH_FAIL,
        FindingType.SPF_SOFTFAIL: EvidenceKind.EMAIL_AUTH_FAIL,
        FindingType.DKIM_FAIL: EvidenceKind.EMAIL_AUTH_FAIL,
        FindingType.DMARC_FAIL: EvidenceKind.EMAIL_AUTH_FAIL,
        FindingType.REPLY_TO_MISMATCH: EvidenceKind.EMAIL_SPOOF_INDICATOR,
        FindingType.RETURN_PATH_MISMATCH: EvidenceKind.EMAIL_SPOOF_INDICATOR,
        FindingType.DISPLAY_NAME_SPOOF: EvidenceKind.EMAIL_SPOOF_INDICATOR,
        FindingType.TYPOSQUAT_TLD_SWAP: EvidenceKind.EMAIL_LOOKALIKE_DOMAIN,
        FindingType.TYPOSQUAT_NEAR_MISS: EvidenceKind.EMAIL_LOOKALIKE_DOMAIN,
        FindingType.HOMOGRAPH: EvidenceKind.EMAIL_LOOKALIKE_DOMAIN,
        FindingType.BRAND_SUBDOMAIN_BAIT: EvidenceKind.EMAIL_LOOKALIKE_DOMAIN,
        FindingType.HEADER_ANOMALY: EvidenceKind.EMAIL_HEADER_ANOMALY,
    }
)

_FINDING_CREDIBILITY: Mapping[str, float] = MappingProxyType(
    {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.5}
)
_AUTH_PASS_CREDIBILITY = 0.9  # gateway-stamped (S12 review A/H hardened)


def evidence_from_email(env: EmailEnvelope, verdict: PhishingVerdict) -> tuple[Evidence, ...]:
    """Deterministic ACH evidence from a parsed email + its S11 findings. The
    findings are reused verbatim (detection stays in phishing/*); this adapter
    only assigns the ACH direction vector per finding type."""
    if not env.parsed:
        return ()
    out: list[Evidence] = [
        _make(
            _FINDING_KINDS[f.type],
            f.detail,
            _FINDING_CREDIBILITY.get(f.confidence, 0.5),
            "phishing:finding",
        )
        for f in verdict.findings
        if f.type in _FINDING_KINDS
    ]
    # Positive auth evidence exists only when the S11 BENIGN gate would accept
    # it — same predicate, so ACH can never see "auth passed" where the
    # phishing verdict would not.
    if env.auth_all_pass:
        out.append(
            _make(
                EvidenceKind.EMAIL_AUTH_PASS,
                "Sender authentication positively passed (gateway-stamped)",
                _AUTH_PASS_CREDIBILITY,
                "phishing:auth",
            )
        )
    return tuple(out)


# ── S5 enrichment ────────────────────────────────────────────────────────────

_LABEL_KINDS: Mapping[VerdictLabel, EvidenceKind] = MappingProxyType(
    {
        VerdictLabel.MALICIOUS: EvidenceKind.ENRICHMENT_MALICIOUS,
        VerdictLabel.SUSPICIOUS: EvidenceKind.ENRICHMENT_SUSPICIOUS,
        VerdictLabel.BENIGN: EvidenceKind.ENRICHMENT_BENIGN,
        # VerdictLabel.UNKNOWN deliberately absent: unknown is context, never
        # a claim (enrich/types.py) — it becomes NO evidence here.
    }
)

_MAX_STATEMENT = 300  # persisted analyst copy, defensively bounded


def evidence_from_enrichment(item: ObservableEnrichment) -> tuple[Evidence, ...]:
    """Deterministic ACH evidence from one observable's enrichment. One
    Evidence per provider SIGNAL (unknown labels drop); a skipped or
    unanswered observable yields nothing — unavailable is not negative."""
    if item.skip_reason is not None:
        return ()
    out: list[Evidence] = []
    for sig in item.signals:
        kind = _LABEL_KINDS.get(sig.label)
        if kind is None:
            continue
        statement = f"{sig.provider}: {sig.summary}"[:_MAX_STATEMENT]
        out.append(
            _make(
                kind,
                statement,
                sig.confidence,
                f"enrichment:{sig.provider}",
                obs_id=item.observable.obs_id,
            )
        )
    return tuple(out)
