"""Client parsing vs SAVED probe fixtures (tests/fixtures/llm/ollama/) — offline.

Every wire shape asserted here was captured live on 2026-07-15
(docs/probes/2026-07-15-ollama-endpoint.md). No network in pytest.
"""

import json
from pathlib import Path

import httpx
import pytest

from auspex.llm.client import (
    LLMClient,
    LLMError,
    StreamEvent,
    _extract_error,
    accumulate_stream,
    parse_sse_line,
)

FIXTURES = Path(__file__).parent / "fixtures" / "llm" / "ollama"
FIXTURES_VLLM = Path(__file__).parent / "fixtures" / "llm" / "northflank"
# Live Z.ai responses, 2026-10-10 (docs/probes/2026-10-10-zai-endpoint.md); the
# stream is trimmed to its first 3 reasoning chunks, verbatim otherwise.
FIXTURES_ZAI = Path(__file__).parent / "fixtures" / "llm" / "zai"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


async def as_stream(events: list[StreamEvent]):
    for event in events:
        yield event


def events_from_sse_fixture(name: str, base: Path = FIXTURES) -> list[StreamEvent]:
    events = []
    for line in (base / name).read_text().splitlines():
        events.extend(parse_sse_line(line))
    return events


# -- non-streaming ----------------------------------------------------------


def test_parse_basic_completion():
    result = LLMClient.parse_completion(load("chat_basic.json"))
    assert result.content == "pong"
    assert result.finish_reason == "stop"
    assert result.tool_calls == []
    assert result.usage and result.usage.completion_tokens > 0


def test_parse_tool_call_completion():
    result = LLMClient.parse_completion(load("chat_tools.json"))
    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.name == "get_weather"
    assert call.id.startswith("call_")
    args = call.parse_arguments()  # arguments arrive as a JSON string
    assert args["city"] == "Riyadh"


def test_parse_parallel_tool_calls():
    result = LLMClient.parse_completion(load("chat_tools_parallel.json"))
    assert [c.name for c in result.tool_calls] == ["get_weather", "lookup_ip"]
    assert result.tool_calls[1].parse_arguments() == {"ip": "8.8.8.8"}


def test_malformed_arguments_raise_value_error():
    result = LLMClient.parse_completion(load("chat_tools.json"))
    call = result.tool_calls[0]
    call.arguments = '{"city": '  # truncated — the harness scores this invalid
    with pytest.raises(ValueError):
        call.parse_arguments()


# -- streaming --------------------------------------------------------------


async def test_stream_fixture_content_accumulates():
    events = events_from_sse_fixture("chat_stream.sse.txt")
    result = await accumulate_stream(as_stream(events))
    assert "1" in result.content and "5" in result.content
    assert result.finish_reason == "stop"
    # include_usage rides a final chunk with empty choices (probe finding 9)
    assert result.usage is not None and result.usage.completion_tokens > 0


async def test_stream_fixture_tool_calls_accumulate_by_index():
    events = events_from_sse_fixture("chat_tools_stream.sse.txt")
    result = await accumulate_stream(as_stream(events))
    assert result.finish_reason == "tool_calls"
    assert [c.name for c in result.tool_calls] == ["get_weather", "lookup_ip"]
    assert result.tool_calls[0].parse_arguments()["city"] == "Riyadh"
    assert all(c.id for c in result.tool_calls)


async def test_vllm_fragmented_stream_fixture_accumulates():
    """REAL vLLM stream (Northflank, 2026-07-15): arguments fragmented across
    ~9 deltas, id null on continuation chunks — the wire style the synthetic
    test below models. This is the live capture."""
    events = events_from_sse_fixture("chat_tools_stream.sse.txt", base=FIXTURES_VLLM)
    result = await accumulate_stream(as_stream(events))
    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.name == "get_weather"
    assert call.id.startswith("chatcmpl-tool-")
    assert call.parse_arguments() == {"city": "Riyadh", "unit": "celsius"}
    assert result.usage is not None


async def test_fragmented_arguments_accumulate():
    """vLLM/OpenAI style: name first, arguments split across deltas (the Ollama
    fixture sends them whole — the accumulator must handle BOTH)."""
    fragments = [
        {"index": 0, "id": "call_x", "type": "function",
         "function": {"name": "get_weather", "arguments": ""}},
        {"index": 0, "function": {"arguments": '{"city": "Ri'}},
        {"index": 0, "function": {"arguments": 'yadh"}'}},
    ]
    lines = [
        "data: " + json.dumps(
            {"choices": [{"index": 0, "delta": {"tool_calls": [frag]}, "finish_reason": None}]}
        )
        for frag in fragments
    ]
    lines.append('data: {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}')
    lines.append("data: [DONE]")
    events = [e for line in lines for e in parse_sse_line(line)]
    result = await accumulate_stream(as_stream(events))
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_x"
    assert result.tool_calls[0].parse_arguments() == {"city": "Riyadh"}


def test_sse_parser_tolerates_noise():
    assert parse_sse_line("") == []
    assert parse_sse_line(": comment") == []
    assert parse_sse_line("data: [DONE]") == []
    assert parse_sse_line("data: {not json") == []


def test_reasoning_field_captured_and_kept_out_of_content():
    """Thinking models emit a separate `reasoning` field (message + deltas) —
    content stays clean AND reasoning is captured on its own field (qwen3 fixture)."""
    result = LLMClient.parse_completion(load("chat_reasoning.json"))
    assert result.content == "pong"
    assert "reasoning" not in result.content
    assert result.reasoning.startswith("Okay")  # captured, not dropped
    assert "pong" not in result.reasoning or result.reasoning != result.content


async def test_reasoning_stream_content_stays_clean_and_reasoning_accumulates():
    events = events_from_sse_fixture("chat_reasoning_stream.sse.txt")
    result = await accumulate_stream(as_stream(events))
    assert result.content == "pong"
    assert result.reasoning.startswith("Okay")  # reasoning deltas folded separately
    assert result.finish_reason == "stop"
    assert result.usage is not None


def test_reasoning_content_spelling_is_captured_and_kept_out_of_content():
    """Z.ai (and DeepSeek, older vLLM) spell the thinking field `reasoning_content`.
    Read only `reasoning` and a thinking model reads as one that does not think —
    the scorecard records native_reasoning False, the chat route pays for a
    two-pass fallback, and the model's own thinking tokens are billed anyway
    (116 of 117 completion tokens on this fixture)."""
    body = json.loads((FIXTURES_ZAI / "chat_reasoning.json").read_text())
    raw = body["choices"][0]["message"]["reasoning_content"]
    assert raw and "reasoning" not in body["choices"][0]["message"]  # the input IS the case

    result = LLMClient.parse_completion(body)
    assert result.content == "pong"
    assert result.reasoning == raw  # all of it, not a prefix
    assert raw not in result.content


async def test_reasoning_content_stream_folds_onto_the_reasoning_channel():
    lines = (FIXTURES_ZAI / "chat_reasoning_stream.sse.txt").read_text().splitlines()
    sent = "".join(
        json.loads(ln[5:])["choices"][0]["delta"].get("reasoning_content") or ""
        for ln in lines if ln.startswith("data:") and ln[5:].strip() != "[DONE]"
    )
    assert len(sent) >= 3  # floor: three reasoning chunks are in the fixture

    result = await accumulate_stream(as_stream(events_from_sse_fixture(
        "chat_reasoning_stream.sse.txt", FIXTURES_ZAI)))
    assert result.reasoning == sent
    assert result.content.split() == ["1", "2", "3", "4", "5"]
    # Z.ai puts usage on the SAME chunk as finish_reason; both must survive.
    assert result.finish_reason == "stop"
    assert result.usage is not None and result.usage.completion_tokens == 415


@pytest.mark.parametrize("where", ["message", "delta"])
def test_an_endpoint_sending_both_spellings_is_not_counted_twice(where):
    """vLLM emitted both fields with the same text during its rename. Summing the
    two would double every thinking token the analyst sees."""
    both = {"reasoning": "think once", "reasoning_content": "think once"}
    if where == "message":
        got = LLMClient.parse_completion({"choices": [{"message": {"content": "x", **both}}]})
        assert got.reasoning == "think once"
    else:
        events = parse_sse_line("data: " + json.dumps({"choices": [{"delta": both}]}))
        assert [(e.kind, e.text) for e in events] == [("reasoning", "think once")]


# -- errors (Finding 0: bodies may be JSON envelopes OR raw text) ------------


def test_error_envelope_message_extracted():
    body = (FIXTURES / "error_bad_model.json").read_text()
    err = _extract_error(404, "application/json", body)
    assert isinstance(err, LLMError)
    assert err.status == 404
    assert "not found" in str(err)


def test_error_text_plain_survives():
    body = "upstream connect error or disconnect/reset before headers"
    err = _extract_error(503, "text/plain", body)
    assert err.status == 503
    assert "upstream connect error" in str(err)


def test_error_json_content_type_with_garbage_body():
    err = _extract_error(500, "application/json", "<html>oops</html>")
    assert err.status == 500  # must not raise while parsing


# -- the base URL is the provider's documented API root (D-033) --------------


def _recording_client(base_url: str, seen: list[str], status: int = 200) -> LLMClient:
    """An LLMClient whose transport records every request path instead of
    sending it. Bodies are the minimum each operation parses."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if status != 200:
            return httpx.Response(status, text="not here")
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": []})
        if b'"stream":true' in request.content.replace(b" ", b""):
            sse = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, text=sse)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = LLMClient(base_url, "m")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.parametrize(
    ("base_url", "root"),
    [
        # Z.ai's general API: the root has no /v1, and a /v1 inserted under it
        # is a live 404 while GET .../v1/models is a live 200 — a liveness check
        # that passes for an endpoint chat cannot reach
        # (docs/probes/2026-10-10-zai-endpoint.md).
        ("https://api.z.ai/api/paas/v4", "/api/paas/v4"),
        ("https://api.z.ai/api/paas/v4/", "/api/paas/v4"),  # as the provider's SDK page prints it
        ("http://localhost:11434/v1", "/v1"),  # Ollama / vLLM / OpenAI-style roots
    ],
)
async def test_every_operation_appends_to_the_documented_root_and_nothing_else(base_url, root):
    seen: list[str] = []
    client = _recording_client(base_url, seen)
    ok, _ = await client.check_reachable()
    await client.chat([{"role": "user", "content": "hi"}])
    await accumulate_stream(client.chat_stream([{"role": "user", "content": "hi"}]))
    await client.aclose()

    assert ok is True
    # Arithmetic floor: three operations, three requests — an assertion over
    # an empty list would pass with the client never called.
    assert seen == [
        f"GET {root}/models",
        f"POST {root}/chat/completions",
        f"POST {root}/chat/completions",
    ]


async def test_a_404_at_the_root_names_the_likely_misconfiguration():
    """A pre-D-033 value (`http://host:11434`, no /v1) now 404s at /models. A bare
    "status 404" reads like the endpoint is down; the note must say what to fix."""
    seen: list[str] = []
    client = _recording_client("http://localhost:11434", seen, status=404)
    ok, detail = await client.check_reachable()
    await client.aclose()

    assert seen == ["GET /models"]
    assert ok is False
    assert "LLM_BASE_URL" in detail and "API root" in detail
