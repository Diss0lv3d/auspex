"""F4 Step 0.4: probe S30's GET /api/auth/me and POST /api/auth/switch as each
D-061 persona, against the running container (http://localhost:8000).

Seeds `f4-probe-*` organizations with the tenancy CLI (organizations are
CLI-only, D-068) and deletes them, and only them, in a `finally`. Prints a
redacted record: emails become persona labels, row ids become names, tokens are
never printed. No engine call: the only deep turn is the ksa one the region
guard refuses before anything is stored.

    .venv/bin/python docs/probes/f4-step0/probe_s30_routes.py
"""

import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[3]
BASE = "http://localhost:8000"
DOMAIN = "f4-probe.auspex.dev"
ORGS = ["f4-probe-bank", "f4-probe-telco", "f4-probe-gov", "f4-probe-mssp"]
PEOPLE = {
    "p-admin": "provider admin",
    "m-explicit": "MSSP analyst, explicit memberships",
    "m-wide": "MSSP analyst, provider-wide grant",
    "c-admin": "client admin (bank)",
    "c-analyst": "client analyst (bank)",
    "c-viewer": "client viewer (bank)",
}
NAMES: dict[str, str] = {}  # uuid -> readable label, filled from /me answers


def email(who: str) -> str:
    return f"{who}@{DOMAIN}"


def redact(text: str) -> str:
    for who in PEOPLE:
        text = text.replace(email(who), f"<{who}>")
    for raw, label in NAMES.items():
        text = text.replace(raw, f"<{label}>")
    return text


def show(title: str, payload) -> None:
    body = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    print(f"$ {redact(title)}\n{redact(body)}\n")


def cli(*args: str) -> None:
    run = subprocess.run(
        ["docker", "compose", "exec", "-T", "app", "python", "-m", "auspex.tenancy", *args],
        capture_output=True, text=True, cwd=REPO, check=False,
    )
    out = (run.stdout.strip() or run.stderr.strip())
    show("tenancy " + " ".join(args), f"{out}\n[exit {run.returncode}]")


def psql(sql: str) -> str:
    run = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "auspex", "-d", "auspex",
         "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True, cwd=REPO, check=False,
    )
    return (run.stdout + run.stderr).strip()


def login(client: httpx.Client, who: str) -> str:
    r = client.post("/api/auth/dev-login", json={"email": email(who)})
    r.raise_for_status()
    return r.json()["access_token"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def me(client: httpx.Client, token: str) -> httpx.Response:
    return client.get("/api/auth/me", headers=bearer(token))


def learn(body: dict) -> None:
    """Map every id /me returned to a readable name, so the record redacts it."""
    NAMES[body["user"]["id"]] = "user"
    NAMES[body["organization"]["id"]] = "org:" + body["organization"]["name"]
    for ws in body["workspaces"]:
        NAMES[ws["id"]] = "ws:" + ws["name"]
        NAMES[ws["organization"]["id"]] = "org:" + ws["organization"]["name"]


def summary(body: dict) -> str:
    rows = [f"  {w['name']:<16} {w['region']:<6} {w['role']:<8} via={w['via']:<13}"
            f" org={w['organization']['name']} ({w['organization']['kind']})"
            for w in body["workspaces"]]
    return (f"home org {body['organization']['name']} ({body['organization']['kind']});"
            f" active {body['workspace']['name']} as {body['workspace']['role']}"
            f" (org {body['workspace']['organization']})\n" + "\n".join(rows))


def setup() -> None:
    cli("create-org", "--kind", "provider", "--name", "f4-probe-mssp",
        "--workspace", "f4-probe-mssp", "--admin", email("p-admin"))
    cli("create-client", "--provider", "f4-probe-mssp", "--name", "f4-probe-bank",
        "--workspace", "f4-probe-bank", "--admin", email("c-admin"))
    cli("create-client", "--provider", "f4-probe-mssp", "--name", "f4-probe-telco",
        "--workspace", "f4-probe-telco", "--region", "ksa")
    cli("create-client", "--provider", "f4-probe-mssp", "--name", "f4-probe-gov",
        "--workspace", "f4-probe-gov", "--restricted")
    cli("set-member", "--workspace", "f4-probe-mssp", "--email", email("m-explicit"),
        "--role", "analyst")
    cli("set-member", "--workspace", "f4-probe-bank", "--email", email("m-explicit"),
        "--role", "analyst")
    cli("set-member", "--workspace", "f4-probe-gov", "--email", email("m-explicit"),
        "--role", "viewer")
    cli("set-member", "--workspace", "f4-probe-mssp", "--email", email("m-wide"),
        "--role", "analyst", "--provider-wide")
    cli("set-member", "--workspace", "f4-probe-bank", "--email", email("c-analyst"),
        "--role", "analyst")
    cli("set-member", "--workspace", "f4-probe-bank", "--email", email("c-viewer"),
        "--role", "viewer")
    cli("list")


def cleanup() -> None:
    ids = "SELECT id FROM organizations WHERE name LIKE 'f4-probe-%'"
    print("$ cleanup")
    print(psql(
        "BEGIN;"
        f" DELETE FROM workspaces WHERE org_id IN ({ids});"
        f" DELETE FROM users WHERE home_org_id IN ({ids}) OR email LIKE '%@{DOMAIN}';"
        " DELETE FROM organizations WHERE name LIKE 'f4-probe-%' AND kind = 'client';"
        " DELETE FROM organizations WHERE name LIKE 'f4-probe-%';"
        " COMMIT;"
    ))
    print(psql(f"SELECT count(*) AS left_behind FROM users WHERE email LIKE '%@{DOMAIN}'"
               " UNION ALL SELECT count(*) FROM organizations WHERE name LIKE 'f4-probe-%'"))


def personas(client: httpx.Client) -> dict[str, str]:
    tokens = {}
    for who, label in PEOPLE.items():
        tokens[who] = login(client, who)
        r = me(client, tokens[who])
        body = r.json()
        learn(body)
        show(f"[{label}] GET /api/auth/me -> {r.status_code}", summary(body))
    # One full body, unabridged, for the shape.
    show("[MSSP analyst, provider-wide grant] GET /api/auth/me (full body)",
         me(client, tokens["m-wide"]).json())
    return tokens


def switches(client: httpx.Client, tokens: dict[str, str]) -> None:
    for who in ("m-explicit", "m-wide", "p-admin"):
        start = me(client, tokens[who]).json()
        for ws in start["workspaces"]:
            if ws["id"] == start["workspace"]["id"]:
                continue
            r = client.post("/api/auth/switch", headers=bearer(tokens[who]),
                            json={"workspace_id": ws["id"]})
            body = r.json()
            token = body.pop("access_token", None)
            show(f"[{PEOPLE[who]}] POST /api/auth/switch -> {ws['name']}: {r.status_code}", body)
            if token:
                now = me(client, token).json()["workspace"]
                old = me(client, tokens[who]).json()["workspace"]
                print(f"  new token's /me: active {now['name']} as {now['role']},"
                      f" org {now['organization']}")
                print(f"  old token's /me: active {old['name']} (still valid)\n")
    gov = next(n for n, label in NAMES.items() if label == "ws:f4-probe-gov")
    mssp = next(n for n, label in NAMES.items() if label == "ws:f4-probe-mssp")
    refusals = [
        ("m-wide", "the restricted client gov", {"workspace_id": gov}),
        ("m-wide", "a workspace that does not exist", {"workspace_id": str(uuid.uuid4())}),
        ("m-wide", "a malformed id", {"workspace_id": "not-a-uuid"}),
        ("c-admin", "the client's provider", {"workspace_id": mssp}),
        ("c-analyst", "the restricted sibling gov", {"workspace_id": gov}),
    ]
    for who, what, payload in refusals:
        r = client.post("/api/auth/switch", headers=bearer(tokens[who]), json=payload)
        show(f"[{PEOPLE[who]}] POST /api/auth/switch -> {what}: {r.status_code}", r.json())


def api_key_switch(client: httpx.Client, tokens: dict[str, str]) -> None:
    r = client.post("/api/auth/api-keys", headers=bearer(tokens["c-analyst"]),
                    json={"name": "f4-probe"})
    key = r.json()["api_key"]
    print(f"$ [client analyst] POST /api/auth/api-keys -> {r.status_code} (key not shown)\n")
    r = client.get("/api/auth/me", headers={"X-API-Key": key})
    print(f"$ [client analyst, API key] GET /api/auth/me -> {r.status_code}\n")
    bank = next(n for n, label in NAMES.items() if label == "ws:f4-probe-bank")
    r = client.post("/api/auth/switch", headers={"X-API-Key": key}, json={"workspace_id": bank})
    show(f"[client analyst, API key] POST /api/auth/switch -> {r.status_code}", r.json())


def viewer_writes(client: httpx.Client, tokens: dict[str, str]) -> None:
    v = bearer(tokens["c-viewer"])
    r = client.post("/api/chat", headers=v, json={"message": "What is CVE-2021-44228?"})
    show(f"[client viewer] POST /api/chat -> {r.status_code}", r.json())
    r = client.post(f"/api/proposals/{uuid.uuid4()}/reject", headers=v)
    show(f"[client viewer] POST /api/proposals/<random>/reject -> {r.status_code}", r.json())
    r = client.get("/api/proposals", headers=v)
    print(f"$ [client viewer] GET /api/proposals -> {r.status_code}\n")
    r = client.get("/api/workspace/members", headers=bearer(tokens["c-analyst"]))
    show(f"[client analyst] GET /api/workspace/members -> {r.status_code}", r.json())
    r = client.get("/api/workspace/members", headers=bearer(tokens["c-admin"]))
    print(f"$ [client admin] GET /api/workspace/members -> {r.status_code},"
          f" {len(r.json().get('members', []))} members\n")


def residency(client: httpx.Client, tokens: dict[str, str]) -> None:
    telco = next(n for n, label in NAMES.items() if label == "ws:f4-probe-telco")
    r = client.post("/api/auth/switch", headers=bearer(tokens["m-wide"]),
                    json={"workspace_id": telco})
    token = r.json()["access_token"]
    print(f"$ [MSSP analyst, provider-wide] switch -> f4-probe-telco (ksa): {r.status_code}\n")
    deep = "Walk me through how attackers use PsExec for lateral movement and how to detect it."
    r = client.post("/api/chat", headers=bearer(token), json={"message": deep})
    show(f"[provider-wide, in ksa] POST /api/chat (deep turn) -> {r.status_code}"
         f" content-type={r.headers.get('content-type')}", r.text)
    stored = psql("SELECT count(*) AS sessions FROM chat_sessions s JOIN workspaces w"
                  " ON w.id = s.workspace_id WHERE w.name = 'f4-probe-telco'")
    print(f"$ chat sessions stored in f4-probe-telco\n{stored}\n")


def removed_member(client: httpx.Client, tokens: dict[str, str]) -> None:
    frames: list[str] = []
    token = tokens["c-analyst"]

    def watch() -> None:
        with httpx.Client(base_url=BASE, timeout=30) as c, c.stream(
            "GET", "/api/proposals/stream", headers=bearer(token)
        ) as r:
            frames.append(f"status {r.status_code}")
            for line in r.iter_lines():
                if line.startswith("data:"):
                    frames.append(line)
                    if '"error"' in line:
                        return

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    time.sleep(2.5)
    cli("remove-member", "--workspace", "f4-probe-bank", "--email", email("c-analyst"))
    r = me(client, token)
    show(f"[client analyst, removed] GET /api/auth/me -> {r.status_code}", r.json())
    r = client.get("/api/proposals", headers=bearer(token))
    show(f"[client analyst, removed] GET /api/proposals -> {r.status_code}", r.json())
    t.join(timeout=10)
    show("[client analyst, removed] the open approvals stream", "\n".join(frames) or "(nothing)")
    r = client.post("/api/auth/dev-login", json={"email": email("c-analyst")})
    show(f"[client analyst, removed] POST /api/auth/dev-login -> {r.status_code}",
         {k: v for k, v in r.json().items() if k != "access_token"})


def main() -> None:
    try:
        setup()
        with httpx.Client(base_url=BASE, timeout=30) as client:
            tokens = personas(client)
            switches(client, tokens)
            api_key_switch(client, tokens)
            viewer_writes(client, tokens)
            residency(client, tokens)
            removed_member(client, tokens)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
