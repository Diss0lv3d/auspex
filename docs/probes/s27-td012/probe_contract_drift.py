"""S27 — TD-012(b) step 1: how often does the engine actually drift from each
mode's contract, on both deep paths?

TD-012(b) has been carried since S9 on the premise that a non-conforming answer
is a problem worth repairing. Nobody has measured how often it happens on the
dev endpoint. This does, before any repair is designed.

**What is measured.** For every mode, a few prompts that the CODE routes to it
(asserted before a single call is made — a prompt that lands elsewhere aborts
the run), each run REPEATS times on:
- the conversational path: the composition `/api/chat` sends on a native-
  reasoning endpoint (one call, `_history` + mode directive + the deterministic
  verdict block for alert/phishing), and
- the agent path: the composition `/api/chat` sends on a native_tools endpoint
  (`AgentLoop` with the platform's READ tools, `_agent_history`), for the modes
  D-037 lets reach it. ALERT_TRIAGE and PHISHING_ANALYSIS never do (clause 1),
  so they are measured on the conversational path only — which is where they
  run in production.

Every answer is validated with the turn's own contract and, for alert/phishing,
the same `pinned` values the route computes. The result is the denominator
TD-012(b) has never had.

**The known-failing control** (IDEAS.md): a non-security question resolves to
`threat_intel` and cannot meet its contract. It is run and reported apart, so it
neither inflates nor hides the drift rate on real security questions.

Composition is imported from `auspex.routes.chat` wherever the route exposes it
(`_history`, `_agent_history`, the prompts, the budgets); what the route inlines
(the verdict blocks, the pins) is mirrored line for line from chat.py.

Live against the primary dev endpoint, from the host. No route, no
usage_counters, no shared user — safe to run alongside nothing else that spends.

Run:  .venv/bin/python docs/probes/s27-td012/probe_contract_drift.py [REPEATS]
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
from auspex.alerts import normalize, score_alert  # noqa: E402
from auspex.alerts.render import deterministic_triage_block  # noqa: E402
from auspex.classify import classify, shortcut_answer  # noqa: E402
from auspex.config import Settings  # noqa: E402
from auspex.enrich import EnrichmentService  # noqa: E402
from auspex.kb import KnowledgeService  # noqa: E402
from auspex.llm.client import LLMClient  # noqa: E402
from auspex.modes import Mode, contract_for, resolve_mode  # noqa: E402
from auspex.phishing import decide_verdict, deterministic_phishing_block, parse_email  # noqa: E402
from auspex.routes.chat import (  # noqa: E402
    CHAT_ANSWER_MAX_TOKENS,
    CODE_DECIDED_MODES,
    _agent_history,
    _history,
)

WORKSPACE = "00000000-0000-0000-0000-000000000001"
REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 2
CONCURRENCY = 3

PROMPTS: dict[Mode, list[str]] = {
    Mode.ALERT_TRIAGE: [
        "CEF:0|Trellix|ENS|10.7|1201|Malware detected|9|src=10.1.2.3 "
        "cs1=powershell -enc SQBFAFgA externalId=T1059.001 confidence=90",
        # signal-poor: the DEFERRED rail's case
        '{"alert": "Unusual activity", "host": "ws-12", "user": "jdoe"}',
        "<134>Oct 10 02:00:01 fw01 kernel: DROP IN=eth0 SRC=185.220.101.5 "
        "DST=10.0.0.5 PROTO=TCP DPT=445 severity=medium",
    ],
    Mode.PHISHING_ANALYSIS: [
        "From: \"PayPal Security\" <security@paypa1-support.com>\n"
        "Reply-To: verify@mail-paypa1.ru\n"
        "To: alice@example.org\n"
        "Subject: Urgent: your account is limited\n"
        "Authentication-Results: mx.example.org; spf=fail; dkim=none; dmarc=fail\n\n"
        "Your account has been limited. Verify within 24 hours at "
        "http://paypa1-support.com/verify or it will be closed.",
        # sparse: the DEFERRED rail's case
        "From: someone@example.net\nTo: bob@example.org\nSubject: hi\n\n",
        "From: IT Newsletter <news@example.org>\n"
        "To: all-staff@example.org\n"
        "Subject: October security newsletter\n"
        "Authentication-Results: mx.example.org; spf=pass; dkim=pass; dmarc=pass\n\n"
        "This month: patch Tuesday reminders and how to report phishing.",
    ],
    Mode.IOC_ENRICHMENT: [
        "Our WAF logged 185.220.101.5 sending ${jndi:ldap://x} strings to the payroll "
        "app at 02:00. Is that Log4Shell exploitation and how worried should I be?",
        "Host fin-ws-07 beaconed to 45.155.205.233 every 60 seconds overnight over "
        "HTTPS. What does that pattern suggest and what should we do first?",
        "A user downloaded a file with SHA256 "
        "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f "
        "from a shared link. How should we handle it?",
    ],
    Mode.THREAT_INTEL: [
        "What do we know about LockBit 3.0's initial access techniques, and how "
        "should a mid-size bank prioritise its defences against them?",
        "How do ransomware groups typically abuse remote monitoring and management "
        "tools after initial access?",
        "We found a scheduled task created by an Office macro on a finance "
        "workstation. Which ATT&CK techniques does that map to, and what should I "
        "check next?",
    ],
    Mode.BRIEF: [
        "Give me a quick brief on ransomware targeting hospitals this year.",
        "Summarize the main risks of exposing RDP to the internet for our CISO.",
        "Write me a report-style rundown of why MFA fatigue attacks work.",
    ],
    Mode.DEFINITION: [
        "What is the difference between kerberoasting and AS-REP roasting, and how "
        "would I detect each one in Active Directory logs?",
        "What's a living-off-the-land binary, and why do EDR tools struggle to flag "
        "them reliably?",
        "What are the practical differences between EDR and XDR for a small SOC "
        "deciding what to buy?",
    ],
}

CONTROL = "Write me a status update for my manager about this week."


class _Store:
    async def create(self, **kw):  # READ tools only; never called
        return {"id": "probe", "card": {}}


def compose(message: str):
    """Mirror of chat.py's deep-path composition for a fresh session."""
    c = classify(message)
    mode = resolve_mode(message, c.observables)
    contract = contract_for(mode)
    turns = [{"role": "user", "content": message}]
    messages = _history(turns)
    messages.append({"role": "system", "content": contract.system_directive()})
    pinned = None
    if mode is Mode.ALERT_TRIAGE:
        env = normalize(message)
        risk = score_alert(env)
        pinned = {"Risk": risk.risk_level}
        messages.append({"role": "system", "content": deterministic_triage_block(env, risk)})
    elif mode is Mode.PHISHING_ANALYSIS:
        env = parse_email(message)
        verdict = decide_verdict(env)
        pinned = {"Verdict": verdict.allowed}
        messages.append(
            {"role": "system", "content": deterministic_phishing_block(env, verdict)}
        )
    return c, mode, contract, messages, pinned


async def conversational(client, message):
    _, mode, contract, messages, pinned = compose(message)
    parts, finish, usage, thinking = [], None, None, 0
    async for ev in client.chat_stream(messages, max_tokens=CHAT_ANSWER_MAX_TOKENS,
                                       temperature=0):
        if ev.kind == "content":
            parts.append(ev.text)
        elif ev.kind == "reasoning":
            thinking += len(ev.text)
        elif ev.kind == "finish":
            finish = ev.finish_reason
        elif ev.kind == "usage" and ev.usage:
            usage = ev.usage
    answer = "".join(parts)
    return mode, contract, answer, pinned, finish, usage, thinking, 1, []


async def agent(client, enrichment, kb, message):
    c, mode, contract, _, pinned = compose(message)
    loop = AgentLoop(
        build_capability_registry(enrichment=enrichment, kb=kb, observables=c.observables,
                                  supplied=c.observables),
        _Store(), mode="native_tools", workspace_id=WORKSPACE,
        max_tokens=CHAT_ANSWER_MAX_TOKENS,
    )
    history = _agent_history([], contract.system_directive())
    done, thinking, calls, tools = None, 0, 0, []
    async for ev in loop.run_stream(client, message, history=history):
        if ev.kind == "reasoning":
            thinking += len(ev.text)
        elif ev.kind == "usage":
            calls += 1
        elif ev.kind == "tool":
            tools.append(ev.invocation.name)
        elif ev.kind == "done":
            done = ev
    answer = "" if done.stop_reason == "empty_answer" else (done.text or "")
    return mode, contract, answer, pinned, done.finish_reason, None, thinking, calls, tools


async def main() -> None:
    s = Settings()
    enrichment = EnrichmentService.from_settings(s)
    kb = KnowledgeService.from_settings(s)
    client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
    print("S27 — TD-012(b): contract drift, measured")
    print("=" * 78)
    print(f"model: {s.llm_model}  repeats: {REPEATS}  enrichment={enrichment.active} "
          f"kb={kb.active}")

    # ── control: every prompt lands where it is meant to, decided by CODE ────
    jobs = []
    for want, prompts in PROMPTS.items():
        for i, p in enumerate(prompts):
            c = classify(p)
            deep = shortcut_answer(c) is None
            got = resolve_mode(p, c.observables)
            assert deep, f"CONTROL FAILED: {want.value}[{i}] takes the shortcut"
            assert got is want, f"CONTROL FAILED: {want.value}[{i}] resolves to {got.value}"
            paths = ["conversational"] if want in CODE_DECIDED_MODES else [
                "conversational", "agent"]
            for path in paths:
                for r in range(REPEATS):
                    jobs.append((want.value, i, path, r, p))
    c = classify(CONTROL)
    assert shortcut_answer(c) is None and resolve_mode(CONTROL, c.observables) is Mode.THREAT_INTEL
    for path in ("conversational", "agent"):
        for r in range(REPEATS):
            jobs.append(("CONTROL(non-security)", 0, path, r, CONTROL))
    print(f"control passed: {len(jobs)} runs planned\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    results = []

    async def one(job):
        label, i, path, r, p = job
        async with sem:
            t0 = time.monotonic()
            try:
                if path == "conversational":
                    out = await conversational(client, p)
                else:
                    out = await agent(client, enrichment, kb, p)
            except Exception as err:  # an endpoint failure is a result, not a crash
                results.append((label, i, path, r, "ERROR", type(err).__name__, 0, 0, 0, [], ""))
                print(f"  {label}[{i}] {path} #{r}: ERROR {type(err).__name__}", flush=True)
                return
            mode, contract, answer, pinned, finish, usage, thinking, calls, tools = out
            res = contract.validate(answer, pinned=pinned) if answer else None
            verdict = "EMPTY" if res is None else ("ok" if res.ok else "DRIFT")
            reason = "" if res is None or res.ok else res.reason()
            dt = time.monotonic() - t0
            results.append((label, i, path, r, verdict, reason, len(answer), thinking,
                            calls, tools, answer))
            print(f"  {label}[{i}] {path} #{r}: {verdict} {reason} finish={finish} "
                  f"answer={len(answer)} thinking={thinking} calls={calls} tools={tools} "
                  f"pinned={pinned} {dt:.1f}s", flush=True)
            if verdict != "ok":
                print(f"      answer head: {answer[:700]!r}", flush=True)

    try:
        await asyncio.gather(*(one(j) for j in jobs))
    finally:
        await client.aclose()
        if hasattr(enrichment, "aclose"):
            await enrichment.aclose()

    # ── summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(f"{'mode':24} {'path':15} {'n':>3} {'ok':>3} {'drift':>5} {'empty':>5} {'err':>3}")
    keys = sorted({(r[0], r[2]) for r in results})
    for label, path in keys:
        rows = [r for r in results if r[0] == label and r[2] == path]
        n = len(rows)
        cnt = {v: sum(1 for r in rows if r[4] == v) for v in ("ok", "DRIFT", "EMPTY", "ERROR")}
        print(f"{label:24} {path:15} {n:>3} {cnt['ok']:>3} {cnt['DRIFT']:>5} "
              f"{cnt['EMPTY']:>5} {cnt['ERROR']:>3}")
    real = [r for r in results if not r[0].startswith("CONTROL")]
    for path in ("conversational", "agent"):
        rows = [r for r in real if r[2] == path]
        bad = [r for r in rows if r[4] != "ok"]
        print(f"security questions, {path}: {len(rows) - len(bad)}/{len(rows)} conformant")
    print("\ndrift reasons:")
    for r in real:
        if r[4] != "ok":
            print(f"  {r[0]}[{r[1]}] {r[2]} #{r[3]}: {r[4]} {r[5]}")


if __name__ == "__main__":
    asyncio.run(main())
