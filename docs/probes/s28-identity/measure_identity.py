"""S28 (D-047): the identity shortcut against an independently written battery.

Each battery was written by a separate agent that never read the repo (D-044
discipline): `identity` must classify IDENTITY, `not_identity` (analyst
questions built to be confusable) must not. A wrong shortcut gives a wrong
answer, so false positives are the number that matters most.

Run:  .venv/bin/python docs/probes/s28-identity/measure_identity.py battery-A.json
"""

import json
import sys
from pathlib import Path

from auspex.classify import classify
from auspex.classify.classifier import Category


def measure(path: Path) -> tuple[int, int, int, int]:
    d = json.loads(path.read_text())
    miss = [q for q in d["identity"] if classify(q).category is not Category.IDENTITY]
    fp = [q for q in d["not_identity"] if classify(q).category is Category.IDENTITY]
    print(f"{path.name}: identity recall {len(d['identity']) - len(miss)}/{len(d['identity'])}, "
          f"false positives {len(fp)}/{len(d['not_identity'])}")
    for q in miss:
        print(f"  MISSED          {q!r}")
    for q in fp:
        print(f"  FALSE POSITIVE  {q!r}")
    return len(d["identity"]) - len(miss), len(d["identity"]), len(fp), len(d["not_identity"])


if __name__ == "__main__":
    for name in sys.argv[1:]:
        measure(Path(__file__).parent / name)
