---
description: Summarize a GitHub issue in plain, non-technical language
argument-hint: <issue number or URL>
---

Explain issue $ARGUMENTS in plain terms, as if to a smart person who doesn't
code. Fetch it with `gh issue view <n> --comments` (if no remote exists, ask
for the pasted text).

Produce, in under 150 words total:
- **What's broken** — one or two sentences, zero jargon (no stack traces, no
  class names; "the login button" not "the OAuth callback handler").
- **Who feels it** — which users/situations hit this, and how often.
- **How bad** — real-world consequence, not severity labels ("you could see
  someone else's data" beats "P1").
- **Status** — what's known, what's being done, what's still unknown.
- **Analogy** (optional) — one everyday comparison if it genuinely clarifies.

Rules: no code snippets, no file paths, no acronyms without expansion. If the
issue thread is contradictory or unclear, say what's ambiguous instead of
smoothing over it.
