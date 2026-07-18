# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: S11 is COMPLETE, live-verified, CI-green (515 tests) on
`staging` — but NOT yet reviewed or promoted. S12 starts with the review+promote
drill (#13), then the hypothesis engine. The S11 demo: a spoofed auth-failing
email `From: "PayPal Support" <security@paypa1.com>`, `Reply-To:
recover@account-verify.ru`, spf/dkim/dmarc=fail, link paypa1.com → PHISHING
Verdict **MALICIOUS** (floor-locked; 3 auth fails + reply-to mismatch +
display-name spoof + paypa1~paypal typosquat, all code-decided); an all-auth-pass
email → **BENIGN** (positive-evidence gate). Both scored in CODE (no LLM on the
parse/verdict) and rendered by Scout through the phishing_analysis contract with
the code Verdict floor. The recipient's own domain is NOT surfaced as an IOC.
S11 closes the phishing portion of TD-013 — the model renders the code verdict,
not the raw paste, and the validator pin blocks any launder below the floor.)_

---

SESSION S12 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S12` first (full ritual). Primary dev LLM is **Llama-4-Scout
via Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline
endpoint (D-013) and is what the session-start local-Ollama gate validates.
Any mismatch → STOP and tell me. (D-011: `gh` flips to the work account between
AND mid-session — re-check before every `gh` call; at S11 start the active
account was already the personal one, but re-check anyway.)

Step 0 (carried follow-up, do BEFORE new scope):
- **Adversarial review of S11's feature work** — scope: the commits that landed
  AFTER promote #12 (136992f) — on `staging`. Files: `auspex/phishing/`
  (envelope.py the closed-vocab types, parser.py the regex header parse +
  auth-token extraction + display-spoof parseaddr fallback + anomaly detection,
  brands.py the allow-list, lookalike.py the TLD-swap/near-miss/homograph/
  subdomain-bait checks + Damerau-Levenshtein, verdict.py the additive score +
  Verdict FLOOR + BENIGN-gate + DEFERRED rails, victims.py the IOC filter,
  render.py the authoritative directive), `auspex/classify/classifier.py` (the
  email→DEEP `_is_email_paste` gate), `auspex/modes/contract.py` (the validator
  set-pin), `auspex/routes/chat.py` (the phishing wiring), `auspex/untrusted.py`
  (the shared flattener), and the tests (test_phishing.py, the S11 additions to
  test_chat_sse.py / test_modes.py / test_classifier.py, the .eml fixtures).
  Same 5-lens drill (correctness, honesty/copy, security, test-hygiene, ops;
  verify findings BY EXECUTION against code before fixing). Push hard on:
  (security) can a crafted email move the code Verdict FLOOR, slip a victim IOC
  past the filter, or crash the parser? does the floor pin actually hold
  end-to-end (a launder below the floor MUST fail the contract)? is the sender
  ever wrongly victim-filtered when it spoofs the victim's own domain?
  (correctness) auth-token placement edge cases (Authentication-Results folding,
  Received-SPF, ARC), the parseaddr display-spoof fallback, punycode decode +
  confusable folding, the naive registrable-domain compound-TLD gap (TD-015),
  near-miss min-length / distance thresholds, brand-subdomain-bait false
  positives; (honesty) the DEFERRED reason strings and the BENIGN-gate copy (is
  BENIGN only reachable on positive auth evidence?), the "withheld victim IOC"
  note. Fix what's real with regression tests, then **`/promote`** (#13). Only
  then start S12 scope.

Goal (scope-locked, from ROADMAP.md S12 — Hypothesis engine v1 / ACH):

**IMPORTANT — this is a DIFFERENT shape from S9–S11.** S9/S10/S11 were all the
"code decides a verdict, model renders it" pattern (mode contract + code-owned
scorer + authoritative directive + validator pin). S12 is NOT that — it's a
**reasoning structure** (Analysis of Competing Hypotheses). Scope it carefully
against ROADMAP.md at session start; do NOT force it into the mode/contract mold
without deciding that's right. Sketch the design first (probe SARA if it has an
ACH/hypothesis analogue; snapshot before coding), get the shape right, then
build.

1. **Competing hypotheses per investigation.** A session/investigation can hold
   N candidate hypotheses (e.g. "this alert is a true positive / a false
   positive / a benign admin action / a test"). Typed, code-owned structure —
   decide where it lives (Postgres? in-session?) and how it's seeded.
2. **Per-evidence scoring against each hypothesis.** Each piece of evidence
   (an enrichment verdict, an alert signal, an email finding) scores FOR or
   AGAINST each hypothesis — the ACH matrix. Code owns the scoring math (ADR
   0006); the model may PROPOSE evidence/hypotheses but not decide the matrix.
3. **Next-lookup by expected information gain.** The engine picks the next
   enrichment/lookup that would most discriminate between the surviving
   hypotheses — not a fixed checklist. This is the "capability-negotiated" idea
   applied to investigation flow.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic — the scoring math
  and hypothesis-elimination logic are ZERO-LLM and pinned by fixture tests, no
  live LLM in pytest.
- LLM-path changes (if any hypothesis/evidence proposal uses the model) MUST be
  live-verified against the real dev endpoint (Scout via Northflank) before
  session end — probe file for the live verification. But the CORE (the ACH
  matrix, scoring, information-gain selection) should be deterministic code.
- Reuse where it fits: the S10/S11 authoritative-directive + validator-pin
  pattern IF the model renders any hypothesis summary; the observable extractor;
  the enrichment verdicts (S5) as evidence inputs; the alert/phishing findings
  (S10/S11) as evidence inputs.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
- TD-005 standing trigger: any NEW doc_type or embedding-model change → re-run
  the calibration battery. S12 likely adds no doc_type — trigger not expected.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): the
  ioc_check→KB-CVE-context stretch (parked 5×, IDEAS.md sketch — sets
  `has_enrichment=True` on the S10 alert score path AND could feed S12 evidence);
  TD-012 (post-hoc contract validation, no re-ask loop); TD-014 (unbounded
  history); TD-015 (S11 phishing heuristic coverage — brand list / confusables /
  compound-TLD registrable domain, false-negative biased, fix on a real miss).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers,
  move on. Tired human = short session; rituals anyway.
- End with `/session-end`; S12 done = an investigation holds competing
  hypotheses, evidence scores against each in CODE (the ACH matrix), the engine
  picks the next most-discriminating lookup by expected information gain, pinned
  by fixture tests, and (if any model rendering is added) one path live-verified
  through a contract against Scout.
