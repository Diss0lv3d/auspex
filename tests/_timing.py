"""Timing helpers for the backtracking tests (B-010, B-029), shared by
test_classifier.py, test_observables.py and test_guard.py.

A bounded rule runs an 8,000-character input in a few milliseconds; a
regressed one takes hundreds of milliseconds to seconds. A single sample on a
shared CI runner can stall on its own: PR #41's GitHub run measured one 84 ms
sample for a refang call that takes 4 ms locally (B3). So each input is timed
three times and the fastest run counts: a stall in one sample does not fail
the test, while a rule that is really slow is slow every time.
"""

import time

BOUNDED_MS = 50
RUNS = 3


def elapsed_ms(fn, arg) -> float:
    best = float("inf")
    for _ in range(RUNS):
        start = time.perf_counter()
        fn(arg)
        best = min(best, (time.perf_counter() - start) * 1000)
    return best
