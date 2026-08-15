"""S23 — can the agent loop STREAM? Reality snapshot of tool calls over SSE.

Why this probe exists before a line of wiring. `AgentLoop.run()` drives
`client.chat(...)` — one blocking call per step (auspex/agent/loop.py:321).
`/api/chat` is an SSE route that streams `reasoning`/`content` frames. Those two
shapes do not compose: a turn that calls tools cannot emit its final answer until
the tools have run, and the loop as built returns only when the whole chain is
done.

So the wiring has exactly one interesting question, and it is not a design
preference — it is a fact about the customer's endpoint:

    **Does the endpoint emit tool calls over `chat_stream`, and in what shape?**

`chat_stream` already accepts `tools` and declares a `tool_call` StreamEvent
(auspex/llm/client.py:222, :74). Declaring the event is not evidence that a real
endpoint produces it, and S2's `native_tools` capability was measured through the
NON-streaming `chat` path. Coding a streaming loop against an unprobed wire shape
is exactly what CLAUDE.md rule 4 forbids.

What this measures, against the real dev endpoint (D-015, Llama-4-Scout via
Northflank):

  1. does a streamed request with `tools` yield `tool_call` events at all?
  2. are `arguments` delivered whole, or fragmented across deltas so the loop
     must accumulate before it can parse JSON?
  3. what `finish_reason` closes a tool-calling turn?
  4. does the endpoint interleave `content` with tool calls in one turn — i.e.
     can an answer legitimately begin before the tools have run?

(4) is the one that decides the shape of the wiring. If content only ever arrives
AFTER the tool round-trip, the route can stream the final answer honestly. If the
endpoint interleaves, the route would be streaming prose that the tool results may
contradict.

Run: python docs/probes/s23-agentloop/probe_streaming_tools.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

_REPO = Path(os.environ.get("AUSPEX_REPO", Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(_REPO))

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

from auspex.config import get_settings  # noqa: E402
from auspex.llm.client import LLMClient, tool_spec  # noqa: E402

TOOL = tool_spec(
    "lookup_observable",
    "Look up reputation and enrichment for a single IP, domain, or file hash.",
    {"value": {"type": "string", "description": "the IOC to look up"}},
    ["value"],
)

CASES = [
    (
        "forces a tool call",
        "Check the reputation of 185.220.101.5 using the tool available to you.",
    ),
    (
        "needs no tool",
        "In one sentence, what does the acronym SIEM stand for?",
    ),
]


async def run_case(client: LLMClient, label: str, question: str) -> dict:
    print(f"\n=== {label}: {question!r}")
    events: list = []
    tool_frags: dict[int, list[str]] = defaultdict(list)
    tool_names: dict[int, str] = {}
    order: list[str] = []
    async for ev in client.chat_stream(
        [{"role": "user", "content": question}],
        max_tokens=300,
        temperature=0,
        tools=[TOOL],
    ):
        events.append(ev)
        if not order or order[-1] != ev.kind:
            order.append(ev.kind)
        if ev.kind == "tool_call" and ev.tool_delta:
            fn = (ev.tool_delta or {}).get("function") or {}
            if fn.get("name"):
                tool_names[ev.tool_index] = fn["name"]
            if fn.get("arguments"):
                tool_frags[ev.tool_index].append(fn["arguments"])

    kinds = [e.kind for e in events]
    finish = next((e.finish_reason for e in events if e.kind == "finish"), None)
    content = "".join(e.text for e in events if e.kind == "content")

    print(f"  event kinds in order : {' -> '.join(order)}")
    print(f"  counts               : "
          f"{ {k: kinds.count(k) for k in sorted(set(kinds))} }")
    print(f"  finish_reason        : {finish!r}")
    print(f"  content chars        : {len(content)}")

    parsed = {}
    for idx, frags in tool_frags.items():
        whole = "".join(frags)
        name = tool_names.get(idx, "?")
        try:
            args = json.loads(whole)
            ok = True
        except Exception as exc:
            args, ok = f"UNPARSEABLE: {exc}", False
        print(f"  tool[{idx}] {name}: {len(frags)} argument delta(s) -> {args!r}")
        if len(frags) > 1:
            print(f"      FRAGMENTED — the loop must ACCUMULATE before parsing "
                  f"(fragments: {frags!r})")
        parsed[idx] = {"name": name, "fragments": len(frags), "args": args, "parsed_ok": ok}

    # The question that decides the wiring shape.
    interleaved = "content" in order and "tool_call" in order and order.index(
        "content"
    ) < order.index("tool_call")
    if "tool_call" in kinds:
        verdict = (
            "answer prose precedes tool results — cannot stream it honestly"
            if interleaved
            else "tool calls come first — the answer can stream after"
        )
        print(f"  CONTENT BEFORE TOOL CALLS: {interleaved} ({verdict})")

    return {
        "label": label,
        "order": order,
        "counts": {k: kinds.count(k) for k in sorted(set(kinds))},
        "finish_reason": finish,
        "content_chars": len(content),
        "tools": parsed,
        "content_before_tool_calls": interleaved if "tool_call" in kinds else None,
    }


async def main() -> None:
    settings = get_settings()
    print(f"endpoint : {settings.llm_base_url}")
    print(f"model    : {settings.llm_model}")
    client = LLMClient.from_settings(settings)
    out = []
    try:
        for label, question in CASES:
            try:
                out.append(await run_case(client, label, question))
            except Exception as exc:
                print(f"  ERROR: {type(exc).__name__}: {exc}")
                out.append({"label": label, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        await client.aclose()

    print("\n================ SUMMARY ================")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
