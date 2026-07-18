# STATE — Auspex

_Last updated: 2026-07-18 (S9 — S8 adversarial review DONE, 8 fix commits +
tests; ready for promote #10, then S9 modes scope)_

## Where we are
- **S8 review COMPLETE (the outstanding Step 0).** promote #9 had shipped the
  S8 feature work to `main` UNREVIEWED (an unrecorded 08:41–09:31 session merged
  it + KB strategy docs). This session ran the 5-lens adversarial review over
  the S8 diff (da42735..144b247) and fixed what was real — **8 fix/test commits
  on staging**, all with regression tests, CI-green (426 tests, was 412).
  → **promote #10** carries them, THEN S9 scope (Response modes, NEXT-SESSION).
- **S8 review findings fixed** (verified against code + live before fixing):
  1. **Phase isolation (major, correctness):** NVD/KEV phases ran unwrapped
     before the only guarded phase (ATT&CK, last) — a bad NVD key starved ALL
     technique content (seeds were removed in S8). CVE pipeline now isolated
     from the independent ATT&CK phase.
  2. **Bundle parse resilience (major):** one malformed object crashed the
     whole parse; now skip-and-count like NVD.
  3. **extras bypassed the content cap (major, security):** poisoned platforms
     fanned out ~100k chunks; assembled content now capped. + name/version
     bound & control-stripped (trailer-forgery), re.ASCII ids.
  4. **Version-bump retirement (major, 2 lenses):** withdrawn techniques were
     served forever; retire_absent(source, keep) runs before the cursor. +
     modified compare (in-place re-release), + doc-count shrink floor.
  5. **MITRE ToU notice (major, honesty):** verbatim ATT&CK text shipped
     without the required copyright notice; now on every STIX-derived answer.
  6. **Markdown/HTML in descriptions (honesty):** normalized out at ingest.
  7. **Floor pinning (critical, test-hygiene):** NEURAL_FLOORS now pinned
     verbatim + a per-doc_type coverage test (a new feed trips it).
  8. Docs: ATT&CK egress in INGEST_ENABLED; TD-010 scope grew to attack.py
     (unbounded body — deferred, shared bounded_json helper); fixture trimmed
     103,694→330 lines.
- **Live-verified this session:** MITRE ToU notice renders on "what is T1059"
  end-to-end; retire_absent bool query valid against real OpenSearch (1398
  ATT&CK chunks, keep-set math correct). NOTE: stored ATT&CK content still has
  markdown (ingest-time fix) — self-heals on the next version bump / re-ingest.
- **Promoted:** promote #9 on `main` == everything through 144b247 (S8 feature
  work + KB strategy). promote #10 (pending) adds the 8 review fixes.
- **No LLM paths touched** — every fix is ingest/KB/echo (zero-LLM); TD-005
  battery NOT re-triggered (no new doc_type, no model change).
- **Primary dev LLM (D-015):** Llama-4-Scout via Northflank; secondary/offline
  Ollama `qwen3:14b` (D-013). S8 touched no LLM paths (everything shipped is
  shortcut/ingest — zero LLM).
- **CI-green: 412 tests** (was 357 at S7 end). `./ci.sh` green end-to-end at
  session close; `/api/health/ready` 200.

## S8 shipped (all committed on staging, 2026-07-18)
- **Step 0 first — adversarial review of S7** (5 parallel lenses:
  correctness, honesty/copy, security, test-hygiene, ops; 18 verified
  findings, nothing refuted; every finding verified against code before
  fixing). 13 fix commits, highlights:
  - KEV cursor DATA LOSS (2 lenses independently): cap + strict `>` horizon
    permanently dropped same-date entries; now horizon = newest FULLY-covered
    date + done_ids, 304 cycles scan the cached catalog, freshness persists,
    kb_refreshed only when the refresh ran.
  - Ingest brick: one failed boot bootstrap left embed() dead forever (and
    _bulk could auto-create a poisoned dynamic index); cycles now gate on
    `kb.bootstrapped`, embed() lazy-resolves like the neural leg.
  - NVD page-streaming (120-day window ≈ 92k dicts was one in-memory
    all-or-nothing) + hard page ceiling + refresh-once-per-ingest + keyless
    6.5 s spacing (5/30s quota) + 403/429→NVDError.
  - Feed poisoning: NaN/Infinity EPSS wedged the watermark forever →
    isfinite + allow_nan=False + CVE-id shape rail + 20k description cap.
  - Honesty: rejected CVEs now DELETE held chunks ("deleted" DocChange);
    re-ingest prunes orphaned chunks; EPSS copy never crosses boundaries it
    doesn't hold (<0.01 / >0.99 / >99.9th); kev_listed presence field;
    lookup_ids re-queries truncated ids (BM25-idf false miss); definition
    miss copy says "no curated definition", not KB-wide absence.
  - First-run KEV refresh = ONE update_by_query (was ≤1,647 paced NVD
    singles, uncapped, all-or-nothing).
  - Deferred with paths: TD-009 (prompt-injection fence → S9 modes work),
    TD-010 (feed byte ceilings), TD-011 (index rollover trigger).
  - Then **promote #8** (PR #8, checks green, squash + back-merge verified).
- **ATT&CK STIX feed** (probe: docs/probes/2026-07-18-attack-stix.md):
  31 KB version index is the cursor (`attack-enterprise` row,
  {version, modified}); 53 MB bundle only on version change (~2×/yr).
  bundle_to_docs filters revoked(149)/deprecated(12), shape-validates ids,
  scrubs (Citation:…), honest provenance "MITRE ATT&CK (STIX-derived) ·
  …attack.mitre.org… (ATT&CK v19.1)". 712 docs (697 techniques + 15
  tactics) INGESTED LIVE in ~26 s → 1,398 chunks. Hand-curated technique
  seeds REMOVED (same doc_ids → STIX overwrites; concepts stay). Definition
  filter grew to (concept, technique, tactic). Live-verified: "what is
  T1059" (real STIX text + sub-technique Related entries via prefix rail),
  "what is T1055.011" (never hand-seeded), "what is credential access"
  (TA0006). Bundle URLs pinned to the mitre-attack repo prefix; phase
  failures isolated from CVE phases.
- **TD-005 RESOLVED** (probe: docs/probes/2026-07-18-td005-calibration.md):
  14-query labeled battery on the live 3,417-chunk corpus. It re-caught the
  fabrication LIVE: ATT&CK's 1,398 curated chunks pushed filtered noise
  over the flat 0.6 floor — "what is quantum entanglement" answered
  T1090.002 (0.617) until the fix, same day. Per-doc_type floors from
  measured separation: curated 0.65 (noise 0.618 / weakest relevant 0.691),
  cve 0.70 (0.624 / 0.766), default 0.6. Regression-pinned: every boundary
  row is a parametrized test naming the live query that breaks. Battery
  also caught a labeling trap — "kubernetes ingress controller
  configuration" was a planned hard negative but the corpus HELD
  CVE-2026-55723 (real ingress CVE, 0.793): the corpus decides relevance.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Run the S8 adversarial review (STILL outstanding), then `/promote`
   (#10)** — promote #9 shipped the S8 feature work to `main` unreviewed
   (attack.py, scheduler attack phase, per-doc_type floors, kev_listed,
   seed change, echo label/copy changes). Same multi-lens drill; verify
   findings before fixing; fixes go out via promote #10.
2. **TD-005 re-battery trigger (standing):** corpus > 30k chunks, ANY new
   doc_type, or embedding-model change → re-run the labeled battery
   (script pattern in the probe doc). Sigma/abuse.ch ingestion (parked in
   IDEAS) trips this trigger by definition.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   /api/chat; modes land S9. TD-009 (feed-text prompt-injection fence) is
   scoped INTO the S9 modes work.
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly
   (watermarks hold, catch-up on recovery; ATT&CK/KEV phase failures are
   isolated from NVD).
4. **Corpus ~3.4k chunks, grows ~770 docs/day** while the container runs.
   OpenSearch 1 GiB heap fine; TD-011 tracks the rollover trigger
   (>150k chunks / RSS >70% / p95 >500 ms).

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`
  (ENRICHMENT_ENABLED=false, KB_ENABLED=false, INGEST_ENABLED=false —
  override in shell for host-run live ingest).
- `ingest_state` rows: `nvd-delta` (window-end cursor), `kev` (last_modified
  + date_added_horizon + done_ids + kb_refreshed), **`attack-enterprise`
  ({version: "19.1", modified}) — new in S8**. Gap-catch-up demo: rewind
  `nvd-delta.cursor.last_mod_end`, restart app.
- auspex-knowledge: ~3,417 chunks (seed 8 + live NVD/KEV/EPSS + 1,398
  ATT&CK). Index _meta carries the seed fingerprint; mapping now includes
  kev_listed (+1 additive upgrade, live-verified).
- Ollama 0.24.0 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
- `gh` flips to SIRP-Burhan between sessions AND mid-session (D-011) —
  re-check before EVERY `gh` call. It flipped again at S8 start.
- S8 demo turns: `what is T1059` / `what is T1055.011` / `what is credential
  access` (STIX-derived, zero LLM); `what is quantum entanglement` → honest
  miss; `check CVE-2026-58644` → KEV/EPSS lines (unchanged from S7).

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
Base: `/home/burhan/sara-open/` (paths re-verified 2026-07-15):
- ReACT loop: /home/burhan/sara-open/sara/core/agent_loop.py:60
- Plan→DAG→Judge loop: /home/burhan/sara-open/.claude/worktrees/1359-chain-surface/sara/core/orchestrator_loop/runner.py:39
  (worktrees get cleaned; re-snapshot to docs/probes/ before S9 modes work)
- Permission hard-rails: /home/burhan/sara-open/sara/core/permissions.py:65-176
- Fast classifier / 92-8: docs/probes/2026-07-16-sara-fastpath-pattern.md
- Enrichment/fan-out: probe docs 2026-07-16
- RRF retrieval + ID bypass: docs/probes/2026-07-17-sara-rrf-retriever-pattern.md
- DEFERRED rail: /home/burhan/sara-open/sara/agents/alert_triage.py:1429
- Capability shape: /home/burhan/sara-open/sara/core/unified_registry.py:37

## Next session should
Review S8 (multi-lens, verify before fixing) → `/promote` (#9) → then S9
exactly as written in NEXT-SESSION.md (Response modes: 6 modes, code-owned
priority resolver, typed output contracts; TD-009 fence rides along).
