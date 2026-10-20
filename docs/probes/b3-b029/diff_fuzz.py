"""B3 / B-029: differential fuzz -- the guard before the fix against after.

    .venv/bin/python docs/probes/b3-b029/diff_fuzz.py <path to the old guard.py>

The old guard is auspex/guard.py at 9475752 (`git show 9475752:auspex/guard.py`),
imported as a separate module. For every input it compares inspect()'s whole
answer (verdict, rule, reason) and, for the two run-led rules, the spans over
the raw text and over the folded text. Inputs: seeded strings heavy on
newline and whitespace runs, plus every string in tests/fixtures.
"""

import importlib.util
import json
import random
import sys
from pathlib import Path

from auspex import guard as NEW

spec = importlib.util.spec_from_file_location("old_guard", sys.argv[1])
OLD = importlib.util.module_from_spec(spec)
sys.modules["old_guard"] = OLD  # its dataclasses look themselves up here
spec.loader.exec_module(OLD)
OLD_RULES, NEW_RULES = dict(OLD._INJECTION_PATTERNS), dict(NEW._INJECTION_PATTERNS)
RUN_LED = ("persona_override", "role_marker_injection")


def answer(mod, text):
    o = mod.inspect(text)
    return (o.verdict.value, o.label, o.reason)


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
    for p in sorted(Path("tests/fixtures").rglob("*")):
        if p.suffix == ".json":
            try:
                yield from strings_in(json.loads(p.read_text()))
            except (ValueError, UnicodeDecodeError):
                continue
        elif p.is_file() and p.suffix in (".eml", ".txt", ".md"):
            yield p.read_text(errors="replace")


PIECES = ["\n", "\n\n", " ", "  ", "\t", "\r", "\r\n", " ", " ", "​", ".", "!", "?",
          "x", "<", "[", "> ", "```", '"', "you are now", "You Are Now", "from now on, you",
          "pretend to be", "pretend you are", "act as if you were", "act as an unrestricted",
          "you must now obey", "system", "assistant", ":", "###", " you are", " you must",
          "<|im_start|>", "<|system|>", "[INST]", "<<SYS>>", "ignore all previous instructions",
          "is this phishing? ", "the email says ", "Subject: hi\nFrom: a@b.co\n\n", "ｙｏｕ ａｒｅ ｎｏｗ"]


def generated(n, seed=1029):
    rng = random.Random(seed)  # noqa: S311
    for _ in range(n):
        yield "".join(rng.choice(PIECES) for _ in range(rng.randint(0, 16)))


if __name__ == "__main__":
    counts, diffs = {"generated": 0, "real": 0}, 0
    for kind, inputs in (("generated", generated(200_000)), ("real", list(real_inputs()))):
        for text in inputs:
            counts[kind] += 1
            a, b = answer(OLD, text), answer(NEW, text)
            if a != b:
                diffs += 1
                print(f"DIFF inspect {kind}: {text[:80]!r} old={a} new={b}")
            folded = NEW._normalize(text)[0]
            for label in RUN_LED:
                for t in (text, folded):
                    old = [m.span() for m in OLD_RULES[label].finditer(t)]
                    new = NEW._spans_of(label, NEW_RULES[label], t)
                    if old != new:
                        diffs += 1
                        print(f"DIFF {label} {kind}: {t[:80]!r} old={old[:4]} new={new[:4]}")
    print(f"inputs: {counts['generated']} generated, {counts['real']} real (tests/fixtures); "
          f"compared: inspect() answer + 2 rules x raw and folded spans; differences: {diffs}")
    sys.exit(1 if diffs else 0)
