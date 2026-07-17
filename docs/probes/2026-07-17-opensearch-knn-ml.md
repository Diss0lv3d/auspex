# Probe: local OpenSearch 2.19.4 — analyzers, kNN, ML-plugin embeddings

- **Date:** 2026-07-17 (S6)
- **Target:** our own container `auspex-opensearch-1`
  (`opensearchproject/opensearch:2.19.4`, single node, `-Xms1g -Xmx1g`,
  security plugin disabled — D-009: this is the ONLY cluster Auspex touches)
- **Why:** design `auspex-knowledge` index + decide embeddings approach
  (S2 open blocker) before writing any mapping/retrieval code.
- **How:** curl against `localhost:9200`; timings via `date +%s.%N` around the
  call (includes ~1–3 ms curl process overhead — fine at these magnitudes).

## Cluster facts

- 2.19.4 (Lucene 9.12.3), build 2025-11-01.
- Plugins present (all 2.19.4.0): `opensearch-knn`, `opensearch-ml`,
  `opensearch-neural-search` (plus alerting/security-analytics/sql/etc.).
- Container memory before ML model: 1.64 GiB. Heap 1 GiB.

## Analyzer behavior (standard analyzer) — ID tokenization

```
"CVE-2024-3400 affects PAN-OS GlobalProtect"
  → [cve, 2024, 3400, affects, pan, os, globalprotect]
"T1059.001 PowerShell is a sub-technique of T1059"
  → [t1059.001, powershell, is, a, sub, technique, of, t1059]
```

Quirks:
- `CVE-2024-3400` is SPLIT into 3 tokens → BM25 "exact CVE match" is a lie:
  `CVE-2024-9999` shares 2 of 3 tokens with any 2024 CVE query.
- `T1059.001` stays ONE token (digit.digit keeps the dot) → BM25 won't match
  parent `T1059` against sub-technique docs (no prefix expansion).

**Therefore:** exact-ID retrieval must use a `keyword` field with
`term`/`prefix` queries (the ID-bypass rail), never the analyzed text field.

## kNN (index.knn=true, engine=lucene, hnsw, cosinesimil)

- Index creation with `knn_vector` (dim 4 probe / dim 384 real) — acknowledged,
  no surprises. `m:16, ef_construction:128` accepted.
- **Score normalization measured:** query `[1,0,0,0]` →
  identical vec `1.0`; 45° vec `0.8535`; orthogonal `0.5`.
  I.e. score = `(1 + cosine) / 2`, **bounded [0,1]** — absolute score floors
  are meaningful on the kNN leg.
- BM25 on the same corpus: 0.98 for a 1-term match on 3 docs — **unbounded**,
  corpus-dependent → floors on the BM25 leg must be relative/regime-aware;
  fusion must be rank-based (RRF), not score-mixed.
- `filter` inside the `knn` clause works (lucene efficient filtering):
  filtered probe returned only the filtered doc, correct score.

## ML-plugin server-side embeddings (all-MiniLM-L6-v2)

Prerequisite: `plugins.ml_commons.only_run_on_ml_node` defaults to **true**
→ deploy on our single (data) node fails until it's set `false` (persistent
cluster setting; lives in the data volume → a FRESH volume loses it —
bootstrap code must (re)apply it idempotently).

### Reality bite: TORCH_SCRIPT format is broken on 2.19.4

`huggingface/sentence-transformers/all-MiniLM-L6-v2` v1.0.2 `TORCH_SCRIPT`:
register OK, **deploy FAILS**:

```
Unknown builtin op: aten::scaled_dot_product_attention
  (torchscript traced with newer PyTorch than the DJL engine bundled in 2.19.4)
```

**ONNX format of the same model works.** Pin `model_format: "ONNX"`.

### Measured numbers (ONNX, v1.0.2, dim=384)

| Step | Number |
|---|---|
| register (downloads from artifacts.opensearch.org) | ~12 s (needs outbound net once per volume) |
| deploy | ~3 s |
| disk (container `data/ml_cache`) | 609 MB (model + onnxruntime natives) |
| container RSS delta | 1.64 → 2.17 GiB (+~0.5 GiB) |
| `_predict` single text, warm | 25–30 ms (first call ~107 ms) |
| `_predict` batch of 16 | 100–175 ms (~8 ms/text amortized) |
| `neural` query (server-side embed, 1 round trip), warm | ~30 ms |

`neural` query scores come back on the same [0,1] cosinesimil scale
(semantically correct ranking verified: "scripting engine command execution"
→ PowerShell doc 0.695, phishing doc 0.498).

### Restart behavior (host reboots between sessions — this matters)

- `plugins.ml_commons.model_auto_redeploy.enable` defaults **true** (retry 3).
- `docker compose restart opensearch` → model state `DEPLOYED` immediately
  after cluster green; first neural query 176 ms, then ~29 ms. **No manual
  redeploy needed** as long as the data volume survives.

### Error shapes (for the deferred rail / breaker)

- `_predict` on missing model → HTTP 404,
  `{"error":{"type":"status_exception","reason":"Failed to find model"},"status":404}`
- `neural` query with bad model_id → search error, same
  `status_exception` / "Failed to find model".
- `model_id` is volume-specific (assigned at register time) → resolve by
  model NAME at startup, cache; never hardcode an ID.

## Fallback option measured: in-process sentence-transformers

Not installed anywhere (host, app container, venv). pip resolver report
(`--dry-run --report`): **59 packages, 2 821 MB of wheels** (default pull is
CUDA torch: torch 527 MB + ~1.9 GB nvidia-* + triton 198 MB). Even CPU-only
torch is ~200 MB+ and adds a second copy of the model RAM-resident in the
app container. Latency was NOT measured — footprint alone disqualifies it
while the server-side path works (it adds ~2.8 GB to an image that today has
no torch at all).

## What our code must therefore do

1. **Bootstrap idempotently** (service init, not compose): apply
   `only_run_on_ml_node=false`; register+deploy `all-MiniLM-L6-v2` v1.0.2
   **ONNX** if absent (match by name, reuse existing model_id); create
   `auspex-knowledge` index if absent. Fresh volume ⇒ all three re-run.
2. **Resolve model_id by name** at startup → app.state; never hardcode.
3. Mapping: IDs (`CVE-…`, `T….…`) in `keyword` fields; ID bypass via
   `term`/`prefix` on keyword, never neural. `knn_vector`: dim 384,
   lucene/hnsw/cosinesimil.
4. Fusion: client-side RRF over ranks. Floors: absolute floor OK on kNN leg
   (bounded scores); BM25 leg regime-aware/relative.
5. KB down / model missing / index missing → honest deferred copy
   (S5 breaker pattern), never a 500; 404 "Failed to find model" is the
   signal to re-bootstrap or defer.
6. CI/pytest: fresh OpenSearch has NO model → unit tests mock the KB seam
   (like `app.state.enrichment`); container/integration path bootstraps.
7. First-boot registration needs outbound HTTPS to artifacts.opensearch.org
   — air-gapped deploys will need `allow_registering_model_via_url/local_file`
   (parked; not an S6 problem).

## Probe hygiene

Probe indices `probe-knn`, `probe-neural` deleted. Model + cluster setting
left in place (they ARE the S6 deliverable's substrate). No secrets involved
(local dev container, security disabled).

## Addendum (same day): model search-by-name API

`POST /_plugins/_ml/models/_search` with `term: name.keyword` returns the
model doc **plus one hit per binary chunk** (11 hits for one model; chunk ids
are `<model_id>_0…_9`). The real model doc is isolated with
`must_not: exists(chunk_number)` — it alone carries `model_state`
(e.g. `DEPLOYED`) and `total_chunks`. Bootstrap must filter accordingly, and
`model_version` in this index is the internal revision ("2"), NOT the
registry version ("1.0.2") — don't match on it.
