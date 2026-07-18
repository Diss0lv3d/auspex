"""Deterministic email-header parse — S11 (ADR 0006: code owns the parse, NO
LLM). Mirrors the S10 alert normalizer's posture: regex-per-header extraction
over the raw paste (pastes are partial and mangled — `email.parser` wants a
well-formed message; line-anchored regexes survive reality, the SARA pattern),
errors bias to `parsed=False` (→ verdict DEFERRED), and the function never
raises.

Recovers: From (display + address), Reply-To, Return-Path, recipients
(To/Cc/Delivered-To/X-Original-To — the victim side), Subject, SPF/DKIM/DMARC
results (Authentication-Results / Received-SPF, result-token regexes tolerant
of placement), Received count, and NAMED header anomalies (multiple From,
control characters, invisible Unicode, deceptive encoded-words). IOCs reuse
the observable extractor uniformly over the whole paste.
Reference: docs/probes/2026-07-18-sara-phishing-header-patterns.md §1.
"""

from __future__ import annotations

import re
from email.header import decode_header
from email.utils import getaddresses, parseaddr

from auspex.classify.observables import ObservableType, extract
from auspex.phishing.envelope import AuthResult, EmailEnvelope

# RFC-5322 header line with folded continuations.
_HEADER_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9-]{0,60})[ \t]*:[ \t]*(.*(?:\r?\n[ \t].*)*)", re.MULTILINE
)

_RESULT_TOKENS = "|".join(r.value for r in AuthResult)
_SPF_RE = re.compile(rf"\bspf=({_RESULT_TOKENS})\b", re.IGNORECASE)
_DKIM_RE = re.compile(rf"\bdkim=({_RESULT_TOKENS})\b", re.IGNORECASE)
_DMARC_RE = re.compile(rf"\bdmarc=({_RESULT_TOKENS})\b", re.IGNORECASE)
_RECEIVED_SPF_RE = re.compile(
    rf"^Received-SPF[ \t]*:[ \t]*({_RESULT_TOKENS})\b", re.IGNORECASE | re.MULTILINE
)

_ENCODED_WORD_RE = re.compile(r"=\?[^?]+\?[BbQq]\?[^?]*\?=")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INVISIBLE_RE = re.compile(
    r"[\u200b-\u200f\u2028-\u202f\u205f-\u206f\ufeff]"
)
_EMAIL_IN_TEXT_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w{2,}")

_RECIPIENT_HEADERS = ("to", "cc", "delivered-to", "x-original-to")


def _decode_2047(raw: str) -> str:
    """Decode RFC-2047 encoded-words; on any error return the raw string."""
    try:
        return "".join(
            part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part
            for part, enc in decode_header(raw)
        )
    except Exception:  # noqa: BLE001 — untrusted header, bias to raw
        return raw


_ANGLE_ADDR_RE = re.compile(r"<\s*([\w.+-]+@[\w.-]+\.\w{2,})\s*>")


def _split_from(raw_decoded: str) -> tuple[str | None, str | None]:
    """(display, address) from a From value. `parseaddr` returns ('','') when
    the display name holds a bare '@' — the display-name-spoof hallmark
    ('ceo@acme.com <attacker@evil.ru>') — so on that failure we take the
    angle-bracketed address and keep the deceptive prefix as the display name."""
    display, addr = parseaddr(raw_decoded)
    if addr:
        return (display.strip() or None, addr.lower())
    m = _ANGLE_ADDR_RE.search(raw_decoded)
    if m:
        display = raw_decoded[: m.start()].strip().strip('"').strip() or None
        return (display, m.group(1).lower())
    return (None, None)


def _domain_of(addr: str | None) -> str | None:
    if not addr or "@" not in addr:
        return None
    return addr.rsplit("@", 1)[-1].lower().strip(".>") or None


def _auth(text: str, headers: dict[str, str]) -> tuple[AuthResult | None, ...]:
    """SPF/DKIM/DMARC result tokens. Prefer Authentication-Results headers;
    fall back to result tokens anywhere in the head of the paste (forwarded
    reports paste them loose), then Received-SPF for SPF."""
    auth_src = headers.get("authentication-results") or headers.get("arc-authentication-results")
    scope = auth_src if auth_src else text[:3000]
    spf = _SPF_RE.search(scope)
    dkim = _DKIM_RE.search(scope)
    dmarc = _DMARC_RE.search(scope)
    spf_result = AuthResult(spf.group(1).lower()) if spf else None
    if spf_result is None:
        rspf = _RECEIVED_SPF_RE.search(text)
        spf_result = AuthResult(rspf.group(1).lower()) if rspf else None
    return (
        spf_result,
        AuthResult(dkim.group(1).lower()) if dkim else None,
        AuthResult(dmarc.group(1).lower()) if dmarc else None,
    )


def _anomalies(
    raw_from: str, decoded_from: str, decoded_subject: str, from_count: int
) -> list[str]:
    out: list[str] = []
    if from_count > 1:
        out.append(f"multiple From headers ({from_count}) — sender-field confusion")
    if _CONTROL_RE.search(decoded_from):
        out.append("control characters in From header — header-injection attempt")
    if _INVISIBLE_RE.search(decoded_from):
        out.append("invisible Unicode in From header — obfuscation")
    if _INVISIBLE_RE.search(decoded_subject):
        out.append("invisible Unicode in Subject — filter evasion")
    # Encoded-words are legitimate for non-ASCII display names; only flag when
    # the DECODED form hides an address (deception) — not the encoding itself.
    if _ENCODED_WORD_RE.search(raw_from):
        hidden = _EMAIL_IN_TEXT_RE.search(_decode_2047(raw_from).split("<")[0])
        if hidden:
            out.append(
                "RFC-2047 encoded From display name conceals an address — spoof obfuscation"
            )
    return out


def parse_email(text: str) -> EmailEnvelope:
    """Parse one pasted email into the typed envelope. Never raises; a paste
    without ≥2 recognizable headers yields `parsed=False`, which the verdict
    layer maps to DEFERRED (an un-analyzable message is not a safe one)."""
    try:
        return _parse(text)
    except Exception as err:  # noqa: BLE001 — bias to DEFERRED on any parse error
        return EmailEnvelope(
            parsed=False,
            notes=(f"parse error ({type(err).__name__}) — biased to DEFERRED",),
        )


def _parse(text: str) -> EmailEnvelope:
    headers: dict[str, str] = {}
    from_count = 0
    received_count = 0
    header_count = 0
    for m in _HEADER_RE.finditer(text):
        key = m.group(1).lower()
        val = re.sub(r"\r?\n[ \t]+", " ", m.group(2)).strip()
        header_count += 1
        if key == "from":
            from_count += 1
        if key == "received":
            received_count += 1
        headers.setdefault(key, val)  # first wins (matches _sections order rule)

    raw_from = headers.get("from", "")
    decoded_from = _decode_2047(raw_from)
    display, from_addr = _split_from(decoded_from)

    _, reply_to = parseaddr(_decode_2047(headers.get("reply-to", "")))
    _, return_path = parseaddr(headers.get("return-path", ""))
    reply_to = reply_to.lower() or None
    return_path = return_path.lower() or None

    recipients: list[str] = []
    for h in _RECIPIENT_HEADERS:
        if headers.get(h):
            recipients.extend(
                a.lower() for _, a in getaddresses([_decode_2047(headers[h])]) if a
            )
    recipients = list(dict.fromkeys(recipients))
    recipient_domains = tuple(dict.fromkeys(d for a in recipients if (d := _domain_of(a))))

    decoded_subject = _decode_2047(headers.get("subject", ""))
    spf, dkim, dmarc = _auth(text, headers)

    iocs = tuple(
        o for o in extract(text).observables if o.type is not ObservableType.CVE
    )

    return EmailEnvelope(
        from_display=display,
        from_addr=from_addr,
        from_domain=_domain_of(from_addr),
        reply_to_addr=reply_to,
        reply_to_domain=_domain_of(reply_to),
        return_path_addr=return_path,
        return_path_domain=_domain_of(return_path),
        recipient_addrs=tuple(recipients),
        recipient_domains=recipient_domains,
        subject=decoded_subject.strip() or None,
        spf=spf,
        dkim=dkim,
        dmarc=dmarc,
        received_count=received_count,
        header_count=header_count,
        anomalies=tuple(_anomalies(raw_from, decoded_from, decoded_subject, from_count)),
        iocs=iocs,
        parsed=header_count >= 2,
    )
