"""S27 — D-044 live, through the running app: what does a `general` turn get?

Two kinds of turn:
- non-security questions the fallback exists for (the S26 control, and one
  more);
- security questions the frozen vocabulary MISROUTES to general, taken from the
  independent battery (heldout2-battery.json). This tests D-044's claim that a
  misroute costs structure and not substance, under a neutral directive.

Prints each answer in full so a human can judge the substance. Spends about 8
inference calls on the shared `default` workspace. Do NOT run pytest at the
same time.

Run:  .venv/bin/python docs/probes/s27-modes/probe_app_general.py
"""

import json
import sys

import httpx

API = "http://localhost:8000/api"
TURNS = [
    ("non-security: the S26 control", "Write me a status update for my manager about this week."),
    ("non-security", "My Excel file with 200k rows takes forever to open and recalculates every "
                     "time I type. How can I speed it up?"),
    ("MISROUTED security", "All the files on the marketing share suddenly have a weird extension "
                           "and there's a text note in every folder asking for bitcoin."),
    ("MISROUTED security", "Our printer in the HR office has been emailing scanned documents to an "
                           "outside address. Nobody set that up as far as we know."),
    ("MISROUTED security", "Someone tailgated through the side door this morning and walked around "
                           "the office floor for 20 minutes before anyone asked who they were."),
]


def main() -> None:
    with httpx.Client(timeout=180) as http:
        token = http.post(f"{API}/auth/dev-login",
                          json={"email": "analyst@auspex.dev"}).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        for label, message in TURNS:
            frames = []
            with http.stream("POST", f"{API}/chat", json={"message": message},
                             headers=auth) as resp:
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        frames.append(json.loads(line[5:].strip()))
            done = frames[-1].get("done", {})
            answer = "".join(f["content"] for f in frames if "content" in f)
            tools = [f["tool"]["call"] for f in frames if "tool" in f]
            print(f"\n[{label}] path={done.get('path')} mode={done.get('mode')} "
                  f"contract_valid={done.get('contract_valid')} tools={tools} "
                  f"errors={[f['error'] for f in frames if 'error' in f]}")
            print(f"Q: {message}")
            print("A: " + answer.replace("\n", "\n   "))


if __name__ == "__main__":
    main()
