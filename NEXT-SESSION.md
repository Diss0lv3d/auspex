# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: S10 is COMPLETE, live-verified, CI-green (478 tests) on
`staging` — but NOT yet reviewed or promoted. S11 starts with the review+promote
drill (#12), then the phishing/header agent. The S10 demo: a rich CEF
`CEF:0|Trellix|ENS|10.7|1201|Malware detected|9|src=10.1.2.3 cs1=powershell -enc
SQBFAFgA externalId=T1059.001 confidence=90` → ALERT_TRIAGE Risk **CRITICAL (90)**
with itemized contributions; the signal-poor CEF
`CEF:0|Vendor|Product|1.0|100|generic activity observed|0|` → Risk **DEFERRED**
(score nulled). Both scored in CODE (no LLM on the parse/score) and rendered by
Scout with the code Risk level through the alert_triage contract. The DEFERRED
rail fires on both SARA conditions; the alert path now mitigates TD-013 — the
model scores the code verdict, not the raw paste.)_

---

SESSION S11 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S11` first (full ritual). Primary dev LLM is **Llama-4-Scout
via Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline
endpoint (D-013) and is what the session-start local-Ollama gate validates.
Any mismatch → STOP and tell me. (D-011: `gh` flips to the work account between
AND mid-session — re-check before every `gh` call; at S10 start it was on the
personal account, but re-check anyway.)

Step 0 (carried follow-up, do BEFORE new scope):
- **Adversarial review of S10's feature work** — scope: the commits that landed
  AFTER promote #11 (5f00f25) — `40af4b9..HEAD` on `staging`. Files:
  `auspex/alerts/` (envelope.py the closed-vocab types, normalizer.py the
  CEF/LEEF/syslog/JSON parsers + severity/signal/MITRE detection, scorer.py the
  additive score + both DEFERRED conditions, render.py the authoritative
  directive), `auspex/routes/chat.py` (the ALERT_TRIAGE wiring + drift/triage
  logs), and the tests (test_alerts.py, the S10 additions to test_chat_sse.py).
  Same 5-lens drill (correctness, honesty/copy, security, test-hygiene, ops;
  verify findings BY EXECUTION against code before fixing). Push hard on:
  (correctness) CEF/LEEF escaping + delimiter edge cases, syslog PRI math,
  JSON flatten/leaf-match collisions, severity scale ambiguity (0-10 vs /100),
  the INFORMATIONAL-only → DEFERRED refinement; (security) malformed/adversarial
  pastes that crash or mis-parse, and whether a crafted alert can move the
  code-computed Risk level (the TD-013 alert-path mitigation must hold);
  (honesty) the pending-enrichment tail firing on every non-LOW score (is that
  copy honest given no enrichment is wired?), the DEFERRED reason strings.
  Fix what's real with regression tests, then **`/promote`** (#12). Only then
  start S11 scope.

Goal (scope-locked, from ROADMAP.md S11 — Phishing/header agent):

1. **Deterministic email-header analysis (code-owned, ADR 0006).** Parse a
   pasted email (the resolver already routes ≥2 RFC-5322 headers → DEEP →
   PHISHING_ANALYSIS). Extract + evaluate in CODE: SPF / DKIM / DMARC
   authentication results (from Authentication-Results / Received-SPF headers),
   sender/reply-path/return-path mismatch, display-name vs From-address spoof.
   No LLM on the parse (mirror S10's normalizer pattern).
2. **Typosquat / homograph / lookalike detection.** Deterministic checks on the
   sender domain: known-brand typosquatting (levenshtein/keyboard-distance to a
   brand list), IDN homograph (mixed-script / punycode), lookalike TLD swaps.
   Emit named findings with a confidence, not an opaque flag.
3. **AUTHORITATIVE injection into phishing_analysis (same pattern as S10).** The
   deterministic verdict (auth pass/fail, spoof indicators, typosquat findings)
   is compiled into the system directive; the model renders the phishing_analysis
   contract sections (Verdict enum / Indicators / Recommendation) around the CODE
   findings — it does NOT invent the Verdict. This CLOSES the still-open phishing
   portion of TD-013 (a pasted email body stops being free attacker prose the
   model reasons over unguarded — the code findings drive the Verdict).
4. **Victim-domain IOC filtering.** The recipient/victim's own domain + internal
   infrastructure must not be surfaced as malicious IOCs (a phishing email names
   the victim; don't flag them). Filter before the Indicators section.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic — parser tests use
  fixture emails (real headers: passing SPF/DKIM, failing, spoofed display name,
  IDN homograph), no live LLM in pytest.
- LLM-path changes (the phishing_analysis wiring) MUST be live-verified against
  the real dev endpoint (Scout via Northflank) before session end — but most of
  S11 is deterministic header/domain analysis (zero-LLM). Probe file for the
  live verification.
- No new LLM calls on the parse path. Errors/absence bias to DEFERRED/SUSPICIOUS,
  never a confident BENIGN (the phishing_analysis contract already has the
  DEFERRED rule: "an un-analyzable message is not a safe one").
- Reuse where it fits: the S10 `render.py` authoritative-directive pattern, the
  observable extractor, the `_is_email_paste` detection. Don't re-invent the
  alert normalizer — phishing is its own shape.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth (a brand list
  for typosquat may want to be configurable — decide, and if a file/const, no
  env var needed).
- TD-005 standing trigger: any NEW doc_type or model change → re-run the
  calibration battery. S11 adds no doc_type (emails aren't KB docs) — trigger not
  expected.
- Thrash brake: two failed approaches on one problem → STATE.md Blockers,
  move on. Tired human = short session; rituals anyway.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): the
  ioc_check→KB-CVE-context stretch (parked 5×, IDEAS.md sketch — this is what
  would set `has_enrichment=True` on the S10 score path); TD-012 (post-hoc
  contract validation, no re-ask loop); TD-014 (unbounded history fetch).
- End with `/session-end`; S11 done = a pasted email parses to deterministic
  auth/spoof/typosquat findings (code-owned, no LLM), the findings feed
  phishing_analysis as AUTHORITATIVE, the Verdict is code-decided (spoofed/failed
  auth → not BENIGN), victim-domain IOCs are filtered, pinned by fixture tests,
  and one email analyzed end-to-end live-verified through the contract against
  Scout.
