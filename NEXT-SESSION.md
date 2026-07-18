# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: S9 is COMPLETE, live-verified, CI-green (447 tests) on
`staging` — but NOT yet reviewed or promoted. S10 starts with the review+promote
drill (#11), then the alert-normalizer work. The S9 demo: `give me a brief on
the Log4Shell vulnerability` → BRIEF mode with `## Bottom line/Details/Watch
items`, done frame `{mode:brief, contract_valid:true}`; a signal-poor CEF paste
`CEF:0|Vendor|Product|1.0|100|generic activity observed|0|` → ALERT_TRIAGE with
Risk **DEFERRED** (not LOW). Both live through their typed contracts against
Scout. TD-009 is closed — deep-turn history fences feed-derived assistant text
as `⟦DATA⟧` blocks, regression-tested with an instruction-bearing payload.)_

---

SESSION S10 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S10` first (full ritual). Primary dev LLM is **Llama-4-Scout
via Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline
endpoint (D-013) and is what the session-start local-Ollama gate validates.
Any mismatch → STOP and tell me. (D-011: `gh` flips to the work account
between AND mid-session — re-check before every `gh` call; at S9 start it was
already on the personal account, but re-check anyway.)

Step 0 (carried follow-up, do BEFORE new scope):
- **Adversarial review of S9's feature work** — scope: the commits that landed
  AFTER promote #10 (306b9c7) — `cae88e9..HEAD` on `staging`. Files:
  `auspex/modes/` (contract.py compile+validate, catalog.py the 6 contracts +
  the alert_triage DEFERRED rail, resolver.py format-beats-keywords priority),
  `auspex/routes/chat.py` (mode resolution + directive append, post-hoc
  contract validation + done-frame `{mode,contract_valid}`, the TD-009
  `_history` fence + `_fence_assistant` marker-neutralization), and the tests
  (test_modes.py, the S9 additions to test_chat_sse.py). Same 5-lens drill
  (correctness, honesty/copy, security, test-hygiene, ops; verify findings
  against code before fixing). Security lens should hammer the TD-009 fence
  specifically — fence break-out, marker smuggling, unicode look-alikes of the
  fence chars, whether a USER turn can carry feed text that bypasses the fence.
  Fix what's real with regression tests, then **`/promote`** (#11). Only then
  start S10 scope.

Goal (scope-locked, from ROADMAP.md S10 — Alert normalizer + risk score):

1. **Multi-SIEM format detection → closed-vocab envelope.** Detect CEF / LEEF /
   syslog / JSON alert shapes (the classifier already routes these to DEEP →
   ALERT_TRIAGE; now PARSE them into a typed, closed-vocabulary envelope:
   severity, source/dest, signals, IOCs, MITRE ids, timestamps). Code-owned
   parsing (ADR 0006), no LLM on the parse. This envelope is the structured
   input the S9 `alert_triage` mode scores.
2. **Additive 0–100 risk score with itemized contributions.** Port the SARA
   pattern (each signal adds points with a named `contribution`, not an opaque
   number) — see the DEFERRED-rail snapshot
   (docs/probes/2026-07-18-sara-orchestrator-deferred.md) and, if it still
   exists, the live SARA source at
   `/home/burhan/sara-open/sara/agents/alert_triage.py` (re-snapshot to
   docs/probes/ if you rely on it — it may be cleaned).
3. **DEFERRED rail from day one (both SARA conditions):** (a) signal-poor
   envelope (no severity, no enrichment, no IOCs, no MITRE) → Risk DEFERRED,
   score nulled, `needs_deep_triage` flag; (b) severity-known but all evidence
   is post-enrichment (IOCs present, un-enriched) → DEFERRED naming the
   specific reason. "No data ≠ low risk" is CODE, not a prompt instruction —
   the S9 contract enum already includes DEFERRED; S10 makes the SCORER emit it.
4. Wire the normalizer+scorer as the structured feed into `alert_triage` mode
   (the S9 contract validates the shape; S10 fills it deterministically).

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic — parser/scorer
  tests use fixture alerts (real CEF/LEEF/syslog samples), no live LLM in
  pytest.
- LLM-path changes MUST be live-verified against the real dev endpoint (Scout
  via Northflank) before session end — but most of S10 is deterministic
  parse/score (zero-LLM). Probe file for anything new.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
- No new LLM calls on the parse/score path. Errors bias to DEFERRED, never a
  confident LOW (the SARA rail's whole point).
- TD-005 standing trigger: any NEW doc_type or model change → re-run the
  calibration battery (docs/probes/2026-07-18-td005-calibration.md pattern).
  S10 adds no doc_type (alerts aren't KB docs) — trigger not expected.
- Thrash brake: two failed approaches on one problem → STATE.md Blockers,
  move on. Tired human = short session; rituals anyway.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): the
  ioc_check→KB-CVE-context stretch (parked 4×, IDEAS.md sketch); TD-012
  (contract validation is post-hoc — a re-ask/repair loop for
  structured-critical modes); stored ATT&CK markdown self-heals on the next
  re-ingest.
- End with `/session-end`; S10 done = a CEF/LEEF/syslog/JSON alert parses to
  the typed envelope, the additive scorer emits an itemized 0–100 score, the
  DEFERRED rail fires (both conditions) on signal-poor input pinned by tests,
  and the scorer feeds `alert_triage` mode (one alert scored end-to-end,
  live-verified through the contract against Scout).
