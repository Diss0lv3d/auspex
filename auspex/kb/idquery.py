"""ID-query detection — the neural bypass rail (SARA pattern, re-snapshotted in
docs/probes/2026-07-17-sara-rrf-retriever-pattern.md §2).

An exact CVE/MITRE-ID lookup must never depend on vector similarity: embeddings
don't understand "T1548", and RRF would *promote* the neural noise. When a
query is ID-dominant, retrieval takes the keyword rail (term/prefix on `ids`)
and skips the neural leg entirely.

Pure functions, no I/O.
"""

import re

# MITRE ATT&CK object ids (T/TA/M/G/S/DS + digits, optional .sub) and CVE ids.
# The CVE arm matches auspex/classify/observables.py:_CVE_RE.
KB_ID_RE = re.compile(
    r"\b(T[A-Z]?\d{4}(?:\.\d{3})?|M\d{4}|G\d{4}|S\d{4}|DS\d{4}|CVE-\d{4}-\d{4,7})\b",
    re.IGNORECASE,
)

# Words that don't make an ID query "about" anything beyond the ID itself
# (SARA sara_retriever.py:587-597, trimmed to what our shortcuts see).
_TRIVIAL_QUALIFIERS = frozenset(
    """
    overview description describe explain details detail summary info
    information what is are tell me about and the a an show give provide for
    of its this that define definition meaning
    mitre att&ck attck attack technique techniques sub-technique subtechnique
    sub-techniques subtechniques framework list how do i can detect detection
    mitigate mitigation mitigations prevent prevention in my environment use
    used by to with vulnerability vuln cve
    """.split()
)


def extract_kb_ids(text: str) -> tuple[str, ...]:
    """All KB ids in the text, normalized upper, order kept, de-duplicated."""
    seen: dict[str, None] = {}
    for m in KB_ID_RE.finditer(text):
        seen.setdefault(m.group(1).upper())
    return tuple(seen)


def is_id_query(text: str) -> bool:
    """True when the query is *about* an ID and nothing else — empty remainder,
    ≤ 2 leftover words, or only trivial qualifiers ("what is", "describe",
    "mitre technique", …)."""
    if not KB_ID_RE.search(text):
        return False
    remaining = KB_ID_RE.sub(" ", text)
    remaining = re.sub(r"[?!.,;:'\"]", "", remaining).strip()
    if not remaining:
        return True
    words = remaining.split()
    if len(words) <= 2:
        return True
    return not ({w.lower() for w in words} - _TRIVIAL_QUALIFIERS)
