"""Alert normalization + additive risk scoring (S10) — code-owned, no LLM.

A multi-SIEM paste (CEF/LEEF/syslog/JSON) is `normalize()`d into a typed,
closed-vocab `AlertEnvelope`, then `score_alert()`d into an additive 0-100
`RiskScore` with itemized contributions. The DEFERRED rail ("no data ≠ low
risk") lives in the scorer as CODE, feeding the S9 `alert_triage` mode contract.
"""

from auspex.alerts.envelope import AlertEnvelope, AlertFormat, Severity, Signal
from auspex.alerts.normalizer import detect_format, normalize
from auspex.alerts.scorer import Contribution, RiskScore, score_alert

__all__ = [
    "AlertEnvelope",
    "AlertFormat",
    "Contribution",
    "RiskScore",
    "Severity",
    "Signal",
    "detect_format",
    "normalize",
    "score_alert",
]
