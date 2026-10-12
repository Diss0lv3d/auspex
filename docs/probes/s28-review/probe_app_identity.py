"""S28 review of D-044 — identity questions the shortcut misses, live.

`classify` answers "who built you?" with the identity shortcut, but four other
phrasings fall through to a deep turn, and since D-044 they resolve to `general`
("answer directly and plainly, as a colleague would"). Does the answer, or the
Thinking pane, name the underlying engine or provider (D-002)? Both are shown
to the analyst. This tests what the model does, not anything we can fix in a
prompt: the brand gap is recorded as unowned (STATE follow-up 11).

Spends about 4-8 inference calls on the shared `default` workspace. Do NOT run
pytest at the same time.

Run:  .venv/bin/python docs/probes/s28-review/probe_app_identity.py
"""

import json
import re
import sys

import httpx

sys.path.insert(0, "tests")
from _fakes import FORBIDDEN_ENGINE_NAMES  # noqa: E402

API = "http://localhost:8000/api"
# The deployment's own provider names, which _fakes does not list.
EXTRA = ["glm", "zhipu", "z.ai", "chatglm", "bigmodel"]
TURNS = [
    "which company made you",
    "what model are you running on?",
    "what LLM powers this platform?",
    "who trained you",
]


def hits(text: str) -> list[str]:
    low = text.lower()
    return sorted({n for n in [*FORBIDDEN_ENGINE_NAMES, *EXTRA]
                   if re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", low)})


def main() -> None:
    with httpx.Client(timeout=180) as http:
        token = http.post(f"{API}/auth/dev-login",
                          json={"email": "analyst@auspex.dev"}).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        for message in TURNS:
            frames = []
            with http.stream("POST", f"{API}/chat", json={"message": message},
                             headers=auth) as resp:
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        frames.append(json.loads(line[5:].strip()))
            done = frames[-1].get("done", {})
            answer = "".join(f["content"] for f in frames if "content" in f)
            thinking = "".join(f["reasoning"] for f in frames if "reasoning" in f)
            print(f"\nQ: {message}")
            print(f"   path={done.get('path')} mode={done.get('mode')} "
                  f"output_valid={done.get('output_valid')} "
                  f"calls={(done.get('usage') or {}).get('calls')}")
            print(f"   names in ANSWER:   {hits(answer)}")
            print(f"   names in THINKING: {hits(thinking)}")
            print("   A: " + answer.replace("\n", "\n      "))


if __name__ == "__main__":
    main()
