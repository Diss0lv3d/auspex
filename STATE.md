# STATE — Auspex

_Last updated: 2026-07-17 (S7 complete — Ingestion 1 live-verified; promote #7 shipped S6 to main)_

## Where we are
- **S7 COMPLETE** (steps 1–4 + live verify; stretch skipped deliberately)
  → **next is S8** (Ingestion 2 + the now-mandatory TD-005 calibration — see
  NEXT-SESSION.md). S7 is on `staging`, NOT yet reviewed/promoted — S8 starts
  with the adversarial review, then `/promote` (#8).
- **Promoted:** promote #7 on `main` (e760567) == full S6 milestone + the 10
  S6-review fixes (see below). `main` does NOT have S7.
- **Primary dev LLM (D-015):** Llama-4-Scout via Northflank; secondary/offline
  Ollama `qwen3:14b` (D-013). S7 touched no LLM paths (ingest + shortcuts are
  LLM-free; the one "deep turn" seen live — sourdough — was correct routing).
- **CI-green: 357 tests** (was 320 at S6 end). `./ci.sh` green end-to-end at
  session close; `/api/health/ready` 200.

## S7 shipped (all committed on staging, 2026-07-17)
- **Step 0 first:** adversarial multi-lens review of S6 ran (subagent budget
  died mid-run — 14 findings verified INLINE instead; 10 fixed with regression
  tests, 2 refuted → TD-007/TD-008, 2 test-hygiene). Highlights: never-a-500
  on malformed OpenSearch 200s; per-turn CVE cap (25) + scaled fetch with
  honest "N more requested" copy (false-miss + maxClauseCount DoS); analyst-
  calm `KBUnavailable.public` (no "(breaker open)"/httpx names in copy);
  breaker counts a dead turn once not thrice; seed content FINGERPRINT in
  index `_meta` (count check served stale edits forever); model-lookup memo
  expires (60 s); cluster setting written only when absent; numeric chunk
  order; CONCEPT-* ids never in copy. Then **promote #7** (PR squash-merged,
  staging back-merged, tree-identity verified, ready 200 on main's tree).
- **Probes first (rule 4):** 2026-07-17-nvd-delta.md (768 modified CVEs in ONE
  day; 404-with-empty-body + `message` HEADER for ≥3 unrelated client errors;
  caps 2000/page, 120-day window; Rejected CVEs ride the stream),
  2026-07-17-cisa-kev.md (If-Modified-Since→304 works, **ETag lies across
  encodings**; gzip 1.5 MB→178 KB; ransomware enum Known/Unknown only),
  2026-07-17-first-epss.md (comma-batch keyed by RESPONSE cve, arbitrary
  order; unknown ids silently dropped; scores are 9-decimal STRINGS; daily
  bulk CSV behind a dated 302). Fixtures trimmed verbatim → tests/fixtures/.
- **`auspex/ingest/` package:** NVDFeed (full paging + spacing, NVDError from
  the message header, windows() chunks gaps at 120 d), KEVFeed (conditional
  GET only when the in-memory cache can back a 304 — reboots never go blind),
  EPSSFeed (≤100-id batches), enrich_doc() pure merge (absence stays absent;
  ransomware "Unknown" ⇒ False ⇒ silence), events.NullSink = the S14
  retro-hunt extension point (emit-only: DocChange per doc, "kev-added" kind).
- **KEV/EPSS end-to-end:** KBDoc/KBHit/mapping grew 5 fields;
  `_ensure_mapping_fields` upgrades strict S6-era indexes additively
  (live-verified: "mapping upgraded (+5 fields)"); cve_lookup echo renders
  held evidence only — "Known exploited — in CISA KEV since …; used in
  ransomware campaigns." / "EPSS 1.00 — 100.0th percentile (as of …)".
- **`ingest_state` + scheduler:** Postgres watermarks (jsonb cursor; partial
  unique index on global feeds; workspace_id nullable = D-008-compliant
  global), IngestScheduler as ONE background task that also owns KB bootstrap
  (**TD-008 resolved** — port binds immediately). Watermark advances
  per-window AFTER ingest; KEV first run skips the 1 647-entry backfill and
  re-enriches KB-held docs; new-KEV singles paced + deduped against the
  cycle's NVD coverage. INGEST_ENABLED born; devhost pins it false.
- **Live-verified** (docs/probes/2026-07-17-s7-ingest-live.md): first run
  643 chunks + 3 live Rejected skipped; **simulated 2-day gap** → 1 844
  chunks, 30 rejected skipped, ~2.5 min; fresh post-seed CVE-2026-58644
  answerable with KEV+EPSS context, zero LLM, path=shortcut.
- **TD-005 spot-check CAUGHT 2 SCALE BUGS** (corpus 14→~2 500 chunks): lucene
  HNSW recall collapse at k=10 (the 0.840 best match absent from top-10 — the
  S6 demo query silently missed) and floor erosion (two CVE chunks ≥0.6 for
  "quantum entanglement" — fabrication returned). Fixed the probed way:
  `search(doc_types=…)` filters BOTH legs (lucene kNN goes exact on small
  subsets — restores recall); definition shortcut pins ("concept",
  "technique"). Full matrix re-verified live post-fix.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Run the S7 adversarial review, then `/promote` (#8)** — S7 is demoable
   and CI-green on staging but unreviewed. Scope: `auspex/ingest/` (whole
   package), kb changes (mapping upgrade, fingerprint, list_cve_ids,
   doc_types filter, public copy), chat/echo changes, app lifespan rewiring,
   migrations. Same multi-lens drill; verify findings before fixing.
2. **TD-005 is now S8-BLOCKING for any unfiltered free-text surface:** the
   spot-check confirmed both failure modes live (see probe doc). S8 must
   calibrate per-doc_type floors AND neural k/ef together with a labeled
   query set before shipping search over CVE prose.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat; modes land S9.
3. **KB bootstrap needs outbound HTTPS once per fresh volume** (model
   download ~12 s); ingest additionally needs NVD/CISA/FIRST reachability —
   failures degrade honestly (watermark holds, catch-up on recovery).
4. **Corpus now grows ~770 docs/day while the container runs** (hourly
   cycles). OpenSearch 1 GiB heap fine at current scale; watch RSS/disk as
   it accumulates (~5 k docs/week). Multi-day host gaps catch up on boot by
   design — a many-week gap will chunk into ≤120-day windows and take
   minutes, politely paced.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`
  (…, ENRICHMENT_ENABLED=false, KB_ENABLED=false, **INGEST_ENABLED=false** new
  in S7 — override in shell for host-run live ingest).
- `ingest_state` rows: `nvd-delta` (cursor = last window end) and `kev`
  (Last-Modified + dateAdded horizon 2026-07-16 + kb_refreshed). Rewinding
  `nvd-delta.cursor.last_mod_end` + app restart = the gap-catch-up demo.
- auspex-knowledge: ~2 500 chunks (14 seed + live NVD/KEV/EPSS). Index _meta
  carries the seed fingerprint.
- Ollama 0.24.0 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- `gh` may wake up as SIRP-Burhan — session-start switches to
  bh3082336888-cell (D-011); **it flipped back MID-SESSION this time** (after
  the morning switch) — re-check before any `gh` call, not just at start.

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
Base: `/home/burhan/sara-open/` (paths re-verified 2026-07-15):
- ReACT loop: /home/burhan/sara-open/sara/core/agent_loop.py:60
- Plan→DAG→Judge loop: /home/burhan/sara-open/.claude/worktrees/1359-chain-surface/sara/core/orchestrator_loop/runner.py:39
  (worktrees get cleaned; re-snapshot to docs/probes/ before S8)
- Permission hard-rails: /home/burhan/sara-open/sara/core/permissions.py:65-176
- Fast classifier / 92-8: docs/probes/2026-07-16-sara-fastpath-pattern.md
- Enrichment/fan-out: probe docs 2026-07-16
- RRF retrieval + ID bypass: docs/probes/2026-07-17-sara-rrf-retriever-pattern.md
- DEFERRED rail: /home/burhan/sara-open/sara/agents/alert_triage.py:1429
- Capability shape: /home/burhan/sara-open/sara/core/unified_registry.py:37

## Next session should
Review S7 (multi-lens, verify before fixing) → `/promote` (#8) → then S8
exactly as written in NEXT-SESSION.md (Ingestion 2: ATT&CK + Sigma + abuse.ch;
TD-005 calibration FIRST if any unfiltered search surface is touched).
