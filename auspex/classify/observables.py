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
from collections.abc import Iterator
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


def _canonical_ipv6(ip: ipaddress.IPv6Address) -> str:
    """Our OWN canonical form for an IPv6 address, not the stdlib's.

    `observable_id` hashes the VALUE, so the text an address normalizes to is
    that observable's identity — and identity is what every verdict, decay
    curve, watcher and retro-hunt match hangs off. Delegating it to
    `ip.compressed` looked like reusing a canonical form and was actually
    delegating our primary key to a formatting choice that moves.

    It moved: CPython renders IPv4-mapped addresses in mixed notation on newer
    patch releases, so `::ffff:203.0.113.9` compresses to `::ffff:cb00:7109` on
    3.12.3 and to itself on the runner. Found by the S20 CI gate on its first
    run — the suite was green locally and red on a different interpreter. A
    silent interpreter upgrade would have forked every IPv4-mapped observable
    into a second identity and split its verdict history in half.

    Pinned to the all-hex form: it is what this code has produced to date, so
    no existing obs_id changes. The mixed form is what RFC 5952 §5 recommends
    for readability and is a display concern, not an identity one — parked in
    IDEAS.md rather than silently swapped here.

    Applied to EVERY address, not just the mapped ones. Measured against the
    stdlib over 200,268 addresses (random 128-bit draws plus structured sweeps
    of zero-runs, mapped and compatible ranges): zero disagreements, and every
    output re-parses to the address it came from. So doing it universally
    changes no identity today and leaves none of them depending on a formatting
    policy tomorrow — the narrow version would only have covered the one case
    that has bitten us so far. `test_our_canonical_ipv6_agrees_with_the_stdlib`
    keeps that measurement running.
    """
    # Rendered from the integer and compressed HERE. Handing the hex back to
    # `IPv6Address(...).compressed` would not help: the result is the same
    # address, so the same formatting policy would apply again.
    groups = [f"{(int(ip) >> shift) & 0xFFFF:x}" for shift in range(112, -1, -16)]
    # RFC 5952 §4.2: collapse the longest run of zero groups (2 or more).
    best_start, best_len, run_start = -1, 0, -1
    for i, group in enumerate([*groups, "end"]):
        if group == "0":
            run_start = i if run_start < 0 else run_start
            continue
        if run_start >= 0 and i - run_start > best_len:
            best_start, best_len = run_start, i - run_start
        run_start = -1
    if best_len < 2:
        return ":".join(groups)
    return f"{':'.join(groups[:best_start])}::{':'.join(groups[best_start + best_len:])}"


# -- refang -------------------------------------------------------------------

# One pattern per replacement, any bracket pair ([.], (.), {.}, and mixed pairs —
# a harmless superset in defang context; nobody writes a literal "[.)" in prose).
#
# B-010: a leading `\s*` let every position inside a run of spaces start a new
# attempt that scanned to the run's end and failed: 16 s at the 32,000-character
# cap (B3). The leading whitespace is now taken only from where its run begins
# (`(?<!\s)`), or not at all; a match never starts mid-run, which the leftmost
# match never did, since a run is consumed whole by the match before it. The
# rest is possessive, each part followed by something it cannot match.
_REFANG_LEAD = r"(?:(?<!\s)\s++)?"
_REFANG_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bhxxps\b", re.IGNORECASE), "https"),
    (re.compile(r"\bhxxp\b", re.IGNORECASE), "http"),
    (re.compile(_REFANG_LEAD + r"[\[({]\s*+(?:\.|dot)\s*+[\])}]\s*+", re.IGNORECASE), "."),
    (re.compile(_REFANG_LEAD + r"[\[({]\s*+(?:@|at)\s*+[\])}]\s*+", re.IGNORECASE), "@"),
    (re.compile(r"\[\s*:\s*\]"), ":"),
)


def refang(text: str) -> str:
    """Canonical live form of defanged text. Idempotent on clean input."""
    return _refang_tracked(text)[0]


def _refang_tracked(text: str) -> tuple[str, list[bool]]:
    """Refang + per-character "was rewritten" flags for the OUTPUT text.

    The flags are what make the per-occurrence `defanged` signal precise: a
    value that appears both clean and defanged in one message ("8.8.8.8 …
    8.8.8[.]8") can't be told apart by searching text — only by position.
    Matches are replaced right-to-left so earlier indices stay valid.
    """
    chars: list[tuple[str, bool]] = [(c, False) for c in text]
    for pattern, replacement in _REFANG_RULES:
        current = "".join(c for c, _ in chars)
        for m in reversed(list(pattern.finditer(current))):
            chars[m.start() : m.end()] = [(c, True) for c in replacement]
    refanged = "".join(c for c, _ in chars)
    return refanged, [rewritten for _, rewritten in chars]


# -- the regex table ----------------------------------------------------------

_URL_RE = re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE)
_URL_TRAILING_JUNK = ".,;:!?)\"'>]"

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")
_EMAIL_LOCAL_RUN_RE = re.compile(r"[A-Za-z0-9._%+-]+")
_EMAIL_START_RE = re.compile(r"\b[A-Za-z0-9._%+-]")

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)

_SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
_SHA1_RE = re.compile(r"\b[a-fA-F0-9]{40}\b")
_MD5_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")

# Candidate only — ipaddress.IPv4Address is the validator. The lookarounds keep
# "v1.2.3.4" (glued version) and "1.2.3.4.5" (dotted version) from matching;
# a trailing defang dot ("10.0.0.1.") still does.
_IPV4_CAND_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w)(?!\.\d)")
# "version 1.2.3.4" / "build 1.2.3.4" — explicit guard SARA lacked (its study
# flagged the gap); applied to the ~12 chars before the candidate. Bare "v" only
# counts as a word on its own — "-v" is a CLI flag, not a version marker.
_VERSION_CTX_RE = re.compile(
    r"(?:\b(?:version|ver\.?|build|release)|(?<![\w-])v)\s*[:=]?\s*$", re.IGNORECASE
)

# Candidate only — ≥2 colon groups; ipaddress validates (rejects MACs, times).
# The boundary check rejects candidates glued to identifiers ("std::vector"
# yields a technically-valid "d::") — any alphanumeric neighbor disqualifies.
# A trailing sentence period is fine ("Block 2001:db8::1."); a ".<digit>"
# continuation is not (partial dotted structure).
_IPV6_CAND_RE = re.compile(r"[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}")
_IPV6_V4_TAIL_RE = re.compile(r"^(?:\.\d{1,3}){3}")
_IPV6_BOUNDARY_JUNK = ":_%-"

_DOMAIN_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\."
_DOMAIN_CAND_RE = re.compile(r"\b(?:" + _DOMAIN_LABEL + r")+[a-z]{2,24}\b", re.IGNORECASE)
_DOMAIN_LABEL_RE = re.compile(_DOMAIN_LABEL, re.IGNORECASE)
_DOMAIN_START_RE = re.compile(r"\b[a-z0-9]", re.IGNORECASE)
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


# -- linear scans for the domain and email rules (B-010) -----------------------
# `finditer` retries a failed rule at every later position. On "a." repeated, a
# failed domain attempt had walked every label to the end of the run and back,
# and so did the attempt at each following label: 49 s at the 32,000-character
# cap, and 4 s for the email rule (B3). These scans try the same rule at the
# same positions, in the same order, but skip the positions that are proven to
# fail after a failure, so what they find is exactly what `finditer` found
# (tests/test_observables.py fuzzes the two against each other).


def _domain_candidates(text: str) -> Iterator[re.Match[str]]:
    """`_DOMAIN_CAND_RE.finditer(text)`, in linear time.

    When the rule fails at a label that is followed by its dot, it also fails at
    the next label: whatever could follow the next label could follow this one
    too, one label longer. The same holds at a start just after a hyphen inside
    a label. So the scan skips to the first point the chain of labels cannot
    reach, and tries again there.
    """
    pos = 0
    while (start := _DOMAIN_START_RE.search(text, pos)) is not None:
        at = start.start()
        m = _DOMAIN_CAND_RE.match(text, at)
        if m is not None:
            yield m
            pos = m.end()
            continue
        reach = at
        while (label := _DOMAIN_LABEL_RE.match(text, reach)) is not None:
            reach = label.end()
        pos = max(reach, at + 1)


def _email_candidates(text: str) -> Iterator[re.Match[str]]:
    """`_EMAIL_RE.finditer(text)`, in linear time.

    The local part is the whole run of its characters up to the "@", so every
    start inside one run needs the same "@" and the same domain after it: when
    one fails, they all do, and the scan skips the rest of the run.
    """
    pos = 0
    while (start := _EMAIL_START_RE.search(text, pos)) is not None:
        at = start.start()
        m = _EMAIL_RE.match(text, at)
        if m is not None:
            yield m
            pos = m.end()
            continue
        # `at` holds a local-part character, so the run is at least that one
        pos = _EMAIL_LOCAL_RUN_RE.match(text, at).end()


# -- extraction ---------------------------------------------------------------


def _spans_overlap(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < s_end and end > s_start for s_start, s_end in spans)


def _normalize_url(raw: str) -> str:
    """Lowercase scheme + host (not path or query), and drop any userinfo.

    B-018: the value is looked up at URLhaus and stored in `observables`, so a
    pasted `user:pass@` must never reach it. The URL without it is the same
    indicator.
    """
    try:
        parts = urlsplit(raw)
        netloc = parts.netloc.rsplit("@", 1)[-1].lower()
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
    refanged, rewritten = _refang_tracked(text)

    # (type, value, raw_matched_text, span) — the span drives double-extraction
    # guards, the residual, and the positional defanged flag.
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

    for m in _email_candidates(refanged):
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
        after_dot = refanged[end + 1] if end + 1 < len(refanged) else ""
        if prev and (prev.isalnum() or prev in _IPV6_BOUNDARY_JUNK or prev == "."):
            continue
        if nxt and (nxt.isalnum() or nxt in _IPV6_BOUNDARY_JUNK):
            continue
        if nxt == "." and after_dot.isdigit():
            continue
        # Bare "::" (C++ scope, slicing) is a *valid* IPv6 address — require hex.
        if not candidate.strip(":"):
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
        found.append((ObservableType.IPV6, _canonical_ipv6(ip), candidate, (start, end)))

    host_spans = url_spans + ipv6_spans  # complete by now; loop-invariant
    for m in _IPV4_CAND_RE.finditer(refanged):
        if _spans_overlap(m.start(), m.end(), host_spans):
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
            if _spans_overlap(m.start(), m.end(), hash_spans) or _spans_overlap(
                m.start(), m.end(), email_spans
            ):
                continue
            hash_spans.append(m.span())
            found.append((hash_type, m.group().lower(), m.group(), m.span()))

    nonhost_spans = url_spans + email_spans  # loop-invariant
    for m in _domain_candidates(refanged):
        if _spans_overlap(m.start(), m.end(), nonhost_spans):
            continue
        domain = _domain_backtrack(m.group())
        if domain is None:
            continue
        found.append((ObservableType.DOMAIN, domain.lower(), domain, m.span()))

    found.sort(key=lambda item: item[3])

    observables: list[Observable] = []
    index_of: dict[tuple[ObservableType, str], int] = {}
    for type_, value, _raw, (start, end) in found:
        # Positional: was any character of THIS occurrence rewritten by refang?
        defanged = any(rewritten[start:end])
        key = (type_, value)
        if key in index_of:
            # dedup keeps the first occurrence, but defanged-anywhere wins:
            # one defanged appearance is deliberate-analyst signal.
            i = index_of[key]
            if defanged and not observables[i].defanged:
                observables[i] = Observable(type_, value, observables[i].obs_id, True)
            continue
        index_of[key] = len(observables)
        observables.append(
            Observable(
                type=type_,
                value=value,
                obs_id=observable_id(type_, value),
                defanged=defanged,
            )
        )

    residual_chars = list(refanged)
    for _type, _value, _raw, (start, end) in found:
        residual_chars[start:end] = " " * (end - start)
    residual = " ".join("".join(residual_chars).split())

    return Extraction(observables=tuple(observables), residual=residual)


def extract_observables(text: str) -> list[Observable]:
    """Convenience wrapper when the residual isn't needed."""
    return list(extract(text).observables)
