# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: S8 is complete, live-verified, CI-green (412 tests) on
`staging` — but NOT yet reviewed or promoted. S9 starts with the
review+promote drill (#9), then the response-modes work. The S8 demo:
`what is T1059` → real STIX-derived ATT&CK content with "Source: MITRE
ATT&CK (STIX-derived) · … (ATT&CK v19.1)"; `what is T1055.011` answers
though it was never hand-seeded; `what is quantum entanglement` misses
honestly again — the TD-005 battery caught live fabrication the same day
ATT&CK landed, and the per-doc_type floors (curated 0.65 / cve 0.70) are
regression-pinned.)_

---

SESSION S9 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S9` first (full ritual). Primary dev LLM is **Llama-4-Scout
via Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline
endpoint (D-013) and is what the session-start local-Ollama gate validates.
Any mismatch → STOP and tell me. (D-011: `gh` flips to the work account
between AND mid-session — re-check before every `gh` call.)

Step 0 (carried follow-up, do BEFORE new scope):
- **Adversarial review of S8's feature work** — scope: `auspex/ingest/attack.py`
  (index-as-cursor, URL pinning, bundle_to_docs filtering/provenance),
  scheduler attack phase + failure isolation, per-doc_type NEURAL_FLOORS
  (fuse.py) + the battery-pinned tests, kev_listed field plumbing
  (types/mapping/enrich/service/echo), seed technique removal, echo
  related-entries + source-label changes, definition filter growing to
  ("concept","technique","tactic"). The 13 S7-review fix commits are ALREADY
  promoted and reviewed — the review scope is what landed AFTER promote #8
  (da42735..HEAD). Same multi-lens drill (correctness, honesty/copy,
  security, test-hygiene, ops; verify findings against code before fixing).
  Fix what's real with regression tests, then **`/promote`** (#9). Only then
  start S9 scope.

Goal (scope-locked, from ROADMAP.md S9 — Response modes):

1. **6 modes only:** definition, ioc_enrichment, threat_intel, alert_triage,
   phishing_analysis, brief. Code-owned priority resolver — format beats
   keywords (ADR 0006 spirit: code over prompts for routing).
2. **Typed output contracts** (ADR 0007 spirit: specs over prompts):
   contracts compile to prompts + validators — not the other way around.
   The existing shortcut paths (cve_lookup, definition, ioc_check) stay
   zero-LLM; modes shape the DEEP path's system prompt + output validation.
3. **TD-009 rides along (from the S8 review):** feed/KB-derived text
   replayed into deep-turn history must be fenced as data-not-instructions
   (SARA instructions-in-system/data-in-user pattern,
   docs/probes/2026-07-16-sara-fastpath-pattern.md + agent_loop reference).
   Add the regression test with an instruction-bearing description.
4. Reference intelligence before coding: re-snapshot the SARA orchestrator
   worktree path if needed (STATE.md notes it gets cleaned), and re-read
   the DEFERRED rail (alert_triage.py:1429) — alert_triage mode must ship
   with "no data ≠ low risk" semantics from day one.
5. Stretch (parked three times — S5/S7/S8): ioc_check echo cites KB CVE
   context for InternetDB `vulns[]` hits (IDEAS.md has the sketch).

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic — mode/contract
  tests use fixtures, no live LLM in pytest.
- LLM-path changes MUST be live-verified against the real dev endpoint
  (Scout via Northflank) before session end — probe file for anything new.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
- No new LLM calls on shortcut paths. Errors bias deep (S4 rule).
- TD-005 standing trigger: any NEW doc_type (Sigma etc. stay parked in
  IDEAS) or model change → re-run the calibration battery
  (docs/probes/2026-07-18-td005-calibration.md has the pattern).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers,
  move on. Tired human = short session; rituals anyway.
- End with `/session-end`; S9 done = the 6 modes resolve by code (format
  beats keywords, pinned by tests), at least one mode (definition or brief)
  runs end-to-end live through a typed contract that validated real Scout
  output, and deep-turn history fences feed-derived text (TD-009 closed
  with a regression test).
