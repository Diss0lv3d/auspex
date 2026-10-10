"""S26 — the agent path, live, through the running app (D-031, D-037).

Everything before this drove `AgentLoop` directly. This goes through
`/api/chat` the way the analyst does, against the rebuilt container and the dev
deployment's own scorecard (row a8113b41…, agent_mode native_tools), and
records per turn what the analyst is shown and what the workspace is charged:

  - which path ran (`done.path`), the mode, and whether the contract held
  - the tool frames, in order, and where they fall relative to the answer
  - time to the first reasoning / tool / content frame
  - inference units claimed (from /api/usage, before and after)
  - what was persisted as the assistant turn, and whether it equals what
    streamed as content

Four turns: the KB-shaped question (case C of the routing probe), an IOC
narrative long enough to be deep, the no-tool question (S25's control), and a
CEF alert, which must stay on the conversational path (D-037 clause 1).

Spends roughly 8 inference calls on the shared `default` workspace. Do NOT run
pytest at the same time: the suite purges the shared analyst user mid-turn.

Run:  .venv/bin/python docs/probes/s26-step0/probe_app_agent_turn.py
"""

import asyncio
import json
import sys
import time

import asyncpg
import httpx

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

from auspex.config import Settings  # noqa: E402

API = "http://localhost:8000/api"
EMAIL = "analyst@auspex.dev"
TURNS = [
    ("C  KB-shaped, no observable",
     "We found a scheduled task created by an Office macro on a finance workstation. "
     "Which ATT&CK techniques does that map to, and what should I check next?"),
    ("B' IOC narrative",
     "Our WAF logged 185.220.101.5 sending ${jndi:ldap://x} strings to the payroll app "
     "at 02:00. Is that Log4Shell exploitation and how worried should I be?"),
    ("A  no-tool question", "Write me a status update for my manager about this week."),
    ("X  CEF alert (control)",
     "CEF:0|Trellix|ENS|10.7|1201|Malware detected|9|src=10.1.2.3 "
     "cs1=powershell -enc SQBFAFgA externalId=T1059.001 confidence=90"),
]


def used(http, auth) -> int:
    return http.get(f"{API}/usage", headers=auth).json()["meters"]["inference_calls"]["used"]


async def persisted(session_id: str) -> list[tuple[str, str]]:
    conn = await asyncpg.connect(Settings().database_url)
    try:
        rows = await conn.fetch(
            "SELECT role, content FROM messages WHERE session_id = $1::uuid ORDER BY created_at",
            session_id,
        )
        return [(r["role"], r["content"]) for r in rows]
    finally:
        await conn.close()


def main() -> None:
    with httpx.Client(timeout=300.0) as http:
        token = http.post(f"{API}/auth/dev-login", json={"email": EMAIL}).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        print("S26 — the agent path through the running app")
        print("=" * 78)
        for label, message in TURNS:
            before = used(http, auth)
            t0 = time.monotonic()
            first, frames = {}, []
            with http.stream("POST", f"{API}/chat", headers=auth, json={"message": message}) as r:
                status = r.status_code
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[5:])
                    key = next(iter(ev))
                    first.setdefault(key, round(time.monotonic() - t0, 1))
                    frames.append(ev)
            wall = round(time.monotonic() - t0, 1)
            after = used(http, auth)
            kinds = [next(iter(f)) for f in frames]
            done = frames[-1].get("done", {}) if frames else {}
            content = "".join(f["content"] for f in frames if "content" in f)
            reasoning = "".join(f["reasoning"] for f in frames if "reasoning" in f)
            tools = [f["tool"] for f in frames if "tool" in f]
            errors = [f["error"] for f in frames if "error" in f]
            last_tool = max((i for i, k in enumerate(kinds) if k == "tool"), default=None)
            first_content = next((i for i, k in enumerate(kinds) if k == "content"), None)
            stored = asyncio.run(persisted(frames[0]["session"])) if frames else []
            answer_rows = [c for role, c in stored if role == "assistant"]

            print(f"\n[{label}]  HTTP {status}  wall {wall}s")
            print(f"  path={done.get('path')} mode={done.get('mode')} "
                  f"contract_valid={done.get('contract_valid')} "
                  f"output_valid={done.get('output_valid')} finish={done.get('finish_reason')}")
            print(f"  first frame at: {first}")
            print(f"  units claimed: {after - before}   usage: {done.get('usage')}")
            for t in tools:
                print(f"  tool: {t['name']}({t['arguments']}) -> {t['status']}")
            print(f"  tools before the answer: "
                  f"{last_tool is None or first_content is None or last_tool < first_content}")
            print(f"  reasoning: {len(reasoning)} chars   content: {len(content)} chars "
                  f"in {kinds.count('content')} frames   errors: {errors}")
            print(f"  persisted == streamed content: "
                  f"{answer_rows == [content] if content else answer_rows == []}")
            print(f"  answer: {content[:700]!r}")
    print("\n" + "=" * 78)


if __name__ == "__main__":
    main()
