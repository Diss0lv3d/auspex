# Probe: Z.ai general API (GLM family) as the dev LLM endpoint

- **Date:** 2026-10-10 (S26, mid-session detour — the primary dev LLM disappeared)
- **Why:** Llama-4-Scout on Northflank is decommissioned. Measured, not assumed:
  `p01--new-llm--9nq2hvq25g8m.code.run` is **NXDOMAIN** from host and container,
  while `code.run` itself and github.com resolve. Burhan supplied a **pay-as-you-go**
  Z.ai key (`GLM_API_KEY` in `.env`, gitignored) and asked whether GLM-5.2, or a
  cheaper Z.ai model, can back the platform.
- **Target:** `https://api.z.ai/api/paas/v4` — the GENERAL endpoint only. The Coding
  Plan endpoint (`/api/coding/paas/v4`) was never called; see §Docs (4).
- **Harness:** `docs/probes/s26-zai/probe_zai_wire.py` (raw httpx — none of our
  parsing in the way). Every request/response saved under
  `docs/probes/s26-zai/raw/`, passed through `redact()` first; a scan of every
  saved file for the key and both of its halves found none.
- **Depends on this:** D-033 (base-URL convention, response-shape handling),
  `auspex/llm/client.py`, the capability battery, and the S26 route wiring
  (§Wire finding 9 is a TD-036 trigger).

---

## Docs — read before the key was used (2026-10-10)

Six agents read ~30 docs.z.ai pages and `openapi.json` (OpenAPI 3.0.1), then a
critic resolved contradictions. Where the docs and the wire disagree, **the wire
section below wins** — four of the docs' claims did not survive contact.

1. **Endpoint.** Base `https://api.z.ai/api/paas/v4`, chat at `{base}/chat/completions`
   — **no `/v1`**. The OpenAI-SDK page sets `base_url="https://api.z.ai/api/paas/v4/"`.
   No models endpoint is documented (the spec's 14 paths contain none).
2. **Request surface.** Bearer auth. OpenAI-shaped `tools` (≤128 functions), `role:
   "tool"` + `tool_call_id`, assistant `tool_calls` replay. Z.ai-only fields:
   `thinking: {type: enabled|disabled, clear_thinking}` (default enabled),
   `reasoning_effort` (GLM-5.2+: default **`max`**), `tool_stream`, `do_sample`,
   `request_id`, `user_id`. Documented as absent: `stream_options`, `json_schema`,
   `parallel_tool_calls`; `tool_choice` documented as **"only supports auto"**.
3. **Response surface.** Thinking text in `message.reasoning_content` /
   `delta.reasoning_content` — **not** `reasoning`, which is what our client read.
   `finish_reason` adds `sensitive`, `model_context_window_exceeded`, `network_error`.
   Errors documented two ways (flat `{code,message}` in the spec; `{error:{code,
   message}}` in the guide). Insufficient balance = 1113 (HTTP 429), rate limit
   1302 / overload 1305 (429), content filter 1301 (400).
4. **Coding Plan vs pay-as-you-go.** Different endpoints. The subscription terms
   forbid Coding Plan quota "for general-purpose API access or any scenarios outside
   such tools, including … directly invoking model APIs from your own applications,
   bots, websites, SaaS products". **Auspex may only ever use a pay-as-you-go key on
   the general endpoint** — which is what this key is (Burhan, 2026-10-10).
5. **Data.** Operator: JINGSHENG HENGXING TECHNOLOGY PTE. LTD. (Singapore); data
   "generally processed in Singapore". API DPA: customer content "not saved on our
   servers"; Terms: API End User Content not used for training without explicit
   agreement. No KSA region exists → under org policy §1 this endpoint may **never**
   carry KSA-tenant data. As a **dev** endpoint with synthetic prompts it is fine.
6. **Price per 1M tokens (input / cached / output), pricing page:**

   | model | in | cached | out | ctx |
   |---|---|---|---|---|
   | glm-5.3, glm-5.2, glm-5.1 | $1.40 | $0.26 | $4.40 | 1M (5.1: 200K) |
   | glm-5 | $1.00 | $0.20 | $3.20 | 200K |
   | glm-4.7 / 4.6 / 4.5 | $0.60 | $0.11 | $2.20 | 200K / 128K |
   | glm-4.5-air | $0.20 | $0.03 | $1.10 | 128K |
   | glm-5.3-flashx | $0.37 | $0.075 | $1.25 | 1M |
   | glm-5.3-flash | $0.15 | $0.03 | $0.50 | 1M |
   | glm-4.7-flashx | $0.07 | $0.01 | $0.40 | 200K |
   | glm-4.7-flash, glm-4.5-flash | free | free | free | 200K / 128K |

   Rate limits are console-only (`docs.z.ai/api-reference/rate-limit.md` 307s to a
   login page).

---

## Wire — what the live API actually does

### Finding 1 — the base-URL convention was the bug, and it hid itself

| request | status |
|---|---|
| `GET  {base}/models` | **200** — OpenAI list: glm-4.5 … glm-5.3-flashx, plus an undocumented `glm-5-turbo` |
| `GET  {base}/v1/models` | **200** — a DIFFERENT catalog (with pricing, `context_length`) |
| `POST {base}/v1/chat/completions` | **404** `{"path":"/v4/v1/chat/completions"}` |

Under the pre-D-033 client (`{base}/v1/...`), the liveness check would have
**passed** and every chat would have 404'd. A models endpoint exists after all
(docs finding 1 was wrong) — so `check_reachable` works unchanged once the root is
right.

### Finding 2 — `temperature: 0` is accepted (every capability probe sends it).

### Finding 3 — thinking is `reasoning_content`, on by default, and billed

- `message.reasoning_content` / `delta.reasoning_content`; never `reasoning`.
- `usage.completion_tokens_details.reasoning_tokens` is reported, and reasoning
  tokens are **inside** `completion_tokens` (GLM-5.2 "pong": 117 = 116 + 1).
- GLM-5.2 "Reply with exactly: pong": **116 reasoning tokens, 2.7 s** with the
  default; `thinking: {type: disabled}` → **0 tokens, 1.2 s**.
- GLM-5.2 on a routine SOC question: **1088 reasoning tokens**, 28.6 s, and
  `finish_reason: length` at `max_tokens=2000` — thinking took over half the budget.
- `glm-5.3-flash` **cannot** disable thinking: HTTP 400 `{"error":{"code":"1210",
  "message":"This model always engages in thinking and cannot be disabled; please
  use low, high, or max"}}`.
- GLM-4.5-family usage carries **no** `completion_tokens_details`.

### Finding 4 — tool calls are OpenAI-shaped

`arguments` is a **JSON string** on every model (the spec's `object` typing is
wrong); ids look like `call_-7184289652554066785`; `finish_reason: tool_calls`.
`role: "tool"` round trips work on every model tried — **including glm-5.3-flash**,
whose spec schema (vision) lists no tool role.

### Finding 5 — the "unsupported" knobs are honoured or ignored, never rejected (GLM-5.2)

| sent | docs say | wire |
|---|---|---|
| `tool_choice: "required"` | only `auto` | 200, 1 tool call — **honoured** |
| `tool_choice: {type: function, …}` | only `auto` | 200, 1 tool call — **honoured** |
| `tool_choice: "none"` | only `auto` | 200, 0 tool calls (answered from thinking, 11.9 s) — **honoured** |
| `response_format: json_schema` | absent | 200, **silently ignored** — markdown prose came back |
| `response_format: json_object` | supported | 200, valid JSON |
| `stream_options.include_usage` | absent | 200, accepted |

`json_schema` being silently ignored is the dangerous one: our battery scores it
by *adherence*, not by status, so it reads correctly as unsupported.

### Finding 6 — streaming

- SSE `data:` lines, terminated by `data: [DONE]`.
- **Usage rides the LAST chunk together with `choices[0].finish_reason`** (not an
  empty-choices chunk as on vLLM/Ollama). `parse_sse_line` already emits both.
- Tool calls **without** `tool_stream`: the whole call arrives in ONE delta (id,
  name and complete arguments). **With** `tool_stream: true`: 8 fragments, id/name
  on the first only — the vLLM shape `fold_stream_event` already handles.
- GLM-5.2 "count 1–5": first chunk at 2.1 s, but **405 reasoning chunks before 9
  content chunks** — time-to-first-*answer* is the thinking time.

### Finding 7 — parallel tool calls: GLM-5.2 emitted 2 in one response.

### Finding 8 — the error envelope is the guide's, not the spec's

Unknown model → HTTP **400** `{"error":{"code":"1211","message":"Unknown Model,
please check the model code."}}` — the shape `_extract_error` already reads.

### Finding 9 — PROSE BEFORE TOOL CALLS (a TD-036 trigger)

TD-036 rests on "no prose precedes tool calls on the endpoints we have". On Z.ai
it does, on several models:

| model | probe | content alongside the tool call |
|---|---|---|
| glm-5.2 | parallel tools | "I'll run both requests at the same time since they're independent of each other!" (80 ch) |
| glm-4.7-flashx | single tool | 58 ch |
| glm-4.5-air | single tool | 60 ch |
| glm-4.5-flash | single tool | 60 ch |
| glm-5.3-flash | single tool | 0 ch |

Streamed, glm-4.7-flashx sent **14 content deltas before its tool call**. This is
the measurement TD-036 said would be needed before it is touched — recorded there.

### Finding 10 — the content filter did not fire on routine SOC content

Mimikatz `sekurlsa::logonpasswords` + an outbound IP, as an analyst question:
HTTP 200, a full answer, no `sensitive` finish. One prompt — not a clearance.

### Finding 11 — the free tier and one paid model were unreliable on the day

- `glm-4.7-flash` (free): HTTP 429 `code 1305` "temporarily overloaded" on first call.
- `glm-4.5-flash` (free): 6–15 s per call.
- `glm-4.7-flashx`: its first tool call **hung past 180 s** (ReadTimeout); a re-run
  minutes later answered in 2.0 s. Flaky, not dead.

### Per-model wire summary (single requests — the harness runs are the real comparison)

| model | basic (default thinking) | tool call | roundtrip | streamed tool call |
|---|---|---|---|---|
| glm-5.2 | 2.7 s, 116 rt | 2.1 s ✓ | 2.9 s ✓ | 2.0 s, 1 delta |
| glm-5.3-flash | 2.4 s, 64 rt | 5.2 s ✓ | 5.8 s ✓ | 5.0 s, 1 delta |
| glm-4.7-flashx | 2.3 s, 130 rt | 2.0 s ✓ (hung once) | 1.2 s ✓ | 1.8 s, 1 delta |
| glm-4.5-air | 2.6 s | 1.9 s ✓ | 1.4 s ✓ | 1.5 s, 1 delta |
| glm-4.5-flash | 6.5 s | 15.2 s ✓ | 5.2 s ✓ | 4.5 s, 1 delta |
| glm-4.7-flash | 429 overloaded | — | — | — |

(rt = reasoning tokens)
