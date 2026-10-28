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


def _thinking_seen(where: str, fields: dict) -> list[tuple[str, str]]:
    """What the client makes of `fields` on a message or on a stream delta."""
    if where == "message":
        got = LLMClient.parse_completion({"choices": [{"message": {"content": "x", **fields}}]})
        return [("reasoning", got.reasoning)] if got.reasoning else []
    events = parse_sse_line("data: " + json.dumps({"choices": [{"delta": fields}]}))
    return [(e.kind, e.text) for e in events if e.kind == "reasoning"]


@pytest.mark.parametrize("where", ["message", "delta"])
def test_an_endpoint_sending_both_spellings_is_not_counted_twice(where):
    """Defensive: no probe has seen both spellings on one message, but summing
    them would double every thinking token the analyst sees if one ever did."""
    both = {"reasoning": "think once", "reasoning_content": "think once"}
    assert _thinking_seen(where, both) == [("reasoning", "think once")]


@pytest.mark.parametrize("where", ["message", "delta"])
@pytest.mark.parametrize("empty", [None, ""])
def test_a_present_but_empty_spelling_does_not_hide_the_other(where, empty):
    """vLLM writes `"reasoning": null` on every completion
    (tests/fixtures/llm/northflank/chat_basic.json:16). A reader that picks the
    first key PRESENT rather than the first value non-empty would return that
    null and drop a `reasoning_content` thought sitting right beside it."""
    fields = {"reasoning": empty, "reasoning_content": "thought"}
    assert _thinking_seen(where, fields) == [("reasoning", "thought")]


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
    # The DIRECTION of the advice, not just its keywords: a note that said
    # "drop the /v1" would mention LLM_BASE_URL and the API root too.
    assert "LLM_BASE_URL must be the API root" in detail
    assert "ending in /v1" in detail


@pytest.mark.parametrize("status", [401, 500, 503])
async def test_a_failure_that_is_not_a_404_is_reported_as_itself(status):
    """The reverse boundary of the 404 hint. A scaled-to-zero edge (503,
    docs/probes/2026-07-14-llm-endpoint.md) or a bad key (401) on a CORRECT
    root must not send the operator to change a URL that is already right."""
    seen: list[str] = []
    client = _recording_client("http://localhost:11434/v1", seen, status=status)
    ok, detail = await client.check_reachable()
    await client.aclose()

    assert seen == ["GET /v1/models"]
    assert ok is False
    assert detail.startswith(f"status {status}") and "not here" in detail
    assert "LLM_BASE_URL" not in detail


# -- TD-040: what an endpoint error says to the analyst ------------------------


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (0, "could not be reached"),
        (400, "rejected the request"),
        (401, "refused the platform's credentials"),
        (429, "is busy"),
        (503, "failed"),
    ],
)
def test_an_endpoint_error_has_a_public_sentence_that_never_quotes_the_provider(status, kind):
    """The provider's own error body can name the model and the provider. The
    analyst is told the class of failure in the platform's words, and the body
    stays with the exception for the server's own use."""
    body = "model glm-4.5-air not found on zhipu; see z.ai console"
    err = LLMError(status, body)

    assert kind in err.public
    assert "glm" not in err.public.lower() and "z.ai" not in err.public.lower()
    assert body in str(err)  # still there for whoever handles the exception


def test_the_provider_error_code_is_kept_for_the_log():
    """A code (Z.ai's 1113 balance, 1302 rate limit) tells an operator what is
    wrong without logging the message, which may echo the request."""
    err = _extract_error(429, "application/json",
                         '{"error": {"code": "1302", "message": "rate limit for glm"}}')

    assert (err.status, err.code) == (429, "1302")


def _b017() -> dict:
    path = Path(__file__).parent / "fixtures" / "llm" / "b017_malformed_tool_calls.json"
    return json.loads(path.read_text())


def test_a_non_string_tool_name_parses_as_text_not_a_crash():
    """B-017: the endpoint is the customer's; a list where a name belongs becomes its
    JSON text, which no tool is called, so the loop answers "unknown tool"."""
    call = LLMClient.parse_completion(_b017()["completion"]).tool_calls[0]
    assert call.name == '["lookup_ip"]'
    assert isinstance(call.arguments, str)


async def test_a_streamed_tool_call_with_object_fields_parses_as_text():
    """B-017: an object-valued `arguments` (and a numeric id) once raised in the fold."""
    line = "data: " + json.dumps(_b017()["stream_chunk"])

    async def events():
        for event in parse_sse_line(line):
            yield event

    call = (await accumulate_stream(events())).tool_calls[0]
    assert (call.id, call.name) == ("7", '["lookup_ip"]')
    assert json.loads(call.arguments) == {"ip": "203.0.113.9"}


@pytest.mark.parametrize("entry", ["lookup_ip", {"id": "c1", "function": "lookup_ip"}, None])
def test_a_tool_call_that_is_not_an_object_parses_as_an_empty_call(entry):
    """B-017's class: the call, or its `function`, is not an object at all."""
    body = {"choices": [{"message": {"tool_calls": [entry]}, "finish_reason": "tool_calls"}]}
    call = LLMClient.parse_completion(body).tool_calls[0]
    assert (call.name, call.arguments) == ("", "")


@pytest.mark.parametrize("deltas", [
    [{"tool_calls": "abc"}],
    [{"tool_calls": [None, 1, "abc"]}],
    [{"tool_calls": [{"index": [1], "function": {"name": "x"}}]}],
    [{"tool_calls": [{"index": 0, "function": {"name": "a"}}]},
     {"tool_calls": [{"index": None, "function": {"name": "b"}}]},
     {"tool_calls": [{"index": "1", "function": {"name": "c"}}]}],
], ids=["not-a-list", "not-objects", "list-index", "mixed-index"])
async def test_a_streamed_tool_call_list_in_any_shape_never_crashes_the_fold(deltas):
    """B-017's class, the streaming side (its review): the call list or a call's
    `index` in a shape the wire does not promise is read, not raised on."""
    lines = ["data: " + json.dumps({"choices": [{"delta": d}]}) for d in deltas]

    async def events():
        for line in lines:
            for event in parse_sse_line(line):
                yield event

    result = await accumulate_stream(events())
    assert all(isinstance(c.name, str) for c in result.tool_calls)


async def test_a_numeric_string_index_keeps_two_parallel_calls_apart():
    """Burhan's review of PR #50: `"1"` folded to call 0, so two parallel calls
    merged (names overwrote, arguments concatenated). An index that parses as an
    int is that int; only what does not parse folds into call 0."""
    deltas = [{"tool_calls": [{"index": "0", "id": "a", "function": {"name": "lookup_ip",
                                                                       "arguments": "{}"}}]},
              {"tool_calls": [{"index": "1", "id": "b", "function": {"name": "lookup_domain",
                                                                       "arguments": "{}"}}]}]
    lines = ["data: " + json.dumps({"choices": [{"delta": d}]}) for d in deltas]

    async def events():
        for line in lines:
            for event in parse_sse_line(line):
                yield event

    calls = (await accumulate_stream(events())).tool_calls
    assert [(c.id, c.name, c.arguments) for c in calls] == [
        ("a", "lookup_ip", "{}"), ("b", "lookup_domain", "{}")]
