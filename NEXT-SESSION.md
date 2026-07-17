# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: S6 is complete, live-verified, CI-green (320 tests) on
`staging` — but NOT yet reviewed or promoted. S7 starts with the review+promote
drill, then the ingestion work. The S6 KB demo: `CVE-2021-44228` → "CRITICAL
(CVSS 10.0) … Source: NVD", `what is lateral movement` → seed-corpus answer,
`what is quantum entanglement` → honest miss — all zero LLM.)_

---

SESSION S7 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S7` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch
→ STOP and tell me.

Step 0 (carried follow-up, do BEFORE new scope):
- **Adversarial review of S6** (`auspex/kb/` + chat wiring + Dockerfile
  change) — same multi-lens drill as S5's review (correctness, honesty/copy,
  security, test-hygiene, ops lenses; verify findings before fixing). Fix
  what's real with regression tests, then **`/promote`** (promote #7 = S6
  milestone). Only then start S7 scope.

Goal (scope-locked, from ROADMAP.md S7 — Ingestion 1):

1. **Probes first** (`/probe` → docs/probes/): NVD CVE API 2.0 *delta*
   querying (lastModStartDate/lastModEndDate windows, pagination,
   resultsPerPage caps, rate limits keyless vs keyed) — the single-CVE shape
   is already probed (2026-07-17-nvd-api.md); CISA KEV JSON feed (shape,
   size, update cadence, caching headers); FIRST EPSS API (shape, batch
   query, daily scoring). Save real trimmed responses; fixtures come from
   these probes.
2. **One enriched doc per CVE:** merge NVD (description, CVSS) + KEV
   (known-exploited flag, dates, ransomware use) + EPSS (score, percentile)
   into a single `auspex-knowledge` doc per CVE — extend `KBDoc`/mapping
   only if measured need (KEV/EPSS fields); `nvd_to_doc()`
   (auspex/kb/seed.py) is the parser to extend, `ingest_docs()` the writer
   (upsert by chunk_id makes re-ingest idempotent). KEV/EPSS presence must
   upgrade the cve_lookup echo (e.g. "known exploited — KEV since …; EPSS
   0.97") — code renders, zero LLM, honesty rails intact.
3. **`ingest_state` table + startup catch-up scheduler:** Postgres table
   (feed name, cursor/last-modified watermark, last run, doc counts);
   startup task catches up missed windows (host reboots between sessions —
   the scheduler must tolerate multi-day gaps); SKIP LOCKED job pattern from
   S1 if a jobs table is the right shape. NO live feed calls in pytest —
   fixtures from probes; the scheduler gets a hermetic seam like
   app.state.kb/enrichment.
4. **Retro-hunt hooks stay OUT (S14)** — but new-KEV-entry events will be the
   retro-hunt trigger later; leave a clean extension point (e.g. ingest
   emits per-doc change events to a no-op sink), don't build consumers.
5. Stretch (only if 1–3 land clean): wire the S5 ioc_check echo to cite KB
   CVE context for InternetDB `vulns[]` hits (parked in IDEAS.md with the
   wiring sketch).

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic — no live feeds
  in pytest, fixtures from probe snapshots only.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth (NVD API
  key is optional-but-recommended — probe both).
- No new LLM calls on shortcut paths. Errors bias deep (S4 rule).
- TD-005 note: if ingestion meaningfully grows the corpus, spot-check the
  0.6 neural floor against a few known-good/known-bad definition queries;
  full recalibration can wait for S8.
- Thrash brake: two failed approaches on one problem → STATE.md Blockers,
  move on. Tired human = short session; rituals anyway.
- End with `/session-end`; S7 done = a fresh CVE (post-seed) answerable via
  cve_lookup with KEV/EPSS context, catch-up proven across a simulated gap.
