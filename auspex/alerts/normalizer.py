"""Multi-SIEM alert normalizer — S10 (ADR 0006: code owns the parse, NO LLM).

Detects CEF / LEEF / syslog / JSON alert shapes and parses each into the typed,
closed-vocabulary `AlertEnvelope` (envelope.py). Format-specific parsing recovers
the header facts (severity, name, source/dest, timestamp, confidence); signal /
MITRE / IOC detection runs UNIFORMLY over the raw paste, so an encoded command or
a LOLBin is caught wherever a given SIEM happens to place it.

Errors bias to DEFERRED, never to a confident parse: any exception yields an
`UNKNOWN`, `parsed=False` envelope, and an unrecognized shape is `UNKNOWN` — the
scorer turns both into Risk DEFERRED (the SARA rail's whole point: "no data ≠ low
risk"). The alert paste is untrusted (TD-013); reducing it to closed vocab here
is the structural mitigation — downstream scoring reads facts, not attacker prose.
"""

from __future__ import annotations

import json
import re

from auspex.alerts.envelope import AlertEnvelope, AlertFormat, Severity, Signal
from auspex.classify.observables import ObservableType, extract

# -- format detection (aligned with the classifier's alert-paste gate) --------

_CEF_RE = re.compile(r"\bCEF:\d+\|")
_LEEF_RE = re.compile(r"\bLEEF:\d+(?:\.\d+)?\|")
_SYSLOG_PRI_RE = re.compile(r"^\s*<(\d{1,3})>")
_JSON_KEY_RE = re.compile(r"\"\w+\"\s*:")


def detect_format(text: str) -> AlertFormat:
    q = text.strip()
    if q.startswith("CEF:") or _CEF_RE.search(q):
        return AlertFormat.CEF
    if q.startswith("LEEF:") or _LEEF_RE.search(q):
        return AlertFormat.LEEF
    if _SYSLOG_PRI_RE.match(q):
        return AlertFormat.SYSLOG
    if q.lstrip().startswith("{") and _JSON_KEY_RE.search(q):
        return AlertFormat.JSON
    return AlertFormat.UNKNOWN


# -- severity normalization (every scale → the five-level enum) ----------------

_SEV_WORDS = {
    "critical": Severity.CRITICAL,
    "crit": Severity.CRITICAL,
    "severe": Severity.CRITICAL,
    "emergency": Severity.CRITICAL,
    "fatal": Severity.CRITICAL,
    "high": Severity.HIGH,
    "important": Severity.HIGH,
    "error": Severity.HIGH,
    "err": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "med": Severity.MEDIUM,
    "moderate": Severity.MEDIUM,
    "warning": Severity.MEDIUM,
    "warn": Severity.MEDIUM,
    "low": Severity.LOW,
    "minor": Severity.LOW,
    "notice": Severity.LOW,
    "informational": Severity.INFORMATIONAL,
    "information": Severity.INFORMATIONAL,
    "info": Severity.INFORMATIONAL,
    "debug": Severity.INFORMATIONAL,
}


def _sev_from_number(n: float) -> Severity:
    """0-10 (CEF) scale; values 11-100 are treated as a /100 scale."""
    if n > 10:
        n = n / 10.0
    if n >= 9:
        return Severity.CRITICAL
    if n >= 7:
        return Severity.HIGH
    if n >= 4:
        return Severity.MEDIUM
    if n >= 1:
        return Severity.LOW
    return Severity.INFORMATIONAL


def _syslog_severity(pri: int) -> Severity:
    """syslog PRI → severity level. severity = PRI % 8 (0=emerg … 7=debug)."""
    sev = pri % 8
    if sev <= 2:  # emergency, alert, critical
        return Severity.CRITICAL
    if sev == 3:  # error
        return Severity.HIGH
    if sev == 4:  # warning
        return Severity.MEDIUM
    if sev == 5:  # notice
        return Severity.LOW
    return Severity.INFORMATIONAL  # info, debug


def _normalize_severity(raw: str | None) -> Severity | None:
    """A severity token (word or number) → the enum, or None if absent/unknown.
    None is deliberate: 'no severity' must reach the DEFERRED rail, not default."""
    if raw is None:
        return None
    token = str(raw).strip().lower()
    if not token or token in ("unknown", "none", "n/a", "na", "-"):
        return None
    if token in _SEV_WORDS:
        return _SEV_WORDS[token]
    try:
        return _sev_from_number(float(token))
    except ValueError:
        return None


# -- signal / MITRE detection (uniform over the raw paste) ---------------------

_ENCODED_RE = re.compile(
    r"-enc(?:odedcommand)?\b|frombase64string|(?<![a-z])base64\b", re.IGNORECASE
)
_LOLBIN_RE = re.compile(
    r"\b(?:certutil|bitsadmin|mshta|regsvr32|rundll32|wmic|msbuild|installutil|"
    r"iex|invoke-expression|downloadstring|vssadmin|wevtutil|schtasks)\b",
    re.IGNORECASE,
)
_SUSPICIOUS_EXE_RE = re.compile(
    r"\b(powershell|cmd|wscript|cscript|mshta|certutil|rundll32|regsvr32|"
    r"bitsadmin|wmic|wsl|bash|sh)(?:\.exe)?\b",
    re.IGNORECASE,
)
_BARE_SHELLS = {"powershell", "cmd", "bash", "sh", "wsl"}
# A bare dual-use shell needs a command-line exec co-signal before it counts
# (SARA #1587 — the process name alone is not a risk signal on a legit script).
_EXEC_COSIGNAL_RE = re.compile(
    r"-enc|-nop|-noni|-w\s*hidden|-windowstyle\s*hidden|iex|downloadstring|"
    r"frombase64|-c\s|/c\s|http[s]?://|\.ps1|\.vbs",
    re.IGNORECASE,
)
_LOW_PREV_RE = re.compile(
    r"\b(?:low[\s_-]?prevalence|rare[\s_-]?(?:process|binary|file)|"
    r"first[\s_-]?seen|never[\s_-]?before[\s_-]?seen|unusual[\s_-]?for)\b",
    re.IGNORECASE,
)
_MITRE_TECH_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")
_MITRE_TACTIC_RE = re.compile(r"\bTA\d{4}\b")


def _detect_signals(text: str) -> tuple[Signal, ...]:
    found: list[Signal] = []
    if _ENCODED_RE.search(text):
        found.append(Signal.ENCODED_COMMAND)
    if _LOLBIN_RE.search(text):
        found.append(Signal.LOLBIN)
    exe = _SUSPICIOUS_EXE_RE.search(text)
    if exe:
        bare = exe.group(1).lower() in _BARE_SHELLS
        # #1587 gate: a bare shell without an exec co-signal is not a risk signal.
        if not bare or _EXEC_COSIGNAL_RE.search(text):
            found.append(Signal.SUSPICIOUS_PROCESS)
    if _LOW_PREV_RE.search(text):
        found.append(Signal.LOW_PREVALENCE)
    return tuple(found)


def _extract_mitre(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tactics = tuple(dict.fromkeys(m.group(0).upper() for m in _MITRE_TACTIC_RE.finditer(text)))
    # A technique regex also matches the TA#### tactics' trailing digits? No —
    # TA#### starts with 'TA', T#### with 'T' then a digit; \bT\d{4} won't match
    # inside 'TA0002'. De-dupe and upper-case.
    techniques = tuple(dict.fromkeys(m.group(0).upper() for m in _MITRE_TECH_RE.finditer(text)))
    return techniques, tactics


def _iocs(text: str):
    """Non-CVE observables are the scoreable IOC artifacts (ip/host/hash/url/
    email); a bare CVE is threat context, not an artifact to enrich."""
    return tuple(o for o in extract(text).observables if o.type is not ObservableType.CVE)


# -- per-format header parsers -------------------------------------------------


def _split_escaped(s: str, sep: str) -> list[str]:
    """Split on `sep` honoring `\\`-escapes (CEF/LEEF header fields)."""
    out, buf, esc = [], [], False
    for ch in s:
        if esc:
            buf.append(ch)
            esc = False
        elif ch == "\\":
            buf.append(ch)
            esc = True
        elif ch == sep:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def _parse_kv(ext: str, sep_re: str = r"\s+") -> dict[str, str]:
    """Parse `key=value` runs where a value extends to the next `key=` (CEF
    extension / LEEF attributes). Unescapes `\\=` `\\|` `\\\\`."""
    out: dict[str, str] = {}
    keys = list(re.finditer(rf"(?:^|{sep_re})([A-Za-z][\w.]*)=", ext))
    for i, m in enumerate(keys):
        key = m.group(1)
        val_start = m.end()
        val_end = keys[i + 1].start() if i + 1 < len(keys) else len(ext)
        val = ext[val_start:val_end].strip()
        val = val.replace("\\=", "=").replace("\\|", "|").replace("\\\\", "\\")
        out[key.lower()] = val
    return out


def _first(d: dict[str, str], *keys: str) -> str | None:
    for k in keys:
        if d.get(k):
            return d[k]
    return None


def _parse_cef(text: str) -> dict:
    # CEF:Ver|Vendor|Product|Version|SigID|Name|Severity|Extension
    body = text.strip()
    header = _split_escaped(body, "|")
    name = header[5].strip() if len(header) > 5 else None
    sev_raw = header[6].strip() if len(header) > 6 else None
    ext = _parse_kv("|".join(header[7:])) if len(header) > 7 else {}
    sev = _normalize_severity(sev_raw) or _normalize_severity(_first(ext, "severity", "cat"))
    return {
        "name": name or None,
        "severity": sev,
        "src": _first(ext, "src", "shost", "suser"),
        "dst": _first(ext, "dst", "dhost", "dvchost"),
        "timestamp": _first(ext, "rt", "start", "end", "devicecustomdate1"),
        "confidence": _confidence(_first(ext, "confidence", "cn1")),
        "cmdline": _first(ext, "cs1", "msg", "deviceprocessname", "dproc"),
    }


def _parse_leef(text: str) -> dict:
    # LEEF:Ver|Vendor|Product|Version|EventID|[Delimiter|]attrs
    body = text.strip()
    header = _split_escaped(body, "|")
    ver = header[0].split(":", 1)[1] if ":" in header[0] else "1.0"
    # LEEF 2.0 carries a custom delimiter in field 5; 1.0 uses tab.
    if ver.startswith("2") and len(header) > 6:
        delim = header[5] or "\t"
        attrs_str = "|".join(header[6:])
    else:
        delim = "\t"
        attrs_str = "|".join(header[5:])
    if delim.startswith("x") or delim.startswith("0x"):  # hex delimiter spec
        try:
            delim = chr(int(delim.lstrip("x0"), 16))
        except ValueError:
            delim = "\t"
    sep_re = re.escape(delim) if delim.strip() else r"\s+"
    attrs = _parse_kv(attrs_str, sep_re=sep_re)
    sev = _normalize_severity(_first(attrs, "sev", "severity"))
    return {
        "name": _first(attrs, "name", "cat", "eventid"),
        "severity": sev,
        "src": _first(attrs, "src", "srcip", "srchost"),
        "dst": _first(attrs, "dst", "dstip", "dsthost"),
        "timestamp": _first(attrs, "devtime", "rt", "time"),
        "confidence": _confidence(_first(attrs, "confidence")),
        "cmdline": _first(attrs, "command", "cmd", "process"),
    }


def _parse_syslog(text: str) -> dict:
    body = text.strip()
    m = _SYSLOG_PRI_RE.match(body)
    pri = int(m.group(1)) if m else None
    sev = _syslog_severity(pri) if pri is not None else None
    rest = body[m.end() :] if m else body
    # RFC5424 timestamp (ISO) or RFC3164 (Mmm dd hh:mm:ss), best-effort.
    ts = None
    iso = re.search(r"\d{4}-\d{2}-\d{2}T[\d:.+Z-]+", rest)
    bsd = re.search(r"[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}", rest)
    ts = iso.group(0) if iso else (bsd.group(0) if bsd else None)
    kv = _parse_kv(rest)
    return {
        "name": None,
        "severity": sev,
        "src": _first(kv, "src", "srcip", "src_ip", "source"),
        "dst": _first(kv, "dst", "dstip", "dst_ip", "dest"),
        "timestamp": ts,
        "confidence": _confidence(_first(kv, "confidence")),
        "cmdline": _first(kv, "cmd", "command", "cmdline"),
    }


def _flatten_json(obj, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{k}".lower()
            if isinstance(v, (dict, list)):
                out.update(_flatten_json(v, prefix=f"{key}."))
            else:
                out[key] = "" if v is None else str(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten_json(v, prefix=f"{prefix}{i}."))
    return out


def _leaf(flat: dict[str, str], *names: str) -> str | None:
    """Match a key by its LAST path segment (so `alert.severity` matches 'severity')."""
    for name in names:
        for k, v in flat.items():
            if (k == name or k.endswith("." + name)) and v:
                return v
    return None


def _parse_json(text: str) -> dict:
    obj = json.loads(text)
    flat = _flatten_json(obj)
    sev = _normalize_severity(_leaf(flat, "severity", "sev", "priority", "level"))
    return {
        "name": _leaf(flat, "name", "rule", "signature", "rule_name", "title", "alert", "event"),
        "severity": sev,
        "src": _leaf(flat, "src_ip", "source_ip", "src", "source", "srcip"),
        "dst": _leaf(flat, "dst_ip", "dest_ip", "dst", "dest", "destination", "dstip"),
        "timestamp": _leaf(flat, "timestamp", "@timestamp", "time", "event_time", "rt"),
        "confidence": _confidence(_leaf(flat, "confidence", "conf")),
        "cmdline": _leaf(flat, "cmdline", "command_line", "command", "process_command_line"),
    }


def _confidence(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        n = int(float(str(raw).strip().rstrip("%")))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


_PARSERS = {
    AlertFormat.CEF: _parse_cef,
    AlertFormat.LEEF: _parse_leef,
    AlertFormat.SYSLOG: _parse_syslog,
    AlertFormat.JSON: _parse_json,
}


def normalize(text: str) -> AlertEnvelope:
    """Parse one alert paste into the typed envelope. Never raises — a parse
    failure or unrecognized shape yields `fmt=UNKNOWN, parsed=False`, which the
    scorer maps to DEFERRED (errors bias to DEFERRED, never a confident LOW)."""
    fmt = detect_format(text)
    header: dict = {}
    parsed = fmt is not AlertFormat.UNKNOWN
    notes: list[str] = []
    if fmt in _PARSERS:
        try:
            header = _PARSERS[fmt](text)
        except Exception as err:  # noqa: BLE001 — bias to DEFERRED on any parse error
            parsed = False
            notes.append(f"parse error ({type(err).__name__}) — biased to DEFERRED")
            header = {}

    techniques, tactics = _extract_mitre(text)
    return AlertEnvelope(
        fmt=fmt,
        name=header.get("name"),
        severity=header.get("severity"),
        confidence=header.get("confidence"),
        src=header.get("src"),
        dst=header.get("dst"),
        timestamp=header.get("timestamp"),
        cmdline=header.get("cmdline"),
        signals=_detect_signals(text),
        iocs=_iocs(text),
        mitre_techniques=techniques,
        mitre_tactics=tactics,
        parsed=parsed,
        notes=tuple(notes),
    )
