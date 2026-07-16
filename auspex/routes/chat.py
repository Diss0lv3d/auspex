"""SSE chat (/api/chat) + dev model list (/api/models) — S3 step 4, D-016, S4 92/8.

Single-key JSON event protocol over `text/event-stream`; every frame has exactly
one key: `session` / `reasoning` / `content` / `done` / `error`.

The 92/8 split (S4 step 4): every turn is classified in code BEFORE the model
is touched. Shortcut categories (greeting/identity/ioc_check/cve_lookup/
definition) stream a deterministic answer with zero LLM calls — the `done`
frame says which path ran (`"path": "shortcut" | "model"`). Only DEEP turns
reach the endpoint; with no endpoint configured, shortcut turns still work.

Reasoning is universal + customer-facing (D-016 feature 1): if the resolved
endpoint emits native reasoning it is streamed; if not, a TWO-PASS fallback
generates a brief analyst pre-pass (streamed as `reasoning`) then the answer
(streamed as `content`). It is presented as the platform reasoning — never the
model's, never "unsupported". Both passes use the same (customer) endpoint, so
D-005 holds (we never pay for inference).

The model switcher (`endpoint_id` + /api/models) is INTERNAL/dev-only (D-016
feature 2): honored only when APP_ENV=dev, invisible + inert in prod, per the
org policy that multi-LLM / BYO-LLM stays internal infrastructure.
"""

import json
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auspex.auth import AuthContext, resolve_user
from auspex.classify import classify, shortcut_answer
from auspex.config import Settings
from auspex.llm.client import LLMClient, LLMError, Usage
from auspex.llm.registry import DevEndpoint
from auspex.llm.scorecard import load_latest_scorecard

router = APIRouter(prefix="/api", tags=["chat"])

Auth = Annotated[AuthContext, Depends(resolve_user)]

CHAT_SYSTEM_PROMPT = (
    "You are Auspex, a calm, precise security operations co-analyst. Answer "
    "concisely and analyst-to-analyst. If you are unsure, say so."
)

# Token budgets (previously reused PROBE_MAX_TOKENS — a smell). Answer cap keeps
# the prior value; the reasoning pre-pass is deliberately brief (probe 2026-07-16
# showed Scout uses ~100 tokens for a good analyst brief).
CHAT_ANSWER_MAX_TOKENS = 2000
CHAT_REASONING_MAX_TOKENS = 256

# Two-pass reasoning directives (probe-verified on real Scout, docs/probes/
# 2026-07-16-two-pass-scout.md — appended as trailing system messages).
PASS1_DIRECTIVE = (
    "Before answering, think as a security analyst. In 2-4 short sentences, lay "
    "out your read of the question, the key factors, and any caveats or unknowns. "
    "This is your private working analysis — do not write the final answer yet."
)


def _pass2_directive(analysis: str) -> str:
    return (
        f"Your private analysis: «{analysis}». Now give the final answer to the "
        "analyst — concise, precise, analyst-to-analyst. Do not restate the "
        "analysis or mention that you reasoned in steps. If you are unsure, say so."
    )


@dataclass
class ChatEndpoint:
    """The endpoint a turn will run against + whether it reasons natively.

    `client is None` means no endpoint is configured: shortcut turns still
    answer (the 92% path is LLM-free); a DEEP turn 503s in the handler."""

    client: LLMClient | None
    native_reasoning: bool
    id: str = "default"


class ChatBody(BaseModel):
    message: str = Field(min_length=1)
    session_id: UUID | None = None
    endpoint_id: str | None = None  # dev-only model switch; ignored in prod


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _usage_dict(usage: Usage) -> dict:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def select_dev_endpoint(
    registry: dict[str, DevEndpoint], app_env: str, endpoint_id: str | None
) -> DevEndpoint | None:
    """Resolve a dev endpoint override. Returns None (⇒ use the default) unless
    APP_ENV=dev and a non-default `endpoint_id` is given; an unknown id in dev is
    a 404. In prod this always returns None — the switcher is inert (D-005)."""
    if not endpoint_id or endpoint_id == "default" or app_env != "dev":
        return None
    entry = registry.get(endpoint_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown endpoint")
    return entry


async def _default_native_reasoning(request: Request, auth: AuthContext) -> bool:
    """Whether the configured default endpoint emits native reasoning, from its
    persisted scorecard. Unknown ⇒ False (safe default = two-pass fallback)."""
    settings = _settings(request)
    loaded = await load_latest_scorecard(
        request.app.state.pool, auth.workspace_id, settings.llm_base_url, settings.llm_model
    )
    return bool(loaded and loaded[0].native_reasoning)


async def get_chat_endpoint(request: Request, auth: Auth) -> ChatEndpoint:
    """Resolve the endpoint for this turn (the overridable test seam). A dev-only
    `endpoint_id` selects a registry endpoint; otherwise the configured default."""
    settings = _settings(request)
    body = await request.json()
    endpoint_id = body.get("endpoint_id") if isinstance(body, dict) else None
    selected = select_dev_endpoint(
        request.app.state.dev_llm_registry, settings.app_env, endpoint_id
    )
    if selected is not None:
        return ChatEndpoint(selected.build_client(), selected.native_reasoning, selected.id)
    if not settings.llm_base_url:
        # Unconfigured is not an error yet — shortcut turns never need a model.
        # The handler 503s only when a DEEP turn actually asks for one.
        return ChatEndpoint(None, False, "default")
    native = await _default_native_reasoning(request, auth)
    return ChatEndpoint(LLMClient.from_settings(settings), native, "default")


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


@router.get("/models")
async def list_models(request: Request, auth: Auth) -> dict:
    """Dev-only: list selectable endpoints for the internal switcher. Returns
    id/label/capability flags ONLY — never base_url/model/keys. 404 in prod."""
    settings = _settings(request)
    if settings.app_env != "dev":
        raise HTTPException(status_code=404, detail="Not found")
    endpoints = [
        {
            "id": "default",
            "label": "Standard",
            "capabilities": {"native_reasoning": await _default_native_reasoning(request, auth)},
        }
    ]
    for entry in request.app.state.dev_llm_registry.values():
        endpoints.append(
            {
                "id": entry.id,
                "label": entry.label,
                "capabilities": {"native_reasoning": entry.native_reasoning},
            }
        )
    return {"default": "default", "endpoints": endpoints}


@router.post("/chat")
async def chat(
    request: Request,
    body: ChatBody,
    auth: Auth,
    endpoint: Annotated[ChatEndpoint, Depends(get_chat_endpoint)],
) -> StreamingResponse:
    pool: asyncpg.Pool = request.app.state.pool
    # 92/8 gate (S4): code picks the path before the model is ever touched.
    shortcut = shortcut_answer(classify(body.message))
    if shortcut is None and endpoint.client is None:
        raise HTTPException(status_code=503, detail="LLM endpoint not configured")
    session_id = await _ensure_session(pool, auth, body.session_id)
    await pool.execute(
        "INSERT INTO messages (workspace_id, session_id, role, content)"
        " VALUES ($1, $2, 'user', $3)",
        auth.workspace_id, session_id, body.message,
    )

    if shortcut is not None:
        # Shortcut path: deterministic answer, zero LLM calls. The client built
        # by the dependency (if any) is never used — release it.
        if endpoint.client is not None:
            await endpoint.client.aclose()
        await pool.execute(
            "INSERT INTO messages (workspace_id, session_id, role, content)"
            " VALUES ($1, $2, 'assistant', $3)",
            auth.workspace_id, session_id, shortcut.text,
        )

        async def shortcut_stream():
            yield _sse({"session": str(session_id)})
            yield _sse({"content": shortcut.text})
            yield _sse({"done": {"finish_reason": "stop", "usage": None, "path": "shortcut"}})

        return StreamingResponse(
            shortcut_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    messages = await _history(pool, auth, session_id)

    async def event_stream():
        yield _sse({"session": str(session_id)})
        content_parts: list[str] = []
        finish_reason = None
        usage = None
        try:
            if endpoint.native_reasoning:
                # Native path: one call; reasoning + content stream on their own fields.
                async for ev in endpoint.client.chat_stream(
                    messages, max_tokens=CHAT_ANSWER_MAX_TOKENS, temperature=0
                ):
                    if ev.kind == "reasoning":
                        yield _sse({"reasoning": ev.text})
                    elif ev.kind == "content":
                        content_parts.append(ev.text)
                        yield _sse({"content": ev.text})
                    elif ev.kind == "finish":
                        finish_reason = ev.finish_reason
                    elif ev.kind == "usage" and ev.usage:
                        usage = _usage_dict(ev.usage)
            else:
                # Two-pass fallback: pass 1 = brief analyst reasoning → Thinking pane.
                analysis_parts: list[str] = []
                async for ev in endpoint.client.chat_stream(
                    [*messages, {"role": "system", "content": PASS1_DIRECTIVE}],
                    max_tokens=CHAT_REASONING_MAX_TOKENS, temperature=0,
                ):
                    if ev.kind == "content":
                        analysis_parts.append(ev.text)
                        yield _sse({"reasoning": ev.text})
                analysis = "".join(analysis_parts).strip()
                # pass 2 = the answer, grounded in the private analysis → content.
                async for ev in endpoint.client.chat_stream(
                    [*messages, {"role": "system", "content": _pass2_directive(analysis)}],
                    max_tokens=CHAT_ANSWER_MAX_TOKENS, temperature=0,
                ):
                    if ev.kind == "content":
                        content_parts.append(ev.text)
                        yield _sse({"content": ev.text})
                    elif ev.kind == "finish":
                        finish_reason = ev.finish_reason
                    elif ev.kind == "usage" and ev.usage:
                        usage = _usage_dict(ev.usage)
        except LLMError as err:
            # Endpoint failure: report it, persist nothing as the assistant turn.
            yield _sse({"error": str(err)})
            return
        finally:
            await endpoint.client.aclose()

        answer = "".join(content_parts)
        if answer:
            await pool.execute(
                "INSERT INTO messages (workspace_id, session_id, role, content)"
                " VALUES ($1, $2, 'assistant', $3)",
                auth.workspace_id, session_id, answer,
            )
        yield _sse({"done": {"finish_reason": finish_reason, "usage": usage, "path": "model"}})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
