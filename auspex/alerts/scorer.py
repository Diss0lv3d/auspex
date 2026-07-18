"""Additive 0-100 risk scorer with itemized contributions — S10 (ADR 0006: code
owns the score, NO LLM). Ports SARA's `alert_triage.assess_risk` pattern
(docs/probes/2026-07-18-sara-alert-triage-scorer.md): each signal adds points
with a NAMED contribution, never an opaque number, so an analyst (and the audit
trail) can see which signals fired and what each was worth.

The DEFERRED rail is the reason this module exists (SARA #1168/#1499, "no data ≠
low risk"): a signal-poor or evidence-pending-enrichment envelope must score
DEFERRED with the number NULLED — never a defaulted, confident-looking LOW. That
decision is CODE here, not a prompt instruction — the alert_triage contract's
enum merely allows DEFERRED; this scorer is what makes it fire.

Auspex note: no enrichment is wired into this path yet (the ioc_check→KB stretch
is parked), so `has_enrichment` is False in practice — any alert whose only
evidence is un-enriched IOCs defers pending enrichment, and every non-LOW score
carries the pending-enrichment tail. That is honest: the IOC verdicts genuinely
aren't in yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from auspex.alerts.envelope import AlertEnvelope, Severity, Signal

# Severity weights (SARA-verbatim). INFORMATIONAL is a real level worth a nod, but
# on its own it is NOT enough to triage — see `_meaningful_severity` / the rail.
_SEVERITY_POINTS = {
    Severity.CRITICAL: 40,
    Severity.HIGH: 30,
    Severity.MEDIUM: 20,
    Severity.LOW: 10,
    Severity.INFORMATIONAL: 5,
}

# Named signal weights (SARA-verbatim; artifact COUNT is deliberately NOT scored —
# what an IOC IS drives the score, via enrichment, not how many were parsed).
_SIGNAL_POINTS = {
    Signal.ENCODED_COMMAND: 20,
    Signal.LOLBIN: 15,
    Signal.SUSPICIOUS_PROCESS: 10,
    Signal.LOW_PREVALENCE: 10,
}
_SIGNAL_DETAIL = {
    Signal.ENCODED_COMMAND: "Encoded / base64 command line",
    Signal.LOLBIN: "Living-off-the-land binary pattern",
    Signal.SUSPICIOUS_PROCESS: "Suspicious / dual-use process",
    Signal.LOW_PREVALENCE: "Low local prevalence (unusual for this environment)",
}

# High-risk MITRE tactics (execution, persistence, priv-esc, defense-evasion,
# credential-access, lateral-movement, exfiltration, impact) — SARA-verbatim.
_HIGH_RISK_TACTICS = {
    "TA0002", "TA0003", "TA0004", "TA0005", "TA0006", "TA0008", "TA0010", "TA0040"
}

_CRITICAL_AT = 85
_HIGH_AT = 70
_MEDIUM_AT = 40


@dataclass(frozen=True)
class Contribution:
    """One named line item in the additive score (never an opaque number)."""

    signal: str
    points: int
    detail: str


@dataclass(frozen=True)
class RiskScore:
    """The scorer's verdict. `risk_level` is a value of the alert_triage contract
    enum (DEFERRED/LOW/MEDIUM/HIGH/CRITICAL); `score` is 0-100, or None when
    DEFERRED (nulled — a DEFERRED alert has no honest number)."""

    risk_level: str
    score: int | None
    contributions: tuple[Contribution, ...]
    recommendation: str
    true_positive_estimate: str  # HIGH/MEDIUM/LOW/UNKNOWN
    needs_deep_triage: bool
    deferred_reason: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def _meaningful_severity(sev: Severity | None) -> bool:
    """A severity that is itself evidence. None (absent) and INFORMATIONAL are
    NOT — an informational-only alert is as un-triageable as one with no
    severity (the S9 signal-poor CEF `…|0|` normalizes to INFORMATIONAL)."""
    return sev is not None and sev is not Severity.INFORMATIONAL


def _build_contributions(env: AlertEnvelope) -> list[Contribution]:
    out: list[Contribution] = []
    if env.severity is not None:
        out.append(
            Contribution(
                "severity", _SEVERITY_POINTS[env.severity], f"Severity: {env.severity.value}"
            )
        )
    conf = env.confidence
    if conf is not None and conf >= 80:
        out.append(Contribution("confidence_high", 15, f"High confidence: {conf}%"))
    elif conf is not None and conf >= 50:
        out.append(Contribution("confidence_medium", 10, f"Medium confidence: {conf}%"))
    for sig in env.signals:
        out.append(Contribution(sig.value, _SIGNAL_POINTS[sig], _SIGNAL_DETAIL[sig]))
    # MITRE: a high-risk tactic scores once; else any technique mapping.
    high_tactic = next((t for t in env.mitre_tactics if t in _HIGH_RISK_TACTICS), None)
    if high_tactic:
        out.append(
            Contribution("high_risk_mitre_tactic", 10, f"High-risk MITRE tactic: {high_tactic}")
        )
    elif env.mitre_techniques:
        shown = ", ".join(env.mitre_techniques[:5])
        out.append(Contribution("mitre_technique_mapped", 5, f"MITRE technique(s): {shown}"))
    return out


def _recommendation(level: str) -> tuple[str, str]:
    """(recommendation, true_positive_estimate) for a non-DEFERRED level."""
    return {
        "CRITICAL": (
            "Escalate immediately — contain the host and investigate the process tree.",
            "HIGH",
        ),
        "HIGH": ("Escalate — investigate the process tree and contain if confirmed.", "HIGH"),
        "MEDIUM": (
            "Investigate within SLA — verify legitimacy and check for lateral movement.",
            "MEDIUM",
        ),
        "LOW": ("Triage and verify — likely benign, but confirm with the asset owner.", "LOW"),
    }[level]


def score_alert(env: AlertEnvelope, *, has_enrichment: bool = False) -> RiskScore:
    """Score a normalized alert envelope. Returns a DEFERRED verdict (score None)
    on a signal-poor or evidence-pending-enrichment envelope — never a defaulted
    LOW. `has_enrichment` is False on the S10 fast-path (no enrichment wired)."""
    contributions = _build_contributions(env)
    non_severity = [c for c in contributions if c.signal != "severity"]
    has_ioc = env.has_iocs

    # ── DEFERRED rail — "no data ≠ low risk" ─────────────────────────────────
    # (a) signal-poor: no meaningful severity, no enrichment, no scoring signal,
    #     and no IOC artifact to enrich → nothing to honestly triage.
    if (
        not _meaningful_severity(env.severity)
        and not has_enrichment
        and not non_severity
        and not has_ioc
    ):
        reason = "no severity, no IOCs, no MITRE mapping, and no process-level indicators"
        if not env.parsed:
            reason = "the alert could not be parsed into a triageable envelope"
        return RiskScore(
            risk_level="DEFERRED",
            score=None,
            contributions=tuple(contributions),
            recommendation=(
                "Insufficient envelope signal — escalate to enrichment and deep "
                "triage before disposition. Fast-path triage cannot honestly "
                f"assess this alert: {reason}."
            ),
            true_positive_estimate="UNKNOWN",
            needs_deep_triage=True,
            deferred_reason=f"signal-poor envelope ({reason})",
            notes=env.notes,
        )
    # (b) evidence pending enrichment: IOC artifacts are present but un-enriched
    #     and nothing else scored — the real evidence is in the IOC verdicts, so
    #     locking in a severity-only floor would be dishonest.
    if not has_enrichment and has_ioc and not non_severity:
        counts: dict[str, int] = {}
        for o in env.iocs:
            counts[o.type.value] = counts.get(o.type.value, 0) + 1
        summary = ", ".join(f"{n} {k}" for k, n in counts.items()) or "IOCs"
        sev_txt = env.severity.value if env.severity else "no"
        return RiskScore(
            risk_level="DEFERRED",
            score=None,
            contributions=tuple(contributions),
            recommendation=(
                f"Severity-only signal ({sev_txt}); {summary} carried in the payload "
                "but not yet enriched. Fast-path triage cannot honestly score the "
                "alert — the threat evidence is in the IOC verdicts. Escalate to "
                "enrichment, then re-triage with enrichment context."
            ),
            true_positive_estimate="UNKNOWN",
            needs_deep_triage=True,
            deferred_reason=f"severity-only, {summary} pending enrichment",
            notes=env.notes,
        )

    # ── additive score → level ───────────────────────────────────────────────
    total = min(sum(c.points for c in contributions), 100)
    if total >= _CRITICAL_AT:
        level = "CRITICAL"
    elif total >= _HIGH_AT:
        level = "HIGH"
    elif total >= _MEDIUM_AT:
        level = "MEDIUM"
    else:
        level = "LOW"
    recommendation, tpe = _recommendation(level)
    if total >= _MEDIUM_AT and not has_enrichment:
        recommendation += (
            " · ⏳ pending enrichment — re-run after IOC verdicts populate; score may shift"
        )
    return RiskScore(
        risk_level=level,
        score=total,
        contributions=tuple(contributions),
        recommendation=recommendation,
        true_positive_estimate=tpe,
        needs_deep_triage=False,
        notes=env.notes,
    )
