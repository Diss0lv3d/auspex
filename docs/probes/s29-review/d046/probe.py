import asyncio, json, sys
sys.path.insert(0, "/home/burhan/auspex-new/tests")
sys.path.insert(0, "/home/burhan/auspex-new")
from _fakes import FakeLLMClient, InMemoryProposalStore, SequencedStreamingFakeLLMClient
from auspex.agent.loop import AgentLoop
from auspex.agent.registry import ToolLevel, ToolRegistry
from auspex.llm.client import ChatResult, ToolCall, StreamEvent, Usage

W = "00000000-0000-0000-0000-000000000001"

def reg(budget, extra=True):
    seen = []
    r = ToolRegistry()
    async def search(args):
        seen.append(args)
        return {"results": [{"id": "T1"}]}
    async def lookup_cve(args):
        return {"ok": 1}
    r.add("search_knowledge", "search", {"query": {"type": "string"}}, ["query"], ToolLevel.READ, search, max_calls_per_turn=budget)
    if extra:
        r.add("lookup_cve", "cve", {"cve_ids": {"type": "array"}}, ["cve_ids"], ToolLevel.READ, lookup_cve)
    return r, seen

def tc(name, args, cid):
    return ToolCall(id=cid, name=name, arguments=args)

def offered(c):
    return [s["function"]["name"] for s in c["kwargs"].get("tools") or []]

async def case_worst_case():
    r, seen = reg(3)
    script = [ChatResult(tool_calls=[tc("search_knowledge", json.dumps({"query": f"q{i}"}), f"c{i}")], finish_reason="tool_calls") for i in range(8)]
    script.append(ChatResult(content="final", finish_reason="stop"))
    client = FakeLLMClient(script)
    res = await AgentLoop(r, InMemoryProposalStore(), mode="native_tools", workspace_id=W).run(client, "q")
    print("WORST CASE: model calls=", client.turns, "executed=", len(seen),
          "statuses=", [i.status for i in res.invocations], "stop=", res.stopped_reason)

async def case_errors_count():
    r, seen = reg(3)
    script = [
        ChatResult(tool_calls=[tc("search_knowledge", "{not json", "a")]),
        ChatResult(tool_calls=[tc("search_knowledge", "{}", "b")]),
        ChatResult(tool_calls=[tc("search_knowledge", "[1]", "c")]),
        ChatResult(tool_calls=[tc("search_knowledge", json.dumps({"query": "lockbit"}), "d")]),
        ChatResult(content="final", finish_reason="stop"),
    ]
    client = FakeLLMClient(script)
    res = await AgentLoop(r, InMemoryProposalStore(), mode="native_tools", workspace_id=W).run(client, "q")
    print("ERRORS COUNT: handler ran", len(seen), "times; statuses=", [(i.status, i.feedback.get("error"), "budget" in i.feedback) for i in res.invocations])
    print("   offered per call:", [offered(c) for c in client.calls])

async def case_parallel():
    r, seen = reg(3)
    script = [
        ChatResult(tool_calls=[tc("search_knowledge", json.dumps({"query": f"q{i}"}), f"a{i}") for i in range(2)]),
        ChatResult(tool_calls=[tc("search_knowledge", json.dumps({"query": f"r{i}"}), f"b{i}") for i in range(3)]),
        ChatResult(content="final", finish_reason="stop"),
    ]
    client = FakeLLMClient(script)
    res = await AgentLoop(r, InMemoryProposalStore(), mode="native_tools", workspace_id=W).run(client, "q")
    print("PARALLEL: handler ran", len(seen), [(i.arguments.get("query"), i.status, i.feedback.get("error"), "budget" in i.feedback) for i in res.invocations])
    print("   offered per call:", [offered(c) for c in client.calls])

async def case_parallel_bad_first():
    r, seen = reg(3)
    script = [
        ChatResult(tool_calls=[tc("search_knowledge", json.dumps({"query": f"q{i}"}), f"a{i}") for i in range(2)]),
        ChatResult(tool_calls=[tc("search_knowledge", '{"query": ', "b0"), tc("search_knowledge", json.dumps({"query": "good"}), "b1")]),
        ChatResult(content="final", finish_reason="stop"),
    ]
    client = FakeLLMClient(script)
    res = await AgentLoop(r, InMemoryProposalStore(), mode="native_tools", workspace_id=W).run(client, "q")
    print("PARALLEL BAD-FIRST: handler ran", len(seen), [(i.arguments.get("query"), i.status, i.feedback.get("error")) for i in res.invocations])

def tool_call_script(name, args, cid):
    return [StreamEvent(kind="tool_call", tool_index=0, tool_delta={"id": cid, "function": {"name": name, "arguments": args}}),
            StreamEvent(kind="finish", finish_reason="tool_calls")]

async def case_stream_all_withdrawn_narration():
    r, seen = reg(1, extra=False)
    narr = [StreamEvent(kind="content", text="Let me search once more for LockBit. ")]
    client = SequencedStreamingFakeLLMClient([
        narr + tool_call_script("search_knowledge", json.dumps({"query": "a"}), "a"),
        narr + tool_call_script("search_knowledge", json.dumps({"query": "b"}), "b"),
        [StreamEvent(kind="content", text="ANSWER."), StreamEvent(kind="finish", finish_reason="stop")],
    ])
    loop = AgentLoop(r, InMemoryProposalStore(), mode="native_tools", workspace_id=W)
    evs = [e async for e in loop.run_stream(client, "q")]
    print("STREAM ALL-WITHDRAWN:", [(e.kind, e.step, e.text) for e in evs if e.kind in ("content", "narration")])
    print("   done.text=", repr(evs[-1].text), "tools on wire per call:", ["tools" in c["kwargs"] for c in client.stream_calls])

async def case_stream_one_left_narration():
    # control: with an unbudgeted tool still on the wire, the same narration is held
    r, seen = reg(1, extra=True)
    narr = [StreamEvent(kind="content", text="Let me search once more for LockBit. ")]
    client = SequencedStreamingFakeLLMClient([
        narr + tool_call_script("search_knowledge", json.dumps({"query": "a"}), "a"),
        narr + tool_call_script("search_knowledge", json.dumps({"query": "b"}), "b"),
        [StreamEvent(kind="content", text="ANSWER."), StreamEvent(kind="finish", finish_reason="stop")],
    ])
    loop = AgentLoop(r, InMemoryProposalStore(), mode="native_tools", workspace_id=W)
    evs = [e async for e in loop.run_stream(client, "q")]
    print("STREAM CONTROL:", [(e.kind, e.step, e.text) for e in evs if e.kind in ("content", "narration")])

async def case_prompted():
    r, seen = reg(1)
    def tcall(q):
        return '<tool_call>{"name": "search_knowledge", "arguments": {"query": "%s"}}</tool_call>' % q
    client = FakeLLMClient([ChatResult(content=tcall("a")), ChatResult(content=tcall("b")), ChatResult(content="final")])
    loop = AgentLoop(r, InMemoryProposalStore(), mode="prompted_tools", workspace_id=W)
    res = await loop.run(client, "q")
    sysmsg = client.calls[1]["messages"][0]["content"]
    print("PROMPTED: handler ran", len(seen), [(i.status, i.feedback.get("error")) for i in res.invocations],
          "| search_knowledge still in system prompt at call 2:", "search_knowledge(" in sysmsg)

async def case_not_offered_but_counted():
    r, seen = reg(3)
    client = FakeLLMClient([ChatResult(tool_calls=[tc("search_knowledge", json.dumps({"query": "a"}), "a")]), ChatResult(content="final")])
    loop = AgentLoop(r, InMemoryProposalStore(), mode="native_tools", workspace_id=W)
    res = await loop.run(client, "q", tool_names=["lookup_cve"])
    print("NOT OFFERED (tool_names scoping, pre-existing):", offered(client.calls[0]), "-> handler ran", len(seen), res.invocations[0].status)

async def main():
    for c in [case_worst_case, case_errors_count, case_parallel, case_parallel_bad_first,
              case_stream_all_withdrawn_narration, case_stream_one_left_narration, case_prompted,
              case_not_offered_but_counted]:
        await c()
asyncio.run(main())
