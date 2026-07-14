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

## What our code must therefore do (from this probe so far)

1. Error bodies are not always JSON (Finding 0) — parse defensively, branch on
   content-type, keep the raw text for diagnostics.
2. Treat edge 503 as `reachable=false` in the capability scorecard — the
   scorecard model already encodes this (`decide_agent_mode` → `plan_only`).
3. The client needs a connect-time reachability probe with retry/backoff and a
   bounded wait — a customer endpoint being asleep is a normal state, not an
   exception (scale-to-zero is common for self-hosted vLLM).
