# STATE — Auspex

_Last updated: 2026-07-17 (S6 complete — KB/RAG on OpenSearch, live-verified)_

## Where we are
- **S6 COMPLETE** (all 5 steps + 2 live-caught fixes, tests shipping with each)
  → **next is S7** (Ingestion 1: NVD delta + CISA KEV + FIRST EPSS — see
  NEXT-SESSION.md). S6 is on `staging`, NOT yet promoted — run the adversarial
  review, then `/promote` (standing follow-up #1 below).
- **Promoted:** promote #5/#6 on `main` == full S5 milestone. `main` does NOT
  have S6 yet.
- **Primary dev LLM (D-015):** Llama-4-Scout via Northflank; secondary/offline
  Ollama `qwen3:14b` (D-013). S6 touched no LLM paths (KB shortcuts are
  LLM-free by design, test-enforced: `done.path == "shortcut"`).
- **CI-green: 320 tests** (was 246 at S5 end; +74 across S6). `./ci.sh` passes
  end-to-end: ruff, pytest, container build + health + ready.

## S6 shipped (all committed on staging, 2026-07-17)
- **Probes first (rule 4):** docs/probes/2026-07-17-opensearch-knn-ml.md — our
  OWN 2.19.4 container measured. Headline reality bites: **TORCH_SCRIPT of
  all-MiniLM-L6-v2 FAILS to deploy on 2.19.4** (`aten::scaled_dot_product_attention`
  unknown to bundled DJL) — **ONNX works and is pinned**; standard analyzer
  SPLITS `CVE-2024-3400` into 3 tokens (exact-ID matching must be keyword-rail);
  `only_run_on_ml_node` default blocks single-node deploy; model auto-redeploys
  after container restart (data volume intact). Also
  2026-07-17-sara-rrf-retriever-pattern.md (RRF/ID-bypass/floor constants) and
  2026-07-17-nvd-api.md (NVD 2.0 shape; terse 54-char MSRC descriptions exist).
- **D-018 ratified (measured):** embeddings are server-side (OpenSearch ML
  plugin, all-MiniLM-L6-v2 1.0.2 ONNX, dim 384): 25–30 ms warm single,
  ~8 ms/text batch-16, +0.5 GiB container RSS, 609 MB disk — vs 2 821 MB of
  wheels for in-process sentence-transformers (disqualified on footprint;
  latency deliberately unmeasured).
- **`auspex/kb/` package:** KnowledgeService on `app.state.kb` (S5 service
  pattern: settings-built, breaker, hermetic seam, KBUnavailable → deferred
  copy, never a 500). Idempotent never-raising bootstrap: ML cluster setting →
  model find/register/deploy (by NAME — model_id is volume-specific) → strict
  mapping `auspex-knowledge` (keyword `ids` rail, knn_vector 384
  lucene/hnsw/cosinesimil) → seed ingest (upsert by chunk_id, self-healing).
  Live-verified both cold ("seeded 14 chunks") and warm ("seed present").
- **Seed corpus (14 chunks):** 5 CVEs live-fetched from NVD (values verbatim,
  incl. the 54-char CVE-2023-23397), 6 ATT&CK technique summaries + 3 concepts
  hand-curated and **honestly labeled** (`attack-seed-summary` / `auspex-seed`
  — never passed off as verbatim MITRE). `nvd_to_doc()` is S7's parser.
- **Retrieval:** ID-dominant queries (ported SARA `is_id_query`) take the
  keyword ID rail — term boost 10 + parent-technique prefix (`T1059.` pulls
  sub-techniques; NEVER prefix for CVEs) — and neural never runs. Free text =
  BM25 + neural fused client-side (RRF k=60, weights 0.4/0.6, legs at
  top_k×2), regime-aware relative floor + **absolute neural floor 0.6**.
  Per-leg degradation: neural *unavailability* ⇒ BM25-only; neural
  *disagreement* (post-floor empty) ⇒ honest miss.
- **Chat wiring:** cve_lookup + definition shortcuts consult the KB, zero LLM
  (test: KB answers, fake LLM never called). Three truths, three copies:
  KB inactive ⇒ S4 static deferred; active-but-down ⇒ "didn't answer this
  turn"; connected-but-ignorant ⇒ explicit per-CVE miss / definition miss
  copy. `KB_ENABLED` born in .env.example + docs/ENV_VARS.md; host pytest
  pins it false (hermetic; fake at `app.state.kb`).
- **Live-verified in-container** (docs/probes/2026-07-17-s6-kb-live.md): full
  turn matrix — Log4Shell CRITICAL/10.0 with NVD source line; multi-CVE with
  explicit miss; hybrid definition (real neural, cosine 0.84); `what is T1059`
  via ID rail; `what is T1566` surfaces T1566.001 via prefix rail; off-corpus
  and unknown-ID queries return honest miss copy. All `path=shortcut`.
- **Two real bugs caught BY the live verify, fixed + pinned as regressions:**
  (1) missing absolute neural floor — kNN returns k neighbors for ANY query;
  off-corpus questions would have fused noise into a fabricated "KB answer"
  (`b0a026a`); (2) BM25 stopword/fuzzy leak — "what is quantum entanglement"
  scored 4.4 on the C2 doc via "what"/"is"+fuzziness; post-floor-empty neural
  leg is now the relevance gate, ID-rail misses stop falling back to fuzzy
  prose, `minimum_should_match: 2<75%` damping (`7446fbc`).

## In-flight / standing follow-ups (carry forward until DONE)
1. **Run the S6 adversarial review, then `/promote`** — S6 is demoable and
   CI-green on staging but unreviewed. Same drill as S5: multi-lens review
   pass over `auspex/kb/` + chat wiring, fix what's real, then promote #7.
   (S5's review found 7 real fixes; don't skip.)
2. **TD-005** — `NEURAL_MIN_SCORE=0.6` is calibrated on a 3-point sample;
   recalibrate with a labeled query set once S7/S8 corpora exist.

## Blockers / open risks
1. ~~Embeddings approach unmeasured~~ RESOLVED: D-018 (measured, ONNX pinned).
2. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
3. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat; history replay unbounded; shortcut answers replayed into
   deep-turn history. Parked in IDEAS.md; modes land S9.
4. **KB bootstrap needs outbound HTTPS once per fresh volume** (model download
   from artifacts.opensearch.org, ~12 s). Air-gapped path parked in IDEAS.md;
   failure degrades to honest deferred copy, app boots fine.

## Host notes (reality snapshot)
- Postgres host port **55432**; app 8000; OpenSearch 9200. Host runs pin via
  `auspex.devhost` (DB/OpenSearch/APP_ENV + ENRICHMENT_ENABLED=false +
  **KB_ENABLED=false** new in S6 — override in shell for host-run live KB).
- OpenSearch container now carries the embedding model: +0.5 GiB RSS
  (~2.2 GiB total), 609 MB ml_cache on the data volume. 1 GiB heap unchanged.
- Ollama 0.24.0 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- Host reboots between sessions — `docker compose up -d --wait` at start;
  the KB model auto-redeploys (probed).
- `gh` may wake up as SIRP-Burhan — session-start switches to
  bh3082336888-cell (D-011); happened again this session.

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
Base: `/home/burhan/sara-open/` (paths re-verified 2026-07-15):
- ReACT loop: /home/burhan/sara-open/sara/core/agent_loop.py:60
- Plan→DAG→Judge loop: /home/burhan/sara-open/.claude/worktrees/1359-chain-surface/sara/core/orchestrator_loop/runner.py:39
  (worktrees get cleaned; re-snapshot to docs/probes/ before S8)
- Permission hard-rails: /home/burhan/sara-open/sara/core/permissions.py:65-176
- Fast classifier / 92-8: docs/probes/2026-07-16-sara-fastpath-pattern.md
- Enrichment/fan-out: probe docs 2026-07-16 (supersede SARA notes)
- RRF retrieval + ID bypass: docs/probes/2026-07-17-sara-rrf-retriever-pattern.md
  (snapshot — the live sara_retriever.py no longer needs to exist)
- DEFERRED rail: /home/burhan/sara-open/sara/agents/alert_triage.py:1429
- Capability shape: /home/burhan/sara-open/sara/core/unified_registry.py:37

## Next session should
Review S6 (`/review` drill or the S5-style multi-lens pass) → `/promote` →
then run S7 exactly as written in NEXT-SESSION.md (Ingestion 1: NVD delta +
KEV + EPSS with ingest_state + catch-up scheduler).
