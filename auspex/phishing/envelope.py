"""The typed, closed-vocabulary email envelope + named findings — S11 (ADR
0006: code owns the parse, no LLM). A pasted email is reduced to THIS shape by
parser.py; the verdict layer (verdict.py) reads only the envelope and the
findings, never the raw paste. Same structural TD-013 mitigation as the S10
alert envelope: the message body stays attacker prose in the user turn, but the
Verdict is a deterministic function of parsed facts.

Everything here is a closed set or a normalized scalar. Authentication results
are the RFC 8601 result tokens or None (absent — which biases the verdict to
DEFERRED, never BENIGN: "an un-analyzable message is not a safe one"). Findings
are NAMED with a confidence and points, mirroring the alert scorer's
contributions (docs/probes/2026-07-18-sara-phishing-header-patterns.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from auspex.classify.observables import Observable


class AuthResult(StrEnum):
    """RFC 8601 authentication result tokens (SPF/DKIM/DMARC). Absence is
    `None` on the envelope, NOT a member — no result is not a failed result,
    but it is also never treated as a pass."""

    PASS = "pass"  # noqa: S105 — an RFC 8601 auth result token, not a secret
    FAIL = "fail"
    SOFTFAIL = "softfail"
    NEUTRAL = "neutral"
    NONE = "none"
    TEMPERROR = "temperror"
    PERMERROR = "permerror"
    BESTGUESSPASS = "bestguesspass"


class FindingType(StrEnum):
    """Closed vocabulary of deterministic phishing findings. Detection lives in
    parser.py / lookalike.py; weighting lives in verdict.py — never mixed
    (the S10 signal/scorer split)."""

    SPF_FAIL = "spf_fail"
    SPF_SOFTFAIL = "spf_softfail"
    DKIM_FAIL = "dkim_fail"
    DMARC_FAIL = "dmarc_fail"
    REPLY_TO_MISMATCH = "reply_to_mismatch"
    RETURN_PATH_MISMATCH = "return_path_mismatch"
    DISPLAY_NAME_SPOOF = "display_name_spoof"
    TYPOSQUAT_TLD_SWAP = "typosquat_tld_swap"
    TYPOSQUAT_NEAR_MISS = "typosquat_near_miss"
    HOMOGRAPH = "homograph"
    BRAND_SUBDOMAIN_BAIT = "brand_subdomain_bait"
    HEADER_ANOMALY = "header_anomaly"


@dataclass(frozen=True)
class Finding:
    """One named deterministic finding — never an opaque flag. `confidence` is
    HIGH/MEDIUM/LOW (how sure the detector is of intent), `points` feed the
    additive verdict score (SARA-derived weights, see the probe doc)."""

    type: FindingType
    confidence: str  # HIGH | MEDIUM | LOW
    points: int
    detail: str  # analyst-facing; flattened before entering any directive


@dataclass(frozen=True)
class EmailEnvelope:
    """The normalized result of parsing ONE pasted email. Free text lives only
    in provenance fields (subject, display name) — the verdict never weighs it."""

    from_display: str | None = None
    from_addr: str | None = None
    from_domain: str | None = None
    reply_to_addr: str | None = None
    reply_to_domain: str | None = None
    return_path_addr: str | None = None
    return_path_domain: str | None = None
    recipient_addrs: tuple[str, ...] = ()  # To/Cc/Delivered-To — the victims
    recipient_domains: tuple[str, ...] = ()
    subject: str | None = None
    spf: AuthResult | None = None
    dkim: AuthResult | None = None
    dmarc: AuthResult | None = None
    received_count: int = 0
    header_count: int = 0  # recognized RFC-5322 headers found
    anomalies: tuple[str, ...] = ()  # named header anomalies (parser-detected)
    iocs: tuple[Observable, ...] = ()  # non-CVE observables from the whole paste
    # Whether the paste parsed into an analyzable envelope (≥2 recognized
    # headers, mirroring the resolver's email gate). False → verdict DEFERRED.
    parsed: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def auth_present(self) -> bool:
        return any(r is not None for r in (self.spf, self.dkim, self.dmarc))

    @property
    def auth_all_pass(self) -> bool:
        """Positive evidence the sender authenticated: DMARC pass (alignment is
        DMARC's own job), or SPF and DKIM both pass when DMARC is absent."""
        if self.dmarc is AuthResult.PASS:
            return True
        return self.spf is AuthResult.PASS and self.dkim is AuthResult.PASS
