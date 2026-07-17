# Probe: TD-005 calibration — labeled query battery on the live grown corpus

- **Date:** 2026-07-18 (S8, post-ATT&CK ingestion)
- **Corpus:** 3,417 chunks live (`auspex-knowledge`): ~2,000 NVD/KEV/EPSS +
  1,398 ATT&CK STIX (712 docs) + seed. Battery hit the neural leg directly
  (`neural` query, model lRDKb…) at k=10/50/100, unfiltered and filtered to
  curated types; scores are lucene cosinesimil, bounded [0,1].
- **Depends on it:** the per-doc_type `NEURAL_FLOORS` operating point in
  `auspex/kb/fuse.py`, regression-pinned in `tests/test_kb_fuse.py`.

## The headline: 0.6 fabricated AGAIN, live, the same day

Ingesting 1,398 curated ATT&CK chunks re-broke the definition path that the
S7 doc_types filter had fixed at ~20 curated chunks: max-of-N noise inside
the FILTERED pool crossed the flat 0.6 floor.

Live repro (before the fix, same container):
`what is quantum entanglement` → **"T1090.002: External Proxy — from the
knowledge base"** (cosine 0.617). After setting the curated floor to 0.65 →
honest "no curated definition" miss, with every true positive still
answering. TD-005's core claim — floors must be calibrated per pool, on the
grown corpus, every time the corpus changes shape — is now twice-proven.

## Battery results (labeled; measured scores)

**Curated pool (filtered to concept/technique/tactic, ~1.4k chunks):**

| query | expected | top score | verdict |
|---|---|---|---|
| what is lateral movement | CONCEPT-LATERAL-MOVEMENT | 0.840 HIT@0 | relevant |
| how do adversaries abuse command line interpreters | T1059 | 0.900 HIT@0 | relevant |
| what is credential access | TA0006 | 0.864 HIT@0 | relevant |
| what is process injection | T1055 | 0.858 HIT@0 | relevant |
| what is phishing | T1566 | 0.828 HIT | relevant |
| what is credential dumping | T1003 | 0.788 HIT | relevant |
| living off the land binaries | CONCEPT-LOLBIN | **0.691** HIT@0 | weakest relevant |
| employee vacation policy template | — | **0.618** (T1556.009) | noise ceiling |
| what is quantum entanglement | — | 0.617 (T1090.002) | noise |
| best hiking trails in the alps | — | 0.594 (T1518.001) | noise |
| how do I bake sourdough bread | — | 0.554 (T1546.004) | noise |

Gap [0.618 … 0.691] → **curated floor 0.65** (±0.032 margin both ways).
The curated pool is structurally bounded (ATT&CK 19.1 is the full technique
universe; concepts are hand-curated), so its noise ceiling should stay put.

**CVE pool (unfiltered, ~2k chunks, grows ~770 docs/day):**

| query | expected | top score | verdict |
|---|---|---|---|
| Log4j JNDI lookup remote code execution | CVE-2021-44228 | 0.841 HIT@0 | relevant |
| kubernetes ingress controller configuration | CVE-2026-55723 | 0.793 HIT@0 | relevant (see below) |
| SharePoint deserialization remote code execution | CVE-2026-58644 | **0.766** HIT@1 | weakest relevant |
| employee vacation policy template | — | **0.624** (CVE-2026-52840) | noise ceiling |
| best hiking trails in the alps | — | 0.609 (CVE-2026-54468) | noise |
| how do I bake sourdough bread | — | 0.575 | noise |

Gap [0.624 … 0.766] → **cve floor 0.70** (0.066 under weakest relevant,
0.076 over today's ceiling — headroom for growth; see trigger below).

**Labeling trap caught:** "kubernetes ingress controller configuration" was
designed as a tech-adjacent hard NEGATIVE — but its 0.793 top hit is
CVE-2026-55723, a real NGINX Ingress Controller configuration-injection
CVE the live delta had ingested. The corpus decides what's off-corpus, not
the test author. Relabeled relevant.

**Noise-ceiling growth series (max-of-N):** 0.498 @ 14 chunks (S6) →
0.617 @ ~2.5k (S7) → 0.624 @ 3.4k (S8) — growth is flattening
logarithmically, supporting an absolute floor WITH a re-battery trigger
rather than a relative scheme.

## k / ef sizing (measured together with the floors)

- Filtered curated queries at k = 2×top_k (=10): **7/7 recall, rank 0–3**
  — the doc_types filter makes lucene kNN exact over the subset, so k stays
  small by construction. No change.
- Unfiltered at k=10 vs 50 vs 100: every relevant query HIT at k=10 and
  stayed HIT at 50/100 (no rank instability observed at 3.4k chunks). The
  S7 HNSW-recall collapse did not reproduce on today's graph — but recall
  on an HNSW graph is state-dependent, so the k=10 result is NOT a license
  to ship unfiltered search; it's a datum. Re-battery before any unfiltered
  surface ships (none exists in v1).

## Operating point (shipped)

`NEURAL_FLOORS = {concept: 0.65, technique: 0.65, tactic: 0.65, cve: 0.70}`,
default `NEURAL_MIN_SCORE = 0.6` for unlabeled future types; applied per hit
in `neural_leg_floor` before fusion. Regression-pinned: every boundary row
above is a parametrized case in `tests/test_kb_fuse.py` — moving a constant
names the live query that breaks.

**Re-battery trigger:** corpus > 30k chunks, any new doc_type, or any
embedding-model change. The battery script pattern lives in this probe.
