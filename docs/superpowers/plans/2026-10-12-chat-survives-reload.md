# A Chat Survives a Reload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An analyst can reload the chat page, or come back to an older chat, and find the conversation, its spend and its proposals' doors where they left them, still signed in.

**Architecture:** Two read routes on the existing chat router list a user's chats and return one chat's turns, paired on the server by a pure module (`auspex/chat_history.py`). The page keeps the sign-in token in `sessionStorage` (D-056) and the open chat's id in the URL hash, shows an always-on sidebar of chats, and renders a reopened chat from a pure render plan in its `// <page-logic>` block.

**Tech Stack:** FastAPI + asyncpg (Postgres), plain JavaScript in `auspex/static/index.html`, pytest, Node's built-in test runner.

**Spec:** `docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md` (approved by Burhan, F2). Read it before any task.

## Global Constraints

- Every query on these routes is scoped to `workspace_id` AND `user_id` (the chat) or `workspace_id` AND an owned chat (its rows). Another analyst's chat is a 404 with the same body as a missing chat (`"Chat session not found"`, from `_ensure_session`).
- Model text and tool text reach the page as text, never as HTML: `textContent`, `append`, or D-053's `el`/`markdownNodes`. `innerHTML` never takes a variable (`tests/test_ui.py` pins it).
- The engine is never named in a user-visible string (D-002; `FORBIDDEN_ENGINE_NAMES`).
- Colours, fonts and voice are D-002's: Night `#0A0D12`, Surface `#11161F`, Text `#E7ECF3`, Aurora `#4FF2C0`, Signal `#FFB454`, Ember `#FF5D5D`, Steel `#7AA2F7`, Slate `#8B93A7`.
- The list returns at most `CHAT_LIST_LIMIT = 50` chats; a title is at most `TITLE_MAX = 80` characters.
- The token's `sessionStorage` key is `auspex.token`. The hash is `#chat=<uuid>`.
- Copy, verbatim:
  - divider: `Reopened · answers and spend only; reasoning and tool steps aren't kept.`
  - endings: `No answer: the engine returned an error` (`endpoint_error`), `No answer: stopped by the platform's output check` (`output_guard`), `No answer: the workspace's usage limit was reached` (`usage_refused`), `No answer: the engine returned none` (`empty_answer`), `No answer was stored` (anything else, or no row);
  - 404 note: `That chat is not available to you.`
- No new env vars, no migration, no new package directory.
- One concern per commit; never amend. Commit messages end with the session's attribution lines (`Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01DhCqy11iYBpKh8zJKuC2bP`).
- Every commit that adds a pytest test updates the README's test count in BOTH places (`README.md` line ~11 "— N tests," and line ~249 "ruff + N tests") to the collected count: `.venv/bin/pytest --collect-only -q | tail -1`.
- Do not edit code while `./ci.sh` runs. Do not run pytest while live `/api/chat` probes run.
- ruff runs in `./ci.sh` with line length 100 and import sorting (`I`). The code blocks below are not
  pre-wrapped: after each Python step run `.venv/bin/ruff check auspex tests` and wrap what it flags
  (`--fix` sorts imports).

## Review Focus

1. **A stored token that expired or was signed by an old key** (12 h TTL): the page must clear it and show sign-in, not hang on "signing in…". Pinned: Task 8 live step (plant a bad token, reload).
2. **Clicking a chat or New chat while a turn streams**: nothing may switch under a half-streamed answer. Pinned: Task 7 disables both while `busy`; Task 8 live step clicks during a turn.
3. **Storage that throws** (blocked site data, some private modes): the page must work exactly as before F2. Pinned: Task 6's pytest counts that `sessionStorage.` appears only inside the three try/catch helpers.
4. **A pasted alert as the first question** (multi-line JSON, thousands of characters): the title must be readable, not `{`. Pinned: Task 2's title test (whitespace collapsed, cut at 80).
5. **A token for another user opening a hash chat** (sign out, sign in as someone else, reload): the page must show the 404 note and a new chat, never another analyst's turns. Pinned: Task 4's 404 test (server) and Task 8 live step 4 (page).

---

### Task 1: Record D-056, and correct the spec's title rule

**Files:**
- Modify: `DECISIONS.md` (append after D-055, end of file)
- Modify: `docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md` (the `title` bullet under `GET /api/chat/sessions`)

**Interfaces:**
- Consumes: nothing.
- Produces: D-056, which Tasks 6 and 7 cite in comments.

- [ ] **Step 1: Append D-056 to `DECISIONS.md`**

```markdown

## D-056 — The sign-in survives a reload in the tab's sessionStorage (2026-10-12, F2)

**Context.** F2's goal is that a chat survives a reload. The page held its
token in memory only (`auspex/static/index.html`, `let token = null`), so a
reload signed the analyst out as well as losing the chat, and B-003's fix makes
reloading normal after every deploy.

**Decision (Burhan's call; the recommended option).**
1. On sign-in the page stores the token in `sessionStorage` under
   `auspex.token`. It survives a reload in the same tab and is gone when the tab
   closes. The token's lifetime is unchanged (`jwt_ttl_minutes`, 12 h).
2. On load, a stored token is checked with `GET /api/auth/whoami`. A 401 clears
   it. Every storage call is in a try/catch, so blocked storage leaves the page
   as it was before.
3. A **Sign out** button clears it.

**Rejected.**
- *Sign in again after every reload:* no security change, one step per deploy.
- *localStorage:* the token would outlive the tab and be shared across tabs.
- *An httpOnly cookie:* scripts could not read it, but the server would read a
  cookie and every POST would need CSRF protection: more than F2.

**The risk this accepts.** Any script running on the page can read the token.
The page sends no Content-Security-Policy (`auspex/routes/ui.py` sets only
`no-cache`), so the one guard is D-053's rule that model and tool text never
become HTML. A CSP is TD-051.
```

- [ ] **Step 2: Correct the spec's title rule**

In the spec, replace:

```markdown
- `title`: the first question's first line, cut at 80 characters with "…".
```

with:

```markdown
- `title`: the first question with its whitespace collapsed, cut at 80
  characters with "…". (Collapsed rather than first-line, found while
  planning: a pasted JSON alert's first line is `{`.)
```

and in its Testing section replace `the title rule: first line, 80 characters;` with `the title rule: whitespace collapsed, 80 characters;`.

- [ ] **Step 3: Commit, one concern each**

```bash
git add DECISIONS.md
git commit -m "docs(decisions): D-056 -- the sign-in survives a reload in the tab's sessionStorage, and the risk that accepts"
git add docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md
git commit -m "docs(specs): a chat's title collapses the first question's whitespace, so a pasted alert is not titled '{'"
```

---

### Task 2: Pair a chat's stored rows into turns (pure)

**Files:**
- Create: `auspex/chat_history.py`
- Create: `tests/test_chat_history.py`
- Modify: `README.md` (test count, two places)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TITLE_MAX: int = 80`
  - `title_of(question: str | None) -> str`
  - `pair_turns(messages: Sequence[Mapping], spend: Sequence[Mapping], proposals: Sequence[Mapping]) -> list[dict]`
    - `messages`: rows with `id`, `role`, `content`, `created_at` (oldest first).
    - `spend`: rows with `message_id`, `engine_calls`, `prompt_tokens`, `completion_tokens`, `ending`, `created_at`.
    - `proposals`: rows with `id`, `tool_name`, `status`, `card`, `decided_at`, `claimed_at`, `result`, `created_at`; `card`/`result` may be dicts or JSON strings (asyncpg returns `jsonb` as `str` here: no codec is registered in `auspex/db.py`).
    - returns `[{"question": str, "asked_at": iso str, "answer": str | None, "spend": {"engine_calls", "prompt_tokens", "completion_tokens", "ending"} | None, "proposals": [{"id": str, "action": str, "summary": str | None, "status": str, "decided_at": iso | None, "claimed_at": iso | None, "result": {"effects": str | None}}]}]`

- [ ] **Step 1: Write the failing tests** — create `tests/test_chat_history.py`:

```python
"""A chat survives a reload (F2): the list and the turns a stored chat replays.

Spec: docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md. The
pairing is pure (auspex/chat_history.py) and tested on plain rows here; the
routes are tested against Postgres further down, with rows inserted directly,
so nothing in this file spends inference.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
    [turn] = pair_turns([q], [ledger(1, ending="output_guard"), ledger(2, ending="empty_answer")], [])
    assert turn["spend"]["ending"] == "output_guard"
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/test_chat_history.py -q`
Expected: FAIL at collection, `ModuleNotFoundError: No module named 'auspex.chat_history'`.

- [ ] **Step 3: Write `auspex/chat_history.py`**

```python
"""What a stored chat replays (F2): its title and its turns.

Pure: the routes in auspex/routes/chat.py fetch the rows and this pairs them,
so the pairing is tested on plain rows (tests/test_chat_history.py). Spec:
docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md.

A question opens a turn, and the turn runs until the next question. Only one
link is an exact key: a ledger row names its answer (`turn_spend.message_id`).
A turn that stored no answer, and every proposal, is placed by time (TD-050).
Reasoning and tool lines were never stored, so nothing here can return them.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

TITLE_MAX = 80


def title_of(question: str | None) -> str:
    """A chat's title: its first question with the whitespace collapsed, cut at
    TITLE_MAX characters. Collapsed, not first-line: a pasted JSON alert's first
    line is "{"."""
    text = " ".join((question or "").split())
    if len(text) <= TITLE_MAX:
        return text
    return text[: TITLE_MAX - 1].rstrip() + "…"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _spend(row: Mapping) -> dict:
    return {
        "engine_calls": row["engine_calls"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "ending": row["ending"],
    }


def _proposal(row: Mapping) -> dict:
    """Only what the page words a status from (the panel's statusText), never
    the whole stored result."""
    card = _json(row["card"]) or {}
    result = _json(row["result"])
    return {
        "id": str(row["id"]),
        "action": row["tool_name"],
        "summary": card.get("summary"),
        "status": row["status"],
        "decided_at": _iso(row["decided_at"]),
        "claimed_at": _iso(row["claimed_at"]),
        "result": {"effects": result.get("effects") if isinstance(result, dict) else None},
    }


def pair_turns(
    messages: Sequence[Mapping],
    spend: Sequence[Mapping],
    proposals: Sequence[Mapping],
) -> list[dict]:
    turns: list[dict] = []
    starts: list[datetime] = []
    answer_ids: dict[Any, int] = {}
    for m in messages:
        if m["role"] == "user":
            turns.append({"question": m["content"], "asked_at": _iso(m["created_at"]),
                          "answer": None, "spend": None, "proposals": []})
            starts.append(m["created_at"])
        elif m["role"] == "assistant" and turns and turns[-1]["answer"] is None:
            turns[-1]["answer"] = m["content"]
            answer_ids[m["id"]] = len(turns) - 1

    def turn_at(when: datetime) -> int | None:
        i = bisect_right(starts, when) - 1
        return i if i >= 0 else None

    for row in spend:
        if row["message_id"] is not None:
            i = answer_ids.get(row["message_id"])
        else:
            i = turn_at(row["created_at"])
            if i is not None and turns[i]["answer"] is not None:
                i = None  # an answered turn's row names its answer
        if i is not None and turns[i]["spend"] is None:
            turns[i]["spend"] = _spend(row)

    for row in proposals:
        i = turn_at(row["created_at"])
        if i is not None:
            turns[i]["proposals"].append(_proposal(row))
    return turns
```

- [ ] **Step 4: Run them to see them pass**

Run: `.venv/bin/pytest tests/test_chat_history.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Mutant — widen the window by one turn**

In `turn_at`, change `bisect_right(starts, when) - 1` to `bisect_right(starts, when) - 2`.
Run: `.venv/bin/pytest tests/test_chat_history.py -q`
Expected: FAIL (`test_a_failed_turns_row_lands_under_its_own_question` and `test_each_proposal_lands_under_the_turn_that_filed_it`). Revert the change, re-run, expect `8 passed`.

- [ ] **Step 6: Update the README count and commit**

Run: `.venv/bin/pytest --collect-only -q | tail -1` → expect `1331 tests collected`. Replace `1323` with that number in both README places.

```bash
git add auspex/chat_history.py tests/test_chat_history.py README.md
git commit -m "feat(chat): a stored chat pairs into turns -- answer, spend and proposals each under the question that made them (1331 tests)"
```

---

### Task 3: `GET /api/chat/sessions` — your chats

**Files:**
- Modify: `auspex/routes/chat.py` (import `title_of`; add `CHAT_LIST_LIMIT` and the route right after `session_spend`, ~line 523)
- Modify: `tests/test_chat_history.py` (append the database tests)
- Modify: `README.md` (count)

**Interfaces:**
- Consumes: `title_of` (Task 2).
- Produces: `GET /api/chat/sessions` → `{"sessions": [{"id", "title", "created_at", "last_at", "spend": {"turns", "engine_calls", "prompt_tokens", "completion_tokens"}}], "complete": bool}`; test helpers `_db`, `_at`, `_h`, `_login`, `_new_chat`, `_say`, `_spent`, `_file`, fixtures `reader`, `neighbour`, `outsider` (Task 4 reuses them).

- [ ] **Step 1: Append the helpers, fixtures and failing tests** to `tests/test_chat_history.py`. Replace its import block with:

```python
import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest

from auspex.auth import issue_jwt
from auspex.chat_history import TITLE_MAX, pair_turns, title_of
```

Then append:

```python
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
    ws = _db(settings, "INSERT INTO workspaces (name) VALUES ('t-chat-history-other')"
             " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id")[0]["id"]
    uid = _db(settings, "INSERT INTO users (workspace_id, email) VALUES ($1, 'history-outsider@auspex.dev')"
              " ON CONFLICT (workspace_id, email) DO UPDATE SET email = EXCLUDED.email RETURNING id",
              ws)[0]["id"]
    yield issue_jwt(settings, uid, ws), uid, ws
    _db(settings, "DELETE FROM workspaces WHERE id = $1", ws)


def _new_chat(settings, ws, user_id):
    return _db(settings, "INSERT INTO chat_sessions (workspace_id, user_id) VALUES ($1, $2)"
               " RETURNING id", ws, user_id)[0]["id"]


def _say(settings, ws, chat, role, content, minutes):
    return _db(settings, "INSERT INTO messages (workspace_id, session_id, role, content, created_at)"
               " VALUES ($1, $2, $3, $4, $5) RETURNING id", ws, chat, role, content, _at(minutes))[0]["id"]


def _spent(settings, ws, chat, minutes, *, message_id=None, calls=1, prompt=10, completion=4,
           ending="stop"):
    _db(settings, "INSERT INTO turn_spend (workspace_id, session_id, message_id, engine_calls,"
        " prompt_tokens, completion_tokens, ending, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
        ws, chat, message_id, calls, prompt, completion, ending, _at(minutes))


def _file(settings, ws, chat, minutes, *, status="pending_approval",
          summary="Attach a note to ipv4 203.0.113.9"):
    return _db(settings, "INSERT INTO proposals (workspace_id, session_id, tool_name, tool_level,"
               " tool_input, status, card, created_at) VALUES ($1, $2, 'annotate_observable', 'write',"
               " $3::jsonb, $4, $5::jsonb, $6) RETURNING id", ws, chat,
               json.dumps({"observable_id": "ipv4-f2test", "note": "seen beaconing"}), status,
               json.dumps({"summary": summary}), _at(minutes))[0]["id"]


def test_the_chat_list_requires_auth(client):
    assert client.get("/api/chat/sessions").status_code == 401


def test_your_chats_come_newest_first_titled_and_totalled(client, settings, reader):
    token, uid, ws = reader
    a = _new_chat(settings, ws, uid)
    _say(settings, ws, a, "user", '\n  {"rule": {"name": "Suspicious PowerShell"},\n "host": "fin-ws-12"}', 1)
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
        " INSERT INTO messages (workspace_id, session_id, role, content) SELECT $1, id, 'user', 'q' FROM s",
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

    listed = lambda t: [s["id"] for s in client.get("/api/chat/sessions", headers=_h(t)).json()["sessions"]]  # noqa: E731
    assert listed(token) == [str(mine)]
    assert listed(n_token) == [str(theirs)]
    assert listed(o_token) == [str(far)]
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/test_chat_history.py -q`
Expected: the four new tests FAIL with 404/405 from `/api/chat/sessions` (no such route); the 8 pure tests pass.

- [ ] **Step 3: Add the route** to `auspex/routes/chat.py`. Add `from auspex.chat_history import title_of` with the other `auspex` imports (Task 4 adds `pair_turns` to it; importing it now would be an unused name ruff rejects). Add right after `session_spend`:

```python
# F2: how many chats the list returns, newest message first. No paging: the
# page says when the list was cut (docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md).
CHAT_LIST_LIMIT = 50


@router.get("/chat/sessions")
async def list_sessions(request: Request, auth: Auth) -> dict:
    """F2: your chats, by their newest message, each titled by its first
    question and totalled like `/spend`. Scoped to the workspace AND the user,
    as `_ensure_session` is: another analyst's chats never appear. A chat with
    no messages is left out."""
    pool = request.app.state.pool
    rows = await pool.fetch(
        "SELECT s.id, s.created_at, m.last_at,"
        "       (SELECT q.content FROM messages q"
        "         WHERE q.session_id = s.id AND q.workspace_id = s.workspace_id AND q.role = 'user'"
        "         ORDER BY q.created_at, q.id LIMIT 1) AS first_question,"
        "       sp.turns, sp.engine_calls, sp.prompt_tokens, sp.completion_tokens"
        "  FROM chat_sessions s"
        "  JOIN LATERAL (SELECT max(created_at) AS last_at FROM messages"
        "                 WHERE session_id = s.id AND workspace_id = s.workspace_id) m"
        "    ON m.last_at IS NOT NULL"
        "  CROSS JOIN LATERAL (SELECT count(*) AS turns, coalesce(sum(engine_calls), 0) AS engine_calls,"
        "                             sum(prompt_tokens) AS prompt_tokens,"
        "                             sum(completion_tokens) AS completion_tokens"
        "                        FROM turn_spend"
        "                       WHERE session_id = s.id AND workspace_id = s.workspace_id) sp"
        " WHERE s.workspace_id = $1 AND s.user_id = $2"
        " ORDER BY m.last_at DESC, s.id"
        " LIMIT $3",
        auth.workspace_id,
        auth.user_id,
        CHAT_LIST_LIMIT + 1,
    )
    return {
        "sessions": [
            {
                "id": str(r["id"]),
                "title": title_of(r["first_question"]),
                "created_at": r["created_at"].isoformat(),
                "last_at": r["last_at"].isoformat(),
                "spend": {
                    "turns": r["turns"],
                    "engine_calls": r["engine_calls"],
                    "prompt_tokens": r["prompt_tokens"],
                    "completion_tokens": r["completion_tokens"],
                },
            }
            for r in rows[:CHAT_LIST_LIMIT]
        ],
        "complete": len(rows) <= CHAT_LIST_LIMIT,
    }
```

- [ ] **Step 4: Run them to see them pass**

Run: `.venv/bin/pytest tests/test_chat_history.py -q`
Expected: `12 passed`.

- [ ] **Step 5: Mutant — drop the user predicate**

Change `" WHERE s.workspace_id = $1 AND s.user_id = $2"` to `" WHERE s.workspace_id = $1 AND $2::uuid IS NOT NULL"`.
Run: `.venv/bin/pytest tests/test_chat_history.py -q -k another_analysts`
Expected: FAIL (the reader's list shows the neighbour's chat). Revert, re-run the file, expect `12 passed`.

- [ ] **Step 6: README count, then commit**

Run: `.venv/bin/pytest --collect-only -q | tail -1` → expect `1335 tests collected`; update both README places.

```bash
git add auspex/routes/chat.py tests/test_chat_history.py README.md
git commit -m "feat(chat): GET /api/chat/sessions lists your chats, newest first, titled and totalled; nobody else's (1335 tests)"
```

---

### Task 4: `GET /api/chat/sessions/{id}/turns` — one chat's turns

**Files:**
- Modify: `auspex/routes/chat.py` (route after `list_sessions`)
- Modify: `tests/test_chat_history.py` (append)
- Modify: `TECHNICAL_DEBT.md` (TD-050 at the top, above TD-049)
- Modify: `README.md` (count)

**Interfaces:**
- Consumes: `pair_turns` (Task 2); `_ensure_session` (`auspex/routes/chat.py:369`); Task 3's test helpers and fixtures.
- Produces: `GET /api/chat/sessions/{session_id}/turns` → `{"id": str, "turns": [<pair_turns turn>]}`; 404 `{"detail": "Chat session not found"}` for a missing or foreign chat.

- [ ] **Step 1: Append the failing tests**

```python
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
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/test_chat_history.py -q`
Expected: the four new tests FAIL (the owner gets 404 too: no such route yet); the other 12 pass.

- [ ] **Step 3: Add the route** after `list_sessions` (and `pair_turns` to the `auspex.chat_history` import):

```python
@router.get("/chat/sessions/{session_id}/turns")
async def session_turns(request: Request, auth: Auth, session_id: UUID) -> dict:
    """F2: one chat's turns, oldest first, paired on the server
    (auspex/chat_history.py). Owned like the chat itself: another analyst's
    chat is a 404 like a missing one. Proposals are reached only through this
    owned chat AND this workspace. What is stored is what was shown: a turn the
    rail cut stored no answer."""
    pool = request.app.state.pool
    await _ensure_session(pool, auth, session_id)
    messages = await pool.fetch(
        "SELECT id, role, content, created_at FROM messages"
        " WHERE workspace_id = $1 AND session_id = $2 ORDER BY created_at, id",
        auth.workspace_id,
        session_id,
    )
    spend = await pool.fetch(
        "SELECT message_id, engine_calls, prompt_tokens, completion_tokens, ending, created_at"
        "  FROM turn_spend WHERE workspace_id = $1 AND session_id = $2 ORDER BY created_at, id",
        auth.workspace_id,
        session_id,
    )
    proposals = await pool.fetch(
        "SELECT id, tool_name, status, card, decided_at, claimed_at, result, created_at"
        "  FROM proposals WHERE workspace_id = $1 AND session_id = $2 ORDER BY created_at, id",
        auth.workspace_id,
        session_id,
    )
    return {"id": str(session_id), "turns": pair_turns(messages, spend, proposals)}
```

- [ ] **Step 4: Run them to see them pass**

Run: `.venv/bin/pytest tests/test_chat_history.py -q`
Expected: `16 passed`.

- [ ] **Step 5: Mutant — drop the workspace pin on proposals**

Change `"  FROM proposals WHERE workspace_id = $1 AND session_id = $2 ..."` to `"  FROM proposals WHERE $1::uuid IS NOT NULL AND session_id = $2 ..."`.
Run: `.venv/bin/pytest tests/test_chat_history.py -q -k another_workspaces`
Expected: FAIL. Revert; re-run the file; expect `16 passed`.

- [ ] **Step 6: Log TD-050** at the top of `TECHNICAL_DEBT.md` (below the title line, above TD-049):

```markdown
## TD-050 (F2) — a reopened chat's turns are paired by time

**Where:** `auspex/chat_history.py` `pair_turns`, behind
`GET /api/chat/sessions/{id}/turns`.
**Risk:** LOW. A ledger row names its answer (`turn_spend.message_id`), but a
turn that stored no answer, and every proposal, is placed by time: inside the
window from its question to the next. Two tabs sending into the SAME chat at
the same moment can interleave, and a proposal or a failed turn's row can land
under the other question. One tab cannot: Send is disabled while a turn runs.
**Why taken:** exact pairing needs a key on `turn_spend` and `proposals` (a
migration that fixes only new turns), for an edge one tab cannot reach.
**Path to fix:** store the question's message id on `turn_spend` and
`proposals` when the turn starts, and pair by it where present.
**Trigger:** a reopened turn shows a proposal or an ending that belongs to its
neighbour, or the page gains a way to run two turns in one chat at once.
```

- [ ] **Step 7: README count, then commit (two commits)**

Run: `.venv/bin/pytest --collect-only -q | tail -1` → expect `1339 tests collected`; update both README places.

```bash
git add auspex/routes/chat.py tests/test_chat_history.py README.md
git commit -m "feat(chat): GET /api/chat/sessions/{id}/turns replays a chat's turns with their spend and proposals; a foreign chat is a 404 (1339 tests)"
git add TECHNICAL_DEBT.md
git commit -m "chore(debt): TD-050 -- a reopened chat's turns are paired by time; two tabs in one chat can interleave"
```

---

### Task 5: The page's reopen logic (pure, Node-tested)

**Files:**
- Modify: `auspex/static/index.html` (inside `// <page-logic>`, right before `// </page-logic>`, after `chatSpendText`)
- Modify: `tests/js/page_logic.test.mjs` (import list; append tests)
- Modify: `tests/test_page_logic.py` (floor 32 → 41)

**Interfaces:**
- Consumes: `spendText`, `calls`, `kTokens`, `statusText` (already in the block); the Node file's `h`, `walk`, `textOf` helpers.
- Produces (Tasks 6–7 call them):
  - `chatIdFromHash(hash: string | null | undefined) -> string | null` (lower-cased UUID)
  - `relativeTime(then: ms, now: ms) -> string`
  - `chatListLabel(chat, now: ms) -> { title: string, meta: string }`
  - `ledgerSpendText(spend | null) -> string | null`
  - `endingText(ending: string | null) -> string`
  - `reopenedTurnPlan(turn, now: ms) -> Array<{kind: "question"|"answer"|"no-answer"|"spend", text} | {kind: "proposal", id, text}>`

- [ ] **Step 1: Write the failing tests.** In `tests/js/page_logic.test.mjs`, extend BOTH lists in the `new Function` destructuring (the `const {...} =` and the `return {...}`) with `chatIdFromHash, relativeTime, chatListLabel, ledgerSpendText, endingText, reopenedTurnPlan,`. Then append:

```js
// -- a chat survives a reload (docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md)

const CHAT = "6b1f0c2e-1d2a-4c3b-9e8f-0a1b2c3d4e5f";
const NOON = Date.parse("2026-10-12T12:00:00Z");

test("a chat id comes from the hash only when it is a UUID", () => {
  assert.equal(chatIdFromHash("#chat=" + CHAT), CHAT);
  assert.equal(chatIdFromHash("#chat=" + CHAT.toUpperCase()), CHAT);
  for (const bad of ["", "#", "#chat=", "#chat=not-a-uuid", "#chat=" + CHAT + "x",
    "#other=" + CHAT, "#chat=" + CHAT + "&x=1", null, undefined]) {
    assert.equal(chatIdFromHash(bad), null, String(bad));
  }
});

test("a chat's age reads in minutes, hours, yesterday, days, then a date", () => {
  const ago = (s) => NOON - s * 1000;
  assert.equal(relativeTime(ago(5), NOON), "just now");
  assert.equal(relativeTime(ago(120), NOON), "2 min");
  assert.equal(relativeTime(ago(3600 * 3), NOON), "3 h");
  assert.equal(relativeTime(ago(3600 * 30), NOON), "yesterday");
  assert.equal(relativeTime(ago(86400 * 3), NOON), "3 days");
  assert.equal(relativeTime(Date.parse("2026-09-01T08:00:00Z"), NOON), "2026-09-01");
  assert.equal(relativeTime(NOON + 5000, NOON), "just now", "a clock a little ahead is not negative");
});

test("a list entry shows its title, its age and what it spent", () => {
  const chat = (extra) => ({ id: CHAT, title: "We saw 185.220.101.133 beaconing", last_at: "2026-10-12T11:58:00Z",
    spend: { turns: 2, engine_calls: 6, prompt_tokens: 5100, completion_tokens: 900 }, ...extra });
  assert.deepEqual(chatListLabel(chat(), NOON), { title: "We saw 185.220.101.133 beaconing", meta: "2 min · 6 engine calls" });
  assert.deepEqual(chatListLabel(chat({ spend: { turns: 0, engine_calls: 0, prompt_tokens: null, completion_tokens: null } }), NOON),
    { title: "We saw 185.220.101.133 beaconing", meta: "2 min" }, "a chat the engine never ran says only its age");
  assert.equal(chatListLabel(chat({ title: "" }), NOON).title, "Untitled chat");
});

test("a ledger row reads like the live spend line, and missing usage is not a zero", () => {
  assert.equal(ledgerSpendText({ engine_calls: 4, prompt_tokens: 2800, completion_tokens: 300, ending: "stop" }),
    "4 engine calls · 3.1k tokens (2.8k in · 300 out)");
  assert.equal(ledgerSpendText({ engine_calls: 1, prompt_tokens: null, completion_tokens: null, ending: "endpoint_error" }),
    "1 engine call · tokens not reported");
  assert.equal(ledgerSpendText(null), null);
});

test("a turn with no answer says why, in words", () => {
  assert.equal(endingText("endpoint_error"), "No answer: the engine returned an error");
  assert.equal(endingText("output_guard"), "No answer: stopped by the platform's output check");
  assert.equal(endingText("usage_refused"), "No answer: the workspace's usage limit was reached");
  assert.equal(endingText("empty_answer"), "No answer: the engine returned none");
  assert.equal(endingText(null), "No answer was stored");
  assert.equal(endingText("toString"), "No answer was stored", "an inherited name is not an ending");
});

const turn = (extra) => ({ question: "check 8.8.8.8 and add a note", asked_at: "2026-10-12T11:00:00Z",
  answer: "## Verdict\nclean", spend: { engine_calls: 4, prompt_tokens: 2800, completion_tokens: 300, ending: "stop" },
  proposals: [], ...extra });
const filed = (id, status, extra = {}) => ({ id, action: "annotate_observable", summary: "add a note to 8.8.8.8",
  status, decided_at: null, claimed_at: null, result: { effects: null }, ...extra });

test("a reopened turn is its question, its answer, then what it spent", () => {
  assert.deepEqual(reopenedTurnPlan(turn(), NOON), [
    { kind: "question", text: "check 8.8.8.8 and add a note" },
    { kind: "answer", text: "## Verdict\nclean" },
    { kind: "spend", text: "4 engine calls · 3.1k tokens (2.8k in · 300 out)" },
  ]);
  assert.deepEqual(reopenedTurnPlan(turn({ spend: null }), NOON).map((p) => p.kind), ["question", "answer"],
    "a shortcut answer has no ledger row, so no spend line");
});

test("a reopened turn with no answer says why, and still shows what it spent", () => {
  assert.deepEqual(reopenedTurnPlan(turn({ answer: null,
    spend: { engine_calls: 2, prompt_tokens: null, completion_tokens: null, ending: "output_guard" } }), NOON), [
    { kind: "question", text: "check 8.8.8.8 and add a note" },
    { kind: "no-answer", text: "No answer: stopped by the platform's output check" },
    { kind: "spend", text: "2 engine calls · tokens not reported" },
  ]);
  assert.deepEqual(reopenedTurnPlan(turn({ answer: null, spend: null }), NOON)[1],
    { kind: "no-answer", text: "No answer was stored" });
});

test("a reopened turn's proposals carry their current status, worded as the panel words it", () => {
  const done = filed("11111111-0000-0000-0000-000000000000", "executed", { decided_at: "2026-10-12T11:00:00Z" });
  const waiting = filed("22222222-0000-0000-0000-000000000000", "pending_approval");
  assert.deepEqual(reopenedTurnPlan(turn({ proposals: [done, waiting] }), NOON).slice(3), [
    { kind: "proposal", id: done.id, text: "Proposal: add a note to 8.8.8.8 · Done" },
    { kind: "proposal", id: waiting.id, text: "Proposal: add a note to 8.8.8.8 · Waiting for your approval" },
  ]);
});

test("a stored answer is still text: HTML in it is never built as elements", () => {
  const stored = '<img src=x onerror="alert(1)"> and <script>steal()</script>';
  const [, answer] = reopenedTurnPlan(turn({ answer: stored }), NOON);
  assert.deepEqual(answer, { kind: "answer", text: stored });
  const nodes = markdownNodes(answer.text, h);
  assert.deepEqual(walk(nodes).map((n) => n.tag), ["p"]);
  assert.equal(textOf(nodes[0]), stored);
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `node --test --test-reporter=spec tests/js/page_logic.test.mjs`
Expected: FAIL: `ReferenceError: chatIdFromHash is not defined` (the `new Function` return cannot find the names).

- [ ] **Step 3: Add the functions** inside the `// <page-logic>` block, after `chatSpendText`, before `// </page-logic>`:

```js
    // -- A chat survives a reload (docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md).
    // The open chat's id lives in the URL hash, and only a UUID is one.
    const CHAT_HASH_RE = /^#chat=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;
    function chatIdFromHash(hash) {
      const m = CHAT_HASH_RE.exec(String(hash ?? ""));
      return m ? m[1].toLowerCase() : null;
    }

    // An age in words. "yesterday" is 24 to 48 hours ago, not a calendar day:
    // the page knows no time zone of the analyst's to be right about.
    function relativeTime(then, now) {
      const s = Math.max(0, Math.floor((now - then) / 1000));
      if (s < 60) return "just now";
      const min = Math.floor(s / 60);
      if (min < 60) return min + " min";
      const hrs = Math.floor(min / 60);
      if (hrs < 24) return hrs + " h";
      const days = Math.floor(hrs / 24);
      if (days < 2) return "yesterday";
      if (days < 7) return days + " days";
      return new Date(then).toISOString().slice(0, 10);
    }

    function chatListLabel(chat, now) {
      const age = relativeTime(Date.parse(chat.last_at), now);
      const n = chat.spend && chat.spend.engine_calls;
      return { title: chat.title || "Untitled chat", meta: n ? `${age} · ${calls(n)}` : age };
    }

    // A ledger row's line reads exactly as the live one (spendText).
    function ledgerSpendText(spend) {
      if (!spend) return null;
      const p = spend.prompt_tokens, c = spend.completion_tokens;
      const usage = p == null && c == null ? null
        : { prompt_tokens: p || 0, completion_tokens: c || 0, total_tokens: (p || 0) + (c || 0) };
      return spendText({ path: "ledger", engine_calls: spend.engine_calls, usage });
    }

    const ENDING_COPY = {
      endpoint_error: "No answer: the engine returned an error",
      output_guard: "No answer: stopped by the platform's output check",
      usage_refused: "No answer: the workspace's usage limit was reached",
      empty_answer: "No answer: the engine returned none",
    };
    function endingText(ending) {
      return Object.hasOwn(ENDING_COPY, ending ?? "") ? ENDING_COPY[ending] : "No answer was stored";
    }

    // What a reopened turn renders, in order. Reasoning and tool lines were
    // never stored (the chat says so once, above its turns); proposals come
    // back with their CURRENT status, in the panel's own words.
    function reopenedTurnPlan(turn, now) {
      const parts = [{ kind: "question", text: String(turn.question) }];
      parts.push(turn.answer
        ? { kind: "answer", text: String(turn.answer) }
        : { kind: "no-answer", text: endingText(turn.spend && turn.spend.ending) });
      const spend = ledgerSpendText(turn.spend);
      if (spend) parts.push({ kind: "spend", text: spend });
      for (const p of turn.proposals || []) {
        parts.push({ kind: "proposal", id: String(p.id), text: `Proposal: ${p.summary || p.action} · ${statusText(p, now)}` });
      }
      return parts;
    }
```

- [ ] **Step 4: Run them to see them pass**

Run: `node --test --test-reporter=spec tests/js/page_logic.test.mjs`
Expected: `ℹ pass 41`, `ℹ fail 0`.

- [ ] **Step 5: Mutant — an unanchored hash**

Remove the `$` from `CHAT_HASH_RE`. Run the Node file. Expected: FAIL in "a chat id comes from the hash only when it is a UUID" (`#chat=<uuid>x`). Revert; re-run; expect `ℹ pass 41`.

- [ ] **Step 6: Raise the floor and commit**

In `tests/test_page_logic.py` change `>= 32` to `>= 41`. Run `.venv/bin/pytest tests/test_page_logic.py -q` → `1 passed`. (The README count is unchanged: the Node file is one pytest test.)

```bash
git add auspex/static/index.html tests/js/page_logic.test.mjs tests/test_page_logic.py
git commit -m "feat(page): what a reopened chat shows -- its id from the hash, list labels, ledger lines, endings in words, a turn's parts (41 Node tests)"
```

---

### Task 6: The sign-in survives a reload (D-056)

**Files:**
- Modify: `auspex/static/index.html` (CSS hidden rule; `#signout` in `.auth`; storage helpers, `signedIn`, `restoreSignIn`, `signOut` below `let sessionId = null;`; `signIn` body; listeners at the end)
- Modify: `tests/test_ui.py` (append)
- Modify: `TECHNICAL_DEBT.md` (TD-051 at the top)
- Modify: `README.md` (count)

**Interfaces:**
- Consumes: D-056 (Task 1).
- Produces: `signedIn()` (Task 7 extends it), `storedToken()`, `storeToken(t)`, `forgetToken()`, `restoreSignIn()`, `signOut()`; `#signout` button.

- [ ] **Step 1: Write the failing test** — append to `tests/test_ui.py`:

```python
def test_the_sign_in_is_kept_for_the_tab_only(client):
    """D-056: the token survives a reload in sessionStorage (never
    localStorage), is checked on load, and has a way out. Storage that throws
    must leave the page working, so the only storage calls are the three
    guarded helpers."""
    body = client.get("/").text
    assert "localStorage" not in body
    assert body.count("sessionStorage.") == 3
    for call in ("sessionStorage.getItem(TOKEN_KEY)", "sessionStorage.setItem(TOKEN_KEY, t)",
                 "sessionStorage.removeItem(TOKEN_KEY)"):
        assert f"try {{ {call}" in body or f"try {{ return {call}" in body, call
    assert "/api/auth/whoami" in body
    assert 'id="signout"' in body
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/pytest tests/test_ui.py -q -k kept_for_the_tab`
Expected: FAIL (`assert 0 == 3`).

- [ ] **Step 3: Wire it into the page.**

CSS: change `#approvals[hidden], .panel[hidden] { display: none; }` to `#approvals[hidden], #signout[hidden], .panel[hidden] { display: none; }`.

HTML: in `.auth`, after `<button id="signin" class="ghost">Sign in</button>`, add `<button id="signout" class="ghost" hidden>Sign out</button>`.

JS: right after `let sessionId = null;` add:

```js
    // D-056: the sign-in survives a reload in this tab, and dies with the tab.
    // Storage that is blocked or missing leaves the page as it was before F2.
    const TOKEN_KEY = "auspex.token";
    function storedToken() { try { return sessionStorage.getItem(TOKEN_KEY); } catch (e) { return null; } }
    function storeToken(t) { try { sessionStorage.setItem(TOKEN_KEY, t); } catch (e) { /* kept in memory only */ } }
    function forgetToken() { try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* nothing was kept */ } }
```

Replace the body of `signIn()` after `if (!r.ok) { ... }` so it reads:

```js
        token = (await r.json()).access_token;
        storeToken(token);
        signedIn();
      } catch (e) { setStatus("network error", "err"); }
    }

    // Everything a page does once it holds a token, whether it just signed in
    // or brought the sign-in back from this tab's storage.
    function signedIn() {
      setStatus("signed in", "ok");
      $("email").style.display = "none"; $("signin").style.display = "none";
      $("signout").hidden = false;
      $("prompt").disabled = false; $("send").disabled = false; $("prompt").focus();
      loadEndpoints();
      startApprovals();
    }

    async function restoreSignIn() {
      const t = storedToken();
      if (!t) return;
      setStatus("signing in…");
      try {
        const r = await fetch("/api/auth/whoami", { headers: { "Authorization": "Bearer " + t } });
        if (r.ok) { token = t; signedIn(); return; }
        if (r.status === 401) forgetToken();  // expired, or signed by a key that changed
        setStatus("not signed in");
      } catch (e) { setStatus("network error", "err"); }
    }

    function signOut() {
      forgetToken();
      history.replaceState(null, "", location.pathname + location.search);
      location.reload();
    }
```

(The removed lines are the old success path: `setStatus("signed in", "ok"); $("email")…; $("prompt")…; loadEndpoints(); startApprovals();` — they now live in `signedIn()`.)

At the end of the script, after the existing listeners, add:

```js
    $("signout").addEventListener("click", signOut);
    restoreSignIn();
```

- [ ] **Step 4: Run the UI tests**

Run: `.venv/bin/pytest tests/test_ui.py tests/test_page_logic.py -q`
Expected: all pass.

- [ ] **Step 5: Log TD-051** at the top of `TECHNICAL_DEBT.md`:

```markdown
## TD-051 (F2) — the page sends no Content-Security-Policy

**Where:** `auspex/routes/ui.py` serves `index.html` and `timeline.html` with
only `Cache-Control: no-cache`.
**Risk:** MEDIUM since D-056. The sign-in token now sits in the tab's
`sessionStorage`, readable by any script on the page. Nothing in the browser
stops an injected script; the one guard is D-053's rule that model and tool
text never become HTML.
**Why taken:** the pages run one inline script, so a useful CSP needs a nonce
per response or a hash per script, and every page edit would move the hash.
That belongs with moving the script into files.
**Path to fix:** with TD-045's split (scripts in their own files, served
`no-cache` like the pages), send `Content-Security-Policy: default-src 'self';
script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
font-src https://fonts.gstatic.com; connect-src 'self'` and pin it in
`tests/test_ui.py`.
**Trigger:** TD-045's split, any new HTML-rendering surface, or any finding of
script injection on the page.
```

- [ ] **Step 6: README count, then commit (two commits)**

Run: `.venv/bin/pytest --collect-only -q | tail -1` → expect `1340 tests collected`; update both README places.

```bash
git add auspex/static/index.html tests/test_ui.py README.md
git commit -m "feat(page): the sign-in survives a reload in the tab's sessionStorage, checked on load, with a Sign out (D-056) (1340 tests)"
git add TECHNICAL_DEBT.md
git commit -m "chore(debt): TD-051 -- the page sends no Content-Security-Policy, and D-056 puts the token where a script can read it"
```

---

### Task 7: The chat sidebar, the hash, and reopened chats on the page

**Files:**
- Modify: `auspex/static/index.html` (CSS; `#chats` nav and `#chats-toggle`; `<chats-dom>` section; `handleEvent`, `send`, `signedIn`, panel divider copy; listeners)
- Modify: `tests/test_ui.py` (append)
- Modify: `README.md` (count)

**Interfaces:**
- Consumes: Task 5's `chatIdFromHash`, `chatListLabel`, `reopenedTurnPlan`; Task 6's `signedIn`; existing `el`, `markdownNodes`, `addMsg`, `scroll`, `showChatSpend`, `setStatus`, `api`, `recordDecided`, `openApprovals`, `approvals`.
- Produces: `loadChats()`, `renderChats()`, `openChat(id)`, `newChat(note?)`, `reviewProposal(id)`, `setHash(id)`, `busy` flag.

- [ ] **Step 1: Write the failing test** — append to `tests/test_ui.py`:

```python
def test_index_lists_and_reopens_chats(client):
    """F2: the sidebar lists your chats and reopens one from its stored turns;
    the open chat's id lives in the hash; a reopened chat says what is not
    kept rather than showing an empty Thinking pane."""
    body = client.get("/").text
    assert 'id="chats"' in body and 'id="new-chat"' in body and 'id="chats-toggle"' in body
    assert '"/api/chat/sessions"' in body and '"/turns"' in body
    assert '"#chat="' in body
    assert "Reopened · answers and spend only; reasoning and tool steps aren't kept." in body
    assert "That chat is not available to you." in body
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/pytest tests/test_ui.py -q -k lists_and_reopens`
Expected: FAIL.

- [ ] **Step 3: CSS** — append before `</style>`:

```css
    /* The chat list (docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md). */
    .sidebar {
      position: fixed; top: 0; left: 0; bottom: 0; width: 260px; z-index: 11;
      background: var(--surface); border-right: 1px solid #1c2431; overflow-y: auto; padding: 16px;
      display: flex; flex-direction: column; gap: 10px;
    }
    .sidebar-head { display: flex; align-items: center; gap: 8px; }
    .sidebar-head .mark { flex: 1; }
    #new-chat { width: 100%; }
    .chat-item {
      display: block; width: 100%; text-align: left; background: transparent; color: var(--text);
      border: 1px solid transparent; border-radius: 8px; padding: 8px 10px; font-weight: 400;
    }
    .chat-item:hover:not(:disabled) { border-color: #232d3d; }
    .chat-item.current { border-color: var(--steel); }
    .chat-item .t { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13.5px; }
    .chat-item .m { display: block; color: var(--slate); font-family: var(--mono); font-size: 11.5px; }
    .reopened {
      color: var(--slate); font-size: 12px; text-transform: uppercase; letter-spacing: .8px;
      border-bottom: 1px solid #1c2431; padding-bottom: 6px; margin-bottom: 18px;
    }
    .noanswer { color: var(--slate); margin-top: 4px; }
    @media (min-width: 900px) {
      body { padding-left: 260px; }
      header .mark, #chats-toggle, #chats-close { display: none; }
    }
    @media (max-width: 899px) {
      .sidebar { display: none; }
      body.chats-open .sidebar { display: flex; }
    }
```

- [ ] **Step 4: HTML.** In `<header>`, before `<span class="mark">`, add `<button id="chats-toggle" class="ghost">Chats</button>`. Right after `<body>`, before `<header>`, add:

```html
  <nav id="chats" class="sidebar" aria-label="Chats">
    <div class="sidebar-head">
      <span class="mark">Auspex<span class="dot">.</span></span>
      <button id="chats-close" class="ghost">Close</button>
    </div>
    <button id="new-chat" class="ghost" disabled>+ New chat</button>
    <div id="chats-list"></div>
    <div id="chats-note" class="panel-note">Sign in to see your chats.</div>
  </nav>
```

- [ ] **Step 5: JS — the busy flag and the session frame.** After `let sessionId = null;` add `let busy = false;  // a turn is streaming: the chat cannot be switched under it`.

In `handleEvent`, change `if ("session" in ev) { sessionId = ev.session; }` to `if ("session" in ev) { sessionId = ev.session; setHash(sessionId); }`.

In `send()`: change `if (!text || !token) return;` to `if (!text || !token || busy) return;` and right after it add `busy = true; renderChats();`. In its `finally`, after `showChatSpend();` add `busy = false; loadChats();`.

In `signedIn()` (Task 6), after `startApprovals();` add:

```js
      $("new-chat").disabled = false;
      loadChats();
      const id = chatIdFromHash(location.hash);
      if (id) openChat(id);
```

In `renderApprovals()`, change the divider copy `"Decided this session"` to `"Decided"` (a card reviewed from a reopened chat may have been decided before this page loaded).

- [ ] **Step 6: JS — the chats section.** Insert before `// <approvals-dom>`:

```js
    // <chats-dom>
    // Thin: what an entry and a reopened turn show come from the page-logic
    // block; this builds elements from it and talks to /api/chat/sessions.
    // Every server string is text (D-053's builder for answers).
    const chats = { list: [], complete: true, failed: false };

    function setHash(id) {
      history.replaceState(null, "", id ? "#chat=" + id : location.pathname + location.search);
    }

    function authed(path) { return fetch(path, { headers: { "Authorization": "Bearer " + token } }); }

    async function loadChats() {
      try {
        const r = await authed("/api/chat/sessions");
        if (!r.ok) throw new Error(String(r.status));
        const body = await r.json();
        chats.list = body.sessions; chats.complete = body.complete; chats.failed = false;
      } catch (e) { chats.failed = true; }
      renderChats();
    }

    function renderChats() {
      const now = Date.now();
      $("chats-list").replaceChildren(...chats.list.map((c) => {
        const label = chatListLabel(c, now);
        const b = el("button", { className: c.id === sessionId ? "chat-item current" : "chat-item", disabled: busy, title: label.title },
          [el("span", { className: "t" }, [label.title]), el("span", { className: "m" }, [label.meta])]);
        b.addEventListener("click", () => openChat(c.id));
        return b;
      }));
      $("new-chat").disabled = busy || !token;
      $("chats-note").textContent = !token ? "Sign in to see your chats."
        : chats.failed ? "Couldn't load your chats."
        : !chats.list.length ? "No chats yet."
        : chats.complete ? "" : `Only the ${chats.list.length} most recent are listed.`;
    }

    function clearTranscript() { $("transcript").replaceChildren(); $("chat-spend").textContent = ""; }

    function newChat(note) {
      if (busy) return;
      sessionId = null;
      setHash(null);
      clearTranscript();
      if (note) $("transcript").appendChild(el("div", { className: "noanswer" }, [note]));
      document.body.classList.remove("chats-open");
      renderChats();
      $("prompt").focus();
    }

    async function openChat(id) {
      if (busy || !token) return;
      let r;
      try { r = await authed("/api/chat/sessions/" + encodeURIComponent(id) + "/turns"); }
      catch (e) { setStatus("network error", "err"); return; }
      if (r.status === 404) { newChat("That chat is not available to you."); return; }
      if (!r.ok) { setStatus("couldn't open that chat", "err"); return; }
      const { turns } = await r.json();
      sessionId = id;
      setHash(id);
      clearTranscript();
      $("transcript").appendChild(el("div", { className: "reopened" },
        ["Reopened · answers and spend only; reasoning and tool steps aren't kept."]));
      const now = Date.now();
      for (const turn of turns) renderReopenedTurn(reopenedTurnPlan(turn, now));
      document.body.classList.remove("chats-open");
      renderChats();
      showChatSpend();
      scroll();
    }

    function renderReopenedTurn(parts) {
      let wrap = null;
      for (const part of parts) {
        if (part.kind === "question") {
          addMsg("You", "user").appendChild(el("div", { className: "bubble" }, [part.text]));
          wrap = addMsg("Co-analyst", "assistant");
        } else if (part.kind === "answer") {
          wrap.appendChild(el("div", { className: "bubble md" }, markdownNodes(part.text, el)));
        } else if (part.kind === "no-answer") {
          wrap.appendChild(el("div", { className: "noanswer" }, [part.text]));
        } else if (part.kind === "spend") {
          wrap.appendChild(el("div", { className: "spend" }, [part.text]));
        } else if (part.kind === "proposal") {
          const review = el("button", { className: "ghost review" }, ["Review"]);
          review.addEventListener("click", () => reviewProposal(part.id));
          wrap.appendChild(el("div", { className: "proposal" }, [part.text, review]));
        }
      }
    }

    // A proposal from a reopened chat may be decided already, so the queue
    // does not hold it: fetch it into the decided list, where its doors are.
    async function reviewProposal(id) {
      if (!approvals.waiting.some((p) => p.id === id)) {
        const r = await api("/" + encodeURIComponent(id));
        if (r.ok && r.body && r.body.id) recordDecided(r.body);
      }
      openApprovals(id);
    }
    // </chats-dom>
```

- [ ] **Step 7: Listeners** — after the existing listeners (before Task 6's `restoreSignIn();`):

```js
    $("new-chat").addEventListener("click", () => newChat());
    $("chats-toggle").addEventListener("click", () => document.body.classList.toggle("chats-open"));
    $("chats-close").addEventListener("click", () => document.body.classList.remove("chats-open"));
    // A hash pasted into this tab's address bar opens that chat without a reload.
    window.addEventListener("hashchange", () => {
      const id = chatIdFromHash(location.hash);
      if (id && id !== sessionId) openChat(id);
    });
```

- [ ] **Step 8: Run the page's tests**

Run: `.venv/bin/pytest tests/test_ui.py tests/test_page_logic.py -q`
Expected: all pass (including the existing "no `innerHTML` takes a variable" pin: nothing in this task uses `innerHTML`).

- [ ] **Step 9: README count, then commit**

Run: `.venv/bin/pytest --collect-only -q | tail -1` → expect `1341 tests collected`; update both README places.

```bash
git add auspex/static/index.html tests/test_ui.py README.md
git commit -m "feat(page): an always-on chat list, the open chat in the URL hash, and reopened chats with their spend and proposals' doors (1341 tests)"
```

---

### Task 8: Prove it — the full gate, then live in a real browser

**Files:**
- Create: `docs/probes/2026-10-12-f2-chat-reload-live.md`

**Interfaces:**
- Consumes: everything above, in the rebuilt container.
- Produces: the live record.

- [ ] **Step 1: Full gate.** Run `./ci.sh > <scratchpad>/ci-f2.log 2>&1; echo $?` (never piped into `tail`). Expected: `0`, `All checks passed!`, `1341 passed`. A red test in a file this plan did not touch is still this plan's to fix.

- [ ] **Step 2: Rebuild the app.** `docker compose up -d --build app`, then poll `/api/health/ready` until 200.

- [ ] **Step 3: Live, in headless Chromium (Playwright) against `http://localhost:8000`, signed in as `fe-probe@auspex.dev`.** Do not run pytest during these steps. Record each result:
  1. Send `check 8.8.8.8` (a shortcut, no inference). Note the hash is `#chat=<uuid>`. Reload: still signed in, the chat is back under the divider, the sidebar lists it.
  2. Send one deep turn on Standard (`What is the difference between T1059.001 and T1059.003? Answer briefly.`; one to a few Z.ai calls). Reload: its answer renders as markdown, its spend line matches the live one, and the chat total matches.
  3. Send the F1 note prompt on a fresh routable IP (`We saw 185.220.101.141 beaconing every 60s from fin-ws-12 since Tuesday. Check it, and add a note to it saying it was seen beaconing from fin-ws-12.`). Approve the proposal in the panel (two clicks). Reload. The reopened turn shows `Proposal: … · Done [Review]`; Review opens the panel with the card under "Decided" and an **Undo** door. Undo it (two clicks) → `Undone`.
  4. In the same tab: sign out, sign in as `fe-probe-2@auspex.dev`, then put the first user's `#chat=<uuid>` in the address bar: the note `That chat is not available to you.` and an empty chat.
  5. Plant a bad token (`sessionStorage.setItem("auspex.token", "x")`) and reload: sign-in is shown, status "not signed in", and the key is gone.
  6. During a deep turn, click another chat and **+ New chat**: both are disabled; nothing switches.
  7. Resize to 390 px wide: the sidebar is hidden, **Chats** opens it as an overlay, picking a chat closes it.
  8. Hygiene: the proposal from step 3 is undone; delete only the observable step 3 recorded (`185.220.101.141`) if the probe created it; delete the two probe users.

- [ ] **Step 4: Write the record** `docs/probes/2026-10-12-f2-chat-reload-live.md`: date, container build, endpoint per turn, each step's observed result (pass/fail, with the exact text seen), the inference calls spent, and anything fixed during the run (each fix is its own commit with its own test, and the gate is re-run).

- [ ] **Step 5: Commit**

```bash
git add docs/probes/2026-10-12-f2-chat-reload-live.md
git commit -m "probe(f2): a chat survives a reload, live -- reload keeps chat and sign-in, a reopened proposal's Undo works, a foreign hash is refused"
```
