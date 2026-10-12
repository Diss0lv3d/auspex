"""The chat page's pure logic (D-052), inside the gate.

The logic is JavaScript in auspex/static/js/page-logic.js, so its behavioural tests
are JavaScript too: tests/js/page_logic.test.mjs, under Node's built-in test
runner (no dependencies). This runs that file, so `./ci.sh` (D-028: the only
definition of green) covers it and the README's count stays the pytest count.

Node missing is a FAILURE, not a skip: a gate that skips its page tests on a
machine without Node reports green for code nobody ran.
"""

import shutil
import subprocess
from pathlib import Path

NODE_TESTS = Path(__file__).parent / "js" / "page_logic.test.mjs"


def test_the_pages_pacing_and_indicator_logic_pass_their_node_tests():
    node = shutil.which("node")
    assert node, "Node is required to run the page's logic tests (tests/js/)"
    # The reporter is named: without it, Node before 23 prints TAP when its output
    # is captured, and the floor below would find no "ℹ pass" line (B-007).
    run = subprocess.run(  # noqa: S603 — argv is node, flags and our own test file
        [node, "--test", "--test-reporter=spec", str(NODE_TESTS)],
        capture_output=True, text=True, timeout=60,
    )
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
    # A file that defined no tests also exits 0. The floor is the count this
    # file holds today; it only ever goes up.
    passed = [line for line in run.stdout.splitlines() if line.startswith("ℹ pass ")]
    assert passed and int(passed[0].split()[-1]) >= 46, run.stdout[-2000:]
