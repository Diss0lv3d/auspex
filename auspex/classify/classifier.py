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
# Public: the enrichment skip-filter (S5) reuses this list — enriching
# google.com wastes provider quota to learn that Google is Google.
COMMON_DOMAINS = frozenset(
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
# Two or more RFC-5322 header lines = a pasted email, not prose about email.
# Same set the mode resolver keys PHISHING_ANALYSIS on (it imports this).
_EMAIL_HEADER_RE = re.compile(
    r"^(?:from|to|cc|subject|date|received|return-path|reply-to|message-id|"
    r"delivered-to|dkim-signature|x-originating-ip|authentication-results)\s*:",
    re.IGNORECASE | re.MULTILINE,
)

# S28 (D-047): the identity shortcut caught 3 of 45 independently written ways
# of asking who made the assistant or what model it runs on. The rest went to
# the model, which answered — live, 4 of 4 — that it was a different vendor's
# product. Widened by the SAME rule as before: the whole message must be the
# question, and it must point at the assistant itself ("you", "this
# assistant"), never at a work object ("this scheduled task", "the firewall").
# Errors still bias DEEP. Judged on a held-out battery:
# docs/probes/2026-10-11-s28-identity-shortcut.md.
_SELF = r"(?:you|u|ya|yourself|this\s+(?:assistant|co-?analyst|bot|chatbot|chat|ai|platform))"
# A model's own name is unambiguous after "is this"; a company's is not ("is
# this google?" is as likely about an IP range), so a maker needs a connective
# ("is this powered by …", "are you from …").
_MODEL_NAME = (
    r"(?:chat-?gpt|gpt[\w.-]*|claude|gemini|bard|llama[\w.-]*|mistral|mixtral|deepseek|"
    r"grok|qwen[\w.-]*|glm[\w.-]*)"
)
_VENDOR = r"(?:" + _MODEL_NAME + r"|openai|anthropic|google|meta|cohere|copilot)"
# What the assistant IS may be asked of a bare "this" ("which AI is this?"); who
# MAKES it may not ("which company is behind this?" is a follow-up about a
# domain as often as about us), so an organisation needs "you" or "this
# assistant".
_KIND_AI = (
    r"(?:ai(?:\s+model)?|llm|model(?:\s+version)?|engine|(?:large\s+)?language\s+model|"
    r"vendor's\s+ai)"
)
_KIND_ORG = r"(?:company|vendor|provider)"
_ASKS = (
    r"(?:\s+(?:are|r|is|do|does|did|powers|made|built|trained|is\s+behind|behind|"
    r"is\s+answering))*"
)
_TAIL = r"(?:\s+(?:running\s+on|using|use|are|exactly|right\s+now|under\s+the\s+hood))?"
_LEAD_IN = (
    r"(?:(?:hey|hi|so|ok|okay|btw|quick\s+question|just\s+curious|out\s+of\s+curiosity|"
    r"curious|sorry\s+if\s+this\s+is\s+random)\s*[,:\-–—]*\s*(?:but\s+)?)*"
)
_IDENTITY_RE = re.compile(
    r"^\s*" + _LEAD_IN + r"""(?:
        who\s+(?:are|r)\s+(?:you|u) |
        who\s+is\s+this |
        what\s+are\s+you |
        what(?:'s|\s+is)\s+your\s+name |
        are\s+you\s+(?:an?\s+)?(?:ai|bot|human|real|llm|model|chatbot|gpt\S*|chatgpt) |
        what\s+(?:model|llm|ai|engine)\s+(?:are\s+you|is\s+this|powers\s+(?:you|this)) |
        which\s+(?:model|llm)\s+(?:are\s+you|is\s+this) |
        introduce\s+yourself |
        tell\s+me\s+about\s+yourself |

        # who made / trained / owns the assistant
        who(?:'s|\s+is)?\s+(?:made|built|created|developed|trained|programmed|designed|
            owns|makes|behind)\s+""" + _SELF + r"""
            (?:\s+and\s+on\s+what\s+data)? |

        # what / which model, LLM, company ... the assistant
        (?:tell\s+me\s+)?(?:what|which|wat)(?:'s|s|\s+is)?\s+(?:the\s+|your\s+|ur\s+)?
            (?:kind\s+of\s+)?(?:
                """ + _KIND_AI + _ASKS + r"""\s+(?:""" + _SELF + r"""|this|me) |
                """ + _KIND_ORG + _ASKS + r"""\s+""" + _SELF + r"""
            )""" + _TAIL + r""" |
        what(?:'s|\s+is)\s+(?:your|ur)\s+(?:underlying\s+|base\s+)?(?:model|llm|engine|ai) |

        # are you / is this <a known model or vendor>
        (?:are|r)\s+(?:you|u)\s+(?:an?\s+)?(?:fine-tuned\s+)?
            (?:(?:built\s+on|based\s+on|made\s+by|from|powered\s+by|running\s+on|trained\s+by)\s+)?
            """ + _VENDOR + r"""(?:\s+or\s+\w+)*(?:\s+under\s+the\s+hood)? |
        (?:are|r)\s+(?:you|u)\s+(?:an?\s+)?open[- ]source\s+(?:model|llm|ai) |
        is\s+this(?:\s+thing)?\s+""" + _MODEL_NAME + r"""(?:\s+or\s+(?:something\s+else|\w+))? |
        is\s+this(?:\s+thing)?\s+(?:powered\s+by|built\s+on|made\s+by|based\s+on)
            \s+""" + _VENDOR + r""" |
        did\s+""" + _VENDOR + r"""\s+(?:make|build|train|create|develop)\s+(?:you|u) |

        # what is it built on
        what(?:'s|\s+is)\s+under\s+the\s+hood(?:\s+of\s+""" + _SELF + r""")? |
        what\s+are\s+(?:you|u)\s+(?:built|based|running|powered)\s+on
    )\s*[?!.\s]*$""",
    re.IGNORECASE | re.VERBOSE,
)

# True salutations only. Bare acknowledgements ("ok", "thanks", "cool") and
# farewells deliberately go DEEP: mid-investigation they are context ("ok" may
# answer the model's question) and must reach the model, not a canned greeting.
_GREETING_RE = re.compile(
    r"""^\s*(?:hi|hiya|hello|hey|heya|howdy|yo|greetings|hola|salam|
           good\s+(?:morning|afternoon|evening|day)|morning|evening)
        (?:\s*,?\s*(?:there|again|all|team|everyone|folks|auspex))?
    \s*[!.,\s]*$""",
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


def _is_email_paste(q: str) -> bool:
    """Format beats keywords (S11): a pasted email (≥2 RFC-5322 header lines) is
    structured input, like an alert paste — it always takes the deep path, never
    the IOC_CHECK shortcut, even when it carries only a couple of addresses. The
    email names its own sender/recipient; treating it as a bag of IOCs to enrich
    would both miss the phishing analysis and surface the victim as an IOC."""
    return len(_EMAIL_HEADER_RE.findall(q)) >= 2


# D-050 (S28): a request to put a note on an indicator — the one change the
# platform can make, and only by proposing it. Measured on an independently
# written battery: 10 of 30 such asks took the IOC-check shortcut (no model,
# no proposal, and nothing said so), and the rest landed in narrative modes they
# could not fill. `_NOTE_ASK` finds the ask anywhere, so it vetoes the shortcut
# for a mixed "check X and add a note" too; `_NOTE_REQUEST` finds it LEADING the
# message, which is what a note-only request looks like — a mixed one asks its
# question first. Both bias the same way: a false ask costs a deep turn, or a
# mode with no sections; never a wrong answer.
_NOTE_NOUN = r"(?:notes?|comments?|remarks?|annotations?)"
_NOTE_VERB = (
    r"(?:add|attach|put|leave|log|pin|stick|write|append|record|place)\s+"
    r"(?:(?:a|an|the|this|following|quick|short|new|another)\s+)*" + _NOTE_NOUN + r"\b"
)
_NOTE_ASK_RE = re.compile(
    r"\b(?:" + _NOTE_VERB + r"|annotat(?:e|ed)\b|annotaet\b|"
    r"(?:jot|mark)\s+(?:it\s+)?down\s+(?:on|against|for)\b|"
    r"record\s+(?:on|against|for)\b|with\s+a\s+" + _NOTE_NOUN + r"\b|"
    r"(?:pls|plz|please)\s+note\b|note\s+(?:on|against)\s+(?:it|that|this|them)\b|"
    r"update\s+(?:the\s+)?" + _NOTE_NOUN + r"\s+(?:on|for)\b)",
    re.IGNORECASE,
)
_NOTE_REQUEST_RE = re.compile(
    r"^\s*(?:(?:hey|hi|ok|so|btw)\s*[,:]?\s*)?"
    r"(?:(?:can|could|would)\s+(?:you|u)\s+|please\s+|pls\s+|plz\s+|kindly\s+)*"
    r"(?:" + _NOTE_VERB + r"|annot\w+\b|(?:jot|mark)\s+(?:it\s+)?down\s+(?:on|against|for)\b|"
    r"record\s+(?:on|against|for)\b|tag\b.{1,160}?\bwith\s+a\s+" + _NOTE_NOUN + r"\b|"
    r"update\s+(?:the\s+)?" + _NOTE_NOUN + r"\s+(?:on|for)\b|"
    r"note\s+(?!that\b|to\b|:)\S)",
    re.IGNORECASE,
)


def asks_for_note(q: str) -> bool:
    """Whether the message asks, anywhere, for a note on an indicator (D-050)."""
    return bool(_NOTE_ASK_RE.search(q))


def is_note_request(q: str) -> bool:
    """Whether the message LEADS with that ask: a note-only request (D-050)."""
    return bool(_NOTE_REQUEST_RE.search(q))


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
    hot = [d for d in domains if d.defanged or not is_common_domain(d.value)]
    if not hot:
        return False
    return len(q.split()) <= DEFINITION_MAX_WORDS or bool(_CHECK_VERB_RE.search(q))


def is_common_domain(domain: str) -> bool:
    """Suffix-aware: www.google.com is as ubiquitous as google.com."""
    return domain in COMMON_DOMAINS or any(
        domain.endswith("." + common) for common in COMMON_DOMAINS
    )


def classify(query: str) -> Classification:
    q = query.strip()
    extraction = extract(q)
    observables = extraction.observables

    def result(category: Category) -> Classification:
        return Classification(category=category, observables=observables)

    if _is_alert_paste(q) or _is_email_paste(q):
        return result(Category.DEEP)
    if len(q) <= IDENTITY_MAX_CHARS and _IDENTITY_RE.match(q):
        return result(Category.IDENTITY)
    if _GREETING_RE.match(q):
        return result(Category.GREETING)
    if asks_for_note(q) or is_note_request(q):
        # D-050: proposing the note needs the model; the shortcut has none.
        return result(Category.DEEP)

    residual_words = len(extraction.residual.split())
    if not _is_analytical(q):
        if _ioc_shaped(observables, q) and residual_words <= IOC_RESIDUAL_MAX_WORDS:
            return result(Category.IOC_CHECK)
        if (
            any(o.type is ObservableType.CVE for o in observables)
            and residual_words <= CVE_RESIDUAL_MAX_WORDS
        ):
            return result(Category.CVE_LOOKUP)
        if not observables and len(q.split()) <= DEFINITION_MAX_WORDS and _DEFINITION_RE.match(q):
            return result(Category.DEFINITION)

    return result(Category.DEEP)
