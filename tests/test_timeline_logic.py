"""The timeline page's pure logic (S16, S17), inside the gate.

Its behavioural tests are JavaScript, under Node's built-in test runner:
tests/js/timeline_logic.test.mjs. This runs that file, so `./ci.sh` (D-028)
covers it, exactly as tests/test_page_logic.py does for the chat page.

Node missing is a FAILURE, not a skip.
"""

import shutil
import subprocess
from pathlib import Path

NODE_TESTS = Path(__file__).parent / "js" / "timeline_logic.test.mjs"


def test_the_timeline_pages_logic_passes_its_node_tests():
    node = shutil.which("node")
    assert node, "Node is required to run the page's logic tests (tests/js/)"
    # The reporter is named so the floor below finds "ℹ pass" on any Node (B-007).
    run = subprocess.run(  # noqa: S603 — argv is node, flags and our own test file
        [node, "--test", "--test-reporter=spec", str(NODE_TESTS)],
        capture_output=True, text=True, timeout=60,
    )
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
    # A file that defined no tests also exits 0. The floor is the count this
    # file holds today; it only ever goes up.
    passed = [line for line in run.stdout.splitlines() if line.startswith("ℹ pass ")]
    assert passed and int(passed[0].split()[-1]) >= 15, run.stdout[-2000:]
