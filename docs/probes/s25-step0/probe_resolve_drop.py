"""S25 Step-0 review harness — does a tool argument lose observables silently?

capabilities.py's `_resolve` docstring: "Unresolvable strings are returned
separately and reported, never dropped." This measures whether a string that
resolves to MORE THAN ONE observable keeps that promise.

Controls are arithmetic: every subject asserts how many observables the shared
extractor finds in it BEFORE _resolve is called, so a null result cannot be
mistaken for a sound one.
"""

import sys

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.agent.capabilities import MAX_TOOL_ARG_ITEMS, _as_list, _resolve
from auspex.classify.observables import extract

ONE = "8.8.8.8"
THREE = "8.8.8.8 and 1.1.1.1 and 9.9.9.9"

# --- arithmetic controls on the INPUTS themselves -------------------------
n_one = len(extract(ONE).observables)
n_three = len(extract(THREE).observables)
assert n_one == 1, f"control broken: ONE holds {n_one} observables, expected 1"
assert n_three == 3, f"control broken: THREE holds {n_three} observables, expected 3"
print(f"control: extract(ONE)={n_one}  extract(THREE)={n_three}  (shared extractor)")

# --- C1: one string, one observable ---------------------------------------
r, u = _resolve([ONE], {})
print(f"C1  one-observable string      -> resolved={len(r)} unresolved={u}")
assert len(r) == 1 and not u

# --- C2: three observables as three separate array items ------------------
# Proves _resolve is capable of returning 3 — so any loss below is the
# per-string collapse, not a limit of _resolve.
r2, u2 = _resolve(["8.8.8.8", "1.1.1.1", "9.9.9.9"], {})
print(f"C2  three items, one each      -> resolved={len(r2)} unresolved={u2}")
assert len(r2) == 3, f"control broken: _resolve cannot return 3 at all ({len(r2)})"

# --- S1: ONE array item holding three observables -------------------------
r3, u3 = _resolve([THREE], {})
print(f"S1  one item, three inside     -> resolved={len(r3)} unresolved={u3}")
print(f"    kept: {[o.value for o in r3]}")
lost = n_three - len(r3)
print(f"    >>> LOST SILENTLY: {lost} of {n_three}; unresolved reported: {len(u3)}")

# --- S2: the bare-string path _as_list explicitly supports ----------------
# _as_list's docstring: models send a bare string where an array is specified
# "often enough that treating it as a contract violation would fail turns".
# That is precisely the shape most likely to carry several indicators.
items, omitted = _as_list(THREE, cap=MAX_TOOL_ARG_ITEMS)
assert items == [THREE] and omitted == 0, f"control broken: _as_list gave {items!r}"
print(f"S2  bare string via _as_list   -> items={len(items)} (the whole string is ONE item)")
r4, u4 = _resolve(items, {})
print(f"    resolved={len(r4)} unresolved={u4}  >>> LOST SILENTLY: {n_three - len(r4)}")

# --- S3: a comma-separated bare string, the most natural model output -----
CSV = "8.8.8.8, 1.1.1.1, 9.9.9.9"
n_csv = len(extract(CSV).observables)
assert n_csv == 3, f"control broken: CSV holds {n_csv}, expected 3"
items5, _ = _as_list(CSV, cap=MAX_TOOL_ARG_ITEMS)
r5, u5 = _resolve(items5, {})
print(f"S3  csv bare string            -> resolved={len(r5)} unresolved={u5}"
      f"  >>> LOST SILENTLY: {n_csv - len(r5)}")

# --- S4: non-string scalar argument ---------------------------------------
for bad in (5, 3.5, True):
    try:
        out = _as_list(bad, cap=MAX_TOOL_ARG_ITEMS)
        print(f"S4  _as_list({bad!r}) -> {out}")
    except Exception as err:
        print(f"S4  _as_list({bad!r}) -> RAISED {type(err).__name__}: {err}")
