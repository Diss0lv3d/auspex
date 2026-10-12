# F1 — where a deep turn's reasoning loses its speed (endpoint · server · page)

_2026-10-12, F1. Burhan, 2026-10-10: "we should perhaps increase the stream bit
rate so it renders faster". Measured before anything was changed. B1's window
was paused for every run; the GPU was idle except for the qwen runs._

## Method

- **Layers 1 and 2 on the SAME completion** — `fe-stream/probe_layers.py`. The
  app runs in-process on the host (uvicorn :8011, KB on), with
  `LLMClient.chat_stream` wrapped to stamp each endpoint event as the app's
  client parses it. A client in the same process stamps each `/api/chat` frame
  on arrival. Each route frame is matched to its endpoint delta in order, so the
  lag is exactly what the server path adds (loop, rail scan, SSE, loopback).
- **Layer 3, the page** — `fe-stream/page_paint.js`, evaluated in headless
  Chromium (Playwright) against the rebuilt container on :8000. It wraps the
  page's own `handleEvent` and stream reader. For each frame it records arrival,
  handling time and the next animation frame (when it can paint), plus long
  tasks.
- Questions: EDR vs XDR (Q1), Kerberoasting (Q2), lateral movement after
  phishing (Q3), pass-the-hash in event logs (page only). Q1 was left out of
  the page runs because of B-002.
- Raw output: `raw-layers-glm-default.log`, `raw-layers-glm-glm-native.log`,
  `raw-layers-qwen.log`, `raw-page-paint.log`. Medians, with [min .. max].

## Results

### Layer 2 − layer 1: what the server adds

| endpoint · path | runs | lag per reasoning delta, p50 | p95 | max | rate, endpoint → route (chars/s) |
|---|---|---|---|---|---|
| glm-4.5-air · agent | 5 | 1.2 ms | 2.4 ms | 4.6 ms | 729 → 729 [633 .. 1160] |
| glm-4.5-air · conversational | 5 | 0.8 ms | 1.6 ms | 2.5 ms | 311 → 311 [252 .. 368] |
| qwen3:14b · conversational | 3 | 0.2 ms | 0.5 ms | 3.9 ms | 165 → 165 [163 .. 165] |

Every endpoint delta reached the client, except one in each of the two B-002
turns. No frame was batched or re-ordered. The time from the POST to the
first endpoint call was 0.02–0.03 s, and between two agent calls the server
spent 0.05–0.35 s (tool execution and the next claim).

**The server path adds about a millisecond. It is not where the time goes.**

### Layer 3: what the page adds

| endpoint (page label) | turns | handle a frame, p50 / max | frame → paint, p50 | p95 | max | long tasks |
|---|---|---|---|---|---|---|
| glm-4.5-air (Standard, agent) | 3 | 0.1 / 15.8 ms | 2.7 ms | 7.9–15.3 ms | 29 ms | 0 |
| qwen3:14b (Deep — shows reasoning) | 3 | 0.3 / 1.6 ms | 2.4 ms | 4.3–13 ms | 41 ms | 0 |

The answer's `textContent +=` never exceeded 1.7 ms per frame at 2.6k chars.
glm's frames arrive in network bursts (574–1152 frames in 28–46 reads); qwen's
arrive one per read. Inside a burst the page paints glm's reasoning at
**990–1026 chars/s**.

**The page adds about 3 ms. It is not where the time goes either.**

### Layer 1: the endpoint is the whole of it

| | glm-4.5-air, agent (page) | glm-4.5-air, agent (in-process) | qwen3:14b (page) |
|---|---|---|---|
| first reasoning on screen | 2.0–2.6 s | 2.35–2.58 s | 0.14–0.21 s (warm) |
| first answer character | 8.5 / 9.8 / 29.8 s | 12.0 [12.0 .. 14.1] s | 11.0 / 12.4 / 20.4 s |
| turn | 11.9 / 13.1 / 32.3 s | 15.2 [9.1 .. 16.6] s | 23.6 / 31.0 / 30.6 s |
| reasoning rate while streaming | ~1000 chars/s in bursts | 729 chars/s within a call | 139–171 chars/s, steady |
| silences over 1 s | 2–7 per turn, 1.0–12.9 s each | — | none |

- **glm-4.5-air** streams fast but in bursts. On the agent path the analyst
  waits through the silences between them: 3–5 model calls per turn, each
  starting 1–3 s after the last, plus one outlier. In the 32 s page turn,
  12.9 s passed between the knowledge searches returning (01:57:10.29 UTC) and
  the endpoint answering the fourth call (01:57:23.17, container log). The
  server's own share of a gap between calls was 0.05–0.35 s in every
  in-process turn.
- **qwen3:14b** is smooth and slow: 139–171 chars/s, half glm-4.5-air's
  conversational rate (311) and a sixth of its agent bursts; 24–31 s a turn. The page's switcher labels it "Deep — shows
  reasoning". "Standard" (glm-4.5-air) shows its reasoning too.
- qwen3:14b's cold start is 4.7 s to the first byte (unloaded, then one direct
  request); warm, 0.08 s. **B-001's turn waited 30 s for headers and 3 min 13 s
  overall. Neither is reproduced here**, and that turn is B1's to explain.

## Conclusion

The model is the bottleneck. On these turns the server adds ~1 ms per delta
and the page ~3 ms to paint, so no change to the stream path or the page's
painting can make the reasoning arrive faster. What the analyst feels as
"slow" is:

1. on glm-4.5-air, the agent path's **silences** between bursts (1–3 s each,
   2–7 per turn, one of 12.9 s), during which the page shows nothing changing;
2. on qwen3:14b, a **slow model**: ~165 chars/s, the slowest endpoint the
   switcher offers, under the label that promises reasoning;
3. the **first ~2.5 s** on glm, where the Co-analyst block is empty.

Pacing the text ("increase the stream bit rate") cannot help: it already
paints as fast as it arrives, and a typewriter pace would only delay text
that has arrived. What the page does while the engine thinks is a choice for
Burhan (F1 does not pick one unasked).
