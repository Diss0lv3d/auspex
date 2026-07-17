# Probe: MITRE ATT&CK Enterprise STIX bundle (attack-stix-data)

- **Date:** 2026-07-18 (S8)
- **Probed:** `raw.githubusercontent.com/mitre-attack/attack-stix-data/master/`
  — `index.json` + `enterprise-attack/enterprise-attack-19.1.json`, live curl.
- **Depends on it:** S8 ATT&CK ingestion (replaces the 6 hand-curated
  `attack-seed-summary` technique docs with real STIX-derived
  `doc_type=technique` docs through the S7 scheduler).

## The version index is the cursor (31.5 KB vs 53 MB)

`index.json` (31,516 bytes) lists every collection + version:
Enterprise ATT&CK has **40 versions**; latest **19.1, modified
2026-05-12T14:00:00.188Z**, with a stable per-version URL
(`enterprise-attack-19.1.json`). Cadence: ~2 major releases/year
(April + October window) plus point releases — a daily/hourly poll of the
index is cheap and the 53 MB bundle downloads only on a version change.

```json
{"version": "19.1", "modified": "2026-05-12T14:00:00.188Z",
 "url": ".../enterprise-attack/enterprise-attack-19.1.json"}
```

## Bundle size & transport

- **53,277,393 bytes raw / 8,969,220 wire** (gzip, `--compressed`); 5.7 s
  download on this host.
- **`If-None-Match` IS honored** (unlike CISA KEV's encoding-varying ETag):
  replaying the ETag → **304, 0 bytes** — on both index.json and the bundle.
  Versioned bundle URLs are effectively immutable anyway; the INDEX drives
  freshness.
- Bad version path (`enterprise-attack-99.9.json`) → plain **404**.
- TD-010 note: 53 MB parsed in one `json.load` — the ATT&CK fetch happens
  only on version change (~2×/year), but it is by far our largest single
  feed read.

## Shape (19.1, live-measured)

25,843 objects:
`relationship` 21,025 · `x-mitre-analytic` 1,758 · **`attack-pattern` 858** ·
`malware` 729 · `x-mitre-detection-strategy` 699 · `course-of-action` 268 ·
`intrusion-set` 189 · `x-mitre-data-component` 109 · `tool` 95 ·
`campaign` 56 · `x-mitre-data-source` 38 · **`x-mitre-tactic` 15**.

One `x-mitre-collection` object carries **`x_mitre_version: "19.1"`** — the
honest provenance label for every derived doc.

### attack-pattern (858 total → **697 live**)

- `revoked: true` on **149**, `x_mitre_deprecated: true` on **12** — both
  must be filtered (no external_id collisions between live and dead ids).
- Live = 222 parents + **475 sub-techniques** (`x_mitre_is_subtechnique`).
- Every live technique has `external_references[source_name=mitre-attack]`
  with `external_id` (`T1059`, `T1055.011`) + canonical attack.mitre.org URL.
  **Sub-technique parentage is encoded in the id itself** (`T1055.011` →
  `T1055`) — our existing ID-rail prefix behavior needs nothing new.
- Fields we consume: `name`, `description`, `kill_chain_phases[].phase_name`
  (tactic shortnames), `x_mitre_platforms`, `x_mitre_version` (per-object,
  e.g. "2.7"), `modified`.
- Descriptions are markdown with `(Citation: …)` markers (T1059 has 3).
  **min 207 / median 1,298 / p90 2,243 / max 4,680 chars — none empty.**
  → chunking: a handful of chunks at worst; the S6 chunker handles it,
  no overlap work needed (IDEAS.md overlap note stays parked).

### Revocation semantics

157 `revoked-by` relationships, e.g.
`T1143 "Hidden Window" → revoked by → T1564.003 "Hidden Window"`.
A revoked id stays queryable in ATT&CK's own navigator via its successor —
v1 ingestion just drops revoked/deprecated (and deletes previously-held ids
via the S8 `delete_docs` path if we ever ingested them).

### x-mitre-tactic (15)

`name` ("Credential Access"), `x_mitre_shortname` ("credential-access" —
joins `kill_chain_phases`), `external_id` ("TA0006"), description ~420 chars.
Worth ingesting as 15 small `doc_type=tactic` docs (definition surface
already filters `("concept","technique")` — decide whether to add "tactic"
to that tuple when we ingest them).

## What our code must therefore do

1. **Cursor = index poll:** feed row `attack-enterprise`; cursor
   `{version, modified, etag}` from index.json. Fetch the 53 MB bundle ONLY
   when the index's latest enterprise version ≠ cursor version. Poll rides
   the hourly scheduler cycle; bundle download ~2×/year.
2. **Filter:** `type == "attack-pattern"`, drop `revoked` OR
   `x_mitre_deprecated` → 697 docs today.
3. **Doc mapping:** `doc_id = external_id` (T1059…), `ids=(external_id,)`
   (parent prefix rail already pulls sub-techniques), `title = "{id}: {name}"`,
   `doc_type = "technique"`, content = description + tactic/platform lines,
   `source = "mitre-attack-stix"` with **version 19.1 in source_ref or
   content trailer** (honest provenance — these are excerpts of ATT&CK, not
   our summaries), scrub `(Citation: …)` markers.
4. **Replace the 6 hand seeds:** the `attack-seed-summary` technique docs
   must stop shipping once real docs land (seed fingerprint machinery
   handles the swap).
5. **Tactics:** 15 `x-mitre-tactic` docs are nearly free; ingest as
   `doc_type = "tactic"` and extend the definition filter deliberately.

## Reality vs assumption — mismatches caught

- Assumed "~40 MB" bundle; reality **53 MB** (9 MB wire) — big enough that
  per-cycle refetch would be rude; the index-as-cursor design is mandatory,
  not an optimization.
- Assumed revoked techniques might reuse ids; reality: **no live∩dead id
  collisions**, and revocation is a first-class `revoked-by` edge.
- Assumed descriptions might need overlap-aware chunking; reality: max
  4,680 chars — ordinary chunking is fine.
- raw.githubusercontent honors If-None-Match properly (KEV taught us not to
  assume that).
