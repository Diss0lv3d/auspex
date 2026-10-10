"""S26 — the ROUTING decision, measured before it is trusted.

S25 measured that offering tools changes what the model does with questions the
tools do not cover: asked for "a status update for my manager", Scout refused —
"the functions provided are insufficient" — with a system message telling it to
answer anyway. So "route every deep turn through the agent loop" was taken to be
wrong, and NEXT-SESSION requires whichever routing rule replaces it to have its
own measurement.

**The proposed rule (code decides, ADR 0006):**

    A deep turn takes the AGENT path iff
      (1) code has not already decided the answer's verdict
          (mode is not ALERT_TRIAGE / PHISHING_ANALYSIS), AND
      (2) the classifier found at least one observable the tools can act on.

**Re-run 2026-10-10 on glm-4.5-air (D-034).** Written against Scout on
2026-08-16; Scout is gone. Three things changed for the re-run, none of them the
rule: REPEATS (one run decided nothing at S25 and should not decide this), a
case C (below), and per-step accounting — on this endpoint prose precedes a tool
call (TD-036, probe record 2026-10-10 Finding 9), so the content of a
tool-calling step is NARRATION and is reported apart from the answer.

**A — is the refusal CAUSED by the tool offer?** Same no-tool question, tools on
vs off. If the model answers it either way, clause (2) is not protecting
anything from a refusal.

**B — does the rule's POSITIVE case work, and is it multi-step?** Every
measured turn before S26 was ONE tool call (STATE.md blocker 3). An observable
plus a broader ask is the case the rule routes to the agent. Does the model
chain tools, stop when it has enough, and write the answer from tool DATA?

**C — what does the rule's NEGATIVE case cost?** Added at the re-run. Clause (2)
sends a security question with NO observable down the conversational path, which
has no retrieval at all (chat.py's deep path is one model call over history). If
the model, offered tools, reaches for `search_knowledge` on such a question and
grounds its answer in the KB, then clause (2) is withholding the KB from exactly
the questions it serves — and the rule should be judged on that, not only on A.

Live against the primary dev endpoint. No route, no usage_counters.

Run:  .venv/bin/python docs/probes/s26-step0/probe_routing.py
"""

import asyncio
import os
import sys

sys.path.insert(0, "/home/burhan/auspex-new")

# `.env` carries compose-internal hostnames that do not resolve from the host,
# and the hermetic defaults switch the KB and enrichment OFF. Without this the
# tools "work" and honestly report misses, which reads exactly like a model
# failing to find anything — the first run of this probe lost CVE-2021-44228
# that way. Live host checks override, per the devhost docstring.
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
from auspex.modes.resolver import resolve_mode  # noqa: E402

WORKSPACE = "00000000-0000-0000-0000-000000000001"
REPEATS = 3

# The question no tool answers — S25's control prompt, reused verbatim so this
# measurement is comparable to that one rather than merely similar.
NO_TOOL_PROMPT = "Write me a status update for my manager about this week."

# The rule's positive case: an observable present AND a question broader than a
# bare reputation check, which is what a DEEP turn carrying an IOC looks like
# (a bare check is answered by the 92/8 shortcut and never reaches here).
MULTI_STEP_PROMPT = (
    "Is 185.220.101.5 involved in anything related to CVE-2021-44228? "
    "Check the indicator and the CVE, then tell me whether they connect."
)

# The rule's negative case: a security question with no observable, which the
# KB can speak to and the conversational path cannot consult.
NO_OBSERVABLE_PROMPT = (
    "We found a scheduled task created by an Office macro on a finance "
    "workstation. Which ATT&CK techniques does that map to, and what should I "
    "check next?"
)


class _Store:
    async def create(self, **kw):
        return {"id": "probe", "card": {}}


async def ask(client, registry, prompt, *, with_tools: bool, max_steps=4):
    """One turn through the real loop. `with_tools=False` offers none, which is
    what the conversational deep path does today."""
    loop = AgentLoop(registry, _Store(), mode="native_tools",
                     workspace_id=WORKSPACE, max_steps=max_steps)
    tool_names = None if with_tools else []
    calls, order, reasoning, done = [], [], 0, None
    tool_steps: set[int] = set()
    content_by_step: dict[int, list[str]] = {}
    async for ev in loop.run_stream(client, prompt, tool_names=tool_names):
        order.append((ev.kind, ev.step))
        if ev.kind == "tool":
            inv = ev.invocation
            calls.append((inv.name, inv.arguments, inv.status, ev.step))
            tool_steps.add(ev.step)
        elif ev.kind == "content":
            content_by_step.setdefault(ev.step, []).append(ev.text)
        elif ev.kind == "reasoning":
            reasoning += len(ev.text)
        elif ev.kind == "done":
            done = ev
    narration = {k: "".join(v) for k, v in content_by_step.items() if k in tool_steps}
    return {
        "tools_offered": len(loop.wire_specs(tool_names)),
        "calls": calls,
        # What the route would persist: the done event's text (the last call's).
        "answer": (done.text or "").strip(),
        "stop_reason": done.stop_reason,
        "finish_reason": done.finish_reason,
        "steps": done.step,
        "reasoning_chars": reasoning,
        "narration": narration,
        "order": order,
    }


REFUSAL_MARKERS = ("insufficient", "unable to fulfill", "cannot fulfill",
                   "functions provided", "no function", "not able to")


def looks_like_refusal(answer: str) -> bool:
    low = answer.lower()
    return any(m in low for m in REFUSAL_MARKERS)


def report(label: str, r: dict) -> None:
    print(f"    {label} offered={r['tools_offered']} steps={r['steps']} "
          f"stop={r['stop_reason']} finish={r['finish_reason']} "
          f"reasoning={r['reasoning_chars']} answer={len(r['answer'])} "
          f"refusal-shaped={looks_like_refusal(r['answer'])}")
    for name, args, status, step in r["calls"]:
        print(f"        step {step}: {name}({args}) -> {status}")
    for step, text in sorted(r["narration"].items()):
        print(f"        narration, step {step} ({len(text)} chars): {text[:160]!r}")
    print(f"        answer: {r['answer'][:500]!r}")


async def main() -> None:
    s = Settings()
    enrichment = EnrichmentService.from_settings(s)
    kb = KnowledgeService.from_settings(s)
    registry = build_capability_registry(enrichment=enrichment, kb=kb)
    client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)

    print("S26 — the routing decision, measured")
    print("=" * 78)
    print(f"model: {s.llm_model}   repeats: {REPEATS}")
    print(f"tools: {registry.names()}  enrichment.active={enrichment.active} "
          f"kb.active={kb.active}\n")

    # ── the rule's own inputs, computed by CODE, before any model call ───────
    print("[0] what the rule decides, per prompt (no model involved)")
    for label, prompt in (("A no-tool question", NO_TOOL_PROMPT),
                          ("B observable + broader ask", MULTI_STEP_PROMPT),
                          ("C no observable, KB-shaped", NO_OBSERVABLE_PROMPT)):
        c = classify(prompt)
        deep = shortcut_answer(c) is None
        mode = resolve_mode(prompt, c.observables)
        actionable = [o.value for o in c.observables]
        agent = deep and mode.value not in ("alert_triage", "phishing_analysis") and bool(actionable)
        print(f"    {label:28} category={c.category.value:10} deep={deep} "
              f"mode={mode.value:16} observables={actionable} -> "
              f"{'AGENT' if agent else 'conversational'}")
    print()

    try:
        # ── A: is the refusal caused by the tool offer? ──────────────────────
        print("[A] the same no-tool question, tools ON vs tools OFF")
        for i in range(1, REPEATS + 1):
            on = await ask(client, registry, NO_TOOL_PROMPT, with_tools=True)
            off = await ask(client, registry, NO_TOOL_PROMPT, with_tools=False)
            assert on["tools_offered"] == 3, f"CONTROL FAILED: {on['tools_offered']} offered"
            assert off["tools_offered"] == 0, f"CONTROL FAILED: {off['tools_offered']} offered"
            print(f"  run {i}")
            report("tools ON ", on)
            report("tools OFF", off)

        # ── B: the rule's positive case, and multi-step ─────────────────────
        print("\n[B] observable + broader ask, through the agent path")
        for i in range(1, REPEATS + 1):
            r = await ask(client, registry, MULTI_STEP_PROMPT, with_tools=True)
            print(f"  run {i}: distinct tools {sorted({c[0] for c in r['calls']})}")
            report("agent    ", r)
            kinds = [k for k, _ in r["order"]]
            last_tool = max((j for j, k in enumerate(kinds) if k == "tool"), default=None)
            answer_steps = {st for k, st in r["order"] if k == "content"} - set(r["narration"])
            first_answer = next((j for j, (k, st) in enumerate(r["order"])
                                 if k == "content" and st in answer_steps), None)
            print(f"        ordering: last tool idx={last_tool}, first ANSWER content "
                  f"idx={first_answer} (tools before the answer: "
                  f"{last_tool is not None and first_answer is not None and last_tool < first_answer})")

        # ── C: the rule's negative case ─────────────────────────────────────
        print("\n[C] no observable, KB-shaped — what clause (2) withholds")
        for i in range(1, REPEATS + 1):
            on = await ask(client, registry, NO_OBSERVABLE_PROMPT, with_tools=True)
            off = await ask(client, registry, NO_OBSERVABLE_PROMPT, with_tools=False)
            print(f"  run {i}")
            report("tools ON ", on)
            report("tools OFF", off)
    finally:
        await client.aclose()
        if hasattr(enrichment, "aclose"):
            await enrichment.aclose()

    print("\n" + "=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
