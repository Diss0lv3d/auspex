import asyncio, sys
sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import test_agent_stream as T
from auspex.llm.client import StreamEvent
class Hist:
    """Calls the withdrawn lookup_ip AND a second junk call every step while tools are on the wire."""
    def __init__(self, second): self.stream_calls = []; self.second = second
    async def chat_stream(self, messages, **kwargs):
        self.stream_calls.append({"kwargs": kwargs}); n = len(self.stream_calls)
        if kwargs.get("tools"):
            evs = [StreamEvent(kind="tool_call", tool_index=0, tool_delta={"id": f"a{n}", "function": {"name": "lookup_ip", "arguments": '{"ip": "203.0.113.1"}'}})]
            if self.second:
                evs.append(StreamEvent(kind="tool_call", tool_index=1, tool_delta={"id": f"b{n}", "function": {"name": self.second[0], "arguments": self.second[1]}}))
            evs.append(StreamEvent(kind="finish", finish_reason="tool_calls"))
        else:
            evs = T._answer_script()
        for e in evs: yield e
    async def aclose(self): pass
async def main():
    for second in (None, ("made_up_tool", "{}"), ("whois", "{not json")):
        reg, seen = T._budgeted_registry(1)
        c = Hist(second)
        events = await T._drain(T._loop(reg), c)
        done = events[-1]
        print(second, "model calls:", len(c.stream_calls), "stop:", done.stop_reason, "step:", done.step,
              "statuses:", [e.invocation.status + ":" + str(e.invocation.feedback.get("error"))[:20] for e in events if e.kind == "tool"][:4])
asyncio.run(main())
