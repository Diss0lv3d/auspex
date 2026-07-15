"""Connect-time capability battery (D-005).

Probes what the endpoint ACTUALLY does — every scorecard field is set from an
executed request, never assumed. Endpoint-agnostic: only OpenAI-compatible
surface is used (wire shapes per docs/probes/2026-07-15-ollama-endpoint.md).
Failures demote gracefully into notes; a dead endpoint yields
reachable=False → plan_only.
"""

import json
import time

from auspex.llm.client import ChatResult, LLMClient, LLMError, accumulate_stream, tool_spec
from auspex.llm.scorecard import CapabilityScorecard

# The fair token budget for thinking models: they spend hundreds of `reasoning`
# tokens before any content/tool call, so a tight cap silently zeroes their
# capabilities (learned from the qwen3:14b run). Non-thinking models stop
# naturally long before this. The harness imports this so both measurement
# paths judge thinking models on the same footing.
PROBE_MAX_TOKENS = 2000

_PROBE_TOOL = tool_spec(
    "get_weather",
    "Get current weather for a city.",
    {
        "city": {"type": "string"},
        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
    },
    ["city"],
)
_PROBE_TOOL_2 = tool_spec(
    "lookup_ip",
    "Look up reputation info for an IPv4 address.",
    {"ip": {"type": "string"}},
    ["ip"],
)
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

_WEATHER_QUESTION = [{"role": "user", "content": "What's the weather in Riyadh in celsius?"}]
_TOOL_ROUNDTRIP_MESSAGES = [
    _WEATHER_QUESTION[0],
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

    async def probe(name: str, messages: list[dict], **kw) -> ChatResult | None:
        """One non-streaming probe; the token/temperature policy lives here only."""
        kw.setdefault("max_tokens", PROBE_MAX_TOKENS)
        try:
            return await client.chat(messages, temperature=0, **kw)
        except (LLMError, ValueError) as err:
            sc.notes.append(f"{name}: {err}")
            return None

    async def fold(name: str, messages: list[dict], **kw) -> ChatResult | None:
        """One streaming probe, folded to a ChatResult; same policy as probe()."""
        kw.setdefault("max_tokens", PROBE_MAX_TOKENS)
        try:
            return await accumulate_stream(client.chat_stream(messages, temperature=0, **kw))
        except (LLMError, ValueError) as err:
            sc.notes.append(f"{name}: {err}")
            return None

    # basic chat sanity (also warms the model for the timing probe)
    basic = await probe("basic_chat", [{"role": "user", "content": "Reply with exactly: pong"}])
    if basic is None:
        sc.notes.append("basic chat failed — endpoint reachable but not usable")
        return sc
    # Native reasoning: thinking models return a separate `reasoning` field. Read
    # it off the basic probe (no extra request). Drives the chat two-pass fallback
    # (D-016): endpoints without it get platform-generated reasoning instead.
    sc.native_reasoning = bool(basic.reasoning)

    # native tool calling
    result = await probe("native_tools", _WEATHER_QUESTION, tools=[_PROBE_TOOL])
    if result and result.tool_calls:
        call = result.tool_calls[0]
        try:
            sc.native_tool_calling = call.name == "get_weather" and "city" in call.parse_arguments()
        except ValueError:
            sc.notes.append("native_tools: tool call emitted but arguments are malformed JSON")

    # parallel tool calls
    result = await probe(
        "parallel_tools",
        [{"role": "user", "content": "Check the weather in Riyadh (celsius) AND look up"
                                     " the IP 8.8.8.8. Do both now."}],
        tools=[_PROBE_TOOL, _PROBE_TOOL_2],
    )
    sc.parallel_tool_calls = bool(result and len(result.tool_calls) >= 2)

    # tool_choice variants
    result = await probe(
        "tool_choice_named",
        _WEATHER_QUESTION,
        tools=[_PROBE_TOOL],
        tool_choice={"type": "function", "function": {"name": "get_weather"}},
    )
    sc.tool_choice_named = bool(
        result and result.tool_calls and result.tool_calls[0].name == "get_weather"
    )
    result = await probe(
        "tool_choice_required", _WEATHER_QUESTION, tools=[_PROBE_TOOL], tool_choice="required"
    )
    sc.tool_choice_required = bool(result and result.tool_calls)

    # tool-role round trip
    result = await probe("tool_roundtrip", _TOOL_ROUNDTRIP_MESSAGES, tools=[_PROBE_TOOL])
    sc.tool_role_roundtrip = bool(result and "43" in (result.content or ""))

    # streaming (content + usage), then streaming tool-call deltas
    folded = await fold(
        "streaming", [{"role": "user", "content": "Count from 1 to 5, digits only."}]
    )
    if folded:
        sc.streaming = bool(folded.content)
        sc.usage_in_stream = folded.usage is not None
    folded = await fold("streaming_tools", _WEATHER_QUESTION, tools=[_PROBE_TOOL])
    if folded:
        sc.streaming_tool_deltas = bool(
            folded.tool_calls and folded.tool_calls[0].name == "get_weather"
        )

    # response_format modes
    result = await probe(
        "json_object",
        [{"role": "user", "content": "Give me a JSON object with keys name (string) and"
                                     " age (int) for a fictional analyst."}],
        response_format={"type": "json_object"},
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
        result = await probe(
            "json_schema",
            [{"role": "user", "content": prompt}],
            response_format=_VERDICT_SCHEMA,
        )
        if result is None:
            break  # mode unsupported — don't burn the remaining prompts
        schema_works = True
        if _adheres(result):
            adherent += 1
    if schema_works:
        sc.json_schema_mode = adherent > 0
        sc.schema_adherence_rate = adherent / len(_ADHERENCE_PROMPTS)

    # throughput: fixed budget on purpose (a comparable-size sample, not a cap fix)
    t0 = time.monotonic()
    result = await probe(
        "throughput",
        [{"role": "user", "content": "Write a 150-word neutral paragraph about network"
                                     " telemetry."}],
        max_tokens=192,
    )
    elapsed = time.monotonic() - t0
    if result and result.usage and elapsed > 0:
        sc.tokens_per_second = round(result.usage.completion_tokens / elapsed, 1)

    return sc
