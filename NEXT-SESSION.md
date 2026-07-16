# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-ups: (1) S5 is complete on `staging` but NOT promoted — the
multi-agent adversarial review was quota-blocked at S5 end (inline pass found
nothing blocking); re-run it, fix anything confirmed, THEN `/promote`. (2)
TD-004: registering the free auth.abuse.ch + AbuseIPDB keys is a HUMAN step —
Burhan, do it when convenient; the moment the env vars exist, key-gated
providers activate and their docs-coded parsers need a live re-probe.)_

---

SESSION S6 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S6` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch
→ STOP and tell me.

**Before S6 work (carried follow-up):** re-run the 5-lens adversarial review
of the S5 diff (`git diff 67c4a76..e2a1381` plus later fixes — or simply
`git diff main..staging` before promoting) — correctness/concurrency,
security/tenancy, probe-contract fidelity, test hermeticity, copy honesty;
adversarially verify findings, fix confirmed ones, then run `/promote`
(S5 = demoable milestone: live keyless enrichment with verdict decay store).

Goal (scope-locked, from ROADMAP.md S6 — KB/RAG on OpenSearch):

1. **Index design, mapping probe first**: probe our OWN OpenSearch container
   (D-009 — never SARA's cluster) for 2.19.x mapping/analyzer/kNN behavior
   before writing any mapping code (`/probe` → docs/probes/). Design the
   `auspex-knowledge` index (auspex-* prefix): chunk docs, metadata fields,
   knn_vector mapping.
2. **Embeddings — measure, then decide** (open blocker from S2): probe
   server-side OpenSearch ML-plugin embedding on the local container first;
   fallback decision = in-process sentence-transformers all-MiniLM-L6-v2.
   Save latency/footprint numbers to the probe file; D-entry the choice.
3. **Chunking + ingestion of a seed corpus** (small: a handful of MITRE
   ATT&CK technique summaries / CVE descriptions as fixtures) — enough to
   prove the pipeline; real feeds land S7/S8.
4. **Retrieval: BM25 + kNN + client-side RRF** (SARA pattern,
   sara_retriever.py:538,599 — re-snapshot the pattern to docs/probes/ before
   coding, worktree paths rot). **CVE/MITRE ID-query neural bypass** (an exact
   ID match must not depend on vector similarity) + regime-aware score floors.
5. **Wire into the S4/S5 shortcut rail**: cve_lookup + definition categories
   consult the KB (still NO LLM on these paths — same pattern as S5
   enrichment: code fetches, code renders, deferred copy stands when the KB
   is empty/unavailable). The S5 ioc_check echo may cite KB context for CVEs
   found via InternetDB `vulns[]` if trivial — else park in IDEAS.md.

Design inputs / reality already in the repo (cite, don't re-derive):
- OpenSearch container: 2.19.4 live (health-checked in /api/health/ready);
  probe conventions in docs/probes/2026-07-14-opensearch-cluster.md (SARA
  cluster study — schema conventions ONLY, D-009).
- S5 enrichment rail to imitate: `auspex/enrich/` (service on app.state,
  hermetic-test seam, honest deferred copy, breaker pattern).
- Shortcut handlers to extend: `auspex/classify/shortcuts.py`
  (CVE_DEFERRED_COPY / DEFINITION_DEFERRED_COPY are the strings to replace
  when the KB answers) + `auspex/routes/chat.py` ioc_check wiring as the
  template for KB-backed shortcut turns.
- Verdict store exists (D-017): retro-hunt hooks come S7 — do NOT build them
  in S6; new ideas → IDEAS.md.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic — OpenSearch is a
  compose dependency (fine, like Postgres), but no live external feeds in
  pytest; KB fixtures from probe snapshots.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
- No new LLM calls on shortcut paths. Errors bias deep (S4 rule).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers,
  move on. Tired human = short session; rituals anyway.
- End with `/session-end`; S6 done = KB-backed cve_lookup/definition answers
  demoable → consider `/promote`.
