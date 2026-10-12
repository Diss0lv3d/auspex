"""S28 (D-050): where action-request turns are routed, on a battery written by
an agent that never read the repo.

`action_only` turns ask only for a note on an indicator; `mixed` ask for
analysis AND a note; `not_action` mention notes but ask the platform to do
nothing. Prints the category (shortcut vs deep) and the resolved mode per group.

Run:  .venv/bin/python docs/probes/s28-candidates/measure_action_routing.py action-battery.json
"""

import json
import sys
from collections import Counter
from pathlib import Path

from auspex.classify import classify, shortcut_answer
from auspex.modes import resolve_mode


def route(q: str) -> str:
    c = classify(q)
    if shortcut_answer(c) is not None:
        return f"shortcut:{c.category.value}"
    return resolve_mode(q, c.observables).value


def main(name: str, verbose: bool) -> None:
    d = json.loads((Path(__file__).parent / name).read_text())
    print(name)
    for group, qs in d.items():
        routes = [route(q) for q in qs]
        print(f"  {group:12} n={len(qs):3}  {dict(Counter(routes).most_common())}")
        if verbose:
            for q, r in zip(qs, routes):
                print(f"      {r:22} {q[:110]!r}")


if __name__ == "__main__":
    main(sys.argv[1], "-v" in sys.argv)
