"""S26 — Z.ai general (pay-as-you-go) API: the WIRE, before any client code moves.

Llama-4-Scout on Northflank is decommissioned (its hostname is NXDOMAIN), and
Burhan supplied a pay-as-you-go Z.ai key (`GLM_API_KEY`). The docs were read
first (record: docs/probes/2026-10-10-zai-endpoint.md, §Docs). The docs leave
open exactly the things our client depends on, so each one is asked of the
live API here, with raw httpx and none of our parsing in the way:

  * is there a GET {base}/models (our liveness check needs one)?
  * does a /v1 alias exist under the documented base (it decides whether the
    base-URL convention change is required, not just nicer)?
  * temperature=0 accepted? (every capability probe sends it)
  * thinking text field: `reasoning_content` vs `reasoning`; does GLM-5.2 think
    by default, and what does that cost in tokens and seconds?
  * tool_calls[].function.arguments: JSON string (OpenAI) or object (the spec)?
  * the error envelope: flat {code,message} (spec) or {error:{...}} (guide)?
  * unsupported OpenAI knobs (tool_choice required/named, json_schema,
    stream_options): rejected, ignored, or honoured?
  * streamed tool calls with and without `tool_stream`; where usage arrives
  * a routine SOC prompt: does the content filter fire?

ONLY the general endpoint https://api.z.ai/api/paas/v4 is called — never the
Coding Plan one. The key is read from .env and never printed; every byte that
is printed or saved passes through `redact()` first.

Run:  .venv/bin/python docs/probes/s26-zai/probe_zai_wire.py [model ...]
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[3]
RAW = Path(__file__).resolve().parent / "raw"
BASE = "https://api.z.ai/api/paas/v4"

KEY = dotenv_values(REPO / ".env").get("GLM_API_KEY") or ""
assert KEY, "GLM_API_KEY missing from .env"
_SECRETS = [s for s in {KEY, *KEY.split(".")} if len(s) >= 8]


def redact(text: str) -> str:
    for s in _SECRETS:
        text = text.replace(s, "<REDACTED>")
    return text


WEATHER = {
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
LOOKUP_IP = {
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
WEATHER_Q = [{"role": "user", "content": "What's the weather in Riyadh in celsius?"}]


def save(name: str, payload) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    body = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    (RAW / name).write_text(redact(body) + "\n")


async def post(http, model, label, body, *, path="/chat/completions"):
    body = {"model": model, **body}
    t0 = time.monotonic()
    try:
        r = await http.post(BASE + path, json=body)
    except httpx.HTTPError as err:  # a hung model is a finding, not a crash
        dt = time.monotonic() - t0
        save(f"{model}--{label}.json", {"status": 0, "seconds": round(dt, 2), "request": body,
                                         "transport_error": err.__class__.__name__})
        return 0, {"transport_error": err.__class__.__name__}, dt
    dt = time.monotonic() - t0
    text = r.text
    save(f"{model}--{label}.json", {"status": r.status_code, "seconds": round(dt, 2),
                                     "content_type": r.headers.get("content-type"),
                                     "request": body, "body": _try_json(text)})
    return r.status_code, _try_json(text), dt


async def stream(http, model, label, body):
    body = {"model": model, "stream": True, **body}
    lines, t0, first = [], time.monotonic(), None
    try:
        return await _stream(http, model, label, body, lines, t0, first)
    except httpx.HTTPError as err:
        save(f"{model}--{label}.json", {"status": 0, "request": body,
                                         "transport_error": err.__class__.__name__})
        return 0, lines, time.monotonic() - t0, first


async def _stream(http, model, label, body, lines, t0, first):
    async with http.stream("POST", BASE + "/chat/completions", json=body) as r:
        status = r.status_code
        if status >= 400:
            text = (await r.aread()).decode("utf-8", "replace")
            save(f"{model}--{label}.json", {"status": status, "request": body,
                                             "body": _try_json(text)})
            return status, [], 0.0, None
        async for line in r.aiter_lines():
            if line.strip():
                if first is None:
                    first = time.monotonic() - t0
                lines.append(line)
    dt = time.monotonic() - t0
    save(f"{model}--{label}.sse.txt", "\n".join(lines))
    return status, lines, dt, first


def _try_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return text[:2000]


def msg(body):
    try:
        return body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return {}


def show(label, status, body, dt=None):
    head = f"  {label:<34} HTTP {status}" + (f"  {dt:5.1f}s" if dt is not None else "")
    if status == 0 or status >= 400:
        print(head, " ERROR:", redact(json.dumps(body)[:300]))
        return
    m = msg(body)
    fr = body["choices"][0].get("finish_reason") if isinstance(body, dict) and body.get("choices") else None
    rc = m.get("reasoning_content") or ""
    print(head, f" finish={fr}  msg_keys={sorted(m)}  content={len(m.get('content') or '')}ch"
                f"  reasoning_content={len(rc)}ch  usage={body.get('usage')}")


def sse_summary(lines):
    chunks = []
    for line in lines:
        if line.startswith("data:") and line[5:].strip() != "[DONE]":
            try:
                chunks.append(json.loads(line[5:].strip()))
            except ValueError:
                pass
    kinds = {"content": 0, "reasoning_content": 0, "reasoning": 0, "tool_calls": 0}
    tool_frags, usage_at, finish = [], [], []
    for i, c in enumerate(chunks):
        for ch in c.get("choices") or []:
            d = ch.get("delta") or {}
            for k in kinds:
                if d.get(k):
                    kinds[k] += 1
            for tc in d.get("tool_calls") or []:
                fn = tc.get("function") or {}
                tool_frags.append({"i": i, "index": tc.get("index"), "id": bool(tc.get("id")),
                                   "name": fn.get("name"), "args_type": type(fn.get("arguments")).__name__,
                                   "args": fn.get("arguments")})
            if ch.get("finish_reason"):
                finish.append((i, ch["finish_reason"]))
        if c.get("usage"):
            usage_at.append((i, bool(c.get("choices")), c["usage"]))
    return {"chunks": len(chunks), "done": any(ln.strip() == "data: [DONE]" for ln in lines),
            "delta_counts": kinds, "tool_fragments": tool_frags, "finish": finish,
            "usage_at": usage_at}


async def wire(model: str, http: httpx.AsyncClient, full: bool) -> None:
    print(f"\n=== {model} ===")
    # 1 basic chat, temperature 0, default thinking
    st, body, dt = await post(http, model, "basic", {
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        "temperature": 0, "max_tokens": 2000})
    show("basic (t=0, default thinking)", st, body, dt)
    if st == 0 or st >= 400:
        return
    # 2 thinking disabled — what the default costs
    st, body, dt = await post(http, model, "basic-nothink", {
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        "temperature": 0, "max_tokens": 2000, "thinking": {"type": "disabled"}})
    show("basic (thinking disabled)", st, body, dt)
    # 3 native tool call
    st, body, dt = await post(http, model, "tools", {
        "messages": WEATHER_Q, "tools": [WEATHER], "temperature": 0, "max_tokens": 2000})
    show("tools (auto)", st, body, dt)
    for tc in msg(body).get("tool_calls") or []:
        a = tc.get("function", {}).get("arguments")
        print(f"      tool_call id={tc.get('id')!r} type={tc.get('type')!r} name="
              f"{tc.get('function', {}).get('name')!r} arguments<{type(a).__name__}>={a!r}")
    # 4 tool role round trip
    rt = WEATHER_Q + [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_probe1", "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "Riyadh", "unit": "celsius"}'}}]},
        {"role": "tool", "tool_call_id": "call_probe1", "content": '{"temp_c": 43, "condition": "sunny"}'}]
    st, body, dt = await post(http, model, "roundtrip", {
        "messages": rt, "tools": [WEATHER], "temperature": 0, "max_tokens": 2000})
    show("tool roundtrip", st, body, dt)
    print(f"      roundtrip mentions 43: {'43' in (msg(body).get('content') or '')}")
    # 5 streaming tool call, default (no tool_stream)
    st, lines, dt, first = await stream(http, model, "stream-tools", {
        "messages": WEATHER_Q, "tools": [WEATHER], "temperature": 0, "max_tokens": 2000})
    print(f"  {'stream tools (no tool_stream)':<34} HTTP {st}  {dt:5.1f}s  {json.dumps(sse_summary(lines))[:900]}")
    if not full:
        return
    # 6 parallel tools
    st, body, dt = await post(http, model, "parallel", {
        "messages": [{"role": "user", "content": "Check the weather in Riyadh (celsius) AND look up"
                                                 " the IP 8.8.8.8. Do both now."}],
        "tools": [WEATHER, LOOKUP_IP], "temperature": 0, "max_tokens": 2000})
    show("parallel tools", st, body, dt)
    print(f"      tool_calls in one response: {len(msg(body).get('tool_calls') or [])}")
    # 7 unsupported knobs
    for label, extra in [
        ("tool_choice=required", {"tools": [WEATHER], "tool_choice": "required"}),
        ("tool_choice=named", {"tools": [WEATHER], "tool_choice": {"type": "function", "function": {"name": "get_weather"}}}),
        ("tool_choice=none", {"tools": [WEATHER], "tool_choice": "none"}),
    ]:
        st, body, dt = await post(http, model, label.replace("=", "-"), {
            "messages": WEATHER_Q, "temperature": 0, "max_tokens": 2000, **extra})
        show(label, st, body, dt)
        if st < 400:
            print(f"      -> tool_calls={len(msg(body).get('tool_calls') or [])}")
    st, body, dt = await post(http, model, "json_schema", {
        "messages": [{"role": "user", "content": "Give a threat verdict for the domain example.test."}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "verdict", "schema": {
            "type": "object", "properties": {"verdict": {"type": "string", "enum": ["benign", "suspicious", "malicious"]}},
            "required": ["verdict"]}}},
        "temperature": 0, "max_tokens": 2000})
    show("response_format=json_schema", st, body, dt)
    if st < 400:
        print(f"      content: {redact((msg(body).get('content') or '')[:200])!r}")
    st, body, dt = await post(http, model, "json_object", {
        "messages": [{"role": "user", "content": "Give me a JSON object with keys name (string) and age (int)"
                                                 " for a fictional analyst."}],
        "response_format": {"type": "json_object"}, "temperature": 0, "max_tokens": 2000})
    show("response_format=json_object", st, body, dt)
    # 8 streaming: plain + stream_options, then tool_stream=true
    st, lines, dt, first = await stream(http, model, "stream-usage", {
        "messages": [{"role": "user", "content": "Count from 1 to 5, digits only."}],
        "stream_options": {"include_usage": True}, "temperature": 0, "max_tokens": 2000})
    print(f"  {'stream + stream_options':<34} HTTP {st}  {dt:5.1f}s  first={first and round(first, 2)}s  {json.dumps(sse_summary(lines))[:600]}")
    st, lines, dt, first = await stream(http, model, "stream-tools-toolstream", {
        "messages": WEATHER_Q, "tools": [WEATHER], "tool_stream": True, "temperature": 0, "max_tokens": 2000})
    print(f"  {'stream tools (tool_stream=true)':<34} HTTP {st}  {dt:5.1f}s  {json.dumps(sse_summary(lines))[:900]}")
    # 9 error envelope: an unknown model
    st, body, dt = await post(http, "glm-does-not-exist", "error-envelope", {
        "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10})
    print(f"  {'error envelope (bad model)':<34} HTTP {st}  body={redact(json.dumps(body))[:300]}")
    # 10 a routine SOC prompt — does the content filter fire?
    st, body, dt = await post(http, model, "soc-content", {
        "messages": [{"role": "user", "content":
            "An EDR alert shows mimikatz `sekurlsa::logonpasswords` run on host FIN-WS-22, followed by "
            "an outbound connection to 185.220.101.4. As a SOC analyst, explain what happened, how "
            "severe it is, and the containment steps."}],
        "temperature": 0, "max_tokens": 2000})
    show("SOC content (filter?)", st, body, dt)


async def endpoint_shape(http: httpx.AsyncClient) -> None:
    print("=== endpoint shape ===")
    for path in ("/models", "/v1/models"):
        r = await http.get(BASE + path)
        print(f"  GET {path:<28} HTTP {r.status_code}  {redact(r.text[:240])!r}")
        save(f"endpoint--GET{path.replace('/', '_')}.json", {"status": r.status_code, "body": _try_json(r.text)})
    r = await http.post(BASE + "/v1/chat/completions", json={
        "model": "glm-4.7-flash", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5})
    print(f"  POST /v1/chat/completions        HTTP {r.status_code}  {redact(r.text[:240])!r}")
    save("endpoint--POST_v1_chat.json", {"status": r.status_code, "body": _try_json(r.text)})


async def main() -> None:
    models = sys.argv[1:] or ["glm-5.2"]
    full_first = not (len(models) > 1 and models[0] == "--short")
    models = [m for m in models if m != "--short"]
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {KEY}"}, timeout=httpx.Timeout(120.0, connect=15.0)) as http:
        await endpoint_shape(http)
        for i, model in enumerate(models):
            await wire(model, http, full=(i == 0 and full_first))


asyncio.run(main())
