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
import logging
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auspex.auth import AuthContext, resolve_user
from auspex.classify import Category, classify, shortcut_answer
from auspex.classify.observables import ObservableType
from auspex.config import Settings
from auspex.enrich import EnrichmentService, persist_enrichment, render_ioc_answer
from auspex.kb import (
    DEFINITION_MISS_COPY,
    KB_UNAVAILABLE_COPY,
    MAX_IDS_PER_LOOKUP,
    KBUnavailable,
    KnowledgeService,
    render_cve_answer,
    render_definition_answer,
)
from auspex.llm.client import LLMClient, LLMError, Usage
from auspex.llm.registry import DevEndpoint
from auspex.llm.scorecard import load_latest_scorecard

logger = logging.getLogger("auspex.chat")

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
    """The endpoint a turn will run against + whether it reasons natively."""

    client: LLMClient
    native_reasoning: bool
    id: str = "default"


class ChatEndpointResolver:
    """Lazy half of endpoint resolution. Cheap validation happens in the
    dependency (unknown dev endpoint_id → 404); the expensive parts — the
    scorecard read and the LLMClient (httpx) construction — happen in
    `resolve()`, which only DEEP turns call. The 92% shortcut path never pays
    for a client it would immediately close."""

    def __init__(self, *, configured: bool, factory=None):
        self.configured = configured
        self._factory = factory  # async () -> ChatEndpoint; None ⇒ unconfigured

    async def resolve(self) -> ChatEndpoint:
        if self._factory is None:
            raise HTTPException(status_code=503, detail="LLM endpoint not configured")
        return await self._factory()

    @classmethod
    def fixed(cls, endpoint: ChatEndpoint) -> "ChatEndpointResolver":
        """A resolver that always yields `endpoint` (the test seam's shape)."""

        async def _factory() -> ChatEndpoint:
            return endpoint

        return cls(configured=True, factory=_factory)

    @classmethod
    def unconfigured(cls) -> "ChatEndpointResolver":
        return cls(configured=False)


class ChatBody(BaseModel):
    # max_length bounds the synchronous classify/extract pass (and storage) —
    # the handler runs regex extraction over this text inside the event loop.
    message: str = Field(min_length=1, max_length=32_000)
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


async def get_endpoint_resolver(request: Request, auth: Auth) -> ChatEndpointResolver:
    """Decide which endpoint this turn WOULD use (the overridable test seam).
    A dev-only `endpoint_id` selects a registry endpoint (unknown id → 404,
    even on shortcut turns — bad params fail fast); otherwise the configured
    default. Unconfigured is not an error yet: shortcut turns never need a
    model, so the 503 fires only when a DEEP turn calls resolve()."""
    settings = _settings(request)
    body = await request.json()
    endpoint_id = body.get("endpoint_id") if isinstance(body, dict) else None
    selected = select_dev_endpoint(
        request.app.state.dev_llm_registry, settings.app_env, endpoint_id
    )
    if selected is not None:
        entry = selected

        async def _dev_factory() -> ChatEndpoint:
            return ChatEndpoint(entry.build_client(), entry.native_reasoning, entry.id)

        return ChatEndpointResolver(configured=True, factory=_dev_factory)
    if not settings.llm_base_url:
        return ChatEndpointResolver.unconfigured()

    async def _default_factory() -> ChatEndpoint:
        native = await _default_native_reasoning(request, auth)
        return ChatEndpoint(LLMClient.from_settings(settings), native, "default")

    return ChatEndpointResolver(configured=True, factory=_default_factory)


async def _insert_message(
    pool: asyncpg.Pool, auth: AuthContext, session_id: UUID, role: str, content: str
) -> None:
    await pool.execute(
        "INSERT INTO messages (workspace_id, session_id, role, content) VALUES ($1, $2, $3, $4)",
        auth.workspace_id,
        session_id,
        role,
        content,
    )


def _sse_response(stream) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _ensure_session(pool: asyncpg.Pool, auth: AuthContext, session_id: UUID | None) -> UUID:
    """Resolve an existing session (must belong to this workspace+user) or create
    one. The workspace+user predicate is the tenant-isolation guard."""
    if session_id is not None:
        owned = await pool.fetchval(
            "SELECT id FROM chat_sessions WHERE id = $1 AND workspace_id = $2 AND user_id = $3",
            session_id,
            auth.workspace_id,
            auth.user_id,
        )
        if owned is None:
            raise HTTPException(status_code=404, detail="Chat session not found")
        return session_id
    return await pool.fetchval(
        "INSERT INTO chat_sessions (workspace_id, user_id) VALUES ($1, $2) RETURNING id",
        auth.workspace_id,
        auth.user_id,
    )


async def _history(pool: asyncpg.Pool, auth: AuthContext, session_id: UUID) -> list[dict]:
    """System prompt + the session's prior turns (oldest first). Reasoning is not
    persisted, so replayed history is content-only — exactly what the model needs."""
    rows = await pool.fetch(
        "SELECT role, content FROM messages"
        " WHERE workspace_id = $1 AND session_id = $2 ORDER BY created_at",
        auth.workspace_id,
        session_id,
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
    resolver: Annotated[ChatEndpointResolver, Depends(get_endpoint_resolver)],
) -> StreamingResponse:
    pool: asyncpg.Pool = request.app.state.pool
    # 92/8 gate (S4): code picks the path before the model is ever touched.
    classification = classify(body.message)
    shortcut = shortcut_answer(classification)
    if shortcut is None and not resolver.configured:
        raise HTTPException(status_code=503, detail="LLM endpoint not configured")
    session_id = await _ensure_session(pool, auth, body.session_id)
    await _insert_message(pool, auth, session_id, "user", body.message)

    if shortcut is not None:
        # Shortcut path: LLM-free always. ioc_check turns additionally run the
        # S5 enrichment fan-out; cve_lookup/definition turns consult the S6
        # knowledge base (code fetches, code renders). When a service is
        # inactive the static deferred copy stands; when it's active but down,
        # distinct honest copy says so — three different truths, three strings.
        answer_text = shortcut.text
        enrichment: EnrichmentService = request.app.state.enrichment
        kb: KnowledgeService = request.app.state.kb
        if shortcut.category is Category.CVE_LOOKUP and kb.active:
            cve_ids = list(
                dict.fromkeys(
                    o.value for o in classification.observables if o.type is ObservableType.CVE
                )
            )
            # Cap per turn (bool-clause limit + shared breaker, S6 review) and
            # size the fetch to the request — the default top_k (8 chunks)
            # rendered CVEs past it as false "not in the knowledge base" misses.
            requested = cve_ids[:MAX_IDS_PER_LOOKUP]
            try:
                answer_text = render_cve_answer(
                    requested,
                    await kb.lookup_ids(tuple(requested), top_k=max(8, 4 * len(requested))),
                    omitted=len(cve_ids) - len(requested),
                )
            except KBUnavailable as err:
                answer_text = KB_UNAVAILABLE_COPY.format(detail=err.public)
        elif shortcut.category is Category.DEFINITION and kb.active:
            try:
                # Definitions come from curated concept/technique/tactic docs,
                # never CVE record chunks. The filter is also load-bearing for
                # retrieval recall at corpus scale (see KnowledgeService.search).
                rendered = render_definition_answer(
                    await kb.search(body.message, doc_types=("concept", "technique", "tactic"))
                )
                # A connected-but-ignorant KB is a miss, not "deferred" — the
                # static deferred copy would claim the KB isn't connected.
                answer_text = rendered if rendered is not None else DEFINITION_MISS_COPY
            except KBUnavailable as err:
                answer_text = KB_UNAVAILABLE_COPY.format(detail=err.public)
        if (
            shortcut.category is Category.IOC_CHECK
            and enrichment.active
            and classification.observables
        ):
            outcome = await enrichment.enrich(classification.observables)
            # A persistence hiccup must not 500 away a fully-computed answer;
            # the copy then says the results were NOT recorded (D-014 — never
            # claim storage that didn't happen). S5 review finding.
            recorded = True
            try:
                await persist_enrichment(pool, auth.workspace_id, outcome)
            except Exception:
                logger.exception("verdict persistence failed; streaming unrecorded results")
                recorded = False
            answer_text = render_ioc_answer(outcome, recorded=recorded)
        await _insert_message(pool, auth, session_id, "assistant", answer_text)

        async def shortcut_stream():
            yield _sse({"session": str(session_id)})
            yield _sse({"content": answer_text})
            yield _sse({"done": {"finish_reason": "stop", "usage": None, "path": "shortcut"}})

        return _sse_response(shortcut_stream())

    messages = await _history(pool, auth, session_id)
    # Build the client as late as possible: everything that can 404/fail above
    # has already run, so the only closer needed is event_stream's finally.
    endpoint = await resolver.resolve()

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
                    max_tokens=CHAT_REASONING_MAX_TOKENS,
                    temperature=0,
                ):
                    if ev.kind == "content":
                        analysis_parts.append(ev.text)
                        yield _sse({"reasoning": ev.text})
                analysis = "".join(analysis_parts).strip()
                # pass 2 = the answer, grounded in the private analysis → content.
                async for ev in endpoint.client.chat_stream(
                    [*messages, {"role": "system", "content": _pass2_directive(analysis)}],
                    max_tokens=CHAT_ANSWER_MAX_TOKENS,
                    temperature=0,
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
            await _insert_message(pool, auth, session_id, "assistant", answer)
        yield _sse({"done": {"finish_reason": finish_reason, "usage": usage, "path": "model"}})

    return _sse_response(event_stream())
