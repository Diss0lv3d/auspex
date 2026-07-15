"""SSE /api/chat endpoint tests (S3 step 4) — hermetic, fake streaming client."""

import asyncio
import json

import asyncpg
from _fakes import StreamingFakeLLMClient

from auspex.llm.client import LLMUnreachable, StreamEvent, Usage
from auspex.routes.chat import get_llm_client

CHAT_EMAIL = "analyst@auspex.dev"


def _token(client) -> str:
    resp = client.post("/api/auth/dev-login", json={"email": CHAT_EMAIL})
    return resp.json()["access_token"]


def _frames(body: str) -> list[dict]:
    """Parse SSE `data: {json}` frames into a list of single-key event dicts."""
    out = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            out.append(json.loads(line[len("data:"):].strip()))
    return out


def _override(app, fake):
    app.dependency_overrides[get_llm_client] = lambda: fake


def test_chat_requires_auth(client):
    resp = client.post("/api/chat", json={"message": "hello"})
    assert resp.status_code == 401


def test_chat_streams_reasoning_then_content_and_persists(client, settings):
    fake = StreamingFakeLLMClient([
        StreamEvent(kind="reasoning", text="Let me think. "),
        StreamEvent(kind="reasoning", text="Simple greeting."),
        StreamEvent(kind="content", text="Hello"),
        StreamEvent(kind="content", text=", analyst."),
        StreamEvent(kind="finish", finish_reason="stop"),
        StreamEvent(kind="usage",
                    usage=Usage(prompt_tokens=10, completion_tokens=4, total_tokens=14)),
    ])
    _override(client.app, fake)
    try:
        resp = client.post(
            "/api/chat", json={"message": "hi"},
            headers={"Authorization": f"Bearer {_token(client)}"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        frames = _frames(resp.text)
        kinds = [next(iter(f)) for f in frames]

        # protocol: session first, a terminal done last
        assert kinds[0] == "session"
        assert kinds[-1] == "done"
        # reasoning arrives and is streamed before any content (thinking model shape)
        assert "reasoning" in kinds and "content" in kinds
        assert kinds.index("reasoning") < kinds.index("content")

        content = "".join(f["content"] for f in frames if "content" in f)
        assert content == "Hello, analyst."
        reasoning = "".join(f["reasoning"] for f in frames if "reasoning" in f)
        assert reasoning == "Let me think. Simple greeting."

        done = frames[-1]["done"]
        assert done["finish_reason"] == "stop"
        assert done["usage"]["total_tokens"] == 14
        assert fake.closed is True  # client lifecycle closed after the stream

        session_id = frames[0]["session"]
    finally:
        client.app.dependency_overrides.clear()

    # the answer was persisted as an assistant message; reasoning was NOT persisted
    async def _check():
        conn = await asyncpg.connect(settings.database_url)
        try:
            rows = await conn.fetch(
                "SELECT role, content FROM messages"
                " WHERE session_id = $1::uuid ORDER BY created_at",
                session_id,
            )
            return [(r["role"], r["content"]) for r in rows]
        finally:
            await conn.close()

    persisted = asyncio.run(_check())
    assert ("user", "hi") in persisted
    assert ("assistant", "Hello, analyst.") in persisted
    assert all("Let me think" not in c for _, c in persisted)  # reasoning is ephemeral


def test_chat_reuses_session_and_rejects_foreign_session(client):
    token = _token(client)
    fake = StreamingFakeLLMClient([
        StreamEvent(kind="content", text="ok"),
        StreamEvent(kind="finish", finish_reason="stop"),
    ])
    _override(client.app, fake)
    try:
        first = client.post("/api/chat", json={"message": "one"},
                            headers={"Authorization": f"Bearer {token}"})
        session_id = _frames(first.text)[0]["session"]

        # reusing the same session id continues it (200)
        fake2 = StreamingFakeLLMClient([
            StreamEvent(kind="content", text="two"),
            StreamEvent(kind="finish", finish_reason="stop"),
        ])
        _override(client.app, fake2)
        second = client.post(
            "/api/chat", json={"message": "again", "session_id": session_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 200
        # the model saw the prior turns replayed as history (system + 3 prior msgs + none new-yet)
        replayed_roles = [m["role"] for m in fake2.stream_calls[0]["messages"]]
        assert replayed_roles[0] == "system"
        assert "assistant" in replayed_roles  # prior answer threaded back in

        # a random/foreign session id is rejected
        bogus = client.post(
            "/api/chat",
            json={"message": "x", "session_id": "00000000-0000-0000-0000-0000000000ff"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert bogus.status_code == 404
    finally:
        client.app.dependency_overrides.clear()


def test_chat_emits_error_event_on_unreachable_endpoint(client):
    fake = StreamingFakeLLMClient(
        [StreamEvent(kind="content", text="part")],
        raise_error=LLMUnreachable("transport: ConnectError"),
    )
    _override(client.app, fake)
    try:
        resp = client.post("/api/chat", json={"message": "hi"},
                           headers={"Authorization": f"Bearer {_token(client)}"})
        assert resp.status_code == 200  # stream opened, error is in-band
        frames = _frames(resp.text)
        kinds = [next(iter(f)) for f in frames]
        assert kinds[-1] == "error"
        assert "done" not in kinds  # no successful completion
        assert fake.closed is True
    finally:
        client.app.dependency_overrides.clear()
