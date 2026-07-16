"""Defang-aware observable extraction + normalization — S4 step 1.

All IOC regexes live HERE; import from this module instead of defining local
copies (single-source pattern, per the SARA study). Everything is a pure
function: no I/O, no LLM, no network — this module sits on the 92% fast path.

Design notes:
- Input may be defanged (`hxxp`, `[.]`, `(.)`, `[at]`, `[dot]`, trailing dot…);
  `refang()` produces the canonical live form before extraction, and each
  Observable carries a `defanged` flag — an analyst defanged it on purpose,
  which is itself signal (verdict-floor input for S7, parked in IDEAS.md).
- IPs are validated with `ipaddress` after a loose regex candidate pass —
  code over regex: the stdlib knows what a valid address is better than any
  octet alternation, and it gives us canonical compression for IPv6.
- Domains use a TLD allowlist. Deliberate: an open-ended pattern turns every
  `report.pdf` and `setup.exe` into a "domain". Extend `_TLDS` as needed.
- Double-extraction guards are span-based: host-ish observables (domain, IP,
  email) are suppressed inside a broader match (URL, email); reference
  identifiers (hashes, CVE IDs) are kept even inside URLs — a VirusTotal link's
  hash is the interesting part, its host is not.
- `obs_id` is a short, deterministic, type-prefixed id so downstream tool args
  can address an observable without carrying raw 64-char strings (S3 harness
  input, IDEAS.md).
"""

import hashlib
import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit


class ObservableType(StrEnum):
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    DOMAIN = "domain"
    URL = "url"
    SHA256 = "sha256"
    SHA1 = "sha1"
    MD5 = "md5"
    EMAIL = "email"
    CVE = "cve"


@dataclass(frozen=True)
class Observable:
    type: ObservableType
    value: str  # canonical (refanged + normalized) form
    obs_id: str  # short deterministic id, e.g. "ipv4-9c463859"
    defanged: bool  # the source text carried this observable defanged


@dataclass(frozen=True)
class Extraction:
    observables: tuple[Observable, ...]  # in order of first appearance
    residual: str  # refanged text with observable spans blanked (word-count gates)


def observable_id(type_: ObservableType, value: str) -> str:
    digest = hashlib.blake2s(f"{type_}:{value}".encode(), digest_size=4).hexdigest()
    return f"{type_}-{digest}"


# -- refang -------------------------------------------------------------------

_REFANG_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bhxxps\b", re.IGNORECASE), "https"),
    (re.compile(r"\bhxxp\b", re.IGNORECASE), "http"),
    (re.compile(r"\s*\[\s*(?:\.|dot)\s*\]\s*", re.IGNORECASE), "."),
    (re.compile(r"\s*\(\s*(?:\.|dot)\s*\)\s*", re.IGNORECASE), "."),
    (re.compile(r"\s*\{\s*(?:\.|dot)\s*\}\s*", re.IGNORECASE), "."),
    (re.compile(r"\s*\[\s*(?:@|at)\s*\]\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s*\(\s*(?:@|at)\s*\)\s*", re.IGNORECASE), "@"),
    (re.compile(r"\[\s*:\s*\]"), ":"),
)


def refang(text: str) -> str:
    """Canonical live form of defanged text. Idempotent on clean input."""
    for pattern, replacement in _REFANG_RULES:
        text = pattern.sub(replacement, text)
    return text


# -- the regex table ----------------------------------------------------------

_URL_RE = re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE)
_URL_TRAILING_JUNK = ".,;:!?)\"'>]"

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)

_SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
_SHA1_RE = re.compile(r"\b[a-fA-F0-9]{40}\b")
_MD5_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")

# Candidate only — ipaddress.IPv4Address is the validator. The lookarounds keep
# "v1.2.3.4" (glued version) and "1.2.3.4.5" (dotted version) from matching;
# a trailing defang dot ("10.0.0.1.") still does.
_IPV4_CAND_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w)(?!\.\d)")
# "version 1.2.3.4" / "build 1.2.3.4" — explicit guard SARA lacked (its study
# flagged the gap); applied to the ~12 chars before the candidate.
_VERSION_CTX_RE = re.compile(r"\b(?:version|ver\.?|v|build|release)\s*[:=]?\s*$", re.IGNORECASE)

# Candidate only — ≥2 colon groups; ipaddress validates (rejects MACs, times).
# The boundary check rejects candidates glued to identifiers ("std::vector"
# yields a technically-valid "d::") — any alphanumeric neighbor disqualifies.
_IPV6_CAND_RE = re.compile(r"[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}")
_IPV6_V4_TAIL_RE = re.compile(r"^(?:\.\d{1,3}){3}")
_IPV6_BOUNDARY_JUNK = ":._%-"

_DOMAIN_CAND_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\b", re.IGNORECASE
)
# Allowlist strategy (SARA pattern): open-ended TLD matching turns filenames and
# version strings into domains. Common gTLD/ccTLD + abuse-heavy TLDs; extend freely.
_TLDS = frozenset(
    """
    com net org io gov edu mil co uk de ru cn br au fr it nl se no es jp kr in us ca
    ch at be dk fi nz pl pt sg za mx ie gr cz sk hu ro bg ua vn th id my ph pk bd lk
    ai me tv sh gg to ly is ws ir sa ae il tr eu ar cl pe uy
    info biz name mobi onion
    xyz top cc pw tk ml ga cf gq su buzz club live site online pro app dev cloud
    zip mov link click download work party date loan win men stream icu cyou rest
    monster quest lol fun shop store vip bond cfd sbs
    """.split()
)


# -- extraction ---------------------------------------------------------------


def _spans_overlap(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < s_end and end > s_start for s_start, s_end in spans)


def _normalize_url(raw: str) -> str:
    """Lowercase scheme + host (not userinfo, path, or query)."""
    try:
        parts = urlsplit(raw)
        netloc = parts.netloc
        if "@" in netloc:
            userinfo, host = netloc.rsplit("@", 1)
            netloc = f"{userinfo}@{host.lower()}"
        else:
            netloc = netloc.lower()
        return urlunsplit((parts.scheme.lower(), netloc, parts.path, parts.query, parts.fragment))
    except ValueError:
        return raw


def _domain_backtrack(candidate: str) -> str | None:
    """Longest label suffix ending in an allowlisted TLD, or None.

    "evil.com.internal" → "evil.com"; "server01.prod.internal" → None.
    """
    labels = candidate.split(".")
    for i in range(len(labels) - 1, 0, -1):
        if labels[i].lower() in _TLDS:
            return ".".join(labels[: i + 1])
    return None


def extract(text: str) -> Extraction:
    """Extract + normalize all observables from (possibly defanged) text."""
    refanged = refang(text)
    original_lower = text.lower()

    # (type, value, raw_matched_text, span) — raw text drives the defanged flag,
    # span drives double-extraction guards and the residual.
    found: list[tuple[ObservableType, str, str, tuple[int, int]]] = []
    url_spans: list[tuple[int, int]] = []
    email_spans: list[tuple[int, int]] = []
    ipv6_spans: list[tuple[int, int]] = []
    hash_spans: list[tuple[int, int]] = []

    # URLs first — they define the spans that suppress host double-extraction.
    for m in _URL_RE.finditer(refanged):
        raw = m.group().rstrip(_URL_TRAILING_JUNK)
        span = (m.start(), m.start() + len(raw))
        url_spans.append(span)
        found.append((ObservableType.URL, _normalize_url(raw), raw, span))

    for m in _EMAIL_RE.finditer(refanged):
        if _spans_overlap(m.start(), m.end(), url_spans):
            continue
        email_spans.append(m.span())
        found.append((ObservableType.EMAIL, m.group().lower(), m.group(), m.span()))

    for m in _IPV6_CAND_RE.finditer(refanged):
        start, end = m.span()
        candidate = m.group()
        # IPv4-mapped tail: "::ffff:" + dotted quad continues past the candidate.
        tail = _IPV6_V4_TAIL_RE.match(refanged[end:])
        if tail:
            candidate += tail.group()
            end += tail.end()
        prev = refanged[start - 1] if start > 0 else ""
        nxt = refanged[end] if end < len(refanged) else ""
        if prev and (prev.isalnum() or prev in _IPV6_BOUNDARY_JUNK):
            continue
        if nxt and (nxt.isalnum() or nxt in _IPV6_BOUNDARY_JUNK):
            continue
        # Bare "::" (C++ scope, slicing) is a *valid* IPv6 address — require a digit.
        if not any(c in "0123456789abcdefABCDEF" for c in candidate):
            continue
        if _spans_overlap(start, end, url_spans):
            continue
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if ip.version != 6:
            continue
        ipv6_spans.append((start, end))
        found.append((ObservableType.IPV6, ip.compressed, candidate, (start, end)))

    for m in _IPV4_CAND_RE.finditer(refanged):
        if _spans_overlap(m.start(), m.end(), url_spans + ipv6_spans):
            continue
        if _VERSION_CTX_RE.search(refanged[max(0, m.start() - 12) : m.start()]):
            continue
        try:
            ip = ipaddress.IPv4Address(m.group())
        except ValueError:
            continue
        found.append((ObservableType.IPV4, str(ip), m.group(), m.span()))

    for m in _CVE_RE.finditer(refanged):
        found.append((ObservableType.CVE, m.group().upper(), m.group(), m.span()))

    # Hashes: longest first; a shorter hash inside a longer one's span is noise.
    for hash_type, pattern in (
        (ObservableType.SHA256, _SHA256_RE),
        (ObservableType.SHA1, _SHA1_RE),
        (ObservableType.MD5, _MD5_RE),
    ):
        for m in pattern.finditer(refanged):
            if _spans_overlap(m.start(), m.end(), hash_spans + email_spans):
                continue
            hash_spans.append(m.span())
            found.append((hash_type, m.group().lower(), m.group(), m.span()))

    for m in _DOMAIN_CAND_RE.finditer(refanged):
        if _spans_overlap(m.start(), m.end(), url_spans + email_spans):
            continue
        domain = _domain_backtrack(m.group())
        if domain is None:
            continue
        found.append((ObservableType.DOMAIN, domain.lower(), domain, m.span()))

    found.sort(key=lambda item: item[3])
    observables: list[Observable] = []
    seen: set[tuple[ObservableType, str]] = set()
    blank_spans: list[tuple[int, int]] = []
    for type_, value, raw, span in found:
        blank_spans.append(span)
        if (type_, value) in seen:
            continue
        seen.add((type_, value))
        observables.append(
            Observable(
                type=type_,
                value=value,
                obs_id=observable_id(type_, value),
                defanged=raw.lower() not in original_lower,
            )
        )

    residual_chars = list(refanged)
    for start, end in blank_spans:
        residual_chars[start:end] = " " * (end - start)
    residual = " ".join("".join(residual_chars).split())

    return Extraction(observables=tuple(observables), residual=residual)


def extract_observables(text: str) -> list[Observable]:
    """Convenience wrapper when the residual isn't needed."""
    return list(extract(text).observables)
