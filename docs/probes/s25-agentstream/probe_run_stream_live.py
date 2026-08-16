"""S25 — `run_stream` against the REAL endpoint and the REAL capability tools.

Everything in tests/test_agent_stream.py runs against fakes. This runs the same
method against live Scout with the three real READ tools, because a streaming
loop that works on scripted StreamEvents and not on a real SSE stream is the
exact class of thing this repo's "reality over memory" rule exists for.

It records the ORDER events arrive in, which is D-031 decision 1's whole claim,
and asserts it arithmetically rather than eyeballing the transcript:
  * every `tool` event index < every `content` event index;
  * content arrives as MORE THAN ONE delta (else nothing streamed);
  * one claim per model call.

No route, no usage_counters — the claim here is a counter in this process.
"""

import asyncio
import sys

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.agent.capabilities import build_capability_registry
from auspex.agent.loop import AgentLoop
from auspex.config import Settings
from auspex.enrich import EnrichmentService
from auspex.kb import KnowledgeService
from auspex.llm.client import LLMClient

WORKSPACE = "00000000-0000-0000-0000-000000000001"


class _Store:
    async def create(self, **kw):
        return {"id": "probe", "card": {}}


async def main() -> None:
    s = Settings()
    # The app's own constructors (app.py:47,53) -- not a second opinion about
    # how a service is built, which is the drift capabilities.py exists to avoid.
    enrichment = EnrichmentService.from_settings(s)
    kb = KnowledgeService.from_settings(s)
    registry = build_capability_registry(enrichment=enrichment, kb=kb)
    print(f"tools: {registry.names()}  enrichment.active={enrichment.active} kb.active={kb.active}")

    client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
    loop = AgentLoop(registry, _Store(), mode="native_tools", workspace_id=WORKSPACE, max_steps=4)

    claims = []

    async def claim() -> bool:
        claims.append(1)
        return True

    prompt = "Is 185.220.101.5 malicious? Check the threat intel and tell me what you find."
    order = []
    steps = []
    content_deltas = 0
    try:
        async for ev in loop.run_stream(client, prompt, claim=claim):
            order.append(ev.kind)
            steps.append(ev.step)
            if ev.kind == "tool":
                inv = ev.invocation
                keys = list(inv.feedback) if isinstance(inv.feedback, dict) else "?"
                print(f"  [tool ] {inv.name} status={inv.status} feedback_keys={keys}")
            elif ev.kind == "content":
                content_deltas += 1
            elif ev.kind == "usage":
                print(f"  [usage] {ev.usage}")
            elif ev.kind == "done":
                print(f"  [done ] stop_reason={ev.stop_reason} finish={ev.finish_reason}")
                print(f"  answer: {ev.text[:300]!r}")
    finally:
        await client.aclose()
        await enrichment.aclose()

    print(f"\nevent order: {order}")
    tool_at = [i for i, k in enumerate(order) if k == "tool"]
    content_at = [i for i, k in enumerate(order) if k == "content"]
    steps_seen = len(set(steps))
    print(f"tool events: {len(tool_at)}  content deltas: {content_deltas}  "
          f"claims: {len(claims)}  model calls (distinct steps): {steps_seen}")

    assert tool_at, "no tool was called — this measures nothing about ordering"
    assert content_at, "no content streamed"
    assert max(tool_at) < min(content_at), f"prose preceded a tool result: {order}"
    assert content_deltas > 1, f"answer did not stream ({content_deltas} delta)"
    assert len(claims) == steps_seen, f"claims={len(claims)} but {steps_seen} model calls"
    print("\nOK — tool steps preceded the answer, the answer streamed, every call claimed")


asyncio.run(main())
