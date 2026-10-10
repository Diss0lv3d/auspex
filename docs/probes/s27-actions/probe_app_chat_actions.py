"""S27 — D-045 live: does the engine file sensible proposals from chat, and
only when asked?

IDEAS asked for this probe before actions reached the chat agent. Through
`/api/chat`, in one fresh session, against the rebuilt container:

1. an IOC check (the 92/8 shortcut), which persists the observable — the
   only way an observable reaches the workspace today;
2. an explicit ask to annotate it — does the agent find the observable's
   short id, call the action, and say it PROPOSED rather than did?
3. the same indicator with "don't change anything" — no proposal may be filed;
4. a question that needs no action at all — no proposal may be filed.

Then it reads the approvals queue and prints every card this session filed,
and REJECTS them, so nothing is left pending on the shared dev workspace.

Spends about 6-10 inference calls on the shared `default` workspace. Do NOT
run pytest at the same time.

Run:  .venv/bin/python docs/probes/s27-actions/probe_app_chat_actions.py
"""

import json

import httpx

API = "http://localhost:8000/api"
IOC = "185.220.101.5"
TURNS = [
    ("1 IOC check (shortcut, persists)", IOC),
    ("2 explicit ask to annotate",
     f"Add a note to {IOC} saying it is a Tor exit node we saw hitting the payroll WAF at "
     "02:00 on Friday, so the next analyst has the context."),
    ("3 same indicator, told not to change anything",
     f"Is {IOC} something to worry about for us? Just tell me, don't change anything."),
    ("4 no action needed", "How does kerberoasting lead to domain admin?"),
]


def main() -> None:
    with httpx.Client(timeout=240) as http:
        token = http.post(f"{API}/auth/dev-login",
                          json={"email": "analyst@auspex.dev"}).json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        before = {p["id"] for p in http.get(f"{API}/proposals", headers=auth).json()["proposals"]}
        session = None
        for label, message in TURNS:
            body = {"message": message, **({"session_id": session} if session else {})}
            frames = []
            with http.stream("POST", f"{API}/chat", json=body, headers=auth) as resp:
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        frames.append(json.loads(line[5:].strip()))
            session = session or next(f["session"] for f in frames if "session" in f)
            done = frames[-1].get("done", {})
            answer = "".join(f["content"] for f in frames if "content" in f)
            print(f"\n[{label}] path={done.get('path')} mode={done.get('mode')} "
                  f"output_valid={done.get('output_valid')} contract_valid={done.get('contract_valid')}")
            for f in frames:
                if "tool" in f:
                    t = f["tool"]
                    print(f"   tool: {t['call']} -> {t['status']}"
                          + (f"  PROPOSAL {t['proposal']['id'][:8]}: {t['proposal']['summary']}"
                             if "proposal" in t else ""))
            print("   answer: " + answer[:600].replace("\n", "\n           "))
        queued = http.get(f"{API}/proposals", headers=auth).json()["proposals"]
        filed = [p for p in queued if p["id"] not in before]
        print(f"\nproposals filed this session: {len(filed)}")
        for p in filed:
            print(f"   {p['id'][:8]} {p['action']} {p['status']} args={p['arguments']} "
                  f"summary={p['card']['summary']!r}")
            r = http.post(f"{API}/proposals/{p['id']}/reject", headers=auth)
            print(f"      rejected (probe cleanup): {r.status_code}")


if __name__ == "__main__":
    main()
