"""Async OpenAI-compatible chat client (S2).

Coded against reality snapshots, not memory (CLAUDE.md rule 4):
- docs/probes/2026-07-15-ollama-endpoint.md  (+ fixtures in tests/fixtures/llm/ollama/)
- docs/probes/2026-07-14-llm-endpoint.md     (Finding 0: error bodies may be text/plain)
- docs/probes/2026-10-10-zai-endpoint.md      (a provider whose API root is not `/v1`)

`base_url` is the API root EXACTLY as the provider documents it for the OpenAI
SDK — `https://api.openai.com/v1`, `https://api.z.ai/api/paas/v4`,
`http://localhost:11434/v1` — and only the operation (`/chat/completions`,
`/models`) is appended here (D-033). Nothing in this module may assume a
version segment: the customer brings the endpoint, so its path is theirs.

Wire facts the parsing below relies on (probe findings 3, 7, 8, 9, 11):
- tool_calls carry `arguments` as a JSON string; streamed deltas are keyed by
  `index` and may arrive complete-in-one-chunk (Ollama) or fragmented across
  chunks (vLLM/OpenAI) — we accumulate by index and append argument fragments.
- SSE frames are `data: <json>` lines terminated by `data: [DONE]`; with
  stream_options.include_usage the usage rides a final chunk with empty choices.
- Error bodies are usually {"error": {"message": ...}} but NEVER guaranteed
  JSON (edge proxies return text/plain) — parse defensively.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from auspex.config import Settings


class LLMError(Exception):
    """HTTP-level failure from the endpoint. Message is best-effort extracted."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(f"LLM endpoint error {status}: {message}")


class LLMUnreachable(LLMError):
    """Endpoint not reachable at transport level (or edge 5xx). Normal state for
    scale-to-zero customer endpoints — callers should degrade, not crash."""

    def __init__(self, detail: str):
        super().__init__(status=0, message=detail)


@dataclass
class ToolCall:
    id: str = ""
    name: str = ""
    arguments: str = ""  # raw JSON string, per OpenAI convention (probe finding 3)

    def parse_arguments(self) -> dict[str, Any]:
        """Raises ValueError on malformed JSON — callers decide how to score it."""
        parsed = json.loads(self.arguments or "{}")
        if not isinstance(parsed, dict):
            raise ValueError(f"tool arguments not an object: {type(parsed).__name__}")
        return parsed


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatResult:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage | None = None
    reasoning: str = ""  # thinking models: separate from content (probe 2026-07-15)


@dataclass
class StreamEvent:
    """One parsed streaming delta.
    kind: 'content' | 'reasoning' | 'tool_call' | 'finish' | 'usage'."""

    kind: str
    text: str = ""  # kind == 'content' or 'reasoning'
    tool_index: int = 0  # kind == 'tool_call'
    tool_delta: dict[str, Any] | None = None  # kind == 'tool_call': raw tool_calls[] entry
    finish_reason: str | None = None  # kind == 'finish'
    usage: Usage | None = None  # kind == 'usage'


def tool_spec(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """The OpenAI function-tool envelope — the only tool shape the wire accepts."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def _extract_error(status: int, content_type: str, text: str) -> LLMError:
    """Finding 0: error bodies may be JSON envelopes or raw text — never assume."""
    message = text.strip()[:500]
    if "json" in content_type:
        try:
            envelope = json.loads(text)
            message = str((envelope.get("error") or {}).get("message") or message)
        except ValueError:
            pass
    return LLMError(status, message)


def _usage_from(chunk: dict[str, Any]) -> Usage | None:
    u = chunk.get("usage")
    if not u:
        return None
    return Usage(
        prompt_tokens=u.get("prompt_tokens", 0),
        completion_tokens=u.get("completion_tokens", 0),
        total_tokens=u.get("total_tokens", 0),
    )


class LLMClient:
    """One instance per endpoint. Async httpx; close with `aclose()` or use as
    an async context manager."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 120.0,
    ):
        if not base_url:
            raise ValueError("LLM base_url is required (LLM_BASE_URL)")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._http = httpx.AsyncClient(headers=headers, timeout=timeout)

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMClient":
        return cls(settings.llm_base_url, settings.llm_model, settings.llm_api_key)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- reachability ------------------------------------------------------

    async def check_reachable(self) -> tuple[bool, str]:
        """GET {base_url}/models — the same root chat uses, so a pass here means
        chat's URL is right too. A sleeping/scaled-to-zero endpoint is a normal
        state (2026-07-14 probe) — report, don't raise."""
        try:
            r = await self._http.get(f"{self.base_url}/models", timeout=10.0)
        except httpx.HTTPError as err:
            return False, f"transport: {err.__class__.__name__}"
        if r.status_code == 404:
            # The likeliest cause is a base URL missing its documented API root
            # (`http://host:11434` instead of `http://host:11434/v1`). Say so —
            # a bare 404 reads like the endpoint is down.
            return False, (
                "status 404 — LLM_BASE_URL must be the API root the provider "
                "documents for OpenAI-compatible clients (often ending in /v1)"
            )
        if r.status_code != 200:
            return False, f"status {r.status_code}: {r.text[:200]}"
        return True, "ok"

    # -- non-streaming -----------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        body = self._build_body(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            r = await self._http.post(f"{self.base_url}/chat/completions", json=body)
        except httpx.HTTPError as err:
            raise LLMUnreachable(f"transport: {err.__class__.__name__}") from err
        if r.status_code >= 400:
            raise _extract_error(r.status_code, r.headers.get("content-type", ""), r.text)
        try:
            data = r.json()
        except ValueError as err:  # 200 with junk body — treat as endpoint fault
            raise LLMError(r.status_code, f"non-JSON success body: {r.text[:200]}") from err
        return self.parse_completion(data)

    @staticmethod
    def parse_completion(data: dict[str, Any]) -> ChatResult:
        """Parse a non-streaming completion body (probe finding 2/3)."""
        choices = data.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        tool_calls = [
            ToolCall(
                id=tc.get("id", ""),
                name=(tc.get("function") or {}).get("name", ""),
                arguments=(tc.get("function") or {}).get("arguments", ""),
            )
            for tc in (message.get("tool_calls") or [])
        ]
        return ChatResult(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            finish_reason=choices[0].get("finish_reason") if choices else None,
            usage=_usage_from(data),
            reasoning=message.get("reasoning") or "",  # thinking models only
        )

    # -- streaming ---------------------------------------------------------

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Yields StreamEvents; use `accumulate_stream` to fold into a ChatResult."""
        body = self._build_body(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        try:
            async with self._http.stream(
                "POST", f"{self.base_url}/chat/completions", json=body
            ) as r:
                if r.status_code >= 400:
                    text = (await r.aread()).decode("utf-8", "replace")
                    raise _extract_error(r.status_code, r.headers.get("content-type", ""), text)
                async for line in r.aiter_lines():
                    for event in parse_sse_line(line):
                        yield event
        except httpx.HTTPError as err:
            raise LLMUnreachable(f"transport: {err.__class__.__name__}") from err

    def _build_body(self, messages: list[dict[str, Any]], **options: Any) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        for key, value in options.items():
            if value is not None:
                body[key] = value
        return body


def parse_sse_line(line: str) -> list[StreamEvent]:
    """Parse one SSE line into 0..n StreamEvents (probe findings 7-9).

    Pure function so pytest can drive it straight from saved fixtures.
    """
    line = line.strip()
    if not line or not line.startswith("data:"):
        return []
    payload = line[len("data:") :].strip()
    if payload == "[DONE]":
        return []
    try:
        chunk = json.loads(payload)
    except ValueError:
        return []  # tolerate mid-stream garbage rather than kill the stream

    events: list[StreamEvent] = []
    choices = chunk.get("choices") or []
    if choices:
        delta = choices[0].get("delta") or {}
        if delta.get("content"):
            events.append(StreamEvent(kind="content", text=delta["content"]))
        if delta.get("reasoning"):  # thinking models stream reasoning on its own field
            events.append(StreamEvent(kind="reasoning", text=delta["reasoning"]))
        for tc in delta.get("tool_calls") or []:
            events.append(
                StreamEvent(kind="tool_call", tool_index=tc.get("index", 0), tool_delta=tc)
            )
        if choices[0].get("finish_reason"):
            events.append(StreamEvent(kind="finish", finish_reason=choices[0]["finish_reason"]))
    usage = _usage_from(chunk)
    if usage:  # rides a chunk with empty choices when include_usage is set
        events.append(StreamEvent(kind="usage", usage=usage))
    return events


def fold_stream_event(
    result: ChatResult, calls: dict[int, ToolCall], event: StreamEvent
) -> None:
    """Fold ONE StreamEvent into an in-progress ChatResult, in place.

    Tool-call deltas accumulate BY INDEX: id/name are set when present,
    `arguments` fragments are APPENDED — this handles both complete-per-chunk
    (Ollama, finding 8) and fragmented-arguments (vLLM/OpenAI) styles. One IP
    address was measured arriving as NINE fragments split mid-token (D-031
    decision 2), so nothing may parse `arguments` until the stream ends.

    Split out so a caller that must act on deltas AS THEY ARRIVE (the streaming
    agent turn, which narrates tool steps and streams the answer) folds them
    with exactly this code rather than a second opinion about fragment
    assembly. `result.tool_calls` is only meaningful once the stream is done —
    call `seal_stream_result` then.
    """
    if event.kind == "content":
        result.content += event.text
    elif event.kind == "reasoning":
        result.reasoning += event.text
    elif event.kind == "tool_call":
        tc_delta = event.tool_delta or {}
        call = calls.setdefault(event.tool_index, ToolCall())
        if tc_delta.get("id"):
            call.id = tc_delta["id"]
        fn = tc_delta.get("function") or {}
        if fn.get("name"):
            call.name = fn["name"]
        if fn.get("arguments"):
            call.arguments += fn["arguments"]
    elif event.kind == "finish":
        result.finish_reason = event.finish_reason
    elif event.kind == "usage":
        result.usage = event.usage


def seal_stream_result(result: ChatResult, calls: dict[int, ToolCall]) -> ChatResult:
    """Attach the accumulated tool calls, in wire order, once the stream ends."""
    result.tool_calls = [calls[i] for i in sorted(calls)]
    return result


async def accumulate_stream(events: AsyncIterator[StreamEvent]) -> ChatResult:
    """Fold a StreamEvent stream into a ChatResult."""
    result = ChatResult()
    calls: dict[int, ToolCall] = {}
    async for event in events:
        fold_stream_event(result, calls, event)
    return seal_stream_result(result, calls)
