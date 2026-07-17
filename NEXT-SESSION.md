# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: S7 is complete, live-verified, CI-green (357 tests) on
`staging` — but NOT yet reviewed or promoted. S8 starts with the review+promote
drill, then the ingestion-2 work. The S7 demo: `CVE-2026-58644` → "CRITICAL
(CVSS 9.8) … Known exploited — in CISA KEV since 2026-07-16. EPSS 0.01 —
70.7th percentile (as of 2026-07-17)". Gap catch-up: rewind
`ingest_state.nvd-delta.cursor.last_mod_end`, restart app, watch the cycle.)_

---

SESSION S8 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S8` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch
→ STOP and tell me. (D-011 note: `gh` flipped back to the work account
MID-session in S7 — re-check the active account before every `gh` call.)

Step 0 (carried follow-up, do BEFORE new scope):
- **Adversarial review of S7** — scope: the whole `auspex/ingest/` package
  (feeds, scheduler, state, events), kb changes (`_ensure_mapping_fields`,
  seed fingerprint, `list_cve_ids`, `doc_types` filter, `KBUnavailable.public`),
  chat/echo changes (CVE cap + omitted copy, KEV/EPSS lines), app lifespan
  rewiring (background task owns bootstrap), `ingest_state` migration. Same
  multi-lens drill as S5/S6 (correctness, honesty/copy, security,
  test-hygiene, ops; verify findings against the code before fixing — S7's
  review verified inline when subagents died; either mode is fine). Fix
  what's real with regression tests, then **`/promote`** (promote #8 = S7
  milestone). Only then start S8 scope.

Goal (scope-locked, from ROADMAP.md S8 — Ingestion 2):

1. **TD-005 calibration GATE (do this FIRST if S8 adds ANY unfiltered
   free-text search surface):** the S7 spot-check proved both failure modes
   live at ~2.5k chunks (docs/probes/2026-07-17-s7-ingest-live.md): lucene
   HNSW recall collapses at k=10 unfiltered, and the 0.6 absolute neural
   floor erodes as max-of-N cosine grows. Build a labeled relevant/irrelevant
   query fixture set from live probes; calibrate per-doc_type floors AND
   neural k/ef sizing TOGETHER; regression-pin the operating point. The
   definition path is already structurally safe (doc_types filter → exact
   kNN) — do not regress that.
2. **Probes first (`/probe` → docs/probes/):** MITRE ATT&CK STIX bundle
   (size, shape, technique/sub-technique/tactic objects, revoked/deprecated
   handling, update cadence — replaces the hand-curated attack-seed-summary
   docs honestly); Sigma rules repo (shape, count, license, useful fields);
   abuse.ch quartet feeds you don't already have probed (URLhaus/ThreatFox
   are S5-probed for enrichment — the KB ingestion angle may differ).
3. **ATT&CK ingestion (lazy + cached):** replace the 6 hand-curated technique
   seeds with real STIX-derived docs (doc_type=technique, source honestly
   labeled as derived-from-STIX with version); keep the ID rail + parent
   prefix behavior (T1059 pulls T1059.001) — the probe decides chunking for
   long technique pages (chunking.py's overlap note in IDEAS.md may activate).
   Feed goes through the S7 scheduler + ingest_state (new feed row, own
   cursor shape).
4. **Sigma + abuse.ch into the KB** only as far as the probes justify — one
   enriched doc type at a time, tests with each; auto-promotion-on-miss
   (queries that miss the KB get queued for curation) only if time allows,
   else park in IDEAS.md.
5. Stretch (parked twice — S5, S7): wire the ioc_check echo to cite KB CVE
   context for InternetDB `vulns[]` hits (IDEAS.md has the sketch).

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic — no live feeds
  in pytest, fixtures from probe snapshots only.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
- No new LLM calls on shortcut paths. Errors bias deep (S4 rule).
- The corpus now grows hourly while the container runs (~770 docs/day) —
  any retrieval change must be spot-checked against the LIVE grown corpus,
  not just the 14-chunk fixture world (S7's lesson).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers,
  move on. Tired human = short session; rituals anyway.
- End with `/session-end`; S8 done = real ATT&CK technique docs answering
  `what is T1059` (and a sub-technique via prefix) from STIX-derived content
  with honest provenance, through the S7 scheduler with its own watermark,
  and the TD-005 operating point regression-pinned.
