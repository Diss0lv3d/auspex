"""S26 — D-040 live: the question whose thinking the rail used to cut, through the app.

Sends the calibration's offending question through /api/chat (the dev
deployment runs it on the agent path) three times, and reports per turn whether
the rail let it through, and how long a verbatim run of our configuration the
live thinking actually carried (against the same instructions the route
indexes, measured the calibration's way).

~6 inference calls. Do NOT run pytest at the same time (it purges the shared
analyst user mid-turn).

Run:  .venv/bin/python docs/probes/s26-step0/probe_app_thinking_floor.py
"""

import json
import sys

import httpx

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

from auspex.agent.loop import DEFAULT_SYSTEM_PROMPT  # noqa: E402
from auspex.modes import Mode, contract_for  # noqa: E402
from auspex.outguard import _words, instruction_index  # noqa: E402
from auspex.routes.chat import HISTORY_FENCE_DIRECTIVE  # noqa: E402

API = "http://localhost:8000/api"
QUESTION = "What is lateral movement, and how does Kerberoasting fit into it? Use the knowledge base."
ISSUED = [DEFAULT_SYSTEM_PROMPT, HISTORY_FENCE_DIRECTIVE,
          contract_for(Mode.DEFINITION).system_directive()]


def longest_run(text: str) -> int:
    words, best = _words(text), 0
    for width in range(2, min(80, len(words)) + 1):
        index = instruction_index(ISSUED, shingle=width)
        if not any(" ".join(words[i:i + width]) in index for i in range(len(words) - width + 1)):
            break
        best = width
    return best


def main() -> None:
    with httpx.Client(timeout=300.0) as http:
        token = http.post(f"{API}/auth/dev-login",
                          json={"email": "analyst@auspex.dev"}).json()["access_token"]
        for run in range(1, 4):
            frames = []
            with http.stream("POST", f"{API}/chat", headers={"Authorization": f"Bearer {token}"},
                             json={"message": QUESTION}) as r:
                for line in r.iter_lines():
                    if line.startswith("data:"):
                        frames.append(json.loads(line[5:]))
            done = frames[-1].get("done", {})
            thinking = "".join(f["reasoning"] for f in frames if "reasoning" in f)
            errors = [f["error"] for f in frames if "error" in f]
            print(f"run {run}: path={done.get('path')} mode={done.get('mode')} "
                  f"output_valid={done.get('output_valid')} finish={done.get('finish_reason')} "
                  f"contract_valid={done.get('contract_valid')} errors={len(errors)} "
                  f"thinking={len(thinking)} chars, longest verbatim run={longest_run(thinking)}")


if __name__ == "__main__":
    main()
