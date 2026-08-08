"""Deterministic phishing verdict — S11 (ADR 0006: code owns the verdict, NO
LLM). Additive, itemized scoring over the parsed envelope + lookalike findings,
ported from SARA's `calculate_verdict` weights
(docs/probes/2026-07-18-sara-phishing-header-patterns.md §3), with the S10 rail
philosophy SARA lacked: absence of evidence can never yield BENIGN.

The verdict is a FLOOR, not just a value: `allowed` lists the contract-enum
values the model may render. Body content is the model's to read (lures,
urgency, credential asks — real signal the deterministic layer can't see), so
the model may RAISE severity above the code floor; it may never lower it, and
an un-analyzable or unauthenticated message may never be rendered BENIGN. The
floor is enforced by the contract validator's pin (chat.py), not by prompt
language — the S10 lesson (review finding A), applied on day one here.

BENIGN is a gate on POSITIVE evidence (DMARC pass, or SPF+DKIM pass, and zero
findings) — never a low-score default. SARA's `CLEAN` at score<20 is exactly
the shape the S10 review killed for alerts."""

from __future__ import annotations

from dataclasses import dataclass, field

from auspex.phishing.envelope import AuthResult, EmailEnvelope, Finding, FindingType
from auspex.phishing.lookalike import check_domain, is_brand_host, registrable_domain

_MALICIOUS_AT = 70
_SUSPICIOUS_AT = 20

# SARA-derived weights for the envelope-level findings (lookalike findings
# carry their own points, set where they're detected — lookalike.py).
_AUTH_POINTS = {
    FindingType.SPF_FAIL: 25,
    FindingType.SPF_SOFTFAIL: 10,
    FindingType.DKIM_FAIL: 25,
    FindingType.DMARC_FAIL: 20,
}


@dataclass(frozen=True)
class PhishingVerdict:
    """The code-decided disposition. `verdict` is the floor value (a member of
    the phishing_analysis contract enum); `allowed` is the full set the model
    may render (floor + raises); `score` is 0-100 or None when DEFERRED."""

    verdict: str
    allowed: tuple[str, ...]
    score: int | None
    findings: tuple[Finding, ...]
    recommendation: str
    deferred_reason: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


def _auth_findings(env: EmailEnvelope) -> list[Finding]:
    out: list[Finding] = []
    checks = (
        (env.spf, AuthResult.FAIL, FindingType.SPF_FAIL, "SPF failed"),
        (env.spf, AuthResult.SOFTFAIL, FindingType.SPF_SOFTFAIL, "SPF softfail"),
        (env.dkim, AuthResult.FAIL, FindingType.DKIM_FAIL, "DKIM signature failed"),
        (env.dmarc, AuthResult.FAIL, FindingType.DMARC_FAIL, "DMARC failed"),
    )
    for result, bad, ftype, label in checks:
        if result is bad:
            out.append(Finding(ftype, "HIGH", _AUTH_POINTS[ftype], label))
    return out


def _mismatch_findings(env: EmailEnvelope) -> list[Finding]:
    out: list[Finding] = []
    fd = registrable_domain(env.from_domain) if env.from_domain else None
    if fd and env.reply_to_domain and registrable_domain(env.reply_to_domain) != fd:
        out.append(
            Finding(
                FindingType.REPLY_TO_MISMATCH,
                "MEDIUM",
                20,
                f"Reply-To domain ({env.reply_to_domain}) differs from the "
                f"sender domain ({env.from_domain})",
            )
        )
    if fd and env.return_path_domain and registrable_domain(env.return_path_domain) != fd:
        out.append(
            Finding(
                FindingType.RETURN_PATH_MISMATCH,
                "MEDIUM",
                15,
                f"Return-Path domain ({env.return_path_domain}) differs from "
                f"the sender domain ({env.from_domain})",
            )
        )
    return out


def _display_name_findings(env: EmailEnvelope) -> list[Finding]:
    """Display-name spoofing: the name the user reads claims a different
    identity than the address the mail actually came from."""
    import re

    from auspex.phishing.brands import BRAND_ALLOWLIST

    if not env.from_display or not env.from_addr:
        return []
    out: list[Finding] = []
    display = env.from_display.lower()
    # An email address embedded in the display name that isn't the real sender
    # ("ceo@acme.com <attacker@evil.ru>") — the classic visual override.
    embedded = re.search(r"[\w.+-]+@[\w.-]+\.\w{2,}", display)
    if embedded and embedded.group(0) != env.from_addr:
        out.append(
            Finding(
                FindingType.DISPLAY_NAME_SPOOF,
                "HIGH",
                25,
                f"Display name shows a different address ({embedded.group(0)}) "
                f"than the actual sender ({env.from_addr})",
            )
        )
    # A protected brand in the display name while the sender domain isn't that
    # brand's ("PayPal Support <x@evil.ru>"). MEDIUM: ESP-mediated legitimate
    # mail can look like this; the finding names the tension, enrichment or the
    # analyst resolves it.
    for brand in BRAND_ALLOWLIST:
        if re.search(rf"\b{re.escape(brand)}\b", display) and not is_brand_host(
            env.from_domain or "", brand
        ):
            out.append(
                Finding(
                    FindingType.DISPLAY_NAME_SPOOF,
                    "MEDIUM",
                    15,
                    f"Display name invokes brand '{brand}' but the sender "
                    f"domain is {env.from_domain or 'absent'}",
                )
            )
            break
    return out


def collect_findings(env: EmailEnvelope) -> tuple[Finding, ...]:
    """All deterministic findings for one envelope: auth results, header
    mismatches, display-name spoofing, lookalike checks over every
    sender-adjacent domain, and parser anomalies."""
    findings: list[Finding] = []
    findings.extend(_auth_findings(env))
    findings.extend(_mismatch_findings(env))
    findings.extend(_display_name_findings(env))
    seen: set[str] = set()
    for domain in (env.from_domain, env.reply_to_domain, env.return_path_domain):
        if domain and domain not in seen:
            seen.add(domain)
            findings.extend(check_domain(domain))
    findings.extend(
        Finding(FindingType.HEADER_ANOMALY, "MEDIUM", 10, detail)
        for detail in env.anomalies
    )
    return tuple(findings)


def _deferred(
    findings: tuple[Finding, ...], reason: str, notes: tuple[str, ...]
) -> PhishingVerdict:
    return PhishingVerdict(
        verdict="DEFERRED",
        allowed=("DEFERRED", "SUSPICIOUS", "MALICIOUS"),
        score=None,
        findings=findings,
        recommendation=(
            f"Escalate for deep analysis — {reason}. Treat links and "
            "attachments as untrusted in the meantime."
        ),
        deferred_reason=reason,
        notes=notes,
    )


def decide_verdict(env: EmailEnvelope) -> PhishingVerdict:
    """Score the envelope and decide the verdict floor. Never BENIGN without
    positive authentication evidence; never anything but DEFERRED for a paste
    that didn't parse."""
    findings = collect_findings(env)

    if not env.parsed:
        return _deferred(
            findings,
            "the paste could not be parsed into an analyzable email envelope",
            env.notes,
        )

    score = min(sum(f.points for f in findings), 100)

    if score >= _MALICIOUS_AT:
        return PhishingVerdict(
            verdict="MALICIOUS",
            allowed=("MALICIOUS",),
            score=score,
            findings=findings,
            recommendation=(
                "Quarantine the message and block the sender. Identify users "
                "who received or interacted with it; reset credentials on any "
                "interaction with links or attachments."
            ),
            notes=env.notes,
        )
    if score >= _SUSPICIOUS_AT:
        return PhishingVerdict(
            verdict="SUSPICIOUS",
            allowed=("SUSPICIOUS", "MALICIOUS"),
            score=score,
            findings=findings,
            recommendation=(
                "Quarantine pending review and verify the sender out-of-band. "
                "Do not trust links or attachments until the findings are "
                "resolved."
            ),
            notes=env.notes,
        )
    if findings:
        # Weak signal (a lone anomaly / softfail): the deterministic layer
        # cannot decide — defer to deep analysis, never round down to BENIGN.
        names = ", ".join(dict.fromkeys(f.type.value for f in findings))
        return _deferred(
            findings,
            f"weak indicators ({names}) below the deterministic decision "
            "threshold",
            env.notes,
        )
    if env.auth_all_pass:
        return PhishingVerdict(
            verdict="BENIGN",
            allowed=("BENIGN", "SUSPICIOUS", "MALICIOUS"),
            score=0,
            findings=findings,
            recommendation=(
                "Sender authentication passes and no spoof indicators were "
                "found in the headers. Judge the message content on its own "
                "merits — an authenticated sender can still ask for something "
                "it shouldn't."
            ),
            notes=env.notes,
        )
    return _deferred(
        findings,
        "authentication results are absent or inconclusive — the sender "
        "cannot be verified from the headers alone",
        env.notes,
    )
