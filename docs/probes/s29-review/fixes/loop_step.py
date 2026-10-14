import asyncio, sys
sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import test_agent_stream as T
import test_agent_loop as L
from auspex.agent.loop import AgentLoop
async def main():
    registry, seen = T._budgeted_registry(1)
    client = T._CallsFromHistory()
    loop = T._loop(registry)
    events = await T._drain(loop, client)
    done = events[-1]
    print("max_steps", loop.max_steps)
    print("stream done:", done.kind, done.stop_reason, "step=", done.step)
    print("engine phase steps:", [e.step for e in events if e.kind == "phase" and e.phase == "engine"])
    print("stream calls:", len(client.stream_calls))
asyncio.run(main())
