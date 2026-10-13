"""B2 — the thinking floor (D-040) re-measured against TODAY's issued text (TD-044).

docs/probes/s26-step0/probe_calibrate_agent.py measured it at S26, indexing
`loop.system_message(specs)`. The route has since grown D-045's action surface
and indexes `loop.issued_instructions(loop.wire_specs())` (chat.py:852-892), so
this probe composes the turn exactly as the route does today:

  - the same capability registry (enrichment, KB, the message's observables);
  - D-045's action manifest on the wire, from the same `ActionRegistry` the app
    builds, with a proposer that files nothing (it declines, as D-045's dry run
    does for an action that would change nothing);
  - the same history (`_agent_history`) and the same `issued` list.

No rail runs: every turn completes, so a run is measured at its full length,
not at the floor that would have cut it. Every channel the route scans is
measured separately against that `issued` list:

  - thinking   (the model's own reasoning; floor THINKING_SHINGLE_WORDS = 40)
  - narration  (the agent's prose between tools; floor SHINGLE_WORDS = 8)
  - content    (the answer; 8)
  - tool       (the rendered tool lines; 8)

Batteries:
  - s26-legit: S26's 12 hard-legit questions (the original calibration);
  - blind-def / blind-ti: battery-blind.json, written by a subagent that never
    read the repo (B2), concept/definition and threat-intel questions;
  - b002: B-002's own question;
  - recite: S26's two recitations (the upper side).

Raw text goes to raw-calibrate-thinking.jsonl (dev-model output on our own
questions). Do NOT run pytest at the same time.

Run:  .venv/bin/python docs/probes/b2-b002/probe_calibrate_thinking.py
"""

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()
os.environ["KB_ENABLED"] = "true"
os.environ["ENRICHMENT_ENABLED"] = "true"

from auspex.actions.builtin import build_builtin_actions  # noqa: E402
from auspex.actions.registry import ActionRegistry  # noqa: E402
from auspex.actions.settlement import NothingToPropose  # noqa: E402
from auspex.agent.capabilities import build_capability_registry  # noqa: E402
from auspex.agent.loop import AgentLoop  # noqa: E402
from auspex.classify import classify  # noqa: E402
from auspex.config import Settings  # noqa: E402
from auspex.enrich import EnrichmentService  # noqa: E402
from auspex.kb import KnowledgeService  # noqa: E402
from auspex.llm.client import LLMClient  # noqa: E402
from auspex.modes import contract_for, resolve_mode  # noqa: E402
from auspex.outguard import (  # noqa: E402
    SHINGLE_WORDS,
    THINKING_SHINGLE_WORDS,
    _words,
    instruction_index,  # noqa: E402
)
from auspex.routes.chat import (  # noqa: E402
    CHAT_ANSWER_MAX_TOKENS,
    CODE_DECIDED_MODES,
    HISTORY_FENCE_DIRECTIVE,
    _agent_history,
    _tool_frame,
)

HERE = Path(__file__).resolve().parent
WORKSPACE = "00000000-0000-0000-0000-000000000001"
FLOORS = {"thinking": THINKING_SHINGLE_WORDS, "narration": SHINGLE_WORDS,
          "content": SHINGLE_WORDS, "tool": SHINGLE_WORDS}


def _s26():
    spec = importlib.util.spec_from_file_location(
        "s26cal", HERE.parent / "s26-step0" / "probe_calibrate_agent.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.HARD_LEGIT, mod.RECITE


class _Store:
    async def create(self, **kw):
        return {"id": "probe", "card": {}}


async def _decline(*, spec, arguments, workspace_id, session_id=None):
    raise NothingToPropose("calibration probe: nothing is filed")


def longest_run(text: str, instructions: list[str]) -> tuple[int, str]:
    words = _words(text)
    best, found = 0, ""
    for width in range(2, min(160, len(words)) + 1):
        index = instruction_index(instructions, shingle=width)
        hit = next((" ".join(words[i:i + width]) for i in range(len(words) - width + 1)
                    if " ".join(words[i:i + width]) in index), None)
        if hit is None:
            break
        best, found = width, hit
    return best, found


def attribute(run: str, issued: list[str]) -> str:
    n = len(run.split())
    hits = [" ".join(_words(t)[:6]) for t in issued
            if n and run in instruction_index([t], shingle=n)]
    return " | ".join(hits)


async def one(client, enrichment, kb, manifest, question: str) -> dict:
    classification = classify(question)
    mode = resolve_mode(question, classification.observables)
    contract = contract_for(mode)
    loop = AgentLoop(
        build_capability_registry(enrichment=enrichment, kb=kb,
                                  observables=classification.observables),
        _Store(), mode="native_tools", workspace_id=WORKSPACE,
        max_tokens=CHAT_ANSWER_MAX_TOKENS, actions=manifest, action_proposer=_decline,
    )
    issued = [*loop.issued_instructions(loop.wire_specs()), HISTORY_FENCE_DIRECTIVE,
              contract.system_directive()]
    history = _agent_history([], contract.system_directive())
    text = {"thinking": [], "narration": [], "content": [], "tool": []}
    done = None
    async for ev in loop.run_stream(client, question, history=history):
        if ev.kind == "reasoning":
            text["thinking"].append(ev.text)
        elif ev.kind == "narration":
            text["narration"].append(ev.text)
        elif ev.kind == "content":
            text["content"].append(ev.text)
        elif ev.kind == "tool":
            frame = _tool_frame(ev.invocation)
            text["tool"].append(frame["call"] + ("\n" + frame["proposal"]["summary"]
                                                 if "proposal" in frame else ""))
        elif ev.kind == "done":
            done = ev
    joined = {ch: ("\n".join(parts) if ch == "tool" else "".join(parts))
              for ch, parts in text.items()}
    runs = {}
    for ch, t in joined.items():
        n, run = longest_run(t, issued)
        runs[ch] = {"len": n, "run": run, "from": attribute(run, issued) if run else "",
                    "trips": n >= FLOORS[ch]}
    return {"mode": mode.value, "route_path": "model" if mode in CODE_DECIDED_MODES else "agent",
            "stop": getattr(done, "stop_reason", None), "tools": len(text["tool"]),
            "runs": runs, "text": joined}


async def main(args) -> None:
    battery = json.loads((HERE / "battery-blind.json").read_text())
    s26_legit, s26_recite = _s26()
    b002 = ["What are the practical differences between EDR and XDR for a small SOC "
            "deciding what to buy?"]
    groups = [("s26-legit", s26_legit), ("blind-def", battery["definition_like"]),
              ("blind-ti", battery["threat_intel_like"]), ("b002", b002 * args.b002_runs),
              ("recite", s26_recite)]
    if args.only:
        groups = [g for g in groups if g[0] in args.only.split(",")]
    s = Settings()
    enrichment = EnrichmentService.from_settings(s)
    kb = KnowledgeService.from_settings(s)
    registry = ActionRegistry()
    registry.register_all(build_builtin_actions(None))  # specs only; nothing executes
    manifest = registry.manifest("native_tools")
    client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
    print(f"model={s.llm_model} kb.active={kb.active} enrichment.active={enrichment.active}")
    out = (HERE / f"raw-calibrate-thinking{args.suffix}.jsonl").open("w")
    try:
        for label, questions in groups:
            for q in questions:
                try:
                    r = await one(client, enrichment, kb, manifest, q)
                except Exception as exc:  # noqa: BLE001
                    print(f"[{label}] ERR {type(exc).__name__}: {q[:60]}", flush=True)
                    continue
                summary = "  ".join(f"{ch}={v['len']}{'!' if v['trips'] else ''}"
                                    for ch, v in r["runs"].items())
                print(f"[{label}] {r['mode']}/{r['route_path']} stop={r['stop']} "
                      f"tools={r['tools']}  {summary}  :: {q[:60]}", flush=True)
                for ch, v in r["runs"].items():
                    if v["len"] >= (20 if ch == "thinking" else 6):
                        print(f"      {ch} {v['len']} from [{v['from']}]: {v['run']!r}",
                              flush=True)
                out.write(json.dumps({"group": label, "question": q, **r}) + "\n")
                out.flush()
    finally:
        out.close()
        await client.aclose()
        if hasattr(enrichment, "aclose"):
            await enrichment.aclose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--only", default="")
    p.add_argument("--b002-runs", type=int, default=2)
    p.add_argument("--suffix", default="")
    asyncio.run(main(p.parse_args()))
