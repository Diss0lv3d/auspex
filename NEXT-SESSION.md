# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: S13 is COMPLETE and PROMOTED — Step-0 review fixed 7
executed findings; citable evidence + the cited summary path shipped and were
live-verified against Scout (run 1 caught 2 real defects, run 2 clean: 19
valid citations, 0 fabricated, 0 uncited); CI-green 597 tests. Promote #14
was merged by Burhan (squash 87eb279 — the classifier blocks `gh pr merge`
for Claude) and back-merged same session (9b61656); main == staging. The S13
demo: POST the typosquat email to `/api/investigations`, then POST
`/{id}/summary` → a Scout-rendered summary where every claim line cites
[E-…] ids that resolve to real ach_evidence rows, with the leading hypothesis
pinned by code and `contract_valid` + `citations.ok` reporting the code's
post-hoc verdict.)_

---

SESSION S14 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S14` first (full ritual). Primary dev LLM is **Llama-4-Scout
via Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline
endpoint (D-013) and is what the session-start local-Ollama gate validates.
Any mismatch → STOP and tell me. (D-011: `gh` flips to the work account
between AND mid-session — re-check before every `gh` call. It did NOT flip
at S13 start, the first clean session; assume it flips anyway.)

Step 0 (carried follow-up, do BEFORE new scope — promote #14 is already
merged AND back-merged, nothing to reconcile):
- **Fresh-eyes review of the S13 feature commits** — scope: `3dd9b7c`
  (evidence_id substrate), `62d332f` (render.py + summary route + guard),
  `376dc13` (live-caught fixes): ~900 insertions. This code was
  live-verified but got NO independent adversarial pass. Angles the build
  didn't test: (injection) can 160 flattened chars of hostile evidence
  statement steer the summary's citations or narrative? Can a crafted
  statement fake a citation label ("E-deadbeef looks real")? (guard limits)
  the line-based uncited check vs multi-line prose claims — how does it
  degrade? (pin edges) what does Scout render when NONE is pinned (empty
  investigation)? (cost) `/summary` spends customer inference with no
  per-workspace bound — chat shares this exposure; decide TD or fix.
  Verify findings BY EXECUTION before fixing; fix with regressions. Then
  consider `/promote` #15 if warranted (or fold into the S14 promote).

Goal (scope-locked, from ROADMAP.md S14 — Retro-hunt, Phase 3 flagship):

1. **On-ingest sweep of historical observables.** When new intel lands
   (NVD/KEV/EPSS/ATT&CK docs via the S7 ingest), sweep the workspace's
   HISTORICAL observables for matches — **indexed join, never scan** (the
   ROADMAP constraint). The hook already exists: `auspex/ingest/events.py`
   emits one `DocChange` per upserted doc into a `NullSink` "so S14 can
   attach a retro-hunt sink without touching ingest" — start by reading
   that file and the S5 `observables`/`verdicts` tables (D-017 decay
   fields were designed for this moment).
2. **Re-open notifications.** A retro-hunt match on an observable with a
   settled verdict emits an event the analyst can see (surface: probably a
   table + a rendered line in ioc_check/chat; decide minimal-typed, the
   proposals-table precedent). Honesty rails: a match is a REASON TO
   RE-EXAMINE, never an auto-flip.
3. **Verdict flip events.** When re-enrichment after a retro-hunt match
   changes a verdict label, record a typed flip event (old → new, why,
   which doc triggered) — the D-017 trail grows its first automated writer.
   ACH investigations whose evidence cites a flipped verdict are the
   S15 seam — note it, do not build it.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic — retro-hunt
  logic pinned by fixtures, zero LLM anywhere on this path (it is
  ingest/join/event code; model rendering of flip notifications, if any,
  goes through a contract and is NOT required for S14 done).
- The sweep MUST be an indexed join on the observables table (workspace-
  scoped), never a full scan per DocChange — probe the query plan
  (EXPLAIN) and save it to docs/probes/ before calling it done.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 7× now); TD-012 (post-hoc
  validation, no re-ask); TD-014 (unbounded history); TD-015
  (brand/confusable coverage); TD-016 (ACH surface bounds); TD-017
  (chat-side NUL hardening — verify by execution first if picked up);
  model-PROPOSED hypotheses/evidence (D-019-later).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers,
  move on. Tired human = short session; rituals anyway.
- End with `/session-end`; S14 done = a DocChange sweep matches historical
  observables through an indexed join (EXPLAIN-probed), re-open events
  exist as typed rows with an honest analyst surface, verdict flips are
  recorded with provenance, all pinned by hermetic fixtures, live-verified
  in-container against the real ingest path.
