"""Where does slow reasoning come from? The model, the server, or the page.

The same deep question, timed twice:
1. straight from the dev endpoint (LLMClient.chat_stream, no route, no rail);
2. through /api/chat, the frames the page receives, timestamped on arrival.

For each: time to first reasoning byte, reasoning chars per second, the
largest gap between two frames, and how many frames. If (2) matches (1), the
server adds nothing and the rate is the model's. About 2-4 inference calls.
Do NOT run pytest at the same time.

Run:  .venv/bin/python docs/probes/fe-stream/probe_reasoning_rate.py
"""

import asyncio
import json
import sys
import time

import httpx

sys.path.insert(0, ".")
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
from auspex.config import Settings  # noqa: E402
from auspex.llm.client import LLMClient  # noqa: E402

API = "http://localhost:8000/api"
QUESTION = "What are the practical differences between EDR and XDR for a small SOC deciding what to buy?"


def report(label, t0, stamps, first_content):
    if not stamps:
        print(f"{label}: no reasoning frames")
        return
    chars = sum(n for _, n in stamps)
    span = stamps[-1][0] - stamps[0][0]
    gaps = [b[0] - a[0] for a, b in zip(stamps, stamps[1:])]
    print(f"{label}: first reasoning {stamps[0][0] - t0:5.2f}s | {len(stamps)} frames, "
          f"{chars} chars over {span:5.2f}s = {chars / span if span else 0:6.1f} chars/s | "
          f"mean frame {chars / len(stamps):4.1f} chars | max gap {max(gaps) if gaps else 0:4.2f}s | "
          f"first answer at {first_content - t0 if first_content else float('nan'):5.2f}s")


async def direct():
    s = Settings()
    client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
    t0, stamps, first_content = time.monotonic(), [], None
    try:
        async for ev in client.chat_stream([{"role": "user", "content": QUESTION}],
                                           max_tokens=1500, temperature=0):
            now = time.monotonic()
            if ev.kind == "reasoning" and ev.text:
                stamps.append((now, len(ev.text)))
            elif ev.kind == "content" and ev.text and first_content is None:
                first_content = now
    finally:
        await client.aclose()
    report("direct endpoint ", t0, stamps, first_content)


async def through_route():
    async with httpx.AsyncClient(timeout=240) as http:
        token = (await http.post(f"{API}/auth/dev-login",
                                 json={"email": "fe-probe@auspex.dev"})).json()["access_token"]
        t0, stamps, first_content, done = time.monotonic(), [], None, {}
        async with http.stream("POST", f"{API}/chat", json={"message": QUESTION},
                               headers={"Authorization": f"Bearer {token}"}) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                f = json.loads(line[5:].strip())
                now = time.monotonic()
                if "reasoning" in f:
                    stamps.append((now, len(f["reasoning"])))
                elif "content" in f and first_content is None:
                    first_content = now
                elif "done" in f:
                    done = f["done"]
        report("through /api/chat", t0, stamps, first_content)
        print(f"   path={done.get('path')} mode={done.get('mode')}")


async def main():
    await direct()
    await through_route()


asyncio.run(main())
