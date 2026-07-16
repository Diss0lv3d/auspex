"""Shortcut handlers — S4 step 3. The 92% answers, with zero LLM and zero network.

Static, deterministic copy in the Auspex voice (calm, precise, analyst-to-
analyst; the engine is never named — brand rule, test-enforced). Deferred
capabilities say so plainly (SARA's DEFERRED rail): honest "not wired up yet"
beats a fabricated verdict — nothing here may claim work that didn't happen
(D-014 spirit).

`shortcut_answer` is fallible by design: DEEP (or anything unrecognized)
returns None and the caller falls through to the model path.
"""

from dataclasses import dataclass

from auspex.classify.classifier import Category, Classification
from auspex.classify.observables import Observable, ObservableType

GREETING_COPY = (
    "Hello — Auspex here, watching with you. Paste an indicator (IP, domain, "
    "URL, hash, CVE) or describe what you're investigating and I'll take it "
    "from there."
)

IDENTITY_COPY = (
    "I'm Auspex — a security intelligence co-analyst. I read the signals: "
    "indicators, vulnerabilities, and the context around them, and I flag "
    "what matters before it lands. Ask me to check an observable, or walk me "
    "through what you're seeing. The flock sees first."
)

ENRICHMENT_DEFERRED_COPY = (
    "Enrichment — reputation, prevalence, verdicts — isn't connected yet "
    "(deferred). These are parsed and normalized only; you can reference any "
    "of them by its id."
)

CVE_DEFERRED_COPY = (
    "The vulnerability knowledge base isn't connected yet (deferred), so I "
    "can't give you curated intel on {cves} in this build. If you want "
    "reasoning about it in context, ask for an analysis and I'll take the "
    "deep path."
)

DEFINITION_DEFERRED_COPY = (
    "Definitions come from the knowledge base, which isn't connected yet "
    "(deferred). Ask me to reason about it in context — e.g. \"explain how "
    "this shows up in an investigation\" — and I'll take the deep path "
    "instead."
)

NO_OBSERVABLES_COPY = (
    "I couldn't parse a well-formed indicator out of that. Supported: IPv4/"
    "IPv6, domains, URLs, file hashes (MD5/SHA-1/SHA-256), emails, CVE IDs — "
    "defanged forms are fine."
)


@dataclass(frozen=True)
class ShortcutAnswer:
    category: Category
    text: str


def _observable_line(o: Observable) -> str:
    # Plain text, no markdown — the chat UI renders content verbatim (S3 shell).
    line = f"- {o.value} — {o.type} (id {o.obs_id})"
    if o.defanged:
        line += " · received defanged"
    return line


def _ioc_check_text(observables: tuple[Observable, ...]) -> str:
    if not observables:  # classifier shouldn't send this, but stay fallible
        return NO_OBSERVABLES_COPY
    count = len(observables)
    noun = "observable" if count == 1 else "observables"
    lines = "\n".join(_observable_line(o) for o in observables)
    return f"Parsed {count} {noun}:\n\n{lines}\n\n{ENRICHMENT_DEFERRED_COPY}"


def _cve_lookup_text(observables: tuple[Observable, ...]) -> str:
    cves = [o.value for o in observables if o.type is ObservableType.CVE]
    return CVE_DEFERRED_COPY.format(cves=", ".join(cves) if cves else "that CVE")


def shortcut_answer(classification: Classification) -> ShortcutAnswer | None:
    """The fast-path answer, or None when this turn needs the model (DEEP)."""
    category = classification.category
    if category is Category.GREETING:
        text = GREETING_COPY
    elif category is Category.IDENTITY:
        text = IDENTITY_COPY
    elif category is Category.IOC_CHECK:
        text = _ioc_check_text(classification.observables)
    elif category is Category.CVE_LOOKUP:
        text = _cve_lookup_text(classification.observables)
    elif category is Category.DEFINITION:
        text = DEFINITION_DEFERRED_COPY
    else:
        return None
    return ShortcutAnswer(category=category, text=text)
