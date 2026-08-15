"""Which retrieved page actually *defines* the thing that was asked about.

TD-026: an analyst asking "what is phishing" was shown **T1598: Phishing for
Information** — a real page, above its floor, about reconnaissance. Retrieval
was not the problem; the canonical page was in the neural leg at rank 2. Ranking
was. RRF fragments a doc's vote across its chunks (fixed in `rrf_fuse_docs`) and
BM25 has no notion of "this page is *about* the query" — it rewards documents
that repeat the query's words, and a sub-technique repeats them more than the
parent whose title simply *is* the term.

So this adds the signal that was missing, in code (D-006), over candidates that
have already cleared their floor — **are the title and the question about each
other?**, asked in both directions and combined as a harmonic mean:

- *How much of the TITLE did the question ask for?* "Phishing" is entirely
  accounted for by "what is phishing"; "Phishing for Information" is not — two
  thirds of that title is about something the analyst did not ask about. This
  runs the direction BM25 cannot: it rewards a title for being short and fully
  asked-for, where BM25 rewards a body for being long and repetitive.
- *How much of the QUESTION does the title account for?* Asked alone, the first
  measure rewards brevity without limit and walks straight into the same class
  of error: asked "what is credential dumping", ATT&CK offers a page titled
  simply **Credentials** — 100% asked-for, and a reconnaissance page about
  harvesting victim identity information. It accounts for one word of the
  question where "OS Credential Dumping" accounts for two.

Requiring both is what "this page is about this question" means; neither alone
says it, and each one alone was measured picking a wrong page.

Deliberately NOT a stopword list. S19's second attempt at TD-026 promoted on
exact title match through a hand-written stopword list and got 4/7 with a list
that would rot; the words that matter here are the ones already in the title,
and a question's filler words dilute every candidate equally, so the ratios need
no vocabulary of their own. The only lexical judgement is that `interpreters`
and `interpreter` are the same word, handled by prefix equivalence rather than a
stemmer dependency.

**It cannot fabricate.** This re-orders an existing post-floor candidate list and
never adds to it, so an off-corpus query that retrieved nothing still renders
nothing, and every honest-miss guarantee in D-018/TD-005 is untouched.
"""

from __future__ import annotations

import re

from auspex.kb.types import KBHit

# Our titles are rendered "T1566: Phishing" — the id prefix is our own
# formatting, not part of the page's name, and leaving it in would penalise
# every ATT&CK page by one unaskable token.
#
# An id is recognised structurally rather than by listing the schemes we happen
# to ingest today: a single leading token that contains a digit, then a colon.
# That covers T1566, T1059.007, TA0008 and CVE-2021-44228 without a per-source
# pattern to keep in sync with the ingest side, and leaves an ordinary title
# like "Phishing: a primer" alone, because "Phishing" has no digit in it.
_TITLE_ID_PREFIX_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9.\-]*\d[A-Za-z0-9.\-]*\s*:\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Below this, a title is not "what the question is about" — it merely shares a
# word with it. Deliberately low: within one query the RANKING is what decides,
# and this only exists to stop a lone coincidental word from re-ordering
# anything. The lowest-scoring correct page in the labeled battery is T1059 at
# 0.36 ("Command and Scripting Interpreter" against a seven-word question, which
# dilutes every candidate equally).
MIN_TITLE_SCORE = 0.3

# Prefix equivalence stands in for stemming: "interpreter" and "interpreters"
# are the same word to an analyst. Short tokens must match exactly, because
# 4-character prefixes of short words collide ("land"/"landing" is fine,
# "the"/"them" is not).
_MIN_PREFIX = 4


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= _MIN_PREFIX and longer.startswith(shorter)


def title_coverage(title: str, query: str) -> float:
    """Fraction of the title's words the question actually asked for, 0.0–1.0."""
    title_words = _tokens(_TITLE_ID_PREFIX_RE.sub("", title or ""))
    if not title_words:
        return 0.0
    query_words = _tokens(query)
    matched = sum(1 for w in title_words if any(_same_word(w, q) for q in query_words))
    return matched / len(title_words)


def query_coverage(title: str, query: str) -> float:
    """Fraction of the question's words the title accounts for, 0.0–1.0."""
    query_words = _tokens(query)
    if not query_words:
        return 0.0
    title_words = _tokens(_TITLE_ID_PREFIX_RE.sub("", title or ""))
    matched = sum(1 for q in query_words if any(_same_word(q, w) for w in title_words))
    return matched / len(query_words)


def title_score(title: str, query: str) -> float:
    """How well a title and a question are *about each other* — the harmonic
    mean of the two coverages.

    Title coverage alone rewards brevity without limit, and the corpus punishes
    that: asked "what is credential dumping", ATT&CK offers a page titled simply
    **Credentials** (T1589.001, a reconnaissance page about harvesting victim
    identity information). Its title is 100% asked-for and it is the wrong
    answer — the same shape of error as the T1598 phishing bug this work exists
    to fix, reintroduced from the other side.

    Query coverage is the counterweight: "Credentials" accounts for one word of
    the question, "OS Credential Dumping" for two. Requiring both to be high is
    what "this page is about this question" means, and neither alone says it.
    """
    t, q = title_coverage(title, query), query_coverage(title, query)
    if not t or not q:
        return 0.0
    return 2 * t * q / (t + q)


def promote_canonical(query: str, hits: list[KBHit]) -> list[KBHit]:
    """Move the page the question is most *about* to the front.

    Ties break on the existing fused score, so retrieval still decides between
    two equally-titled pages — this only overrules retrieval when one candidate
    is unambiguously more on-topic by title than the one retrieval picked.
    """
    if len(hits) < 2:
        return hits
    scored = [(title_score(h.title or h.doc_id, query), h) for h in hits]
    best = max(score for score, _ in scored)
    if best < MIN_TITLE_SCORE:
        return hits
    # Stable: `hits` is already fused-score-ordered, so the first candidate at
    # the best score is the highest-scoring one.
    winner = next(h for score, h in scored if score == best)
    if winner is hits[0]:
        return hits
    return [winner] + [h for h in hits if h is not winner]


__all__ = [
    "MIN_TITLE_SCORE",
    "promote_canonical",
    "query_coverage",
    "title_coverage",
    "title_score",
]
