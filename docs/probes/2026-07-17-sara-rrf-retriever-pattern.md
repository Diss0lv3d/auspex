# Probe: SARA retriever — RRF + ID-bypass + score-floor pattern (code snapshot)

- **Date:** 2026-07-17 (S6)
- **Target:** `/home/burhan/sara-open/sara_retriever.py` (1397 lines, mtime
  2026-07-17) — main checkout, not a worktree (worktree paths rot; this
  snapshot exists so S6+ code never depends on that file being present).
- **Why:** S6 retrieval (BM25 + kNN + client-side RRF) reuses SARA's
  *pattern*, not code (CLAUDE.md origin note). This file is the pattern's
  source of truth, with SARA's own audit findings inline.

## 1. RRF fusion — `_rrf_fuse` (sara_retriever.py:538-562)

Client-side reciprocal-rank fusion, no OpenSearch hybrid pipeline:

```python
rrf_k = 60
for rank, r in enumerate(results_a):           # leg A (BM25)
    score = weight_a / (rrf_k + rank + 1)
    fused.setdefault(uid, {**r, "score": 0.0})
    fused[uid]["score"] += score
# … same for leg B (neural), then sort desc, truncate to top_k
```

- Each leg is fetched at `top_k * 2` before fusing (line 581-583).
- Weights: `bm25_weight=0.4, neural_weight=0.6` defaults; an optional
  `alpha` ∈ [0,1] overrides both (issue #661) with response-mode-keyed
  defaults — technical modes lean lexical, conversational lean semantic
  (lines 1014-1028).
- Deduplication is by `_uid` (OpenSearch `_id`) — a doc appearing in both
  legs accumulates both contributions.

## 2. ID-query neural bypass — `_hybrid_search` + `_is_id_query` (571-613)

```python
if self._is_id_query(query):
    return self._bm25_search(query, top_k, filters)   # neural never runs
```

`_is_id_query` (599-613): regex-match a MITRE/CVE ID
(`T[A-Z]?\d{4}(\.\d{3})?|M\d{4}|G\d{4}|S\d{4}|DS\d{4}|CVE-\d{4}-\d+`,
line 277-280); remove the ID from the query; strip punctuation; the query is
ID-dominant when the remainder is empty, ≤ 2 words, or consists only of
trivial qualifiers (a ~50-word stoplist: "overview, describe, what, is,
mitre, technique, detect, mitigate, …", lines 587-597).

Rationale in code comments: embeddings don't understand "T1548" — neural
results for raw IDs are noise that RRF then *promotes*. Same bypass for
alias-resolved threat-group queries ("Kitten" drowns in other Kitten-named
groups, line 575-579).

## 3. Canonical-doc boosting for CVE queries (282-288, 397-401)

SARA audit 2026-05-06: bare CVE-ID queries landed at rank>1 because
content-rich crawl docs outscored the canonical enriched doc in BM25
multi_match. Fix: explicit `match_phrase` clauses on `doc_id` (and its
analyzed `doc_id.search` subfield) with high boosts for the canonical
prefixed forms (`ENRICHED-CVE-…` boost 50, `KEV-CVE-…` 40, bare 30).

**Auspex divergence:** that prefix zoo (`ENRICHED-`/`KEV-`/`STIX-`/
`TECHNIQUE-`) is SARA legacy. Auspex ingest is greenfield → dedicated
`ids` keyword field (array), exact `term`/`prefix` query, no boost
arithmetic against crawl noise. Our 2026-07-17 OpenSearch probe confirms
keyword-field terms are the only exact-match rail anyway (standard analyzer
splits `CVE-2024-3400` into 3 tokens).

## 4. Regime-aware score floor — `_regime_aware_cutoff` (655-671)

```python
if top_score < 0.1:      # RRF/neural regime — scores structurally tiny
    return max(0.003, top_score * 0.25)
return max(score_threshold, top_score * 0.4)   # BM25/lexical regime
```

SARA audit 2026-05-06 (comment inline): live probes showed two score
regimes — neural/RRF top scores 0.01–0.03, BM25 top scores 16–125. A single
0.4-of-top multiplier annihilated the neural longtail. The regime is
detected from the top score itself (`< 0.1` ⇒ RRF/neural).

`validate_results` (673-707): when the query contains a MITRE ID, the ID
match — not the score — is the quality gate (RRF scores aren't comparable
to BM25 scores).

**Auspex adaptation:** our kNN leg scores are bounded [0,1]
(lucene cosinesimil, measured 2026-07-17 probe) and RRF-fused scores are
~`weight/61`-scale, so the same two-regime shape applies:
- RRF regime (hybrid path): floor `max(0.003, top*0.25)`.
- BM25-only regime (ID-bypass path): floor `max(threshold, top*0.4)`.

## 5. Misc conventions worth copying

- `_source: {excludes: [embeddings…]}` on every search — never ship vectors
  back over the wire (lines 493, 526).
- `search(mode=…)` entry point: explicit `"bm25" | "neural" | "hybrid"`
  selector, filters as a list of `term` clauses ANDed into a `bool.filter`
  (lines 980-1052).
- Multi-field BM25: `multi_match` over `content^3, doc_id.search^5`,
  `type: best_fields`, `fuzziness: AUTO` (line 480-482).
- Tenant scoping exists as a filter + an application-layer monotonicity rail
  (lines 1039-1059) — Auspex: workspace_id lands in the mapping from day
  one; enforcement rails come with multi-workspace phases, not S6.

## What Auspex S6 therefore builds

1. Client-side `rrf_fuse(legs, weights, k=60)` over `top_k*2` per leg.
2. `is_id_query()` port (regex + trivial-qualifier remainder test) →
   ID-dominant queries NEVER touch neural; they hit `term`/`prefix` on the
   `ids` keyword field first, BM25 as fallback.
3. Two-regime score floor keyed off the top score, constants as in §4.
4. `_source` excludes the `embedding` field everywhere.
5. Explicit mode selector on the retriever; filters = bool.filter terms.
