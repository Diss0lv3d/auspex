# Probe: Northflank vLLM endpoint (dev LLM, D-005/D-006)

- **Date:** 2026-07-14 (S2)
- **Target:** `LLM_BASE_URL` from `.env` → `https://p01--new-llm--9nq2hvq25g8m.code.run`
  (keyless during testing, D-006 — no secret to redact)
- **Model:** `nvidia/Llama-4-Scout-17B-16E-Instruct-FP8`
- **Probed by:** scratchpad `probe_llm.py` (httpx 0.28.1, async) + curl. Raw
  responses saved verbatim to `tests/fixtures/llm/` for offline pytest.
- **Depends on this:** `auspex/llm/` client (S2), capability battery, S3 agent loop.

## Finding 0 — edge errors are text/plain, NOT JSON (22:24 UTC+5:30 onwards)

First contact returned, for every path including `/v1/models`:

```
HTTP/2 503
content-type: text/plain
server: istio-envoy

upstream connect error or disconnect/reset before headers. retried and the
latest reset reason: remote connection failure, transport failure reason:
delayed connect error: Connection refused
```

- The Northflank edge (istio-envoy) fronts the service; when the vLLM pod is
  down/asleep/loading, callers get **503 with a `text/plain` body**, not an
  OpenAI-style JSON error envelope.
- **What our code must therefore do:** never `response.json()` an error blindly.
  Branch on `content-type` (or wrap parse in try) and surface status + text.
  Treat 503-from-edge as "endpoint unreachable", distinct from a vLLM 4xx.
- Northflank CLI on this host: personal context has no projects; the three
  team contexts' tokens are expired (401). Service state can't be inspected or
  restarted from this machine — needs a fresh `northflank login` (human step).

## Status log

- 22:24–22:34: polled `/v1/models` every 15 s (40 attempts) → all 503 connection-refused.
- 22:35–22:47: extended poll every 30 s (24 attempts) → all 503. Not a cold
  boot (a wake triggered by our 22:24 request would have come up by now, even
  for a ~109B-total-param MoE): the service is stopped or crashed.

## Verdict for this session

**Endpoint unreachable for ~23 continuous minutes → S2's live deliverables
(probe battery, client-vs-snapshot, 40-task harness) are blocked.** Restarting
the service is a human step (Northflank UI or a fresh `northflank login`; all
CLI tokens on this host are expired). Before resuming S2, verify:

```
curl -s -o /dev/null -w '%{http_code}' "$LLM_BASE_URL/v1/models"   # must be 200
```

## 2026-07-16 — endpoint restored; validation run complete (D-013 follow-up)

Burhan restarted the service; `/v1/models` 200, `max_model_len` 100000.
Wire-shape fixtures captured to `tests/fixtures/llm/northflank/` — vLLM
streams tool-call arguments FRAGMENTED across ~9 deltas with `id: null`
continuations (the style the client's accumulator was built for; now pinned
by a regression test against the real capture). Full battery + 40-task
harness (`harness-run-nvidia-Llama-4-Scout-17B-16E-Instruct-FP8.json`,
scorecard row `153e221a-…`, workspace `dev`):

| Metric | llama3.1:8b | qwen3:14b | **Scout (this endpoint)** |
|---|---|---|---|
| valid-call rate | 98.7 % | 100 % | **100 % (98 calls)** |
| loop-completion | 52.5 % | 87.5 % | **77.5 %** |
| no-tool restraint | 0/4 | 4/4 | **4/4** |
| schema adherence | 10/10 | 5/5 | **5/5** |
| tok/s / wall (40 tasks) | 61 / 88 s | 33 / 943 s | **90.5 / 84 s** |
| **agent mode** | prompted_tools | native_tools | **native_tools** |

**The S2 existential question is answered: Scout does native multi-step
tool-calling above the bar (native_tools).** qwen3:14b still completes more
(87.5 %) but at ~11× the wall clock; Scout is the fastest of the three.

Scout's 9 failures: 5× long-string arg fidelity (the 64-char-hash failure now
reproduced across THREE model families — it even ADDED characters once;
observable-ID tool design is conclusively mandatory), 2× evidence threading,
and a NEW mode: 3 tasks emitted pseudo-code tool plans as plain text
(`[get_alert(...), get_asset(hostname=get_alert(...).observables[0].value)]`,
`{{template}}` placeholders) instead of native calls — the loop correctly
scored these as no-calls. S3 note: a cheap "final answer looks like a tool
plan" detector could retry such turns (parked in IDEAS.md).

## What our code must therefore do (from this probe so far)

1. Error bodies are not always JSON (Finding 0) — parse defensively, branch on
   content-type, keep the raw text for diagnostics.
2. Treat edge 503 as `reachable=false` in the capability scorecard — the
   scorecard model already encodes this (`decide_agent_mode` → `plan_only`).
3. The client needs a connect-time reachability probe with retry/backoff and a
   bounded wait — a customer endpoint being asleep is a normal state, not an
   exception (scale-to-zero is common for self-hosted vLLM).
