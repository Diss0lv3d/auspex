"""A chat survives a reload (F2): the list and the turns a stored chat replays.

Spec: docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md. The
pairing is pure (auspex/chat_history.py) and tested on plain rows here; the
routes are tested against Postgres further down, with rows inserted directly,
so nothing in this file spends inference.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest
from _tenancy import ensure_member, ensure_workspace

from auspex.auth import issue_jwt
from auspex.chat_history import TITLE_MAX, pair_turns, title_of

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def msg(role: str, content: str, minutes: float) -> dict:
    return {"id": uuid4(), "role": role, "content": content, "created_at": at(minutes)}


def ledger(minutes: float, *, message_id=None, calls=1, prompt=10, completion=4, ending="stop"):
    return {"message_id": message_id, "engine_calls": calls, "prompt_tokens": prompt,
            "completion_tokens": completion, "ending": ending, "created_at": at(minutes)}


def filed(minutes: float, *, status="pending_approval", summary="Attach a note", result=None):
    return {"id": uuid4(), "tool_name": "annotate_observable", "status": status,
            "card": {"summary": summary}, "decided_at": None, "claimed_at": None,
            "result": result, "created_at": at(minutes)}


# -- the title ------------------------------------------------------------------


def test_a_title_is_the_first_question_with_its_whitespace_collapsed():
    pasted = '\n  {"rule": {"name": "Suspicious PowerShell"},\n   "host": "fin-ws-12"}\n'
    assert title_of(pasted) == '{"rule": {"name": "Suspicious PowerShell"}, "host": "fin-ws-12"}'
    assert title_of("check 8.8.8.8") == "check 8.8.8.8"
    assert title_of("   ") == "" and title_of(None) == ""


def test_a_long_title_is_cut_at_eighty_characters():
    title = title_of("word " * 40)
    assert len(title) == TITLE_MAX == 80
    assert title.endswith("…") and not title.endswith(" …")
    assert title_of("x" * 80) == "x" * 80  # exactly the limit is not cut


# -- the pairing ----------------------------------------------------------------


def test_an_answered_turn_gets_its_own_ledger_row():
    q, a = msg("user", "what is T1059?", 0), msg("assistant", "An answer.", 1)
    [turn] = pair_turns([q, a], [ledger(1, message_id=a["id"], calls=3)], [])
    assert turn == {
        "question": "what is T1059?",
        "asked_at": at(0).isoformat(),
        "answer": "An answer.",
        "spend": {"engine_calls": 3, "prompt_tokens": 10, "completion_tokens": 4, "ending": "stop"},
        "proposals": [],
    }


def test_a_failed_turns_row_lands_under_its_own_question():
    """The ledger row of a turn that stored no answer has no message_id: it is
    placed by time, inside its own question's window and nobody else's."""
    q1, a1 = msg("user", "one", 0), msg("assistant", "first", 1)
    q2 = msg("user", "two", 2)
    q3, a3 = msg("user", "three", 4), msg("assistant", "third", 5)
    rows = [ledger(1, message_id=a1["id"]), ledger(3, ending="endpoint_error", calls=2),
            ledger(5, message_id=a3["id"])]
    turns = pair_turns([q1, a1, q2, q3, a3], rows, [])
    assert [t["answer"] for t in turns] == ["first", None, "third"]
    assert [t["spend"]["ending"] for t in turns] == ["stop", "endpoint_error", "stop"]
    assert turns[1]["spend"]["engine_calls"] == 2


def test_a_shortcut_answer_has_no_spend():
    """D-054 records deep turns only, so a shortcut answer has no row."""
    [turn] = pair_turns([msg("user", "8.8.8.8", 0), msg("assistant", "No signal.", 0.5)], [], [])
    assert turn["answer"] == "No signal." and turn["spend"] is None


def test_each_proposal_lands_under_the_turn_that_filed_it():
    q1, a1, q2 = msg("user", "one", 0), msg("assistant", "first", 1), msg("user", "two", 2)
    p1, p2 = filed(0.5, status="executed"), filed(2.5)
    turns = pair_turns([q1, a1, q2], [], [p1, p2])
    assert [p["id"] for p in turns[0]["proposals"]] == [str(p1["id"])]
    assert [p["id"] for p in turns[1]["proposals"]] == [str(p2["id"])]
    assert turns[0]["proposals"][0]["status"] == "executed"


def test_a_proposal_carries_only_what_the_panel_words_its_status_from():
    """The page words a status with the panel's statusText, which reads status,
    decided_at, claimed_at and result.effects; nothing else of the result is
    served. A row as asyncpg returns it holds jsonb as a JSON string."""
    p = filed(0.5, status="incomplete")
    p["card"] = json.dumps({"summary": "Attach a note to ipv4 203.0.113.9"})
    p["result"] = json.dumps({"effects": "unknown", "error": "TimeoutError"})
    p["decided_at"] = at(0.6)
    [turn] = pair_turns([msg("user", "one", 0)], [], [p])
    assert turn["proposals"] == [{
        "id": str(p["id"]), "action": "annotate_observable",
        "summary": "Attach a note to ipv4 203.0.113.9", "status": "incomplete",
        "decided_at": at(0.6).isoformat(), "claimed_at": None,
        "result": {"effects": "unknown"},
    }]


def test_two_rows_without_an_answer_in_one_turn_take_the_first():
    q = msg("user", "one", 0)
    rows = [ledger(1, ending="output_guard"), ledger(2, ending="empty_answer")]
    [turn] = pair_turns([q], rows, [])
    assert turn["spend"]["ending"] == "output_guard"


# -- the routes, against Postgres ----------------------------------------------

READER = "history-reader@auspex.dev"
NEIGHBOUR = "history-neighbour@auspex.dev"
BASE = datetime.now(UTC) - timedelta(days=1)


def _at(minutes: float) -> datetime:
    return BASE + timedelta(minutes=minutes)


def _db(settings, sql, *args):
    async def _run():
        conn = await asyncpg.connect(settings.database_url)
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    return asyncio.run(_run())


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(client, email: str):
    token = client.post("/api/auth/dev-login", json={"email": email}).json()["access_token"]
    who = client.get("/api/auth/whoami", headers=_h(token)).json()
    return token, UUID(who["user_id"]), UUID(who["workspace_id"])


def _forget(settings, email: str) -> None:
    """Proposals outlive their chat (ON DELETE SET NULL), so they go first."""
    _db(settings, "DELETE FROM proposals WHERE session_id IN (SELECT s.id FROM chat_sessions s"
        " JOIN users u ON u.id = s.user_id WHERE u.email = $1)", email)
    _db(settings, "DELETE FROM users WHERE email = $1", email)


@pytest.fixture
def reader(client, settings):
    """A user of its own, so the list holds only the chats a test made."""
    yield _login(client, READER)
    _forget(settings, READER)


@pytest.fixture
def neighbour(client, settings):
    """Another analyst in the reader's workspace."""
    yield _login(client, NEIGHBOUR)
    _forget(settings, NEIGHBOUR)


@pytest.fixture
def outsider(settings):
    """A user in ANOTHER workspace, with a token of its own."""

    async def _make():
        conn = await asyncpg.connect(settings.database_url)
        try:
            ws = await ensure_workspace(conn, "t-chat-history-other")
            uid = await ensure_member(conn, ws, "history-outsider@auspex.dev")
            return ws, uid
        finally:
            await conn.close()

    ws, uid = asyncio.run(_make())
    yield issue_jwt(settings, uid, ws), uid, ws
    _db(settings, "DELETE FROM workspaces WHERE id = $1", ws)


def _new_chat(settings, ws, user_id):
    return _db(settings, "INSERT INTO chat_sessions (workspace_id, user_id) VALUES ($1, $2)"
               " RETURNING id", ws, user_id)[0]["id"]


def _say(settings, ws, chat, role, content, minutes):
    return _db(settings, "INSERT INTO messages (workspace_id, session_id, role, content,"
               " created_at) VALUES ($1, $2, $3, $4, $5) RETURNING id",
               ws, chat, role, content, _at(minutes))[0]["id"]


def _spent(settings, ws, chat, minutes, *, message_id=None, calls=1, prompt=10, completion=4,
           ending="stop"):
    _db(settings, "INSERT INTO turn_spend (workspace_id, session_id, message_id, engine_calls,"
         " prompt_tokens, completion_tokens, ending, created_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        ws, chat, message_id, calls, prompt, completion, ending, _at(minutes))


def _file(settings, ws, chat, minutes, *, status="pending_approval",
          summary="Attach a note to ipv4 203.0.113.9"):
    return _db(settings, "INSERT INTO proposals (workspace_id, session_id, tool_name, tool_level,"
                " tool_input, status, card, created_at)"
               " VALUES ($1, $2, 'annotate_observable', 'write',"
               " $3::jsonb, $4, $5::jsonb, $6) RETURNING id", ws, chat,
               json.dumps({"observable_id": "ipv4-f2test", "note": "seen beaconing"}), status,
               json.dumps({"summary": summary}), _at(minutes))[0]["id"]


def test_the_chat_list_requires_auth(client):
    assert client.get("/api/chat/sessions").status_code == 401


def test_your_chats_come_newest_first_titled_and_totalled(client, settings, reader):
    token, uid, ws = reader
    a = _new_chat(settings, ws, uid)
    first_q = '\n  {"rule": {"name": "Suspicious PowerShell"},\n "host": "fin-ws-12"}'
    _say(settings, ws, a, "user", first_q, 1)
    answer = _say(settings, ws, a, "assistant", "An answer.", 2)
    _spent(settings, ws, a, 2, message_id=answer, calls=3, prompt=100, completion=20)
    b = _new_chat(settings, ws, uid)
    _say(settings, ws, b, "user", "check 8.8.8.8", 3)
    _say(settings, ws, b, "assistant", "No signal.", 3.5)
    _say(settings, ws, a, "user", "and the parent process?", 4)  # a is the newest again
    _new_chat(settings, ws, uid)  # never asked anything: left out

    body = client.get("/api/chat/sessions", headers=_h(token)).json()
    assert [s["id"] for s in body["sessions"]] == [str(a), str(b)]
    assert body["complete"] is True
    first, second = body["sessions"]
    assert first["title"] == '{"rule": {"name": "Suspicious PowerShell"}, "host": "fin-ws-12"}'
    assert datetime.fromisoformat(first["last_at"]) == _at(4)
    assert datetime.fromisoformat(first["created_at"]) <= datetime.now(UTC)
    assert first["spend"] == {"turns": 1, "engine_calls": 3, "prompt_tokens": 100,
                              "completion_tokens": 20}
    assert second["spend"] == {"turns": 0, "engine_calls": 0, "prompt_tokens": None,
                               "completion_tokens": None}


def test_the_list_says_when_it_was_cut(client, settings, reader):
    token, uid, ws = reader
    _db(settings, "WITH s AS (INSERT INTO chat_sessions (workspace_id, user_id)"
        " SELECT $1, $2 FROM generate_series(1, 51) RETURNING id)"
        " INSERT INTO messages (workspace_id, session_id, role, content)"
        " SELECT $1, id, 'user', 'q' FROM s",
        ws, uid)
    body = client.get("/api/chat/sessions", headers=_h(token)).json()
    assert len(body["sessions"]) == 50
    assert body["complete"] is False


def test_another_analysts_chats_never_appear(client, settings, reader, neighbour, outsider):
    token, uid, ws = reader
    mine = _new_chat(settings, ws, uid)
    _say(settings, ws, mine, "user", "mine", 1)
    n_token, n_uid, n_ws = neighbour
    theirs = _new_chat(settings, n_ws, n_uid)
    _say(settings, n_ws, theirs, "user", "the neighbour's", 2)
    o_token, o_uid, o_ws = outsider
    far = _new_chat(settings, o_ws, o_uid)
    _say(settings, o_ws, far, "user", "another workspace's", 3)


    def listed(t):
        body = client.get("/api/chat/sessions", headers=_h(t)).json()
        return [s["id"] for s in body["sessions"]]

    assert listed(token) == [str(mine)]
    assert listed(n_token) == [str(theirs)]
    assert listed(o_token) == [str(far)]


def test_a_reopened_chat_pairs_each_turn(client, settings, reader):
    token, uid, ws = reader
    chat = _new_chat(settings, ws, uid)
    _say(settings, ws, chat, "user", "check 185.220.101.133 and add a note", 1)
    note = _file(settings, ws, chat, 1.5, status="executed")
    first = _say(settings, ws, chat, "assistant", "## Verdict\nsuspicious", 2)
    _spent(settings, ws, chat, 2, message_id=first, calls=4, prompt=2800, completion=300)
    _say(settings, ws, chat, "user", "dig deeper", 3)
    _spent(settings, ws, chat, 3.5, calls=2, prompt=None, completion=None, ending="endpoint_error")
    _say(settings, ws, chat, "user", "8.8.8.8", 5)
    _say(settings, ws, chat, "assistant", "No signal.", 5.2)

    resp = client.get(f"/api/chat/sessions/{chat}/turns", headers=_h(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(chat)
    one, two, three = body["turns"]
    assert one["question"] == "check 185.220.101.133 and add a note"
    assert one["answer"] == "## Verdict\nsuspicious"
    assert one["spend"] == {"engine_calls": 4, "prompt_tokens": 2800, "completion_tokens": 300,
                            "ending": "stop"}
    assert one["proposals"] == [{
        "id": str(note), "action": "annotate_observable",
        "summary": "Attach a note to ipv4 203.0.113.9", "status": "executed",
        "decided_at": None, "claimed_at": None, "result": {"effects": None},
    }]
    assert two["answer"] is None
    assert two["spend"] == {"engine_calls": 2, "prompt_tokens": None, "completion_tokens": None,
                            "ending": "endpoint_error"}
    assert three["answer"] == "No signal." and three["spend"] is None and three["proposals"] == []


def test_a_turn_the_output_check_cut_comes_back_without_its_text(client, settings, reader):
    """The route stores nothing of a cut turn (auspex/routes/chat.py, the
    output_guard ending returns before the insert), so replay cannot resurrect
    what the rail stopped."""
    token, uid, ws = reader
    chat = _new_chat(settings, ws, uid)
    _say(settings, ws, chat, "user", "what is kerberoasting?", 1)
    _spent(settings, ws, chat, 2, calls=3, ending="output_guard")
    [turn] = client.get(f"/api/chat/sessions/{chat}/turns", headers=_h(token)).json()["turns"]
    assert turn["answer"] is None and turn["spend"]["ending"] == "output_guard"


def test_a_foreign_chat_is_a_404_like_a_missing_one(client, settings, reader, neighbour, outsider):
    token, uid, ws = reader
    mine = _new_chat(settings, ws, uid)
    _say(settings, ws, mine, "user", "mine", 0.5)
    # The owner reads it: so the 404s below are this route's, not a missing route's.
    assert client.get(f"/api/chat/sessions/{mine}/turns", headers=_h(token)).status_code == 200
    n_token, n_uid, n_ws = neighbour
    theirs = _new_chat(settings, n_ws, n_uid)
    _say(settings, n_ws, theirs, "user", "the neighbour's", 1)
    o_token, o_uid, o_ws = outsider
    far = _new_chat(settings, o_ws, o_uid)
    _say(settings, o_ws, far, "user", "another workspace's", 2)

    missing = client.get("/api/chat/sessions/00000000-0000-0000-0000-0000000000ff/turns",
                         headers=_h(token))
    assert missing.status_code == 404
    for chat in (theirs, far):
        resp = client.get(f"/api/chat/sessions/{chat}/turns", headers=_h(token))
        assert resp.status_code == 404
        assert resp.json() == missing.json()  # no oracle for "exists, not yours"


def test_another_workspaces_proposal_never_attaches(client, settings, reader, outsider):
    """A proposal row is reached only through a chat you own AND your
    workspace: one filed under another workspace never shows, even pointing
    at your chat."""
    token, uid, ws = reader
    chat = _new_chat(settings, ws, uid)
    _say(settings, ws, chat, "user", "one", 1)
    _, _, o_ws = outsider
    _file(settings, o_ws, chat, 1.5)
    [turn] = client.get(f"/api/chat/sessions/{chat}/turns", headers=_h(token)).json()["turns"]
    assert turn["proposals"] == []
