# Probe: S4 deep path live verification (post-92/8-gate, real Scout)

- **Date:** 2026-07-16 (S4, after the lazy-resolver refactor)
- **Target:** containerized app (`localhost:8000`) → Northflank Llama-4-Scout (D-015 primary)
- **Why:** the deep path was refactored in S4 (ChatEndpointResolver, lazy client
  build) with only fake-client test coverage; and the old smoke messages now
  classify as shortcuts, so this run asserts `done.path == "model"` per the
  caution in 2026-07-16-server-to-ollama-networking.md.

## Deep turn — "summarize the risks of exposed RDP in two sentences"

```
frame kinds: session ... done | total: 190
reasoning frames: 147 | chars: 824        ← two-pass (Scout: native_reasoning False)
content: "Exposed RDP increases the risk of unauthorized access, data breaches,
          and malware deployment. …"
done: {'finish_reason': 'stop',
       'usage': {'prompt_tokens': 257, 'completion_tokens': 42, 'total_tokens': 299},
       'path': 'model'}   ✅
```

## Behavior change check — bare "thanks" must reach the model (S4 review)

```
content: "Noted."
done: {'finish_reason': 'stop', 'usage': {..., 'total_tokens': 161}, 'path': 'model'}   ✅
```

Both paths verified the same day the gate landed: shortcut turns stream
`path: "shortcut"` with zero LLM calls (see session log / test suite), deep and
acknowledgement turns stream from the real endpoint with `path: "model"`.
