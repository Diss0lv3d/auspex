# Probe: local Ollama endpoint (interim dev LLM, D-012)

- **Date:** 2026-07-15 (S2 resume)
- **Target:** `http://localhost:11434` (Ollama 0.24.0, snap), keyless, local GPU
  (RTX 5070 Ti Laptop, 12 GB VRAM)
- **Model:** `llama3.1:8b` (8.0B Q4_K_M, `llama.context_length` = **131072**,
  capabilities `["completion", "tools"]` per `/api/show`)
- **Probed by:** scratchpad `probe_ollama.py` (httpx, async). Raw responses saved
  verbatim to `tests/fixtures/llm/ollama/` — these are the pytest fixtures.
- **Why this endpoint:** Northflank vLLM down for days (see
  `2026-07-14-llm-endpoint.md`). Scout go/no-go numbers still owed there.

## Findings (every one backed by a fixture file)

1. **`GET /v1/models`** → 200, OpenAI list shape `{object, data: [{id, ...}]}`
   (`models.json`).
2. **Non-streaming chat** → OpenAI shape: `id`, `choices[0].message{role,content}`,
   `finish_reason: "stop"`, `usage{prompt,completion,total}_tokens`
   (`chat_basic.json`). `temperature: 0` honored (exact "pong").
3. **Native tool calling: YES** (`chat_tools.json`): `finish_reason: "tool_calls"`,
   `message.tool_calls[]` with `{id, index, type: "function",
   function: {name, arguments}}`. **`arguments` is a JSON *string*** (OpenAI
   convention). Quirk: `index` appears even in non-streaming responses.
4. **Parallel tool calls: YES** (`chat_tools_parallel.json`): 2 calls in one
   turn (`get_weather` + `lookup_ip`), indexed 0 and 1.
5. **`tool_choice`**: named `{"type":"function","function":{"name":...}}` and
   `"required"` both honored (`chat_tools_named_choice.json`,
   `chat_tools_required.json`).
6. **Tool-role round-trip: YES** (`chat_tool_roundtrip.json`): accepts replayed
   `assistant.tool_calls` + `role:"tool"` message with `tool_call_id`; the final
   answer used the tool result (`"43°C"`).
7. **Streaming** (`chat_stream.sse.txt`): SSE `data: <json>` lines, terminated
   by `data: [DONE]`. Content arrives token-by-token in
   `choices[0].delta.content`; `role` rides in the first delta; final content
   chunk carries `finish_reason`.
8. **Streaming tool calls** (`chat_tools_stream.sse.txt`): each tool call
   arrives as ONE complete delta chunk (`id` + `name` + full `arguments` in a
   single `tool_calls[]` entry, keyed by `index`), then a
   `finish_reason:"tool_calls"` chunk. **vLLM/OpenAI may instead fragment
   `arguments` across many deltas — the accumulator must support both**
   (append-by-index; set id/name when present).
9. **`stream_options.include_usage`: honored** — usage arrives in a final extra
   chunk with `"choices": []` before `[DONE]` (both stream fixtures).
10. **`response_format`**: `json_object` → valid JSON (`chat_json_object.json`);
    `json_schema` → **adheres, 10/10 on the mini-battery** (required keys +
    enum respected; `chat_json_schema.json`). Grammar-constrained decoding.
11. **Errors ARE JSON here**: `{"error": {"message", "type", "param", "code"}}`
    — 404 unknown model (`error_bad_model.json`), 400 malformed request
    (`error_missing_messages.json`). Finding 0 from the Northflank probe still
    stands: NEVER assume this — proxies/edges return text/plain.
12. **Throughput:** ~**61 tok/s** (208 completion tokens / 3.39 s,
    `chat_throughput.json`). First-token latency not isolated (S3 concern).

## What our code must therefore do

- Accumulate streaming tool calls **by `index`**, appending `function.arguments`
  fragments and setting `id`/`name` when present (handles both complete-per-chunk
  Ollama and fragmented vLLM/OpenAI styles).
- Treat a chunk with empty/absent `choices` as a potential usage carrier.
- Terminate on `data: [DONE]` and tolerate blank SSE lines.
- Parse error bodies defensively (JSON envelope OR raw text — Finding 0).
- Read `usage` from both non-streaming body and include_usage extra chunk.
- Cap context assumptions at what `/api/show` reports (131072 here) — but
  never hardcode: it's per-endpoint scorecard data.

## Harness run (2026-07-15, scripts/llm_harness.py — 40 tasks, 76 tool calls)

Raw run: `harness-run-llama3-1-8b.json`. Scorecard row
`f86da0f3-c438-43dc-85d8-8bfe04815b45` (workspace `dev`).

| Metric | Value |
|---|---|
| **valid-call rate** | **98.7 %** (75/76; one `lookup_ip` missing required param) |
| **loop-completion rate** | **52.5 %** (21/40) |
| single / chain2 / chain3 | 75 % / 30 % / 70 % |
| parallel / no-tool / enum | 50 % / **0 %** / 100 % |
| throughput | ~61 tok/s (GPU-local) |
| **agent mode (decide_agent_mode)** | **`prompted_tools`** (completion < 0.70 bar) |

### Failure taxonomy (why completion is low while call syntax is near-perfect)

1. **Long-string fidelity (4 tasks):** the model truncates 64-char hashes in
   tool args ("aaaaaaaa… (truncated for brevity)") → lookups return unknown.
   Syntactically valid, semantically ruined. *Agent-loop countermeasure:
   observable IDs, never raw long strings, in tool args (S3 design input).*
2. **No-tool restraint: 0/4.** Whenever tools are offered, the model calls one —
   including `create_ticket` for "say hello to the team". *Countermeasure:
   don't offer tools on conversational turns (92/8 fast-path already planned).*
3. **Fabricated actions (3 tasks):** announces a ticket/proposal ("HIGH Severity
   Ticket: …") **without calling the tool**. Dangerous pattern for SOAR;
   hard-gate writes on actual tool calls, never on model claims.
4. **Evidence threading (5–6 tasks):** correct calls, wrong synthesis (says
   "no events" after a tool returned 12; misattributes alert severity to asset
   criticality).
5. **Grading artifacts (2–3 tasks):** correct analysis, paraphrased wording
   ("crown jewel" vs `crown-jewel`, "not a cause for concern" vs `benign`).
   Crediting all of these still yields ≤ 0.60 — the `prompted_tools` verdict
   stands regardless.

### Reading for the go/no-go question

An 8B same-family model produces **excellent native tool-call syntax** (98.7 %)
but **weak multi-step task competence** (52.5 %). The mode ladder currently
demotes on completion rate even though the failures are reasoning-shaped, not
syntax-shaped — prompted tools would not fix these. Logged to IDEAS.md:
consider splitting "call syntax" vs "task competence" thresholds so the
runtime can pick native calls + tighter orchestration. Scout (109B) numbers
from the real endpoint remain the decisive data.

## Second model: qwen3:14b (2026-07-15, same endpoint)

Pulled after the 8B verdict; biggest tool-capable model that fits 12 GB VRAM
entirely on GPU. **Thinking model** — new wire shape captured: reasoning rides
a separate `reasoning` field in messages AND stream deltas; `content` stays
clean; tool-call shapes unchanged (fixtures `chat_reasoning.json`,
`chat_reasoning_stream.sse.txt`; parser needed no change, tests pin it).

**Battery bug found & fixed by this run:** probes capped at 40–300 tokens
false-negatived every content-bearing capability for thinking models (the
model spent the whole budget on reasoning). Fixed: `_PROBE_MAX_TOKENS = 2000`
(harness had the same fix already). Corrected battery: ALL capabilities true,
schema adherence 5/5, ~33 tok/s, ctx metadata 40960.

### Side-by-side (40 tasks, identical harness, temperature 0)

| Metric | llama3.1:8b | qwen3:14b |
|---|---|---|
| valid-call rate | 98.7 % (75/76) | **100 % (73/73)** |
| loop-completion | 52.5 % (21/40) | **87.5 % (35/40)** |
| single / chain2 / chain3 | 75 / 30 / 70 % | 100 / **70** / **100** % |
| parallel / no-tool / enum | 50 / **0** / 100 % | 66.7 / **100** / 100 % |
| throughput | ~61 tok/s | ~33 tok/s (thinking) |
| wall clock (40 tasks) | 88 s | 943 s |
| **agent mode** | prompted_tools | **native_tools** |

Runs: `harness-run-llama3-1-8b.json`, `harness-run-qwen3-14b.json`.
Scorecard rows: `f86da0f3-…` (8B), `37b4b02e-…` (14B corrected; the earlier
`604a72b0-…` row carries the pre-fix false-negative battery flags — superseded,
kept as history).

### qwen3:14b remaining failures (5)

- 2× long-string fidelity (64-char hash mangled in args → "unknown" verdicts) —
  same signature as 8B; observable-ID tool design (IDEAS.md) fixes this class.
- 1× wrong argument value then self-corrected narrative (C208).
- 1× search query returned 0 (arg-value fidelity, C205).
- 1× combined two searches into one OR-query (P06) — arguably task-design
  punishment, not model failure.
- Fabricated actions: **zero** (8B had 3). No-tool restraint: perfect.

### Reading

A 14B thinking model on the same endpoint jumps completion +35 pts and earns
`native_tools` — the S3 loop should be built native-first. Thinking costs
~10× wall clock; S3 must stream (reasoning field available for UI) and budget
tokens generously (min 2000/turn for thinking models). Long-string arg
fidelity fails at BOTH sizes → observable IDs in tool args are mandatory
(S3 design input, IDEAS.md).

## Caveat

These fixtures characterize **Ollama's** OpenAI-compat layer + llama3.1:8b.
The production target remains whatever the customer brings (D-005); the
Northflank vLLM + Llama-4-Scout numbers are still owed (blocked, see
2026-07-14 probe). Scorecards are stored per endpoint fingerprint.
