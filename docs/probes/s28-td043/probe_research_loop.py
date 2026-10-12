"""S28 — TD-043, measured first: what did the agent get back each time it
searched again?

S27 measured 4 of 6 `threat_intel` agent turns making 8 `search_knowledge`
calls plus the synthesis pass. TD-043 lists three fixes, and which one is right
depends on what the re-searches RETURNED, which nobody recorded:
- misses (`results: []`): the KB has nothing, and rewording will not help;
- the same documents again: the model is paraphrasing into the same hits;
- near-misses: new documents each time, so the model is (rationally) still
  finding things.

Same prompts as S27 (`docs/probes/s27-td012/probe_contract_drift.py`, the
THREAT_INTEL list), same composition (`AgentLoop` with the platform's READ
tools, `_agent_history`). `search_knowledge` is wrapped to record each query and
the documents it returned; the handler itself runs unchanged.

Live against the primary dev endpoint, from the host, no route, no
usage_counters, no shared user. About 6 turns x up to 9 calls.

Run:  .venv/bin/python docs/probes/s28-td043/probe_research_loop.py [REPEATS] [LABEL] [BUDGET]
"""

import asyncio
import dataclasses
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
from auspex.classify import classify, shortcut_answer  # noqa: E402
from auspex.config import Settings  # noqa: E402
from auspex.enrich import EnrichmentService  # noqa: E402
from auspex.kb import KnowledgeService  # noqa: E402
from auspex.llm.client import LLMClient  # noqa: E402
from auspex.modes import Mode, contract_for, resolve_mode  # noqa: E402
from auspex.routes.chat import CHAT_ANSWER_MAX_TOKENS, _agent_history  # noqa: E402

WORKSPACE = "00000000-0000-0000-0000-000000000001"
REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 2
LABEL = sys.argv[2] if len(sys.argv) > 2 else "before"
# Optional: measure a different search budget without editing the code constant.
BUDGET = int(sys.argv[3]) if len(sys.argv) > 3 else None
CONCURRENCY = 3

# Verbatim from S27's probe — the before/after must be the same prompts.
PROMPTS = [
    "What do we know about LockBit 3.0's initial access techniques, and how "
    "should a mid-size bank prioritise its defences against them?",
    "How do ransomware groups typically abuse remote monitoring and management "
    "tools after initial access?",
    "We found a scheduled task created by an Office macro on a finance "
    "workstation. Which ATT&CK techniques does that map to, and what should I "
    "check next?",
]


class _Store:
    async def create(self, **kw):  # READ tools only; never called
        return {"id": "probe", "card": {}}


def _doc_key(hit: dict) -> str:
    return hit.get("source_ref") or hit.get("title") or "?"


async def run_turn(client, enrichment, kb, message):
    c = classify(message)
    mode = resolve_mode(message, c.observables)
    contract = contract_for(mode)
    if BUDGET is not None:
        import auspex.agent.capabilities as caps
        caps.SEARCH_KNOWLEDGE_MAX_CALLS = BUDGET
    registry = build_capability_registry(
        enrichment=enrichment, kb=kb, observables=c.observables, supplied=c.observables
    )
    searches: list[dict] = []
    tool = registry.get("search_knowledge")
    inner = tool.handler

    async def recorded(args: dict) -> dict:
        out = await inner(args)
        searches.append({
            "query": str(args.get("query") or ""),
            "docs": [_doc_key(h) for h in out.get("results", [])],
            "miss": "miss" in out,
            "error": out.get("error"),
        })
        return out

    registry._tools["search_knowledge"] = dataclasses.replace(tool, handler=recorded)
    loop = AgentLoop(registry, _Store(), mode="native_tools", workspace_id=WORKSPACE,
                     max_tokens=CHAT_ANSWER_MAX_TOKENS)
    history = _agent_history([], contract.system_directive())
    done, calls, tools = None, 0, []
    async for ev in loop.run_stream(client, message, history=history):
        if ev.kind == "usage":
            calls += 1
        elif ev.kind == "tool":
            inv = ev.invocation
            refused = inv.status == "error" and inv.feedback.get("error") == "call_limit"
            tools.append(inv.name + (":REFUSED" if refused else ""))
        elif ev.kind == "done":
            done = ev
    answer = "" if done.stop_reason == "empty_answer" else (done.text or "")
    res = contract.validate(answer, pinned=None) if answer else None
    return mode, done, calls, tools, searches, res


async def main() -> None:
    s = Settings()
    enrichment = EnrichmentService.from_settings(s)
    kb = KnowledgeService.from_settings(s)
    client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
    print(f"S28 — TD-043 [{LABEL}]: what each re-search returned")
    print("=" * 78)
    print(f"model: {s.llm_model}  repeats: {REPEATS}  kb={kb.active}")
    for i, p in enumerate(PROMPTS):
        c = classify(p)
        assert shortcut_answer(c) is None, f"CONTROL FAILED: [{i}] takes the shortcut"
        assert resolve_mode(p, c.observables) is Mode.THREAT_INTEL, f"CONTROL FAILED: [{i}]"
    jobs = [(i, r, p) for i, p in enumerate(PROMPTS) for r in range(REPEATS)]
    print(f"control passed: {len(jobs)} agent turns planned\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    rows = []

    async def one(job):
        i, r, p = job
        async with sem:
            t0 = time.monotonic()
            try:
                out = await run_turn(client, enrichment, kb, p)
            except Exception as err:  # an endpoint failure is a result
                print(f"[{i}] #{r}: ERROR {type(err).__name__}", flush=True)
                rows.append((i, r, None))
                return
            rows.append((i, r, out))
            mode, done, calls, tools, searches, res = out
            seen: set[str] = set()
            lines = []
            for n, srch in enumerate(searches, 1):
                new = [d for d in srch["docs"] if d not in seen]
                seen.update(srch["docs"])
                kind = ("ERROR " + str(srch["error"]) if srch["error"] else
                        "MISS" if srch["miss"] else
                        "SAME" if not new else f"+{len(new)} new")
                lines.append(f"    s{n}: {kind:10} n={len(srch['docs'])} q={srch['query']!r}\n"
                             f"         docs={srch['docs']}")
            print(f"[{i}] #{r}: calls={calls} steps={done.step} stop={done.stop_reason} "
                  f"searches={len(searches)} distinct_docs={len(seen)} "
                  f"contract={'ok' if res and res.ok else (res.reason() if res else 'EMPTY')} "
                  f"tools={tools} {time.monotonic() - t0:.1f}s\n" + "\n".join(lines),
                  flush=True)

    try:
        await asyncio.gather(*(one(j) for j in jobs))
    finally:
        await client.aclose()
        if hasattr(enrichment, "aclose"):
            await enrichment.aclose()

    print("\n" + "=" * 78)
    ok = [x for x in rows if x[2] is not None]
    tot_calls = sum(x[2][2] for x in ok)
    all_s = [srch for x in ok for srch in x[2][4]]
    print(f"turns={len(ok)} total_calls={tot_calls} mean_calls={tot_calls / max(1, len(ok)):.1f} "
          f"searches={len(all_s)} cap_hits={sum(1 for x in ok if x[2][1].stop_reason == 'step_cap')}")
    kinds = {"MISS": 0, "SAME": 0, "NEW": 0, "ERROR": 0}
    for x in ok:
        seen: set[str] = set()
        for srch in x[2][4]:
            new = [d for d in srch["docs"] if d not in seen]
            seen.update(srch["docs"])
            kinds["ERROR" if srch["error"] else "MISS" if srch["miss"] else
                  "SAME" if not new else "NEW"] += 1
    print(f"re-search outcomes: {kinds}")
    for i in range(len(PROMPTS)):
        mine = [x for x in ok if x[0] == i]
        print(f"  prompt[{i}]: calls={[x[2][2] for x in mine]} "
              f"searches={[len(x[2][4]) for x in mine]} "
              f"contract={[('ok' if x[2][5] and x[2][5].ok else 'x') for x in mine]}")


if __name__ == "__main__":
    asyncio.run(main())
