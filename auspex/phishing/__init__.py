"""Deterministic phishing/header analysis — S11 (ADR 0006: code owns the parse
and the verdict; the model narrates around them). The phishing analogue of the
S10 alert pipeline: parse_email → typed EmailEnvelope → named findings →
verdict FLOOR (decide_verdict) → authoritative directive (render) → validator
pin. Closes the phishing portion of TD-013."""

from auspex.phishing.envelope import (
    AuthResult,
    EmailEnvelope,
    Finding,
    FindingType,
)
from auspex.phishing.parser import parse_email
from auspex.phishing.render import deterministic_phishing_block
from auspex.phishing.verdict import PhishingVerdict, decide_verdict
from auspex.phishing.victims import filter_victim_iocs

__all__ = [
    "AuthResult",
    "EmailEnvelope",
    "Finding",
    "FindingType",
    "PhishingVerdict",
    "decide_verdict",
    "deterministic_phishing_block",
    "filter_victim_iocs",
    "parse_email",
]
