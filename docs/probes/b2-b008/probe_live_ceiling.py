"""B2 — B-008 live, through the running container: a turn refused at the ceiling.

Reaching the ceiling honestly would spend ~100 inference calls. Instead this
sets THIS hour's `inference_calls` counter for the `default` workspace to the
plan's limit, makes two refused turns, and puts the counter back to exactly
what it was (in a `finally`). No inference call is made: the claim is refused
before any endpoint is touched.

  A. a NEW chat, deep question                       -> 429?
  B. an open chat (made by an unmetered IOC check),
     deep follow-up with its session_id               -> 429?

For each: status, the refusal detail, whether the question was stored, and
whether the chat list (`GET /api/chat/sessions`) grew. Do NOT run pytest at the
same time.

Run:  .venv/bin/python docs/probes/b2-b008/probe_live_ceiling.py
"""

import asyncio
import sys

import httpx

sys.path.insert(0, ".")
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402
from auspex.limits import window_start  # noqa: E402

API = "http://localhost:8000/api"
NEW_Q = "B-008 live: how does kerberoasting lead to domain admin? (new chat at the ceiling)"
OPEN_Q = "B-008 live: and how would I detect it? (open chat at the ceiling)"


async def main() -> None:
    pool = await create_pool(get_settings().database_url, retries=2, delay=0.5)
    ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = 'default'")
    window = window_start()
    saved = await pool.fetchval(
        "SELECT used FROM usage_counters WHERE workspace_id = $1 AND meter = 'inference_calls'"
        " AND window_start = $2", ws, window)
    try:
        async with httpx.AsyncClient(timeout=120) as http:
            token = (await http.post(f"{API}/auth/dev-login",
                                     json={"email": "b2-probe@auspex.dev"})).json()["access_token"]
            auth = {"Authorization": f"Bearer {token}"}
            usage = (await http.get(f"{API}/usage", headers=auth)).json()
            limit = usage["meters"]["inference_calls"]["limit"]
            print(f"window {window.isoformat()} used before={saved} limit={limit}")

            # B's open chat first, while under the ceiling: an IOC check is unmetered.
            open_frames = (await http.post(f"{API}/chat", json={"message": "check 8.8.8.8"},
                                           headers=auth)).text
            session = next(line for line in open_frames.splitlines()
                           if line.startswith("data:") and '"session"' in line)
            session = session.split('"session": "')[1].split('"')[0]

            await pool.execute(
                "INSERT INTO usage_counters (workspace_id, meter, window_start, used)"
                " VALUES ($1, 'inference_calls', $2, $3)"
                " ON CONFLICT (workspace_id, meter, window_start) DO UPDATE SET used = $3",
                ws, window, limit)
            print(f"counter set to the limit ({limit})")

            for label, body in (("A new chat", {"message": NEW_Q}),
                                ("B open chat", {"message": OPEN_Q, "session_id": session})):
                chats_before = [s["id"] for s in (await http.get(
                    f"{API}/chat/sessions", headers=auth)).json()["sessions"]]
                resp = await http.post(f"{API}/chat", json=body, headers=auth)
                chats_after = [s["id"] for s in (await http.get(
                    f"{API}/chat/sessions", headers=auth)).json()["sessions"]]
                stored = await pool.fetchval(
                    "SELECT count(*) FROM messages WHERE content = $1", body["message"])
                detail = resp.json().get("detail") if resp.status_code != 200 else None
                print(f"{label}: HTTP {resp.status_code} detail={detail!r}")
                print(f"   question stored: {stored}   chat list grew by: "
                      f"{len(set(chats_after) - set(chats_before))}")
            roles = [r["role"] for r in await pool.fetch(
                "SELECT role FROM messages WHERE session_id = $1::uuid ORDER BY created_at",
                session)]
            print(f"open chat's messages after: {roles}")
    finally:
        if saved is None:
            await pool.execute(
                "DELETE FROM usage_counters WHERE workspace_id = $1"
                " AND meter = 'inference_calls' AND window_start = $2", ws, window)
        else:
            await pool.execute(
                "UPDATE usage_counters SET used = $3 WHERE workspace_id = $1"
                " AND meter = 'inference_calls' AND window_start = $2", ws, window, saved)
        back = await pool.fetchval(
            "SELECT used FROM usage_counters WHERE workspace_id = $1"
            " AND meter = 'inference_calls' AND window_start = $2", ws, window)
        print(f"counter restored: {back} (was {saved})")
        await pool.close()


asyncio.run(main())
