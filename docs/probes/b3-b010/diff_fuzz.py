"""B3 / B-010: differential fuzz — the five rules before the fix against after.

    .venv/bin/python docs/probes/b3-b010/diff_fuzz.py

"Before" is each rule exactly as it stood at 27fc865. "After" is what
extract()/classify() run since the fix. Inputs: seeded generated strings over
the characters that steer the rules, plus every string in tests/fixtures (real
alerts, e-mails, rail and agent fixtures). Any difference in the matched spans
is printed and fails the run.
"""

import json
import random
import re
import sys
from pathlib import Path

from auspex.classify import classifier as C
from auspex.classify import observables as O

BEFORE = {
    "refang_dot": re.compile(r"\s*[\[({]\s*(?:\.|dot)\s*[\])}]\s*", re.IGNORECASE),
    "refang_at": re.compile(r"\s*[\[({]\s*(?:@|at)\s*[\])}]\s*", re.IGNORECASE),
    "domain": re.compile(
        r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}\b", re.IGNORECASE
    ),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b"),
    "greeting": re.compile(
        r"""^\s*(?:hi|hiya|hello|hey|heya|howdy|yo|greetings|hola|salam|
           good\s+(?:morning|afternoon|evening|day)|morning|evening)
        (?:\s*,?\s*(?:there|again|all|team|everyone|folks|auspex))?
    \s*[!.,\s]*$""",
        re.IGNORECASE | re.VERBOSE,
    ),
    # Added after B3's review of the fix found it (search, not match).
    "analytical": re.compile(
        r"""(?:^|[.!?]\s+)\s*(?:
        analy[sz]e | assess | evaluate | investigate | explain | triage\s+this\b |
        break\s+down | walk\s+me\s+through | diagnose |
        why\b | what\s+happened | how\s+did | how\s+was | compare | correlate
    )""",
        re.IGNORECASE | re.VERBOSE,
    ),
}


def before(name, text):
    if name == "greeting":
        m = BEFORE[name].match(text)
        return [m.span()] if m else []
    if name == "analytical":
        m = BEFORE[name].search(text)
        return [m.span()] if m else []
    return [m.span() for m in BEFORE[name].finditer(text)]


def after(name, text):
    if name == "refang_dot":
        return [m.span() for m in O._REFANG_RULES[2][0].finditer(text)]
    if name == "refang_at":
        return [m.span() for m in O._REFANG_RULES[3][0].finditer(text)]
    if name == "domain":
        return [m.span() for m in O._domain_candidates(text)]
    if name == "email":
        return [m.span() for m in O._email_candidates(text)]
    if name == "analytical":
        m = C._ANALYTICAL_INITIAL_RE.search(text)
        return [m.span()] if m else []
    m = C._GREETING_RE.match(text)
    return [m.span()] if m else []


def strings_in(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings_in(v)


def real_inputs():
    root = Path("tests/fixtures")
    for p in sorted(root.rglob("*")):
        if p.suffix == ".json":
            try:
                yield from strings_in(json.loads(p.read_text()))
            except (ValueError, UnicodeDecodeError):
                continue
        elif p.is_file() and p.suffix in (".eml", ".txt", ".md"):
            yield p.read_text(errors="replace")


def generated(n, seed=1010):
    rng = random.Random(seed)  # noqa: S311
    alphabet = "ab1-._@ \t\n[](){}dotDOTatcom%+éK,!"
    words = ["hi", "hiya", "hello", "hey", "good", "morning", "evening", "there", "team",
             "evil", "com", "net", "x" * 64, "a-", "-b", "_", "[.]", "(dot)", "{at}", "@",
             " ", "  ", "\t", "\n", ",", "!", ".", "..", "a.", "bob", "smith", "?",
             "analyze", "why", "what happened", "how did", "triage this", "Explain"]
    for _ in range(n):
        if rng.random() < 0.5:
            yield "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
        else:
            yield "".join(rng.choice(words) for _ in range(rng.randint(0, 12)))


if __name__ == "__main__":
    real = list(real_inputs())
    counts = {"generated": 0, "real": 0}
    diffs = 0
    for kind, inputs in (("generated", generated(200_000)), ("real", real)):
        for text in inputs:
            counts[kind] += 1
            for name in BEFORE:
                b, a = before(name, text), after(name, text)
                if b != a:
                    diffs += 1
                    print(f"DIFF {name} {kind}: {text[:80]!r} before={b[:5]} after={a[:5]}")
    print(f"inputs: {counts['generated']} generated, {counts['real']} real "
          f"(tests/fixtures); rules: {len(BEFORE)}; differences: {diffs}")
    sys.exit(1 if diffs else 0)
