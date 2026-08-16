# S25 — `run_stream` against the real endpoint and the real tools

_Probed 2026-08-16 (S25). Harness: `docs/probes/s25-agentstream/probe_run_stream_live.py`.
Endpoint: Llama-4-Scout via Northflank (D-015). Services: the app's own
`EnrichmentService.from_settings` / `KnowledgeService.from_settings`, live._

## Why

`tests/test_agent_stream.py` drives `run_stream` with scripted `StreamEvent`s.
A streaming loop that folds scripted events correctly and fails on a real SSE
stream is exactly the class of thing the reality-over-memory rule exists for —
and the whole method exists to be wired to a real endpoint next session.

The probe builds the services with **the app's own constructors** (`app.py:47,53`)
rather than a second opinion about how they are built.

## Result — the D-031 guarantees hold against a real stream

```
tools: ['enrich_observable', 'lookup_cve', 'search_knowledge']
       enrichment.active=True kb.active=True

  [usage] Usage(prompt_tokens=651, completion_tokens=19, total_tokens=670)
  [tool ] enrich_observable status=executed feedback_keys=['results']
  [usage] Usage(prompt_tokens=922, completion_tokens=80, total_tokens=1002)
  [done ] stop_reason=final_answer finish=stop

event order: ['usage', 'tool', 'content' x79, 'usage', 'done']
tool events: 1   content deltas: 79   claims: 2   model calls: 2
```

| D-031 | asserted arithmetically | measured |
|---|---|---|
| 1 — answer streams AFTER tool steps | `max(tool_index) < min(content_index)` | **holds** (tool at 1, first content at 2) |
| 1 — it actually *streams* | `content_deltas > 1` | **79 deltas** |
| 2 — arguments assembled before parsing | the handler executed with a real IP | `status=executed`, real provider data returned |
| 4 — claim per model call | `len(claims) == distinct steps` | **2 == 2** |

The controls matter: `assert tool_at` first, because an ordering assertion over
an empty list is vacuously true — the exact shape of the mistake that has been
caught in five consecutive sessions.

## What the analyst got

The answer was written by the model from the tool's **structured data**, not from
our renderers:

> "The IP address 185.220.101.5 is considered malicious according to threat
> intelligence. It has been reported as abusive with a high confidence level of
> 100/100 based on 220 reports in the last 90 days by AbuseIPDB. Additionally, it
> is associated with Tor Exit Nodes and has open ports 80, 443, 9001…"

That is the design in `capabilities.py` working end to end: handlers return data,
the model writes the prose, and our own configuration-shaped copy never enters the
turn for the output rail to trip over.

## What this does NOT establish

- **The route is not wired.** No `/api/chat` code changed this session. What is
  verified is the mechanism, not the surface — the leak index built from
  `system_message()`, the tool-results scanner channel, session persistence and
  the `done` frame are all still to come.
- **One turn, one tool, one endpoint.** Multi-step chains, the step-cap synthesis
  path and the mid-loop refusal path are covered by tests against fakes only.
- **`prompted_tools` remains unprobed** and must not be wired to a streaming
  surface until it is.
- **TD-036 stands.** Content streamed on arrival is safe here because Scout emits
  no prose before its tool calls (`content chars: 0`, measured twice). That is a
  property of this endpoint.
