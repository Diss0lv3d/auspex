# S29 review scripts

Kept so each result in `docs/probes/2026-10-14-s29-s28-code-review.md` can be
re-run. All are pure Python against the repo's own fakes: no DB, no network, no
engine. Run from the repo root with `PYTHONPATH=tests .venv/bin/python <script>`.

- `d046/`, `d049/`, `classify/`: the four reviewers of S28's code.
- `fixes/`: the reviewer of S29's own fixes. Three scripts compare against the
  code before a fix and take a directory holding those old copies as their
  argument (`fuzz_cls.py`, `learn_check.py`, `norm_check.py`). Make it with:

  ```bash
  d=$(mktemp -d)
  git show 8187925^:auspex/classify/classifier.py   > $d/classifier_old.py
  git show b069b84^:auspex/agent/capabilities.py    > $d/capabilities_old.py
  git show d16afaa^:auspex/alerts/normalizer.py     > $d/normalizer_old.py
  PYTHONPATH=tests .venv/bin/python docs/probes/s29-review/fixes/fuzz_cls.py $d
  ```
