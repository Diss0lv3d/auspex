"""S24 Step 0 — angle A, part 2: does a real endpoint INTERLEAVE reasoning and
content deltas on the native path?

probe_channel_carry.py proved that one interleaved delta of the other kind
evicts the carry and a leak inside ONE pane walks through. That is a defect in
the scanner either way. This probe answers the separate question of whether it
is reachable TODAY, on an endpoint we actually have -- which decides how the
finding is written up, not whether it is fixed.

Measured, not assumed: qwen3:14b is a thinking model on local Ollama (D-013),
the one endpoint we have that can emit a `reasoning` field at all. Scout's
persisted scorecard carries no `native_reasoning` key, so the app resolves it
False and Scout takes the two-pass path -- immune by construction, since each
pass feeds exactly one channel.
"""
import asyncio
import sys

sys.path.insert(0, ".")
from auspex.llm.client import LLMClient  # noqa: E402

PROMPT = "Is paypa1-secure.com a lookalike of paypal.com? One short line."


async def main():
    client = LLMClient("http://localhost:11434", "qwen3:14b")
    seq = []          # the ordered kind sequence, collapsed to runs
    counts = {}
    try:
        async for ev in client.chat_stream(
            [{"role": "user", "content": PROMPT}], max_tokens=1500, temperature=0
        ):
            counts[ev.kind] = counts.get(ev.kind, 0) + 1
            if ev.kind in ("reasoning", "content"):
                if not seq or seq[-1][0] != ev.kind:
                    seq.append([ev.kind, 0])
                seq[-1][1] += 1
    finally:
        await client.aclose()

    print(f"event counts: {counts}")
    print(f"channel runs (kind, n deltas): {[(k, n) for k, n in seq]}")
    switches = max(0, len(seq) - 1)
    print(f"channel switches: {switches}")
    print()
    if switches <= 1:
        print("RESULT: no interleave -- reasoning then content, one switch at most.")
        print("        The defect is LATENT on this endpoint, not unreachable in general:")
        print("        the switch count is a property of the endpoint, not of our code.")
    else:
        print(f"RESULT: INTERLEAVED -- {switches} switches. The defect is LIVE here.")


asyncio.run(main())
