"""B3 / B-029: time the input guard on crafted whitespace and newline runs.

    .venv/bin/python docs/probes/b3-b029/guard_timings.py

guard.inspect() runs before classify() on POST /api/chat (auspex/routes/chat.py),
over the folded text and the raw text. Sizes up to the 32,000-character cap.
"""

import time

from auspex import guard as G

PATTERNS = dict(G._INJECTION_PATTERNS)


def ms(fn, arg) -> float:
    start = time.perf_counter()
    fn(arg)
    return (time.perf_counter() - start) * 1000


def rule(name):
    return lambda s: list(PATTERNS[name].finditer(s))


CASES = [
    ("persona, '.'+spaces", rule("persona_override"), lambda n: "." + " " * (n - 2) + "x"),
    ("persona, newlines", rule("persona_override"), lambda n: "\n" * (n - 1) + "x"),
    ("persona, '\\n '*", rule("persona_override"), lambda n: "\n " * (n // 2)),
    ("role, newlines", rule("role_marker_injection"), lambda n: "\n" * (n - 1) + "x"),
    ("role, '\\n '*", rule("role_marker_injection"), lambda n: "\n " * (n // 2)),
    ("inspect(), '.'+spaces", G.inspect, lambda n: "." + " " * (n - 2) + "x"),
    ("inspect(), newlines", G.inspect, lambda n: "\n" * (n - 1) + "x"),
    ("inspect(), '\\n '*", G.inspect, lambda n: "\n " * (n // 2)),
]

if __name__ == "__main__":
    for label, fn, make in CASES:
        row = []
        for n in (2_000, 8_000, 16_000, 32_000):
            row.append(f"{n:>6}: {ms(fn, make(n)):9.1f} ms")
        print(f"{label:<24} " + "  ".join(row), flush=True)
