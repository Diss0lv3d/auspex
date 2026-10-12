"""Where a deep turn's reasoning loses its speed: the endpoint vs the server, on ONE run.

probe_reasoning_rate.py timed the endpoint and the route on two DIFFERENT
completions, so the difference could be the model's. Here the app runs in this
process (uvicorn on 127.0.0.1:8011 in its own thread, host-pinned like pytest,
KB on), with `LLMClient.chat_stream` wrapped so every event the endpoint sends
is stamped as the app's client parses it: layer 1. A client in the main thread
streams /api/chat and stamps every frame on arrival: layer 2. One clock and one
completion, so the lag between a delta's two stamps is exactly what the server
path adds (the agent loop, the rail's scan, SSE framing, loopback). Layer 3,
the page, is measured in a real browser against the container (page_paint.js).

  --endpoint default     the configured endpoint; deep turns take the agent
                         path (D-037: its scorecard says native tools, streamed)
  --endpoint glm-native  the same model as a dev-switcher entry: the
                         conversational path (one native call, no tools)
  --endpoint qwen        qwen3:14b on the host's Ollama, as the page's switcher
                         routes it. Conversational only: a dev entry never takes
                         the agent path (chat.py, get_endpoint_resolver).

Only counts and timings are printed or saved, never model text.
Do NOT run pytest at the same time.

Run:  .venv/bin/python docs/probes/fe-stream/probe_layers.py --endpoint default --runs 5
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")
os.environ["KB_ENABLED"] = "true"  # the agent's search_knowledge must see the real KB
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from auspex.config import Settings  # noqa: E402
from auspex.llm.client import LLMClient  # noqa: E402

PORT = 8011
API = f"http://127.0.0.1:{PORT}/api"
QUESTIONS = [
    "What are the practical differences between EDR and XDR for a small SOC deciding what to buy?",
    "How does Kerberoasting work, and what should a SOC watch for to detect it?",
    "Walk me through how an attacker usually moves laterally after phishing one "
    "workstation in an Active Directory domain, and where we can catch them.",
]

# ---- layer 1: every endpoint event, stamped as the app's client parses it ----
CALLS: list[dict] = []
_orig_stream = LLMClient.chat_stream


def _stamped_stream(self, messages, **kw):
    call = {"start": time.perf_counter(), "events": [], "end": None}
    CALLS.append(call)

    async def gen():
        try:
            async for ev in _orig_stream(self, messages, **kw):
                call["events"].append((time.perf_counter(), ev.kind, ev.text or ""))
                yield ev
        finally:
            call["end"] = time.perf_counter()

    return gen()


LLMClient.chat_stream = _stamped_stream


def _registry(settings: Settings) -> str:
    """A throwaway switcher registry for this process only. The key is named
    by env var, never written (registry.py)."""
    os.environ.setdefault("LLM_API_KEY", settings.llm_api_key)
    entries = [
        {"id": "glm-native", "label": "probe", "base_url": settings.llm_base_url,
         "model": settings.llm_model, "api_key_env": "LLM_API_KEY", "native_reasoning": True},
        {"id": "qwen", "label": "probe", "base_url": "http://localhost:11434/v1",
         "model": "qwen3:14b", "native_reasoning": True},
    ]
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump({"endpoints": entries}, f)
    return path


def _start_server():
    os.environ["DEV_LLM_REGISTRY_FILE"] = _registry(Settings())
    from auspex.app import create_app

    app = create_app(Settings())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    deadline = time.monotonic() + 60
    while not app.state.kb.bootstrapped and time.monotonic() < deadline:
        time.sleep(0.25)
    print(f"app up on :{PORT}, kb bootstrapped={app.state.kb.bootstrapped}")
    return server


def _gaps(stamps):
    return [b - a for a, b in zip(stamps, stamps[1:], strict=False)]


def _pct(xs, p):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def analyse(t0, t_headers, frames, calls):
    # Endpoint deltas, in order, with the call they belong to.
    up_r = [(t, x, ci) for ci, c in enumerate(calls) for t, k, x in c["events"]
            if k == "reasoning" and x]
    up_c = [(t, x, ci) for ci, c in enumerate(calls) for t, k, x in c["events"]
            if k == "content" and x]
    rt_r = [(t, f["reasoning"]) for t, f in frames if "reasoning" in f]
    rt_c = [(t, f["content"]) for t, f in frames if "content" in f]
    done = next((f["done"] for _, f in frames if "done" in f), {})

    # The route forwards each reasoning delta as one frame, verbatim, in order;
    # a route reasoning frame with no endpoint twin is agent narration.
    matched, j, narration = [], 0, 0
    for t, x in rt_r:
        if j < len(up_r) and up_r[j][1] == x:
            matched.append((up_r[j][0], t, len(x), up_r[j][2]))
            j += 1
        else:
            narration += 1
    c_lags, j = [], 0
    for t, x in rt_c:
        k = next((i for i in range(j, len(up_c)) if up_c[i][1] == x), None)
        if k is not None:
            c_lags.append(t - up_c[k][0])
            j = k + 1

    # Reasoning rate WITHIN each call (an agent turn's tool time is not the
    # model's rate), at both layers, over the same matched deltas.
    def rate(which):
        chars = span = 0.0
        for ci in {m[3] for m in matched}:
            ms = [m for m in matched if m[3] == ci]
            if len(ms) > 1:
                chars += sum(m[2] for m in ms[1:])
                span += ms[-1][which] - ms[0][which]
        return chars / span if span else float("nan")

    def max_gap_in_call(which):
        g = []
        for ci in {m[3] for m in matched}:
            g += _gaps([m[which] for m in matched if m[3] == ci])
        return g

    lags = [b - a for a, b, _, _ in matched]
    gaps_up, gaps_rt = max_gap_in_call(0), max_gap_in_call(1)
    all_frames = [t for t, _ in frames]
    first_r_up = up_r[0][0] - t0 if up_r else float("nan")
    first_r_rt = rt_r[0][0] - t0 if rt_r else float("nan")
    return {
        "path": done.get("path"), "mode": done.get("mode"),
        "finish": done.get("finish_reason"), "output_valid": done.get("output_valid"),
        "calls": len(calls),
        "headers_s": t_headers - t0,
        "prep_s": calls[0]["start"] - t0 if calls else float("nan"),
        "first_reasoning_endpoint_s": first_r_up,
        "first_reasoning_route_s": first_r_rt,
        "reasoning_chars": sum(len(x) for _, x in rt_r),
        "reasoning_frames": len(rt_r), "narration_frames": narration,
        "unmatched_endpoint_deltas": len(up_r) - len(matched),
        "rate_endpoint_cps": rate(0), "rate_route_cps": rate(1),
        "max_gap_in_call_endpoint_s": max(gaps_up, default=0.0),
        "max_gap_in_call_route_s": max(gaps_rt, default=0.0),
        "p95_gap_route_s": _pct(gaps_rt, 95),
        "longest_silence_route_s": max(_gaps(all_frames), default=0.0),
        "lag_p50_ms": _pct(lags, 50) * 1000, "lag_p95_ms": _pct(lags, 95) * 1000,
        "lag_max_ms": max(lags, default=float("nan")) * 1000,
        "content_lag_p50_ms": _pct(c_lags, 50) * 1000,
        "content_lag_max_ms": max(c_lags, default=float("nan")) * 1000,
        "first_answer_route_s": rt_c[0][0] - t0 if rt_c else float("nan"),
        "between_calls_s": [round(b["start"] - a["end"], 2)
                            for a, b in zip(calls, calls[1:], strict=False)
                            if a["end"] is not None],
        "turn_s": all_frames[-1] - t0 if all_frames else float("nan"),
    }


async def one_turn(http, token, question, endpoint_id):
    CALLS.clear()
    frames = []
    body = {"message": question}
    if endpoint_id:
        body["endpoint_id"] = endpoint_id
    t0 = time.perf_counter()
    async with http.stream("POST", f"{API}/chat", json=body,
                           headers={"Authorization": f"Bearer {token}"}) as resp:
        t_headers = time.perf_counter()
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                frames.append((time.perf_counter(), json.loads(line[5:].strip())))
    return analyse(t0, t_headers, frames, list(CALLS))


def summary(rows):
    keys = [k for k, v in rows[0].items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)]
    print(f"\n== {len(rows)} runs: median [min .. max] ==")
    for k in keys:
        xs = [r[k] for r in rows if r[k] == r[k]]  # drop NaN
        if xs:
            print(f"  {k:30s} {statistics.median(xs):9.2f}  [{min(xs):9.2f} .. {max(xs):9.2f}]")


async def main(args):
    _start_server()
    endpoint_id = None if args.endpoint == "default" else args.endpoint
    rows = []
    async with httpx.AsyncClient(timeout=900) as http:
        token = (await http.post(f"{API}/auth/dev-login",
                                 json={"email": "fe-probe@auspex.dev"})).json()["access_token"]
        for i in range(args.runs):
            q = QUESTIONS[i % len(QUESTIONS)]
            row = {"run": i + 1, "endpoint": args.endpoint, "q": i % len(QUESTIONS) + 1,
                   **await one_turn(http, token, q, endpoint_id)}
            rows.append(row)
            print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v)
                              for k, v in row.items()}), flush=True)
    summary(rows)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint", choices=["default", "glm-native", "qwen"], default="default")
    p.add_argument("--runs", type=int, default=3)
    asyncio.run(main(p.parse_args()))
