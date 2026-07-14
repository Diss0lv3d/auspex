---
description: Probe a live external system and save the reality snapshot to docs/probes/ before coding against it
argument-hint: <what to probe, e.g. "NVD API delta endpoint" or "vLLM tool-call streaming">
---

Probe: $ARGUMENTS

CLAUDE.md rule 4 made executable — never code against a remembered API. Steps:

1. Identify the exact live thing to hit (endpoint, cluster, model, feed) and
   which upcoming code will depend on it.
2. Hit it for real (curl/httpx/client), using creds from `.env` via shell vars —
   never echo secret values into output or files.
3. Capture what matters: request shape, response shape (trim to the fields we'll
   consume), status/error behavior on bad input, rate-limit headers, timing.
   Probe the failure mode too, not just the happy path.
4. Save to `docs/probes/YYYY-MM-DD-<slug>.md`: what was probed, how, trimmed
   real responses, quirks discovered, and "what our code must therefore do".
   Redact any secret or personal data before saving.
5. Commit the probe file, then answer: does reality match what we assumed? Call
   out every mismatch explicitly — those are the bugs we just avoided.
