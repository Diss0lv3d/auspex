"""B1 — B-001's turn 2 replayed straight at an endpoint, on the CONVERSATIONAL path.

The route's conversational composition, rebuilt from its own pieces
(auspex/routes/chat.py `_history`, `_fence_assistant`, the mode contract's
directive), with turn 1 verbatim from Postgres. One variable changes: the mode
directive appended last.

- `general`        — what the route sends today: "dig deeper" resolves to
                     GENERAL because the resolver reads only the current message.
- `ioc_enrichment` — what it would send if the resolver knew the session's
                     indicator.

A `+owner` suffix (e.g. `general+owner`) replaces turn 1 with what the IOC check
renders once AbuseIPDB's network fields are kept as a context-only signal
(hypothesis H-A): the same echo, with the owner the source actually returned
(docs/probes/b1-b001/raw-owner-fields.log).

Single call per run, temperature 0 and CHAT_ANSWER_MAX_TOKENS, as the native
path makes it. `glm` is the dev endpoint from .env (D-034) — on the route it
takes the AGENT path, so this is the composition a customer endpoint that is
not native_tools would get. `qwen` is local qwen3:14b (D-013), slow.

Run:  .venv/bin/python docs/probes/b1-b001/probe_replay_conversational.py <glm|qwen> <runs> <variant>...
"""

import asyncio
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "docs/probes/b1-b001")
from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
from probe_app_dig_deeper import flags  # noqa: E402

from auspex.config import Settings  # noqa: E402
from auspex.llm.client import LLMClient  # noqa: E402
from auspex.modes import Mode, contract_for  # noqa: E402
from auspex.routes.chat import CHAT_ANSWER_MAX_TOKENS, _fence_assistant, _history  # noqa: E402

TURN1 = "what do you know about this IP: 34.187.179.218"
ANSWER1 = (
    "Parsed 1 observable:\n\n"
    "- 34.187.179.218 — ipv4 (id ipv4-84ed934c)\n"
    "  no signal from 5 connected sources — unknown to them"
)
ANSWER1_OWNER = (
    "Parsed 1 observable:\n\n"
    "- 34.187.179.218 — ipv4 (id ipv4-84ed934c)\n"
    "  no reputation verdict — context: AbuseIPDB: network Google LLC (google.com), "
    "Data Center/Web Hosting/Transit, US · hostname 218.179.187.34.bc.googleusercontent.com\n\n"
    "Verdicts are recorded and decay over time; paste an indicator again for a fresh read."
)
TURN2 = "dig deeper"


def messages(variant: str) -> list[dict]:
    mode, _, data = variant.partition("+")
    turns = [
        {"role": "user", "content": TURN1},
        {"role": "assistant",
         "content": _fence_assistant(ANSWER1_OWNER if data == "owner" else ANSWER1)},
        {"role": "user", "content": TURN2},
    ]
    msgs = _history(turns)
    msgs.append({"role": "system", "content": contract_for(Mode(mode)).system_directive()})
    return msgs


def client(endpoint: str) -> LLMClient:
    if endpoint == "qwen":
        return LLMClient("http://localhost:11434/v1", "qwen3:14b", "")
    s = Settings()
    return LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)


async def one(endpoint: str, variant: str) -> None:
    c = client(endpoint)
    t0 = time.monotonic()
    answer, reasoning, finish = [], [], None
    try:
        async for ev in c.chat_stream(messages(variant), max_tokens=CHAT_ANSWER_MAX_TOKENS,
                                      temperature=0):
            if ev.kind == "content":
                answer.append(ev.text)
            elif ev.kind == "reasoning":
                reasoning.append(ev.text)
            elif ev.kind == "finish":
                finish = ev.finish_reason
    finally:
        await c.aclose()
    a, r = "".join(answer), "".join(reasoning)
    print(f"--- {endpoint} · {variant} · finish={finish} · {time.monotonic() - t0:.0f}s")
    print(f"   ANSWER    {flags(a)}")
    print(f"   REASONING {flags(r)} ({len(r)} chars)")
    print("   answer: " + a.strip()[:900].replace("\n", "\n           "))


async def main(endpoint: str, runs: int, variants: list[str]) -> None:
    for variant in variants:
        for _ in range(runs):
            await one(endpoint, variant)


asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3:]))
