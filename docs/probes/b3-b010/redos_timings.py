"""B3 / B-010: time the classify pass's backtracking rules on crafted input.

Run from the repo root with the project venv:

    .venv/bin/python docs/probes/b3-b010/redos_timings.py

Each line is one rule (or the whole pass) on one input, at sizes up to the
chat route's 32,000-character message cap. Run before and after the fix.
"""

import time

from auspex.classify import classifier as C
from auspex.classify import observables as O


def ms(fn, arg) -> float:
    start = time.perf_counter()
    fn(arg)
    return (time.perf_counter() - start) * 1000


def refang_dot(s):
    return list(O._REFANG_RULES[2][0].finditer(s))


def refang_at(s):
    return list(O._REFANG_RULES[3][0].finditer(s))


def greeting(s):
    return C._GREETING_RE.match(s)


def analytical(s):
    # Found by B3's review of the fix: the same pass, "." then a run of spaces.
    return C._ANALYTICAL_INITIAL_RE.search(s)


def domains(s):
    return list(O._DOMAIN_CAND_RE.finditer(s))


def emails(s):
    return list(O._EMAIL_RE.finditer(s))


def domain_scan(s):
    # B3's fix: what extract() calls since B-010 (absent before it).
    return list(O._domain_candidates(s))


def email_scan(s):
    return list(O._email_candidates(s))


CASES = [
    ("refang [.] rule", refang_dot, lambda n: "x" + " " * (n - 2) + "x"),
    ("refang [@] rule", refang_at, lambda n: "x" + " " * (n - 2) + "x"),
    ("greeting rule", greeting, lambda n: "hi" + " " * (n - 3) + "x"),
    ("analytical rule", analytical, lambda n: "." + " " * (n - 2) + "x"),
    ("domain rule", domains, lambda n: "a." * (n // 2)),
    ("email rule", emails, lambda n: "a." * (n // 2)),
    ("domain scan (B3)", domain_scan, lambda n: "a." * (n // 2)),
    ("email scan (B3)", email_scan, lambda n: "a." * (n // 2)),
    ("extract(), spaces", O.extract, lambda n: "x" + " " * (n - 2) + "x"),
    ("extract(), a.a.a.", O.extract, lambda n: "a." * (n // 2)),
    ("classify(), hi+spaces", C.classify, lambda n: "hi" + " " * (n - 3) + "x"),
    ("classify(), a.a.a.", C.classify, lambda n: "a." * (n // 2)),
    ("classify(), .+spaces", C.classify, lambda n: "." + " " * (n - 2) + "x"),
]

if __name__ == "__main__":
    for label, fn, make in CASES:
        if fn in (domain_scan, email_scan) and not hasattr(O, "_domain_candidates"):
            continue
        row = []
        for n in (2_000, 8_000, 16_000, 32_000):
            row.append(f"{n:>6}: {ms(fn, make(n)):9.1f} ms")
        print(f"{label:<24} " + "  ".join(row), flush=True)
