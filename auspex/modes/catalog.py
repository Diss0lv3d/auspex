"""The six response modes and their typed contracts — S9.

Six modes ONLY (scope-locked, ROADMAP S9): definition, ioc_enrichment,
threat_intel, alert_triage, phishing_analysis, brief. Each is a `ModeContract`
whose fields compile to the DEEP-path system directive and the output validator
(contract.py). Adding a seventh mode is a scope decision, not a code edit — the
enum and this catalog are the closed set the resolver maps onto.

alert_triage ships with the DEFERRED rail from day one (SARA's
sara/agents/alert_triage.py:1414-1554, snapshot
docs/probes/2026-07-18-sara-orchestrator-deferred.md): a signal-poor alert must
render `Risk: DEFERRED`, never a defaulted LOW — "no data ≠ low risk". The enum
+ the rule are the contract; the resolver/renderer enforce it in code.
"""

from __future__ import annotations

from enum import StrEnum

from auspex.modes.contract import ContractField, ModeContract


class Mode(StrEnum):
    DEFINITION = "definition"
    IOC_ENRICHMENT = "ioc_enrichment"
    THREAT_INTEL = "threat_intel"
    ALERT_TRIAGE = "alert_triage"
    PHISHING_ANALYSIS = "phishing_analysis"
    BRIEF = "brief"


_RISK_LEVELS = ("DEFERRED", "LOW", "MEDIUM", "HIGH", "CRITICAL")

CONTRACTS: dict[Mode, ModeContract] = {
    Mode.DEFINITION: ModeContract(
        name=Mode.DEFINITION.value,
        purpose=(
            "explain a security concept precisely for an analyst who wants the "
            "working definition, not a lecture."
        ),
        fields=(
            ContractField("Definition", "one or two sentences stating what the term means."),
            ContractField(
                "In practice",
                "how it shows up in an investigation — signals, telemetry, or "
                "where an analyst meets it.",
            ),
            ContractField(
                "Related",
                "closely related concepts or techniques by name/id, if any.",
                required=False,
            ),
        ),
        rules=(
            "If you are not sure the term is a real security concept, say so "
            "rather than inventing a definition.",
        ),
    ),
    Mode.IOC_ENRICHMENT: ModeContract(
        name=Mode.IOC_ENRICHMENT.value,
        purpose="assess one or more indicators of compromise and what is known about them.",
        fields=(
            ContractField("Indicators", "each indicator, normalized, with its type."),
            ContractField(
                "Assessment",
                "what is known/knowable about each — reputation, category, "
                "associations — and the confidence.",
            ),
            ContractField("Recommended action", "the analyst's next step for these indicators."),
        ),
        rules=(
            "Never assert a reputation verdict you do not have evidence for; "
            "absence of data is 'unknown', not 'benign'.",
        ),
    ),
    Mode.THREAT_INTEL: ModeContract(
        name=Mode.THREAT_INTEL.value,
        purpose=(
            "give an analyst-to-analyst read on a threat, actor, campaign, "
            "malware family, or vulnerability."
        ),
        fields=(
            ContractField("Summary", "the core of what this threat is, in two or three sentences."),
            ContractField(
                "Key facts",
                "the load-bearing specifics — TTPs, affected systems, known "
                "activity, CVE/CVSS if relevant.",
            ),
            ContractField(
                "Assessment",
                "your analytic judgement — severity, relevance, and how confident "
                "you are (with the unknowns).",
            ),
        ),
        rules=(
            "Separate what is established from what you are inferring; name the "
            "gaps in your knowledge.",
        ),
    ),
    Mode.ALERT_TRIAGE: ModeContract(
        name=Mode.ALERT_TRIAGE.value,
        purpose="triage a security alert and decide how urgently it needs attention.",
        fields=(
            ContractField(
                "Risk",
                "the risk level for this alert.",
                allowed_values=_RISK_LEVELS,
            ),
            ContractField("Reasoning", "the signals that drove the risk level."),
            ContractField("Recommendation", "what the analyst should do next."),
        ),
        rules=(
            "No data ≠ low risk. If the alert carries no meaningful signal to score "
            "(no severity, no enrichment, no IOCs, no MITRE mapping), the Risk is "
            "DEFERRED — never a defaulted LOW — and the Recommendation escalates to "
            "enrichment/deep triage. A confident-looking LOW on an un-triageable "
            "alert is the failure this mode exists to prevent.",
            "If IOCs are present but not yet enriched, say the score is pending "
            "enrichment rather than locking in a severity-only floor.",
        ),
    ),
    Mode.PHISHING_ANALYSIS: ModeContract(
        name=Mode.PHISHING_ANALYSIS.value,
        purpose="analyze a suspected phishing message and judge whether it is malicious.",
        fields=(
            ContractField(
                "Verdict",
                "the disposition of the message.",
                allowed_values=("DEFERRED", "BENIGN", "SUSPICIOUS", "MALICIOUS"),
            ),
            ContractField(
                "Indicators",
                "the phishing signals present — sender/reply-path anomalies, "
                "links, lures, spoofing, urgency.",
            ),
            ContractField("Recommendation", "what to do with the message and any exposed users."),
        ),
        rules=(
            "If the message body or headers are too sparse to judge, the Verdict is "
            "DEFERRED, not BENIGN — an un-analyzable message is not a safe one.",
        ),
    ),
    Mode.BRIEF: ModeContract(
        name=Mode.BRIEF.value,
        purpose="produce a short, scannable analyst brief on the requested subject.",
        fields=(
            ContractField("Bottom line", "the single most important takeaway, first."),
            ContractField("Details", "the supporting points, tight and scannable."),
            ContractField(
                "Watch items",
                "what to monitor or follow up on next.",
                required=False,
            ),
        ),
        rules=("Lead with the conclusion. Keep it brief — this is a brief, not a report.",),
    ),
}


def contract_for(mode: Mode) -> ModeContract:
    return CONTRACTS[mode]
