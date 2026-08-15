#!/usr/bin/env bash
# S21 Step 0, angle E — do the S20 docs tests actually FAIL when they should?
#
# A regression test that cannot fail is worse than no test: it reports green
# forever and buys confidence it never earned. `tests/test_docs.py` arrived in
# S20 with no evidence that any of its five assertions bites, and one of them
# (`test_the_demo_only_calls_routes_that_exist`) passes trivially when its input
# set is empty. This breaks each pinned fact deliberately and watches.
#
# Every mutation is reverted by the EXIT trap, including on failure or Ctrl-C.
# Run:  bash docs/probes/s21-step0/probe_docs_tests_bite.sh
set -uo pipefail
cd "$(dirname "$0")/../../.."
ROOT=$(pwd)
BACKUP=$(mktemp -d)
FILES=(README.md .env.example scripts/demo.sh .github/workflows/ci.yml auspex/actions/settlement.py)

for f in "${FILES[@]}"; do
  mkdir -p "$BACKUP/$(dirname "$f")"
  cp "$f" "$BACKUP/$f"
done
restore() {
  for f in "${FILES[@]}"; do cp "$BACKUP/$f" "$ROOT/$f"; done
  rm -rf "$BACKUP"
  echo
  echo "restored: $(cd "$ROOT" && git status --porcelain "${FILES[@]}" | wc -l) of the 5 mutated files still dirty (want 0)"
}
trap restore EXIT

PYTEST=".venv/bin/pytest -q -p no:cacheprovider --no-header"
FAILED_TO_BITE=0

# $1 = human label, $2 = test id, $3 = expected outcome (fail|pass), $4... = mutation command
mutate() {
  local label="$1" test_id="$2" want="$3"; shift 3
  "$@"
  local out; out=$($PYTEST "tests/test_docs.py::$test_id" 2>&1 | tail -3)
  local got="pass"; echo "$out" | grep -qE "^[0-9]+ passed" || got="fail"
  for f in "${FILES[@]}"; do cp "$BACKUP/$f" "$ROOT/$f"; done
  if [ "$got" = "$want" ]; then
    printf '  [ok  ] %-58s -> %s (wanted %s)\n' "$label" "$got" "$want"
  else
    printf '  [FAIL] %-58s -> %s (wanted %s)\n' "$label" "$got" "$want"
    FAILED_TO_BITE=$((FAILED_TO_BITE + 1))
  fi
}

echo "baseline (unmutated):"
$PYTEST tests/test_docs.py 2>&1 | tail -2

echo
echo "E1. does each pinned fact bite when broken?"

mutate "README stops saying the deep path is conversational-only" \
  test_the_readme_does_not_promise_what_the_code_does_not_do fail \
  sed -i 's/conversational-only/fully autonomous/g' README.md

mutate "the code's blast radius changes but the README does not" \
  test_the_readme_does_not_promise_what_the_code_does_not_do fail \
  sed -i 's/EXECUTABLE_SYSTEMS = frozenset({"auspex"})/EXECUTABLE_SYSTEMS = frozenset({"auspex", "splunk"})/' auspex/actions/settlement.py

mutate "the engine name leaks into the README" \
  test_no_engine_or_provider_name_leaks_into_reader_facing_docs fail \
  sed -i '2i Powered by Claude.' README.md

mutate "the engine name leaks into the demo script" \
  test_no_engine_or_provider_name_leaks_into_reader_facing_docs fail \
  sed -i '2i # runs against ollama' scripts/demo.sh

mutate "an env var is born undocumented" \
  test_every_env_var_in_the_example_is_documented fail \
  sed -i '$a AUSPEX_UNDOCUMENTED_PROBE_VAR=1' .env.example

mutate "the demo calls a route that does not exist" \
  test_the_demo_only_calls_routes_that_exist fail \
  sed -i '$a curl -s "$API/does-not-exist" >/dev/null' scripts/demo.sh

mutate "the workflow re-implements pytest instead of calling ci.sh" \
  test_ci_runs_the_same_gate_a_developer_runs fail \
  sed -i '$a\      - run: pytest -q' .github/workflows/ci.yml

echo
echo "E2. the vacuity question: what happens when the INPUT disappears?"
echo "     (a demo that stops using \$API leaves the route test nothing to check)"

mutate "demo.sh renames \$API -> \$BASE (every route now unchecked)" \
  test_the_demo_only_calls_routes_that_exist fail \
  sed -i 's/\$API/$BASE/g' scripts/demo.sh

echo
echo "======================================================================"
echo "$FAILED_TO_BITE assertion(s) failed to bite."
