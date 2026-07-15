"""Client parsing vs SAVED probe fixtures (tests/fixtures/llm/ollama/) — offline.

Every wire shape asserted here was captured live on 2026-07-15
(docs/probes/2026-07-15-ollama-endpoint.md). No network in pytest.
"""

import json
from pathlib import Path

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


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


async def as_stream(events: list[StreamEvent]):
    for event in events:
        yield event


def events_from_sse_fixture(name: str) -> list[StreamEvent]:
    events = []
    for line in (FIXTURES / name).read_text().splitlines():
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
