"""S26 — one DEEP chat turn through the running app, against whatever .env points at.

The harness and the capability battery talk to the endpoint directly. This goes
through `/api/chat` the way the analyst does, so it measures the path that
actually runs — which, for the configured default endpoint, is the TWO-PASS
fallback whenever the user's workspace has no scorecard (STATE follow-up 9):
pass 1 (`CHAT_REASONING_MAX_TOKENS`) streams to the Thinking pane, pass 2
(`CHAT_ANSWER_MAX_TOKENS`) is the answer.

A thinking model on that path is the open question: its own thinking runs
inside pass 1's small budget before any content. This records, per turn, what
the analyst would actually see.

Spends 2 inference calls per question on the shared `default` workspace (hourly
ceiling 100). No key is read here — the app holds it.

Run:  .venv/bin/python docs/probes/s26-zai/probe_app_deep_turn.py
"""

import json
import sys
import time

import httpx

API = "http://localhost:8000/api"
QUESTIONS = [
    "Explain how an attacker typically chains Kerberoasting into domain admin, and "
    "which detections a SOC should prioritise.",
    "Write a short handover note for the next shift about an ongoing phishing campaign "
    "targeting our finance team.",
]


def main() -> None:
    with httpx.Client(timeout=300.0) as http:
        token = http.post(f"{API}/auth/dev-login", json={"email": "analyst@auspex.dev"}).json()[
            "access_token"
        ]
        auth = {"Authorization": f"Bearer {token}"}
        for q in QUESTIONS:
            t0 = time.monotonic()
            first = {}
            parts = {"reasoning": [], "content": []}
            other = []
            with http.stream("POST", f"{API}/chat", headers=auth, json={"message": q}) as r:
                status = r.status_code
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:])
                    except ValueError:
                        continue
                    for k in ("reasoning", "content"):
                        if k in ev:
                            first.setdefault(k, round(time.monotonic() - t0, 1))
                            parts[k].append(ev[k])
                    rest = {k: v for k, v in ev.items() if k not in ("reasoning", "content")}
                    if rest:
                        other.append(rest)
            wall = round(time.monotonic() - t0, 1)
            reasoning, content = "".join(parts["reasoning"]), "".join(parts["content"])
            print(f"\nQ: {q[:80]}...")
            print(f"  HTTP {status}  wall {wall}s  first-reasoning {first.get('reasoning')}s"
                  f"  first-content {first.get('content')}s")
            print(f"  Thinking pane: {len(reasoning)} chars  | answer: {len(content)} chars")
            print(f"  other events: {json.dumps(other)[:600]}")
            print(f"  thinking head: {reasoning[:240]!r}")
            print(f"  answer head:   {content[:240]!r}")
            print(f"  answer tail:   {content[-160:]!r}")


if __name__ == "__main__":
    sys.exit(main())
