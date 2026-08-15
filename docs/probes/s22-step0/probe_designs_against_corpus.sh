#!/usr/bin/env bash
# S22 Step 0 — run each candidate sentence-boundary design against the REAL
# corpus, not a hand-written one: the whole guard suite, the hardening surface,
# and every test that touches the .eml fixtures.
#
# The 10-message corpus in probe_sentence_designs.py is mine, so it is not
# evidence about designs I wrote it alongside — the same trap the S21 review
# named about the quote arm ("the pinned corpus was written by the commit that
# added the arm, so it is not evidence about the arm").
#
# Mutates auspex/guard.py and restores it on EXIT, verified clean afterwards.
set -uo pipefail
cd "$(dirname "$0")/../../.."

GUARD=auspex/guard.py
BACKUP=$(mktemp)
cp "$GUARD" "$BACKUP"
restore() {
  cp "$BACKUP" "$GUARD"
  rm -f "$BACKUP"
  if git diff --quiet -- "$GUARD"; then
    echo "restored: $GUARD clean"
  else
    echo "!! $GUARD NOT RESTORED — check git diff" >&2
  fi
}
trap restore EXIT

SUITES="tests/test_guard.py tests/test_hardening_surface.py tests/test_phishing.py tests/test_chat_paths.py"
# Only the suites that exist.
REAL=""
for s in $SUITES; do [ -f "$s" ] && REAL="$REAL $s"; done
echo "suites:$REAL"
echo

run_design() {
  local name="$1" pattern="$2"
  cp "$BACKUP" "$GUARD"
  python3 - "$GUARD" "$pattern" <<'PY'
import sys, re
path, pattern = sys.argv[1], sys.argv[2]
src = open(path).read()
# A lambda replacement: a plain string would have \s interpreted as an escape.
new, n = re.subn(r'_SENTENCE_END_RE = re\.compile\(r"[^"]*"\)',
                 lambda _: f'_SENTENCE_END_RE = re.compile(r"{pattern}")', src)
assert n == 1, f"expected exactly 1 substitution, made {n}"
open(path, "w").write(new)
PY
  if [ $? -ne 0 ]; then echo "$name: PATCH FAILED"; return; fi
  out=$(python3 -m pytest $REAL -q 2>&1 | tail -3)
  echo "=== $name  ($pattern)"
  echo "$out" | sed 's/^/    /'
  echo
}

run_design "current" '[.!?]\s'
run_design "A" '[.!?](?:\s|$)|\n'
run_design "B" '[.!?](?:\s|$)|\n\s*\n'
run_design "C" '[.!?](?:\s|$)'
