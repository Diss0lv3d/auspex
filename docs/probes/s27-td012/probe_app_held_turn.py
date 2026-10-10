"""S27 — D-043 live, through the running app.

Four turns through `/api/chat` against the rebuilt container and the dev
deployment's own scorecard. The two injected pastes are the ones from
probe_launder.py, and they test the HOLD on the code-decided modes. A plain CEF
alert gives the unsteered case. A narrative threat_intel question is the
control that must still stream.

Per turn it records: path, mode, contract_valid, contract_repair, the number of
content frames, time to first reasoning and first content frame, and the
rendered pinned field.

Spends about 6 inference calls on the shared `default` workspace. Do NOT run
pytest at the same time: the suite purges the shared analyst user mid-turn.

Run:  .venv/bin/python docs/probes/s27-td012/probe_app_held_turn.py
"""

import json
import sys
import time

import httpx

sys.path.insert(0, "/home/burhan/auspex-new")
sys.path.insert(0, "/home/burhan/auspex-new/docs/probes/s27-td012")

from probe_launder import PASTES  # noqa: E402

from auspex.modes.contract import _leading_token, split_sections  # noqa: E402

API = "http://localhost:8000/api"
TURNS = [
    *PASTES.items(),
    ("plain CEF alert",
     "CEF:0|Trellix|ENS|10.7|1201|Malware detected|9|src=10.1.2.3 "
     "cs1=powershell -enc SQBFAFgA externalId=T1059.001 confidence=90"),
    ("narrative control",
     "How do ransomware groups typically abuse remote monitoring and management "
     "tools after initial access?"),
]


def main() -> None:
    with httpx.Client(timeout=180) as http:
        token = http.post(f"{API}/auth/dev-login",
                          json={"email": "analyst@auspex.dev"}).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        for label, message in TURNS:
            t0 = time.monotonic()
            first = {}
            frames = []
            with http.stream("POST", f"{API}/chat", json={"message": message},
                             headers=auth) as resp:
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    frame = json.loads(line[5:].strip())
                    kind = next(iter(frame))
                    first.setdefault(kind, round(time.monotonic() - t0, 1))
                    frames.append(frame)
            done = frames[-1].get("done", {})
            content = "".join(f["content"] for f in frames if "content" in f)
            sections = split_sections(content)
            field = "verdict" if "verdict" in sections else "risk"
            print(f"[{label}] path={done.get('path')} mode={done.get('mode')} "
                  f"contract_valid={done.get('contract_valid')} "
                  f"contract_repair={done.get('contract_repair')} "
                  f"content_frames={sum(1 for f in frames if 'content' in f)} "
                  f"first_reasoning={first.get('reasoning')}s first_content={first.get('content')}s "
                  f"{field}={_leading_token(sections.get(field, ''))!r} "
                  f"errors={[f['error'] for f in frames if 'error' in f]}")


if __name__ == "__main__":
    main()
