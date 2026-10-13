"""B2 — reproduce B-002: a definition question on the agent path stopped by the rail.

The app runs in this process (uvicorn on 127.0.0.1:8011 in its own thread,
host-pinned like pytest, KB on), as docs/probes/fe-stream/probe_layers.py runs
it. Three things are captured on the same turn:

  - every endpoint call's raw reasoning and content, as the app's client parses
    it (`LLMClient.chat_stream` wrapped), so a stopped turn's whole thinking is
    kept, including the delta the route never forwarded;
  - the exact configuration the route indexed this turn (`instruction_index`
    wrapped in the route's namespace), so a match is attributed to the issued
    text it came from rather than guessed;
  - the route's own "output leak" log line and its done frame.

For every run it reports the finish reason, output_valid, the matched run's
length (40 = the thinking channel's floor, 8 = every other channel's), which
issued text holds it, and the longest verbatim run each channel shares with the
issued text (stopped or not, so a passing run shows how close it came).

Raw text goes to raw-repro-<label>.jsonl beside this file; it is the dev
model's output on our own question, kept as B-002's regression evidence.
Do NOT run pytest at the same time.

Run:  .venv/bin/python docs/probes/b2-b002/probe_repro.py --runs 6 --label before
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, ".")
os.environ["KB_ENABLED"] = "true"  # the agent's search_knowledge must see the real KB
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

import httpx  # noqa: E402
import uvicorn  # noqa: E402

import auspex.routes.chat as chat_route  # noqa: E402
from auspex.config import Settings  # noqa: E402
from auspex.llm.client import LLMClient  # noqa: E402
from auspex.outguard import _words  # noqa: E402
from auspex.outguard import instruction_index as _real_index  # noqa: E402

HERE = Path(__file__).resolve().parent
PORT = 8011
API = f"http://127.0.0.1:{PORT}/api"
QUESTION = (
    "What are the practical differences between EDR and XDR for a small SOC deciding what to buy?"
)

# ---- every endpoint call's raw text ----
CALLS: list[dict] = []
_orig_stream = LLMClient.chat_stream


def _captured_stream(self, messages, **kw):
    call = {"reasoning": [], "content": [], "tools": bool(kw.get("tools"))}
    CALLS.append(call)

    async def gen():
        async for ev in _orig_stream(self, messages, **kw):
            if ev.kind in ("reasoning", "content") and ev.text:
                call[ev.kind].append(ev.text)
            yield ev

    return gen()


LLMClient.chat_stream = _captured_stream

# ---- the configuration the route indexed this turn ----
ISSUED: list[list[str]] = []


def _captured_index(instructions, **kw):
    if not kw:  # the answer floor's call; the thinking floor's passes the same list
        ISSUED.append(list(instructions))
    return _real_index(instructions, **kw)


chat_route.instruction_index = _captured_index

# ---- the route's leak line ----
LEAKS: list[str] = []


class _LeakHandler(logging.Handler):
    def emit(self, record):
        if record.getMessage().startswith("output leak"):
            LEAKS.append(record.args[1] if isinstance(record.args, tuple) else "")


logging.getLogger("auspex.chat").addHandler(_LeakHandler())


def _start_server():
    os.environ["DEV_LLM_REGISTRY_FILE"] = ""  # switcher off: the default endpoint only
    from auspex.app import create_app

    app = create_app(Settings())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    deadline = time.monotonic() + 60
    while not app.state.kb.bootstrapped and time.monotonic() < deadline:
        time.sleep(0.25)
    print(f"app up on :{PORT}, kb bootstrapped={app.state.kb.bootstrapped}", flush=True)
    return server


def longest_run(text: str, instructions: list[str]) -> tuple[int, str]:
    """The longest verbatim run (in scanner words) shared with `instructions`."""
    words = _words(text)
    best, found = 0, ""
    for width in range(2, min(120, len(words)) + 1):
        index = _real_index(instructions, shingle=width)
        hit = next((" ".join(words[i:i + width]) for i in range(len(words) - width + 1)
                    if " ".join(words[i:i + width]) in index), None)
        if hit is None:
            break
        best, found = width, hit
    return best, found


def attribute(run: str, issued: list[str]) -> list[str]:
    """Which issued texts contain `run`, named by their first words."""
    n = len(run.split())
    return [" ".join(_words(t)[:8]) + " …" for t in issued
            if n and run in _real_index([t], shingle=n)]


async def one_turn(http, token):
    CALLS.clear()
    ISSUED.clear()
    LEAKS.clear()
    frames = []
    async with http.stream("POST", f"{API}/chat", json={"message": QUESTION},
                           headers={"Authorization": f"Bearer {token}"}) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                frames.append(json.loads(line[5:].strip()))
    done = next((f["done"] for f in frames if "done" in f), {})
    issued = ISSUED[0] if ISSUED else []
    thinking = "".join(x for c in CALLS for x in c["reasoning"])
    content = "".join(x for c in CALLS for x in c["content"])
    t_run, t_text = longest_run(thinking, issued)
    c_run, c_text = longest_run(content, issued)
    matched = LEAKS[0] if LEAKS else ""
    return {
        "mode": done.get("mode"), "path": done.get("path"),
        "finish": done.get("finish_reason"), "output_valid": done.get("output_valid"),
        "calls": len(CALLS),
        "match_words": len(matched.split()) if matched else 0,
        "match_channel": ("thinking" if len(matched.split()) == 40 else "other")
        if matched else None,
        "match_source": attribute(matched, issued) if matched else [],
        "matched": matched,
        "thinking_longest": t_run, "thinking_longest_text": t_text,
        "thinking_longest_source": attribute(t_text, issued) if t_text else [],
        "content_longest": c_run, "content_longest_text": c_text,
        "issued_count": len(issued),
    }, {"calls": [{"tools": c["tools"], "reasoning": "".join(c["reasoning"]),
                   "content": "".join(c["content"])} for c in CALLS],
        "frames_error": [f["error"] for f in frames if "error" in f]}


async def main(args):
    _start_server()
    raw_path = HERE / f"raw-repro-{args.label}.jsonl"
    rows = []
    async with httpx.AsyncClient(timeout=900) as http:
        token = (await http.post(f"{API}/auth/dev-login",
                                 json={"email": "b2-probe@auspex.dev"})).json()["access_token"]
        with raw_path.open("w") as raw:
            for i in range(args.runs):
                row, text = await one_turn(http, token)
                row = {"run": i + 1, **row}
                rows.append(row)
                print(json.dumps({k: v for k, v in row.items()
                                  if k not in ("matched", "thinking_longest_text",
                                               "content_longest_text")}), flush=True)
                if row["matched"]:
                    print(f"   matched: {row['matched']!r}", flush=True)
                print(f"   thinking longest {row['thinking_longest']}: "
                      f"{row['thinking_longest_text']!r}", flush=True)
                raw.write(json.dumps({"run": i + 1, "question": QUESTION, **row, **text}) + "\n")
                raw.flush()
    stopped = [r for r in rows if r["finish"] == "output_guard"]
    print(f"\n== {len(stopped)}/{len(rows)} stopped; thinking longest per run: "
          f"{[r['thinking_longest'] for r in rows]}; content longest: "
          f"{[r['content_longest'] for r in rows]}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=6)
    p.add_argument("--label", default="before")
    asyncio.run(main(p.parse_args()))
