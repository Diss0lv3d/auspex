"""Code-owned mode resolver — S9 (ADR 0006 spirit: code owns routing, not the
model). Only DEEP turns reach here — the 92% shortcut path (greeting/identity/
ioc_check/cve_lookup/definition) already answered with zero LLM. The resolver
picks which mode shapes this deep turn's system prompt + output contract.

**Format beats keywords** — the load-bearing rule. A CEF alert paste that
contains the word "phishing" is still ALERT_TRIAGE; an email whose body
mentions a CVE is still PHISHING_ANALYSIS. Structural signals (log/alert
envelopes, email headers) win over any keyword, because the format is a much
stronger signal of intent than a word that happens to appear. Priority is fixed
in code and pinned by tests; nothing here calls the model.
"""

from __future__ import annotations

import re

from auspex.classify.classifier import _ioc_shaped, _is_alert_paste, _is_email_paste
from auspex.classify.observables import Observable, ObservableType
from auspex.modes.catalog import Mode

# `_is_email_paste` (≥2 RFC-5322 header lines → a pasted email) is defined in
# the classifier so the 92/8 gate and this resolver key PHISHING_ANALYSIS off
# the SAME rule — the classifier fast-tracks email pastes to DEEP, and this
# resolver then routes them to PHISHING_ANALYSIS. One definition, no drift.

_BRIEF_RE = re.compile(
    r"\b(?:brief|briefing|summar(?:y|ize|ise)|tl;?dr|rundown|"
    r"give me a (?:short|quick)|write(?:\s+me)? a report)\b",
    re.IGNORECASE,
)

_DEFINITION_RE = re.compile(
    r"^\s*(?:what\s+is|what\s+are|what's|define|definition\s+of|meaning\s+of)\b",
    re.IGNORECASE,
)

# Threat-intel keyword surface (actors, campaigns, malware, vuln framing). This
# is the LOWEST-priority keyword tier — format and observables beat it.
_THREAT_INTEL_RE = re.compile(
    r"\b(?:apt\d*|threat\s+actor|adversary|campaign|malware|ransomware|"
    r"botnet|c2|command\s+and\s+control|ttps?|cve-\d|exploit|zero-?day|"
    r"vulnerabilit(?:y|ies)|intrusion\s+set|threat\s+intel)\b",
    re.IGNORECASE,
)


# D-044: ANY security vocabulary at all. Deliberately much wider than the
# threat-intel tier above, and deliberately generous with common words ("logs",
# "access", "risk", "keys"): it decides only whether the default stays
# threat_intel, so a word too many keeps today's behaviour, and a word too few
# sends a security question to `general`, which loses its structure. The bias is
# measured, not assumed: docs/probes/s27-modes/probe_resolver_fallback.py.
_SECURITY_RE = re.compile(
    r"\b(?:secur\w*|attack\w*|threat\w*|vulnerab\w*|malicious|malware|phish\w*|"
    r"breach\w*|compromis\w*|incident\w*|alert\w*|soc|siem|edr|xdr|ndr|firewall\w*|"
    r"waf|ids|ips|exploit\w*|cves?|iocs?|indicators?|ransom\w*|credential\w*|"
    r"passwords?|passphrases?|mfa|2fa|authenticat\w*|authori[sz]\w*|privileg\w*|"
    r"access|lateral|persistence|detect\w*|mitre|att&ck|logs?|logging|forensic\w*|"
    r"hunt\w*|sandbox\w*|c2|beacon\w*|payloads?|backdoor\w*|rootkit\w*|trojan\w*|"
    r"worms?|botnet\w*|ddos|spoof\w*|encrypt\w*|decrypt\w*|patch\w*|harden\w*|"
    r"zero[- ]trust|iam|kerberos|ntlm|active directory|sso|tokens?|certificates?|"
    r"tls|ssl|vpn|proxy|dlp|exfiltrat\w*|leak\w*|fraud\w*|scam\w*|impersonat\w*|"
    r"social engineering|bec|wire transfer|suspicious|abus\w*|inject\w*|tor|"
    r"perimeter|risk\w*|audit\w*|pen ?test\w*|red team|blue team|ciso|cyber\w*|"
    r"hack\w*|stolen|insider|keys?|secrets?|safe|safety|customer data|personal data|"
    r"pii|gdpr|compliance|nist|iso 27001|soc ?2|"
    # Approach 2 (S27): the IT, identity and payments vocabulary an analyst uses
    # to DESCRIBE a security situation without naming it ("an admin account was
    # created at 3am", "a laptop keeps calling the same server"). Approach 1,
    # security words alone, sent 15 of 40 such questions to `general` on an
    # independently written battery.
    r"accounts?|log ?ins?|logged|sign[- ]?ins?|signed in|admins?|administrators?|"
    r"laptops?|servers?|endpoints?|hosts?|devices?|phones?|usb|networks?|cloud|aws|"
    r"azure|gcp|s3|buckets?|backups?|powershell|cmd|registry|scheduled tasks?|dns|"
    r"mailbox\w*|inbox|email rules?|forwarding|wire|payments?|charged?|chargebacks?|"
    r"gift cards?|refunds?|invoices?|isolat\w*|contain\w*|revok\w*|quarantin\w*|"
    r"escalat\w*|investigat\w*|on-call|shared drive|permissions?|vpn|api|byod)\b",
    re.IGNORECASE,
)


def _has_scoreable_ioc(observables: tuple[Observable, ...], q: str) -> bool:
    """Whether this turn is about indicators worth enriching. Delegates to the
    classifier's `_ioc_shaped` so the resolver applies the SAME rule the 92/8
    gate does — a bare CVE is threat-intel framing (not an indicator), and a
    ubiquitous domain in prose (microsoft.com, github.com) is NOT a scoreable
    IOC unless the query is short or defanged. The prior naive `any(non-CVE)`
    hijacked ordinary prose ("brief on why campaigns abuse microsoft.com") into
    IOC_ENRICHMENT, shadowing BRIEF/DEFINITION (S9 review, correctness lens)."""
    return _ioc_shaped(observables, q)


def resolve_mode(message: str, observables: tuple[Observable, ...]) -> Mode:
    """Resolve a DEEP turn to its mode. Priority, high → low:

    1. alert/log envelope (CEF/LEEF/syslog/JSON)  → ALERT_TRIAGE
    2. email header envelope                       → PHISHING_ANALYSIS
    3. a scoreable indicator (ioc-shaped)          → IOC_ENRICHMENT
    4. explicit brief/summary ask                  → BRIEF
    5. definition-shaped opener                    → DEFINITION
    6. threat-intel keywords (incl. bare CVE)      → THREAT_INTEL
    7. any security vocabulary, or any observable  → THREAT_INTEL
    8. default — no security signal at all         → GENERAL (D-044)

    Steps 1–3 are FORMAT/structure and beat the keyword tiers 4–6."""
    q = message.strip()
    if _is_alert_paste(q):
        return Mode.ALERT_TRIAGE
    if _is_email_paste(q):
        return Mode.PHISHING_ANALYSIS
    if _has_scoreable_ioc(observables, q):
        return Mode.IOC_ENRICHMENT
    if _BRIEF_RE.search(q):
        return Mode.BRIEF
    if _DEFINITION_RE.match(q):
        return Mode.DEFINITION
    if _THREAT_INTEL_RE.search(q) or any(o.type is ObservableType.CVE for o in observables):
        return Mode.THREAT_INTEL
    if _SECURITY_RE.search(q) or observables:
        return Mode.THREAT_INTEL
    return Mode.GENERAL
