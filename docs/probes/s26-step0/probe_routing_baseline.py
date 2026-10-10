"""S26 — case C again, against the paths the ROUTE would actually run.

`probe_routing.py` case C compared tools ON vs OFF through `AgentLoop` with the
loop's own system message — which says "Use the provided tools" even when none
are offered. Its tools-OFF side therefore is NOT today's conversational path,
and one of its three runs fabricated a tool call as prose (a fenced
`get_attck_techniques()`), which the real path's prompt may never provoke. A
comparison that decides a routing rule has to be against the real thing.

So both sides here are composed the way `/api/chat` composes a fresh session's
deep turn (auspex/routes/chat.py `_history` + the mode directive):

  CONVERSATIONAL  — today's native path, verbatim: [CHAT_SYSTEM_PROMPT,
                    HISTORY_FENCE_DIRECTIVE, user, contract directive], one
                    `chat_stream` at CHAT_ANSWER_MAX_TOKENS.
  AGENT           — what the wiring would send: the loop's system message, then
                    [HISTORY_FENCE_DIRECTIVE, contract directive] as history,
                    then the user turn; tools on; CHAT_ANSWER_MAX_TOKENS per call
                    (reuse the cap, never re-declare it).

Both answers are run through the mode's contract validator — the agent path
must not lose conformance to gain grounding. A control (A, the no-tool
question) runs once through the agent composition, because the full
composition is not what `probe_refusal_cause.py` measured.

Run:  .venv/bin/python docs/probes/s26-step0/probe_routing_baseline.py
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
os.environ["KB_ENABLED"] = "true"
os.environ["ENRICHMENT_ENABLED"] = "true"

from auspex.agent.capabilities import build_capability_registry  # noqa: E402
from auspex.agent.loop import AgentLoop  # noqa: E402
from auspex.classify import classify  # noqa: E402
from auspex.config import Settings  # noqa: E402
from auspex.enrich import EnrichmentService  # noqa: E402
from auspex.kb import KnowledgeService  # noqa: E402
from auspex.llm.client import LLMClient  # noqa: E402
from auspex.modes import contract_for, resolve_mode  # noqa: E402
from auspex.routes.chat import (  # noqa: E402
    CHAT_ANSWER_MAX_TOKENS,
    CHAT_SYSTEM_PROMPT,
    HISTORY_FENCE_DIRECTIVE,
)

WORKSPACE = "00000000-0000-0000-0000-000000000001"
REPEATS = 3

NO_TOOL_PROMPT = "Write me a status update for my manager about this week."
NO_OBSERVABLE_PROMPT = (
    "We found a scheduled task created by an Office macro on a finance "
    "workstation. Which ATT&CK techniques does that map to, and what should I "
    "check next?"
)


class _Store:
    async def create(self, **kw):
        return {"id": "probe", "card": {}}


def _contract(prompt: str):
    mode = resolve_mode(prompt, classify(prompt).observables)
    return mode, contract_for(mode)


async def conversational(client, prompt: str) -> dict:
    mode, contract = _contract(prompt)
    messages = [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT},
        {"role": "system", "content": HISTORY_FENCE_DIRECTIVE},
        {"role": "user", "content": prompt},
        {"role": "system", "content": contract.system_directive()},
    ]
    t0 = time.monotonic()
    content, reasoning, finish = [], 0, None
    async for ev in client.chat_stream(messages, max_tokens=CHAT_ANSWER_MAX_TOKENS, temperature=0):
        if ev.kind == "content":
            content.append(ev.text)
        elif ev.kind == "reasoning":
            reasoning += len(ev.text)
        elif ev.kind == "finish":
            finish = ev.finish_reason
    answer = "".join(content).strip()
    v = contract.validate(answer) if answer else None
    return {"mode": mode.value, "wall": time.monotonic() - t0, "calls": [], "finish": finish,
            "reasoning": reasoning, "answer": answer,
            "contract": (v.ok if v else None), "reason": (v.reason() if v and not v.ok else "")}


async def agent(client, registry, prompt: str) -> dict:
    mode, contract = _contract(prompt)
    loop = AgentLoop(registry, _Store(), mode="native_tools", workspace_id=WORKSPACE,
                     max_tokens=CHAT_ANSWER_MAX_TOKENS)
    history = [
        {"role": "system", "content": HISTORY_FENCE_DIRECTIVE},
        {"role": "system", "content": contract.system_directive()},
    ]
    t0 = time.monotonic()
    calls, reasoning, done, model_calls = [], 0, None, 0
    async for ev in loop.run_stream(client, prompt, history=history):
        if ev.kind == "tool":
            calls.append((ev.step, ev.invocation.name, ev.invocation.arguments, ev.invocation.status))
        elif ev.kind == "reasoning":
            reasoning += len(ev.text)
        elif ev.kind == "usage":
            model_calls += 1
        elif ev.kind == "done":
            done = ev
    answer = (done.text or "").strip()
    v = contract.validate(answer) if answer else None
    return {"mode": mode.value, "wall": time.monotonic() - t0, "calls": calls,
            "finish": done.finish_reason, "stop": done.stop_reason, "steps": done.step,
            "model_calls": model_calls, "reasoning": reasoning, "answer": answer,
            "contract": (v.ok if v else None), "reason": (v.reason() if v and not v.ok else "")}


def report(label: str, r: dict) -> None:
    extra = f" stop={r['stop']} steps={r['steps']} usage_events={r['model_calls']}" if "stop" in r else ""
    print(f"    {label} mode={r['mode']} wall={r['wall']:.1f}s finish={r['finish']}{extra} "
          f"reasoning={r['reasoning']} answer={len(r['answer'])} contract_valid={r['contract']} "
          f"{r['reason']}")
    for step, name, args, status in r["calls"]:
        print(f"        step {step}: {name}({args}) -> {status}")
    print(f"        answer: {r['answer'][:1500]!r}")


async def main() -> None:
    s = Settings()
    enrichment = EnrichmentService.from_settings(s)
    kb = KnowledgeService.from_settings(s)
    registry = build_capability_registry(enrichment=enrichment, kb=kb)
    client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
    print("S26 — case C against the route's own compositions")
    print("=" * 78)
    print(f"model: {s.llm_model}  kb.active={kb.active}  max_tokens={CHAT_ANSWER_MAX_TOKENS}\n")
    try:
        print("[C] no observable, KB-shaped")
        for i in range(1, REPEATS + 1):
            print(f"  run {i}")
            report("CONVERSATIONAL", await conversational(client, NO_OBSERVABLE_PROMPT))
            report("AGENT         ", await agent(client, registry, NO_OBSERVABLE_PROMPT))
        print("\n[A] control — the no-tool question, agent composition")
        report("AGENT         ", await agent(client, registry, NO_TOOL_PROMPT))
    finally:
        await client.aclose()
        if hasattr(enrichment, "aclose"):
            await enrichment.aclose()
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
