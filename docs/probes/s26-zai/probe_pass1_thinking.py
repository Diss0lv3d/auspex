"""S26 — what PASS 1 of the two-pass fallback looks like on a thinking model.

The fix Burhan chose for TD-037 ("make two-pass handle thinking models") rests
on one wire fact: on a thinking endpoint, pass 1's FIRST text event is the
model's own thinking, so the route can tell — inside the turn, from the stream
itself — that it is talking to a thinking model before it has shown anything.
And on the inverse: a model that does not think sends content first.

Pass 1 is built the way the route builds it (system prompt, the question,
PASS1_DIRECTIVE last) at CHAT_REASONING_MAX_TOKENS. The per-mode contract
directive is omitted — it is a system message too and does not change which
field the model streams into first.

Per question: the event sequence collapsed to runs (R = reasoning, C = content),
seconds to the first event, finish_reason, content chars. 3 calls; no route,
no usage_counters. The key is read by Settings from .env, never printed.

Run:  .venv/bin/python docs/probes/s26-zai/probe_pass1_thinking.py
"""

import asyncio
import itertools
import sys
import time

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

from auspex.config import Settings  # noqa: E402
from auspex.llm.client import LLMClient  # noqa: E402
from auspex.routes.chat import (  # noqa: E402
    CHAT_REASONING_MAX_TOKENS,
    CHAT_SYSTEM_PROMPT,
    PASS1_DIRECTIVE,
)

QUESTIONS = [
    "Explain how an attacker typically chains Kerberoasting into domain admin, and which "
    "detections a SOC should prioritise.",
    "Write a short handover note for the next shift about an ongoing phishing campaign "
    "targeting our finance team.",
    "hi",
]


async def main() -> None:
    s = Settings()
    print(f"model: {s.llm_model}  pass-1 max_tokens: {CHAT_REASONING_MAX_TOKENS}")
    async with LLMClient.from_settings(s) as client:
        for q in QUESTIONS:
            messages = [
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": q},
                {"role": "system", "content": PASS1_DIRECTIVE},
            ]
            kinds, first_at, finish, content = [], None, None, ""
            t0 = time.monotonic()
            async for ev in client.chat_stream(
                messages, max_tokens=CHAT_REASONING_MAX_TOKENS, temperature=0
            ):
                if ev.kind in ("reasoning", "content") and ev.text:
                    if first_at is None:
                        first_at = round(time.monotonic() - t0, 2)
                    kinds.append("R" if ev.kind == "reasoning" else "C")
                    if ev.kind == "content":
                        content += ev.text
                elif ev.kind == "finish":
                    finish = ev.finish_reason
            runs = " ".join(f"{k}x{len(list(g))}" for k, g in itertools.groupby(kinds))
            print(f"\nQ: {q[:70]!r}")
            print(f"  first text event at {first_at}s  sequence: {runs or '(none)'}")
            print(f"  finish={finish}  content={len(content)} chars  {content[:120]!r}")


asyncio.run(main())
