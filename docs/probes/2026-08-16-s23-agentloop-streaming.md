# S23 — can the agent loop stream? Reality snapshot before the wiring

_2026-08-16. Harness: `docs/probes/s23-agentloop/probe_streaming_tools.py`.
Endpoint: the real dev primary (D-015) — Llama-4-Scout-17B via Northflank.
Run twice; identical shape both times._

## Why this ran before any wiring

`AgentLoop.run()` drives `client.chat(...)` — one **blocking** call per step
(`auspex/agent/loop.py:321`). `/api/chat` is an **SSE** route that streams
`reasoning`/`content` frames. Those two shapes do not compose on their own, and
the choice between "run the loop to completion, then emit one content frame" and
"stream the answer after the tools have run" is not a taste question — it depends
on a fact about the customer's endpoint.

`chat_stream` already accepts `tools` and declares a `tool_call` StreamEvent
(`auspex/llm/client.py:222`, `:74`). **Declaring the event is not evidence a real
endpoint emits it**, and S2's `native_tools` capability was measured through the
NON-streaming `chat` path. Coding a streaming loop against that gap is what
CLAUDE.md rule 4 forbids.

## What was measured

| question | answer |
|---|---|
| Do tool calls arrive over `chat_stream` at all? | **Yes** — 9 `tool_call` events for one call |
| Are `arguments` whole or fragmented? | **Fragmented across 9 deltas** |
| What closes a tool-calling turn? | `finish_reason: "tool_calls"` (vs `"stop"`) |
| Does prose interleave with tool calls? | **No** — `content chars: 0` on the tool turn |

Forced-tool turn:

```
event kinds in order : tool_call -> finish -> usage
counts               : {'finish': 1, 'tool_call': 9, 'usage': 1}
finish_reason        : 'tool_calls'
content chars        : 0
tool[0] lookup_observable: 9 argument delta(s) -> {'value': '185.220.101.5'}
    FRAGMENTED — fragments: ['{"value": "', '185', '.', '220', '.', '101', '.', '5', '"}']
CONTENT BEFORE TOOL CALLS: False (tool calls come first — the answer can stream after)
```

Control, same request shape with a question needing no tool:

```
event kinds in order : content -> finish -> usage
finish_reason        : 'stop'
content chars        : 58
```

The control matters: it shows the endpoint was genuinely *choosing*, not simply
unable to produce content while `tools` was set.

## The three findings that shape the wiring

**1. The answer CAN stream honestly.** Tool calls arrive with **zero** content
before them. So the route never streams prose that a tool result might
contradict — narrate the tool steps, then stream the final answer. The "run the
whole loop, emit one content blob" fallback is not needed for this endpoint.

**2. Arguments MUST be accumulated before parsing.** A single IP arrived as nine
fragments, split mid-token (`'185', '.', '220'`). Any streaming loop that parses
a `tool_call` delta as it arrives gets `UNPARSEABLE` on the first one. The
non-streaming `chat` path never saw this because the client already joins them.

**3. `finish_reason` is the loop's step signal.** `"tool_calls"` means "another
step follows"; `"stop"` means the turn is done. That is a code-owned signal, not a
model sentence — which is what makes it usable per ADR 0006.

## Three constraints found by reading, not measured here

Recorded because they bound the wiring just as hard:

- **No `ToolRegistry` is populated anywhere in the running app.** `grep` for
  `ToolRegistry()` across `auspex/` returns nothing outside the class itself; the
  only callable surface the app builds is `app.state.action_registry`, with one
  action (`annotate_observable`, `auspex/app.py:64`). So a loop wired in today has
  **zero read tools** — the platform's real capabilities (enrichment, CVE lookup,
  KB retrieval) exist as shortcut code paths, not as agent tools. Exposing them is
  the substance of a useful agent turn, and it is a separate piece of work.
- **Usage metering would break TD-018.** The route claims `1 if native_reasoning
  else 2` inference calls **up front** (`auspex/routes/chat.py:506`). A loop makes
  up to `DEFAULT_MAX_STEPS = 8` plus a synthesis call. Wiring the loop without
  moving the claim lets a workspace cause 9 calls while being charged 1 — the
  exact guarantee D-027/TD-018 exist to hold. The claim has to move inside the
  step loop.
- **The output rail's index must follow the loop.** Today it indexes four fixed
  strings (`chat.py:527`). The loop composes its system message at runtime —
  `system_prompt + channel.system_prefix(specs) + _actions_prefix()` — so the
  index must be built from what the turn actually issued. Tool *results* are data,
  not our configuration, and must stay unindexed for the same reason the analyst's
  paste is (D-030 decision 2). The S23 Step-0 review also made the scanner
  channel-aware, and a tool loop adds channels: a run spanning a tool result and
  the answer is not a leak.

## Not measured

Only the native path was probed. `prompted_tools` mode parses `<tool_call>` tags
out of **content** (`auspex/agent/loop.py:66`), which is a different streaming
shape — the tags arrive as ordinary content deltas and would stream to the analyst
as prose before the loop could strip them. That needs its own probe before
`prompted_tools` is wired to a streaming surface.
