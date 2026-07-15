"""SSE chat endpoint (/api/chat) — S3 step 4.

Single-key JSON event protocol over `text/event-stream`: every frame is
`data: {"<type>": <payload>}` with exactly one key. Types:

  {"session": "<uuid>"}                       first frame — the session id
  {"reasoning": "<delta>"}                    thinking models only (separate field)
  {"content": "<delta>"}                      answer tokens
  {"done": {"finish_reason","usage"}}         terminal, on success
  {"error": "<message>"}                      terminal, on endpoint failure

v1 streams a single conversational turn (no tools — the design input says
conversational turns get none; `tools=None` passes cleanly). The multi-step
tool loop (auspex.agent.loop) streaming its tool/proposal events over this same
protocol is the next increment (IDEAS.md). Auth is the standard `resolve_user`
chokepoint; the session is workspace+user scoped (tenant isolation).
"""

import json
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auspex.auth import AuthContext, resolve_user
from auspex.config import Settings
from auspex.llm.capability import PROBE_MAX_TOKENS
from auspex.llm.client import LLMClient, LLMError

router = APIRouter(prefix="/api", tags=["chat"])

Auth = Annotated[AuthContext, Depends(resolve_user)]

CHAT_SYSTEM_PROMPT = (
    "You are Auspex, a calm, precise security operations co-analyst. Answer "
    "concisely and analyst-to-analyst. If you are unsure, say so."
)


def get_llm_client(request: Request) -> LLMClient:
    """Per-request client, overridable in tests via dependency_overrides."""
    settings: Settings = request.app.state.settings
    if not settings.llm_base_url:
        raise HTTPException(status_code=503, detail="LLM endpoint not configured")
    return LLMClient.from_settings(settings)


class ChatBody(BaseModel):
    message: str = Field(min_length=1)
    session_id: UUID | None = None


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _ensure_session(
    pool: asyncpg.Pool, auth: AuthContext, session_id: UUID | None
) -> UUID:
    """Resolve an existing session (must belong to this workspace+user) or create
    one. The workspace+user predicate is the tenant-isolation guard."""
    if session_id is not None:
        owned = await pool.fetchval(
            "SELECT id FROM chat_sessions WHERE id = $1 AND workspace_id = $2 AND user_id = $3",
            session_id, auth.workspace_id, auth.user_id,
        )
        if owned is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        return session_id
    return await pool.fetchval(
        "INSERT INTO chat_sessions (workspace_id, user_id) VALUES ($1, $2) RETURNING id",
        auth.workspace_id, auth.user_id,
    )


async def _history(pool: asyncpg.Pool, auth: AuthContext, session_id: UUID) -> list[dict]:
    """System prompt + the session's prior turns (oldest first). Reasoning is not
    persisted, so replayed history is content-only — exactly what the model needs."""
    rows = await pool.fetch(
        "SELECT role, content FROM messages"
        " WHERE workspace_id = $1 AND session_id = $2 ORDER BY created_at",
        auth.workspace_id, session_id,
    )
    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    messages.extend({"role": r["role"], "content": r["content"]} for r in rows)
    return messages


@router.post("/chat")
async def chat(
    request: Request,
    body: ChatBody,
    auth: Auth,
    client: Annotated[LLMClient, Depends(get_llm_client)],
) -> StreamingResponse:
    pool: asyncpg.Pool = request.app.state.pool
    session_id = await _ensure_session(pool, auth, body.session_id)
    await pool.execute(
        "INSERT INTO messages (workspace_id, session_id, role, content)"
        " VALUES ($1, $2, 'user', $3)",
        auth.workspace_id, session_id, body.message,
    )
    messages = await _history(pool, auth, session_id)

    async def event_stream():
        yield _sse({"session": str(session_id)})
        content_parts: list[str] = []
        finish_reason = None
        usage = None
        try:
            async for ev in client.chat_stream(
                messages, max_tokens=PROBE_MAX_TOKENS, temperature=0
            ):
                if ev.kind == "reasoning":
                    yield _sse({"reasoning": ev.text})
                elif ev.kind == "content":
                    content_parts.append(ev.text)
                    yield _sse({"content": ev.text})
                elif ev.kind == "finish":
                    finish_reason = ev.finish_reason
                elif ev.kind == "usage" and ev.usage:
                    usage = {
                        "prompt_tokens": ev.usage.prompt_tokens,
                        "completion_tokens": ev.usage.completion_tokens,
                        "total_tokens": ev.usage.total_tokens,
                    }
        except LLMError as err:
            # Endpoint failure: report it, persist nothing as the assistant turn.
            yield _sse({"error": str(err)})
            return
        finally:
            await client.aclose()

        answer = "".join(content_parts)
        if answer:
            await pool.execute(
                "INSERT INTO messages (workspace_id, session_id, role, content)"
                " VALUES ($1, $2, 'assistant', $3)",
                auth.workspace_id, session_id, answer,
            )
        yield _sse({"done": {"finish_reason": finish_reason, "usage": usage}})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
