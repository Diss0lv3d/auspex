"""The shared page modules (F4), inside the gate.

js/shell-logic.js, js/api.js and js/dom.js are imported by every page. Their
behavioural tests are JavaScript, under Node's built-in test runner
(tests/js/*.test.mjs). This runs each file, so `./ci.sh` (D-028) covers them,
as tests/test_page_logic.py does for the chat page.

Node missing is a FAILURE, not a skip.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parent / "js"


# The floor is each file's count today; it only ever goes up.
@pytest.mark.parametrize("name,floor", [
    ("shell_logic.test.mjs", 24),
    ("dom.test.mjs", 5),
    ("api.test.mjs", 11),
])
def test_a_shared_modules_node_tests_pass(name, floor):
    node = shutil.which("node")
    assert node, "Node is required to run the page's logic tests (tests/js/)"
    # The reporter is named so the floor below finds "ℹ pass" on any Node (B-007).
    run = subprocess.run(  # noqa: S603 — argv is node, flags and our own test file
        [node, "--test", "--test-reporter=spec", str(JS / name)],
        capture_output=True, text=True, timeout=60,
    )
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
    passed = [line for line in run.stdout.splitlines() if line.startswith("ℹ pass ")]
    assert passed and int(passed[0].split()[-1]) >= floor, run.stdout[-2000:]
