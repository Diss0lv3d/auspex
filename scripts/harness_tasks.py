"""Task battery for the S2 tool-calling harness (ROADMAP S2).

40 scripted multi-step tool tasks in SOC flavor. Everything here is
deterministic and endpoint-independent: mock tools return canned data derived
from their arguments, so the model must thread real values between steps.

All observables are fictional (documentation IP ranges, example.test domains,
made-up hashes) — no real IOCs, ever.

Measured by scripts/llm_harness.py:
- valid-call rate  = well-formed tool calls / all tool calls
                     (known tool, args parse as JSON, required params present,
                      enum values legal)
- loop-completion  = tasks where every required tool was called validly and the
                     final answer contains the expected evidence substrings.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

from auspex.llm.client import tool_spec


def _stable_id(seed: str, mod: int) -> int:
    """Deterministic across processes (unlike hash(), which is seeded per run)."""
    return int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4], "big") % mod

# ---------------------------------------------------------------------------
# Mock world. Documentation ranges only (RFC 5737 / RFC 2606).
# ---------------------------------------------------------------------------

IPS = {
    "203.0.113.7": {"reputation": "malicious", "score": 94, "country": "XZ", "tags": ["c2", "botnet"]},
    "198.51.100.23": {"reputation": "suspicious", "score": 55, "country": "QT", "tags": ["scanner"]},
    "192.0.2.10": {"reputation": "benign", "score": 2, "country": "US", "tags": []},
    "203.0.113.99": {"reputation": "malicious", "score": 88, "country": "XZ", "tags": ["phishing"]},
    "198.51.100.77": {"reputation": "benign", "score": 5, "country": "DE", "tags": []},
}

DOMAINS = {
    "login-portal.example.test": {"reputation": "malicious", "score": 91, "category": "phishing"},
    "cdn-assets.example.test": {"reputation": "benign", "score": 3, "category": "cdn"},
    "update-check.example.test": {"reputation": "suspicious", "score": 48, "category": "unclassified"},
}

HASHES = {
    "a" * 64: {"family": "RedLoader", "verdict": "malicious", "first_seen": "2026-05-01"},
    "b" * 64: {"family": None, "verdict": "unknown", "first_seen": None},
    "c" * 64: {"family": "GreyDuck", "verdict": "malicious", "first_seen": "2026-06-12"},
}

ALERTS = {
    "A-1001": {
        "title": "Outbound beaconing detected",
        "severity": "high",
        "src_ip": "203.0.113.7",
        "host": "ws-fin-042",
        "user": "j.doe",
    },
    "A-1002": {
        "title": "Suspicious login pattern",
        "severity": "medium",
        "src_ip": "198.51.100.23",
        "host": "srv-db-001",
        "user": "svc-backup",
    },
    "A-1003": {
        "title": "Phishing URL clicked",
        "severity": "medium",
        "domain": "login-portal.example.test",
        "host": "ws-hr-011",
        "user": "m.khan",
    },
    "A-1004": {
        "title": "Malware hash observed",
        "severity": "high",
        "sha256": "a" * 64,
        "host": "ws-eng-107",
        "user": "r.chen",
    },
    "A-1005": {
        "title": "Port scan from internal host",
        "severity": "low",
        "src_ip": "192.0.2.10",
        "host": "ws-it-003",
        "user": "t.ali",
    },
}

ASSETS = {
    "ws-fin-042": {"owner": "finance", "criticality": "crown-jewel", "os": "windows"},
    "srv-db-001": {"owner": "platform", "criticality": "high", "os": "linux"},
    "ws-hr-011": {"owner": "hr", "criticality": "standard", "os": "windows"},
    "ws-eng-107": {"owner": "engineering", "criticality": "high", "os": "macos"},
    "ws-it-003": {"owner": "it", "criticality": "standard", "os": "linux"},
}

EVENT_COUNTS = {  # (query-substring, hours) -> count
    "203.0.113.7": 137,
    "198.51.100.23": 12,
    "login-portal.example.test": 3,
    "ws-fin-042": 89,
    "svc-backup": 41,
}

# ---------------------------------------------------------------------------
# Tool specs (OpenAI function-tool schema) + deterministic executors.
# ---------------------------------------------------------------------------


TOOL_SPECS: dict[str, dict] = {
    "lookup_ip": tool_spec(
        "lookup_ip",
        "Look up threat reputation for an IPv4 address.",
        {"ip": {"type": "string", "description": "IPv4 address, e.g. 203.0.113.7"}},
        ["ip"],
    ),
    "lookup_domain": tool_spec(
        "lookup_domain",
        "Look up threat reputation for a domain name.",
        {"domain": {"type": "string", "description": "Domain, e.g. example.test"}},
        ["domain"],
    ),
    "lookup_hash": tool_spec(
        "lookup_hash",
        "Look up a SHA-256 file hash in malware intelligence.",
        {"sha256": {"type": "string", "description": "64-char hex SHA-256"}},
        ["sha256"],
    ),
    "get_alert": tool_spec(
        "get_alert",
        "Fetch a SIEM alert by its ID (format A-NNNN). Returns title, severity, and observables.",
        {"alert_id": {"type": "string", "description": "Alert ID, e.g. A-1001"}},
        ["alert_id"],
    ),
    "get_asset": tool_spec(
        "get_asset",
        "Fetch asset inventory info (owner, criticality) for a hostname.",
        {"hostname": {"type": "string", "description": "Asset hostname, e.g. ws-fin-042"}},
        ["hostname"],
    ),
    "search_events": tool_spec(
        "search_events",
        "Count SIEM events matching a query string over a lookback window.",
        {
            "query": {"type": "string", "description": "Search term (IP, domain, hostname, user)"},
            "hours": {"type": "integer", "description": "Lookback window in hours"},
        },
        ["query", "hours"],
    ),
    "create_ticket": tool_spec(
        "create_ticket",
        "Create an incident ticket. Returns the new ticket ID.",
        {
            "title": {"type": "string"},
            "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "description": {"type": "string"},
        },
        ["title", "severity", "description"],
    ),
    "propose_quarantine": tool_spec(
        "propose_quarantine",
        "Propose network quarantine for a host (requires human approval; this only files the proposal). Returns the proposal ID.",
        {
            "hostname": {"type": "string"},
            "reason": {"type": "string"},
        },
        ["hostname", "reason"],
    ),
}


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Deterministic mock execution. Unknown entities get a stable 'not found'."""
    if name == "lookup_ip":
        data = IPS.get(str(args.get("ip", "")))
        return {"ip": args.get("ip"), **data} if data else {"ip": args.get("ip"), "reputation": "unknown", "score": 0}
    if name == "lookup_domain":
        data = DOMAINS.get(str(args.get("domain", "")))
        return {"domain": args.get("domain"), **data} if data else {"domain": args.get("domain"), "reputation": "unknown", "score": 0}
    if name == "lookup_hash":
        data = HASHES.get(str(args.get("sha256", "")))
        return {"sha256": args.get("sha256"), **data} if data else {"sha256": args.get("sha256"), "verdict": "unknown"}
    if name == "get_alert":
        data = ALERTS.get(str(args.get("alert_id", "")))
        return {"alert_id": args.get("alert_id"), **data} if data else {"error": f"alert {args.get('alert_id')} not found"}
    if name == "get_asset":
        data = ASSETS.get(str(args.get("hostname", "")))
        return {"hostname": args.get("hostname"), **data} if data else {"error": f"asset {args.get('hostname')} not found"}
    if name == "search_events":
        q = str(args.get("query", ""))
        count = next((v for k, v in EVENT_COUNTS.items() if k in q), 0)
        return {"query": q, "hours": args.get("hours"), "count": count}
    if name == "create_ticket":
        sev = str(args.get("severity", ""))
        return {"ticket_id": f"TCK-{_stable_id(str(args.get('title')), 9000) + 1000}", "severity": sev, "status": "open"}
    if name == "propose_quarantine":
        return {"proposal_id": f"PRP-{_stable_id(str(args.get('hostname')), 900) + 100}", "status": "pending_approval"}
    return {"error": f"unknown tool {name}"}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@dataclass
class Task:
    id: str
    category: str  # single | chain2 | chain3 | parallel | no_tool | enum_stress
    prompt: str
    tools: list[str]  # subset of TOOL_SPECS keys offered to the model
    required_calls: list[str] = field(default_factory=list)  # tool names that MUST be called (order-insensitive)
    success_substrings: list[str] = field(default_factory=list)  # all must appear in the final answer (case-insensitive)
    forbid_tool_calls: bool = False  # task should be answered WITHOUT any tool call
    max_steps: int = 8


SYSTEM_PROMPT = (
    "You are a security operations co-analyst. Use the provided tools to gather "
    "facts before answering. When you have enough information, give a concise "
    "final answer. Never invent tool output."
)

TASKS: list[Task] = [
    # --- A. single tool call (8) ---
    Task("S01", "single", "Look up the reputation of IP 203.0.113.7 and summarize it.",
         ["lookup_ip"], ["lookup_ip"], ["malicious"]),
    Task("S02", "single", "Is the domain cdn-assets.example.test safe? Check its reputation.",
         ["lookup_domain"], ["lookup_domain"], ["benign"]),
    Task("S03", "single", f"Check this SHA-256 in malware intel and name the family if any: {'a' * 64}",
         ["lookup_hash"], ["lookup_hash"], ["RedLoader"]),
    Task("S04", "single", "Pull up alert A-1002 and tell me its severity and source IP.",
         ["get_alert"], ["get_alert"], ["medium", "198.51.100.23"]),
    Task("S05", "single", "Who owns the asset ws-fin-042 and how critical is it?",
         ["get_asset"], ["get_asset"], ["finance", "crown-jewel"]),
    Task("S06", "single", "How many events mention 203.0.113.7 in the last 24 hours?",
         ["search_events"], ["search_events"], ["137"]),
    Task("S07", "single", "Look up IP 192.0.2.10 — is it a threat?",
         ["lookup_ip"], ["lookup_ip"], ["benign"]),
    Task("S08", "single", f"Check hash {'b' * 64} — known malware?",
         ["lookup_hash"], ["lookup_hash"], ["unknown"]),

    # --- B. two-step chains (10) ---
    Task("C201", "chain2", "Get alert A-1001, then look up the reputation of its source IP. Verdict?",
         ["get_alert", "lookup_ip"], ["get_alert", "lookup_ip"], ["malicious"]),
    Task("C202", "chain2", "Get alert A-1003, then check the reputation of the domain it references.",
         ["get_alert", "lookup_domain"], ["get_alert", "lookup_domain"], ["phishing"]),
    Task("C203", "chain2", "Get alert A-1004 and look up its file hash. What malware family is involved?",
         ["get_alert", "lookup_hash"], ["get_alert", "lookup_hash"], ["RedLoader"]),
    Task("C204", "chain2", "Get alert A-1001 and tell me the criticality of the affected host.",
         ["get_alert", "get_asset"], ["get_alert", "get_asset"], ["crown-jewel"]),
    Task("C205", "chain2", "Get alert A-1002, then count events for its source IP over the last 48 hours.",
         ["get_alert", "search_events"], ["get_alert", "search_events"], ["12"]),
    Task("C206", "chain2", "Look up IP 203.0.113.99; if it is malicious, open a HIGH severity ticket titled 'Malicious IP investigation'.",
         ["lookup_ip", "create_ticket"], ["lookup_ip", "create_ticket"], ["TCK-"]),
    Task("C207", "chain2", "Check domain login-portal.example.test; if malicious, file a quarantine proposal for host ws-hr-011 citing the domain as reason.",
         ["lookup_domain", "propose_quarantine"], ["lookup_domain", "propose_quarantine"], ["PRP-"]),
    Task("C208", "chain2", "Get alert A-1005 and look up its source IP. Should we worry?",
         ["get_alert", "lookup_ip"], ["get_alert", "lookup_ip"], ["benign"]),
    Task("C209", "chain2", "Count events for user svc-backup in the last 72 hours, then get asset info for srv-db-001. Summarize.",
         ["search_events", "get_asset"], ["search_events", "get_asset"], ["41", "platform"]),
    Task("C210", "chain2", f"Look up hash {'c' * 64}; if it's malicious, open a ticket (severity high) titled 'GreyDuck infection'.",
         ["lookup_hash", "create_ticket"], ["lookup_hash", "create_ticket"], ["TCK-"]),

    # --- C. three-plus-step chains (10) ---
    Task("C301", "chain3", "Triage alert A-1001: fetch it, look up its source IP, and check the affected asset's criticality. Then give a one-line risk assessment.",
         ["get_alert", "lookup_ip", "get_asset"], ["get_alert", "lookup_ip", "get_asset"], ["malicious", "crown-jewel"]),
    Task("C302", "chain3", "Full triage of A-1001: fetch alert, look up source IP, check asset, then open a ticket titled 'Beaconing on crown jewel' with severity critical.",
         ["get_alert", "lookup_ip", "get_asset", "create_ticket"],
         ["get_alert", "lookup_ip", "get_asset", "create_ticket"], ["TCK-"]),
    Task("C303", "chain3", "For alert A-1003: fetch it, check the domain reputation, and count events mentioning that domain in the last 24h. Summarize exposure.",
         ["get_alert", "lookup_domain", "search_events"],
         ["get_alert", "lookup_domain", "search_events"], ["3"]),
    Task("C304", "chain3", "For alert A-1004: fetch it, look up the hash, check the asset, then propose quarantine of the host with the malware family as the reason.",
         ["get_alert", "lookup_hash", "get_asset", "propose_quarantine"],
         ["get_alert", "lookup_hash", "get_asset", "propose_quarantine"], ["PRP-"]),
    Task("C305", "chain3", "Investigate 203.0.113.7: reputation, event count last 24h on it, and asset info for ws-fin-042. Risk summary in two sentences.",
         ["lookup_ip", "search_events", "get_asset"],
         ["lookup_ip", "search_events", "get_asset"], ["malicious", "137"]),
    Task("C306", "chain3", "For alert A-1002: fetch it, look up the source IP, count events for the user svc-backup over 48h. Is this credential abuse?",
         ["get_alert", "lookup_ip", "search_events"],
         ["get_alert", "lookup_ip", "search_events"], ["suspicious", "41"]),
    Task("C307", "chain3", "Fetch A-1005, look up its IP, and check the asset. If everything is low risk, say 'no action needed' — do NOT open a ticket.",
         ["get_alert", "lookup_ip", "get_asset", "create_ticket"],
         ["get_alert", "lookup_ip", "get_asset"], ["no action needed"]),
    Task("C308", "chain3", "Compare alerts A-1001 and A-1002: fetch both, look up both source IPs, and tell me which is more urgent.",
         ["get_alert", "lookup_ip"], ["get_alert", "lookup_ip"], ["A-1001"]),
    Task("C309", "chain3", "Fetch A-1004, look up the hash, then open a ticket titled 'RedLoader on ws-eng-107' with severity high and a description naming the family.",
         ["get_alert", "lookup_hash", "create_ticket"],
         ["get_alert", "lookup_hash", "create_ticket"], ["TCK-"]),
    Task("C310", "chain3", "Investigate the domain update-check.example.test: reputation, then count of events referencing it over 24h, then a verdict.",
         ["lookup_domain", "search_events"], ["lookup_domain", "search_events"], ["suspicious"]),

    # --- D. parallel fan-out (6) ---
    Task("P01", "parallel", "Look up BOTH 203.0.113.7 and 198.51.100.23 and compare their reputations.",
         ["lookup_ip"], ["lookup_ip", "lookup_ip"], ["malicious", "suspicious"]),
    Task("P02", "parallel", "Check the reputation of the domain login-portal.example.test AND the IP 203.0.113.99. Both now, then compare.",
         ["lookup_domain", "lookup_ip"], ["lookup_domain", "lookup_ip"], ["phishing"]),
    Task("P03", "parallel", f"Look up these two hashes and tell me which is worse: {'a' * 64} and {'b' * 64}",
         ["lookup_hash"], ["lookup_hash", "lookup_hash"], ["RedLoader"]),
    Task("P04", "parallel", "Fetch alerts A-1001 and A-1004 and summarize both in one line each.",
         ["get_alert"], ["get_alert", "get_alert"], ["beaconing", "malware"]),
    Task("P05", "parallel", "Get asset info for ws-fin-042 and srv-db-001 — which is more critical?",
         ["get_asset"], ["get_asset", "get_asset"], ["crown-jewel"]),
    Task("P06", "parallel", "Count events over 24h for BOTH 203.0.113.7 and ws-fin-042.",
         ["search_events"], ["search_events", "search_events"], ["137", "89"]),

    # --- E. no-tool restraint (4) ---
    Task("N01", "no_tool", "In one sentence, what does 'C2 beaconing' mean?",
         ["lookup_ip", "get_alert"], [], ["command"], forbid_tool_calls=True),
    Task("N02", "no_tool", "What's the difference between a vulnerability and an exploit? No lookups needed.",
         ["lookup_hash", "search_events"], [], [], forbid_tool_calls=True),
    Task("N03", "no_tool", "Say hello to the team in one friendly sentence.",
         ["create_ticket", "get_alert"], [], [], forbid_tool_calls=True),
    Task("N04", "no_tool", "Explain what a SHA-256 hash is, briefly. Do not call any tools.",
         ["lookup_hash"], [], [], forbid_tool_calls=True),

    # --- F. enum / required-param stress (2) ---
    Task("F01", "enum_stress", "Open a ticket titled 'Test severity mapping' about a MEDIUM-importance issue; description: 'harness enum check'.",
         ["create_ticket"], ["create_ticket"], ["TCK-"]),
    Task("F02", "enum_stress", "File a quarantine proposal for ws-eng-107. Reason: 'confirmed RedLoader'. Then report the proposal ID.",
         ["propose_quarantine"], ["propose_quarantine"], ["PRP-"]),
]


def tasks_by_category() -> dict[str, int]:
    out: dict[str, int] = {}
    for t in TASKS:
        out[t.category] = out.get(t.category, 0) + 1
    return out


if __name__ == "__main__":
    print(f"{len(TASKS)} tasks: {tasks_by_category()}")
