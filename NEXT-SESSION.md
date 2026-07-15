# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(No standing follow-ups. The S3 Ollama-networking blocker is closed: host
Ollama binds `*:11434` and the containerized app streamed a real /api/chat
end-to-end on 2026-07-16 — docs/probes/2026-07-16-server-to-ollama-networking.md.)_

---

SESSION S4 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S4` first (full ritual, incl. the D-013 dev-LLM gate: local
Ollama + `qwen3:14b`). Any mismatch → STOP and tell me. Note: S4's shortcut
path uses NO LLM; the gate matters only for the deep-path stub + any optional
live check.

Goal (scope-locked, from ROADMAP.md S4 — Fast classifier / 92-8 split).
The 92/8 principle (SARA pattern): ~92% of queries take a deterministic,
CODE-OWNED fast path with NO LLM; only the ~8% deep path reaches the agent
loop. Code picks the path, never a prompt (ADR: code over prompts). Tests ship
WITH each step (CLAUDE.md rule 8), not as a trailing phase.

**Must-ship core: steps 1–3 with their tests. Stretch: step 4.**

1. **IOC regex patterns, defang-aware** (`auspex/classify/` or similar): extract
   + normalize IPv4/IPv6, domains, URLs, SHA-256/-1/MD5, emails, CVE IDs.
   Defang-aware on input (`hxxp`, `[.]`, `(.)`, `[at]`, trailing-dot) → canonical
   form out. Pure functions. Ships with: extraction/normalization unit tests
   incl. defanged inputs. (Design input from S3 harness: downstream tool args
   will carry short observable IDs, NOT raw 64-char strings — keep normalized
   observables addressable by a short id when you design their shape; parked in
   IDEAS.md.)
2. **Query classifier** (code-owned): map a user query to a category —
   greeting / identity / ioc_check / cve_lookup / definition / deep. Deterministic
   (regex + keyword + format signals; format beats keywords). Ships with:
   classifier tests pinning each category + ambiguous-case tiebreaks.
3. **Shortcut handlers** (NO LLM on this path): greeting + identity = static
   on-brand copy (engine never named); ioc_check = extract + normalize + echo
   the observables (enrichment is S5 — do NOT call providers); cve_lookup +
   definition = stub/deferred cleanly (KB is S6) — return a clear "deep path
   needed" or a tiny curated static answer, your call, but NO LLM and NO network.
   Ships with: handler tests (esp. that the shortcut path makes zero LLM/network
   calls).
4. _(stretch)_ **Deep-path wiring**: route classifier `deep` verdicts into the
   existing SSE `/api/chat` (currently always-LLM, conversational). Shortcut
   categories answer without touching the LLM; only `deep` streams from the
   model. Keep the single-key SSE protocol. Ships with: a test that a greeting
   returns a shortcut answer with no LLM client call, and a deep query does hit
   the (fake) client.

Design inputs / reality already in the repo (cite, don't re-derive):
- The agent loop (`auspex/agent/loop.py`) takes `tools=None` cleanly and has a
  plan_only/conversational mode — the deep path plugs into it later (S9 modes).
- SSE endpoint + client reasoning field already exist (S3). The classifier sits
  in FRONT of the LLM call in `/api/chat` for step 4.
- SARA 92/8 + fast-classifier reference (reuse the PATTERN, not the code):
  study `/home/burhan/sara-open` (the fast-path/shortcut handlers); snapshot any
  external behavior to docs/probes/ before coding against it.

Constraints:
- Dev endpoint is local Ollama + qwen3:14b (D-013); live LLM calls outside
  pytest only — CI stays hermetic. The S4 shortcut path must be LLM-free AND
  network-free (assert it in tests).
- No OpenSearch index creation (S6). No enrichment providers (S5).
- Reality over memory: any new external behavior → probe file first.
- New ideas → IDEAS.md, one line, move on.
- End with `/session-end`; if S4 hits a demoable milestone, consider `/promote`
  (staging → main). `main` has NOT been promoted since before S3 — S3 is a full
  demoable milestone (agent loop + chat + UI), so an S3 `/promote` is also
  reasonable to do first.
