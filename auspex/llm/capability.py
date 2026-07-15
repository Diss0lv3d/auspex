"""Connect-time capability battery (D-005).

Probes what the endpoint ACTUALLY does — every scorecard field is set from an
executed request, never assumed. Endpoint-agnostic: only OpenAI-compatible
surface is used (wire shapes per docs/probes/2026-07-15-ollama-endpoint.md).
Failures demote gracefully into notes; a dead endpoint yields
reachable=False → plan_only.
"""

import json
import time

from auspex.llm.client import ChatResult, LLMClient, LLMError, accumulate_stream
from auspex.llm.scorecard import CapabilityScorecard

# Generous cap on every probe: thinking models spend hundreds of `reasoning`
# tokens before any content/tool call — a tight cap silently zeroes their
# capabilities (learned from the qwen3:14b run). Non-thinking models stop
# naturally long before this. Throughput keeps its own fixed budget.
_PROBE_MAX_TOKENS = 2000

_PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city"],
        },
    },
}
_PROBE_TOOL_2 = {
    "type": "function",
    "function": {
        "name": "lookup_ip",
        "description": "Look up reputation info for an IPv4 address.",
        "parameters": {
            "type": "object",
            "properties": {"ip": {"type": "string"}},
            "required": ["ip"],
        },
    },
}
_VERDICT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "verdict",
        "schema": {
            "type": "object",
            "properties": {
                "observable": {"type": "string"},
                "verdict": {"type": "string", "enum": ["benign", "suspicious", "malicious"]},
                "confidence": {"type": "number"},
            },
            "required": ["observable", "verdict", "confidence"],
        },
    },
}
_ADHERENCE_PROMPTS = [
    "Give a threat verdict for the domain example.test.",
    "Verdict for IP 10.0.0.1 (internal address seen beaconing).",
    "Verdict for a file hash seen once in 90 days.",
    "Verdict for a TOR exit node IP.",
    "Verdict for a CDN edge IP with no detections.",
]


def _adheres(result: ChatResult) -> bool:
    try:
        obj = json.loads(result.content)
    except ValueError:
        return False
    return (
        isinstance(obj, dict)
        and set(obj) >= {"observable", "verdict", "confidence"}
        and obj.get("verdict") in ("benign", "suspicious", "malicious")
    )


async def probe_capabilities(
    client: LLMClient, *, max_context_hint: int | None = None
) -> CapabilityScorecard:
    """Fill a CapabilityScorecard from live probes. ~15 requests, temperature 0.

    max_context_hint: callers with provider-specific knowledge (e.g. a value
    from a native metadata API) may pass the context length; the OpenAI surface
    itself does not expose it uniformly.
    """
    sc = CapabilityScorecard(base_url=client.base_url, model=client.model)
    sc.max_context_tokens = max_context_hint

    ok, detail = await client.check_reachable()
    sc.reachable = ok
    if not ok:
        sc.notes.append(f"unreachable: {detail}")
        return sc

    async def attempt(name: str, coro):
        try:
            return await coro
        except (LLMError, ValueError) as err:
            sc.notes.append(f"{name}: {err}")
            return None

    # basic chat sanity (also warms the model for the timing probe)
    basic = await attempt(
        "basic_chat",
        client.chat([{"role": "user", "content": "Reply with exactly: pong"}],
                    max_tokens=_PROBE_MAX_TOKENS, temperature=0),
    )
    if basic is None:
        sc.notes.append("basic chat failed — endpoint reachable but not usable")
        return sc

    # native tool calling
    tool_messages = [{"role": "user", "content": "What's the weather in Riyadh in celsius?"}]
    result = await attempt(
        "native_tools",
        client.chat(tool_messages, tools=[_PROBE_TOOL],
                    max_tokens=_PROBE_MAX_TOKENS, temperature=0),
    )
    if result and result.tool_calls:
        call = result.tool_calls[0]
        try:
            sc.native_tool_calling = call.name == "get_weather" and "city" in call.parse_arguments()
        except ValueError:
            sc.notes.append("native_tools: tool call emitted but arguments are malformed JSON")

    # parallel tool calls
    result = await attempt(
        "parallel_tools",
        client.chat(
            [{"role": "user", "content": "Check the weather in Riyadh (celsius) AND look up"
                                         " the IP 8.8.8.8. Do both now."}],
            tools=[_PROBE_TOOL, _PROBE_TOOL_2],
            max_tokens=_PROBE_MAX_TOKENS,
            temperature=0,
        ),
    )
    sc.parallel_tool_calls = bool(result and len(result.tool_calls) >= 2)

    # tool_choice variants
    result = await attempt(
        "tool_choice_named",
        client.chat(
            tool_messages,
            tools=[_PROBE_TOOL],
            tool_choice={"type": "function", "function": {"name": "get_weather"}},
            max_tokens=_PROBE_MAX_TOKENS,
            temperature=0,
        ),
    )
    sc.tool_choice_named = bool(
        result and result.tool_calls and result.tool_calls[0].name == "get_weather"
    )
    result = await attempt(
        "tool_choice_required",
        client.chat(tool_messages, tools=[_PROBE_TOOL], tool_choice="required",
                    max_tokens=_PROBE_MAX_TOKENS, temperature=0),
    )
    sc.tool_choice_required = bool(result and result.tool_calls)

    # tool-role round trip
    result = await attempt(
        "tool_roundtrip",
        client.chat(
            [
                tool_messages[0],
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_probe1",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city": "Riyadh", "unit": "celsius"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_probe1",
                    "content": '{"temp_c": 43, "condition": "sunny"}',
                },
            ],
            tools=[_PROBE_TOOL],
            max_tokens=_PROBE_MAX_TOKENS,
            temperature=0,
        ),
    )
    sc.tool_role_roundtrip = bool(result and "43" in (result.content or ""))

    # streaming (content + usage)
    try:
        stream = client.chat_stream(
            [{"role": "user", "content": "Count from 1 to 5, digits only."}],
            max_tokens=_PROBE_MAX_TOKENS,
            temperature=0,
        )
        folded = await accumulate_stream(stream)
        sc.streaming = bool(folded.content)
        sc.usage_in_stream = folded.usage is not None
    except LLMError as err:
        sc.notes.append(f"streaming: {err}")

    # streaming tool-call deltas
    try:
        stream = client.chat_stream(tool_messages, tools=[_PROBE_TOOL],
                                    max_tokens=_PROBE_MAX_TOKENS, temperature=0)
        folded = await accumulate_stream(stream)
        sc.streaming_tool_deltas = bool(
            folded.tool_calls and folded.tool_calls[0].name == "get_weather"
        )
    except LLMError as err:
        sc.notes.append(f"streaming_tools: {err}")

    # response_format modes
    result = await attempt(
        "json_object",
        client.chat(
            [{"role": "user", "content": "Give me a JSON object with keys name (string) and"
                                         " age (int) for a fictional analyst."}],
            response_format={"type": "json_object"},
            max_tokens=_PROBE_MAX_TOKENS,
            temperature=0,
        ),
    )
    if result:
        try:
            json.loads(result.content)
            sc.json_object_mode = True
        except ValueError:
            pass

    adherent = 0
    schema_works = False
    for prompt in _ADHERENCE_PROMPTS:
        result = await attempt(
            "json_schema",
            client.chat(
                [{"role": "user", "content": prompt}],
                response_format=_VERDICT_SCHEMA,
                max_tokens=_PROBE_MAX_TOKENS,
                temperature=0,
            ),
        )
        if result is None:
            break  # mode unsupported — don't burn the remaining prompts
        schema_works = True
        if _adheres(result):
            adherent += 1
    if schema_works:
        sc.json_schema_mode = adherent > 0
        sc.schema_adherence_rate = adherent / len(_ADHERENCE_PROMPTS)

    # throughput (~192 tokens; model already warm from the basic probe)
    t0 = time.monotonic()
    result = await attempt(
        "throughput",
        client.chat(
            [{"role": "user", "content": "Write a 150-word neutral paragraph about network"
                                         " telemetry."}],
            max_tokens=192,
            temperature=0,
        ),
    )
    elapsed = time.monotonic() - t0
    if result and result.usage and elapsed > 0:
        sc.tokens_per_second = round(result.usage.completion_tokens / elapsed, 1)

    return sc
