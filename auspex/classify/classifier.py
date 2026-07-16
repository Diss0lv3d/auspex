"""Code-owned query classifier — S4 step 2. The 92/8 split decision point.

Deterministic: regex + keyword + format signals; **format beats keywords**
(an alert paste with IOCs inside is still an alert paste). Errors must bias
DEEP — a wrong deep verdict costs tokens, a wrong shortcut gives a wrong
answer. Pure functions; no LLM, no network, no I/O.

Decision order (each step pinned by tests):
1. alert-format paste (CEF/LEEF/syslog/JSON) → DEEP
2. identity (anchored, short) → IDENTITY — before anything keyword-driven so
   the brand answer never depends on classifier drift (SARA phase-0 pattern)
3. greeting (anchored full match) → GREETING
4. analytical-verb veto → DEEP even when observables are present
5. observables present + small residual → IOC_CHECK (CVE-only → CVE_LOOKUP)
6. definition-shaped, short, observable-free → DEFINITION
7. everything else → DEEP
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from auspex.classify.observables import Observable, ObservableType, extract


class Category(StrEnum):
    GREETING = "greeting"
    IDENTITY = "identity"
    IOC_CHECK = "ioc_check"
    CVE_LOOKUP = "cve_lookup"
    DEFINITION = "definition"
    DEEP = "deep"


@dataclass(frozen=True)
class Classification:
    category: Category
    observables: tuple[Observable, ...]  # extracted once here; downstream reuses


# Residual = words left after blanking observable spans, so a bulk 30-hash
# paste ("triage these: …") stays on the fast path while a paragraph of
# analysis containing one IP does not.
IOC_RESIDUAL_MAX_WORDS = 12
CVE_RESIDUAL_MAX_WORDS = 20
DEFINITION_MAX_WORDS = 10
IDENTITY_MAX_CHARS = 80

# Bare mentions of ubiquitous domains are not IOC queries ("check google.com").
# A *defanged* common domain still counts — the analyst defanged it on purpose.
_COMMON_DOMAINS = frozenset(
    """
    google.com github.com microsoft.com apple.com amazon.com cloudflare.com
    facebook.com twitter.com x.com linkedin.com youtube.com wikipedia.org
    stackoverflow.com reddit.com office.com live.com gmail.com outlook.com
    azure.com portal.azure.com auspex.dev
    """.split()
)

_SYSLOG_PRI_RE = re.compile(r"^\s*<\d{1,3}>")
_CEF_LEEF_RE = re.compile(r"\b(?:CEF:\d+\||LEEF:\d+(?:\.\d+)?\|)")
_JSON_KEY_RE = re.compile(r"\"\w+\"\s*:")

_IDENTITY_RE = re.compile(
    r"""^\s*(?:
        who\s+(?:are|r)\s+(?:you|u) |
        who\s+is\s+this |
        what\s+are\s+you |
        what(?:'s|\s+is)\s+your\s+name |
        are\s+you\s+(?:an?\s+)?(?:ai|bot|human|real|llm|model|chatbot|gpt\S*|chatgpt) |
        what\s+(?:model|llm|ai|engine)\s+(?:are\s+you|is\s+this|powers\s+(?:you|this)) |
        which\s+(?:model|llm)\s+(?:are\s+you|is\s+this) |
        who\s+(?:made|built|created)\s+you |
        introduce\s+yourself |
        tell\s+me\s+about\s+yourself
    )\s*[?!.\s]*$""",
    re.IGNORECASE | re.VERBOSE,
)

_GREETING_RE = re.compile(
    r"""^\s*(?:
        (?:hi|hiya|hello|hey|heya|howdy|yo|greetings|hola|salam|
           good\s+(?:morning|afternoon|evening|day)|morning|evening)
        (?:\s*,?\s*(?:there|again|all|team|everyone|folks|auspex))? |
        (?:thanks|thank\s+you|thx|ty)(?:\s+(?:so\s+much|a\s+lot|very\s+much))? |
        ok(?:ay)?|cool|nice|great|awesome|perfect|cheers|
        (?:bye|goodbye|good\s*night|see\s+you|later)
    )\s*[!.,\s]*$""",
    re.IGNORECASE | re.VERBOSE,
)

# Sentence-initial analytical verbs (SARA classify.py:344-352 pattern) plus a
# few anywhere-markers that are unambiguous asks for analysis.
_ANALYTICAL_INITIAL_RE = re.compile(
    r"""(?:^|[.!?]\s+)\s*(?:
        analy[sz]e | assess | evaluate | investigate | explain | triage\s+this\b |
        break\s+down | walk\s+me\s+through | diagnose |
        why\b | what\s+happened | how\s+did | how\s+was | compare | correlate
    )""",
    re.IGNORECASE | re.VERBOSE,
)
_ANALYTICAL_ANYWHERE_RE = re.compile(
    r"""\b(?:
        is\s+(?:this|that|it)\s+(?:malicious|safe|bad|legit|phishing|a\s+threat) |
        what\s+do\s+you\s+think |
        should\s+i\s+(?:worry|be\s+worried|escalate) |
        why\b
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)

# Verbs that make a lone domain an IOC query even in a longer sentence.
_CHECK_VERB_RE = re.compile(
    r"\b(?:check|verify|enrich|lookup|look\s+up|scan|reputation|resolve|block(?:ed)?|"
    r"seen|flag(?:ged)?|what\s+(?:is|about))\b",
    re.IGNORECASE,
)

_DEFINITION_RE = re.compile(
    r"^\s*(?:what\s+is|what\s+are|what's|define|definition\s+of|meaning\s+of)\s+\S+",
    re.IGNORECASE,
)


def _is_alert_paste(q: str) -> bool:
    """Format beats keywords: structured alert/log pastes always take the deep
    path, no matter what IOCs they contain."""
    if q.startswith(("CEF:", "LEEF:")) or _SYSLOG_PRI_RE.match(q):
        return True
    if _CEF_LEEF_RE.search(q):
        return True
    return q.lstrip().startswith("{") and bool(_JSON_KEY_RE.search(q))


def _is_analytical(q: str) -> bool:
    return bool(_ANALYTICAL_INITIAL_RE.search(q) or _ANALYTICAL_ANYWHERE_RE.search(q))


def _ioc_shaped(observables: tuple[Observable, ...], q: str) -> bool:
    """Hash/IP/URL/email always qualify. A domain qualifies when it isn't a
    ubiquitous domain (unless defanged — deliberate) and the query is short or
    carries a check-verb (SARA classify.py:353-363 pattern)."""
    domains: list[Observable] = []
    for o in observables:
        if o.type is ObservableType.CVE:
            continue
        if o.type is ObservableType.DOMAIN:
            domains.append(o)
        else:
            return True
    hot = [d for d in domains if d.defanged or d.value not in _COMMON_DOMAINS]
    if not hot:
        return False
    return len(q.split()) <= DEFINITION_MAX_WORDS or bool(_CHECK_VERB_RE.search(q))


def classify(query: str) -> Classification:
    q = query.strip()
    extraction = extract(q)
    observables = extraction.observables

    def result(category: Category) -> Classification:
        return Classification(category=category, observables=observables)

    if _is_alert_paste(q):
        return result(Category.DEEP)
    if len(q) <= IDENTITY_MAX_CHARS and _IDENTITY_RE.match(q):
        return result(Category.IDENTITY)
    if _GREETING_RE.match(q):
        return result(Category.GREETING)

    residual_words = len(extraction.residual.split())
    if not _is_analytical(q):
        if _ioc_shaped(observables, q) and residual_words <= IOC_RESIDUAL_MAX_WORDS:
            return result(Category.IOC_CHECK)
        if (
            any(o.type is ObservableType.CVE for o in observables)
            and residual_words <= CVE_RESIDUAL_MAX_WORDS
        ):
            return result(Category.CVE_LOOKUP)

    if (
        not observables
        and len(q.split()) <= DEFINITION_MAX_WORDS
        and _DEFINITION_RE.match(q)
    ):
        return result(Category.DEFINITION)

    return result(Category.DEEP)
