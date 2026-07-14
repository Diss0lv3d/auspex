# STATE — Auspex

_Last updated: 2026-07-14 (S0 bootstrap, done in the sara-open-copy study session)_

## Where we are
- **Current session: S0 complete → next is S1** (see NEXT-SESSION.md).
- Repo bootstrapped at `/home/burhan/new-sara` (note: `/home/new-sara` was
  root-owned; symlink optional: `sudo ln -s /home/burhan/new-sara /home/new-sara`).
- Protocol, roadmap, decisions, brand: written and ratified.
- OpenSearch cluster probed and documented (docs/probes/2026-07-14-opensearch-cluster.md).
- `.env` seeded (gitignored) with OpenSearch creds + Northflank LLM endpoint.
- No application code yet.

## In-flight
- Nothing.

## Blockers / open risks
1. **Llama-4-Scout tool-calling quality unproven** — the existential risk.
   S2's harness answers it. Until then, don't build anything that assumes
   reliable multi-step native tool calls.
2. **DO OpenSearch ML plugin capability unverified** — can we deploy a
   server-side embedding model on a managed cluster? Probe in S6; fallback is
   in-process MiniLM (decided, not a blocker — just unmeasured).
3. **Northflank endpoint unauthenticated** (D-006, accepted for testing).

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
The full 5-part study lives in the sara-open-copy session; the distilled
patterns-to-reuse and patterns-to-avoid are encoded in ROADMAP.md session
descriptions. Key file references if we ever need to re-check a pattern:
- ReACT loop: sara-open-copy/sara/core/agent_loop.py:60
- Plan→DAG→Judge loop: sara-open-copy/sara/core/orchestrator_loop/runner.py:39
- Permission hard-rails: sara-open-copy/sara/core/permissions.py:65-176
- RRF retrieval + ID bypass: sara-open-copy/sara_retriever.py:538,599
- DEFERRED rail: sara-open-copy/sara/agents/alert_triage.py:1429
- Capability shape: sara-open-copy/sara/core/unified_registry.py:37

## Next session should
Run S1 exactly as written in NEXT-SESSION.md.
