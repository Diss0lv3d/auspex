# Probe: S12 ACH loop live in-container — create → recommend → execute → re-assess

_Date: 2026-08-08 (S12) · Target: the running Auspex app container
(`/api/investigations`) with in-container enrichment ENABLED (keyless S5
providers, live outbound). Method: dev-login JWT → POST an investigation over
the S11 spoofed-typosquat email → POST `/lookups` to execute the engine's
recommended enrichment for real → compare assessments. **Zero LLM anywhere on
this path** — no Scout involvement, by design (D-019: the surface v1 is a
deterministic REST resource; model rendering is S13+ and will need its own
live verification when it exists)._

## Turn 1 — create (POST /api/investigations), the typosquat email

Subject: `From: "PayPal Support" <security@paypa1.com>`, `Reply-To:
recover@account-verify.ru`, spf/dkim/dmarc=fail, link `paypa1.com/verify`,
victim `victim@acme.com`.

- 201; `subject_kind: email`; 6 deterministic evidence rows straight from the
  S11 findings (3 × auth_fail cred 0.9, 2 × spoof_indicator 0.7,
  lookalike_domain 0.7).
- Matrix (`ranking_claimed: true`):

  | hypothesis | status | inconsistency | weight |
  |---|---|---|---|
  | true_positive | surviving | 0.00 | 0.465 |
  | test_activity | surviving | 0.00 | 0.465 |
  | false_positive | surviving | 5.50 | 0.069 |
  | benign_activity | **rejected** | 9.60 | 0 |

  Exactly the designed shape: **a lookalike + auth-fail email does not
  discriminate a real phish from an authorized simulation** — TP and TEST tie
  at zero inconsistency; BENIGN is rejected on hard contradictions (auth fails
  at credibility 0.9 against −2 cells); FP survives but heavily inconsistent.
- Lookup plan: prior entropy **1.293685 bits**; candidates victim-filtered
  (nothing acme.com-side); top three all gain 0.207078 (same NET likelihood
  group — the tie is the v1 group-only likelihood limitation, parked in
  IDEAS.md as role-aware likelihoods v2); deterministic tiebreak picked
  `mail.paypa1.com`.

## Turn 2 — execute (POST /api/investigations/{id}/lookups)

Ran the engine's top recommendation through the REAL keyless fan-out.
Answering sources had **no claim** about `mail.paypa1.com`:

- One `enrichment_no_signal` evidence row, credibility 0.3, statement ending
  "(unknown to them — not benign)" — coverage without a fake benign.
- Re-assessment: `test_activity` 0.488 (was 0.465), `true_positive` 0.440 —
  the small shift TOWARD simulation/away from live attack is exactly the
  direction the gain math priced into the "unknown" outcome (feeds miss
  simulation infra more often than live attack infra), so the recorded update
  and the promised expectation agree.
- The answered candidate RETIRED; next recommendations moved to
  `recover@account-verify.ru` / `security@paypal1.com`-side observables.
- Note: realized entropy went UP (1.293685 → 1.300922 bits). Correct, not a
  bug: IG is the EXPECTED entropy reduction; an individual outcome may
  increase uncertainty. The API exposes the per-outcome terms so an analyst
  can see this before running the lookup.

## What this establishes

- The three S12 goals run end-to-end against live infrastructure with zero
  LLM: an investigation holds four competing hypotheses; evidence scores
  against each in code (Heuer least-inconsistency, hard-contradiction
  rejection, honesty rails); the engine picks the next lookup by expected
  information gain, executes it, and folds the answer back in.
- The S5/S10/S11 layers compose unchanged: S11 findings became evidence
  verbatim; the S11/S12 victim filter gates candidates; the S5 fan-out
  executes lookups and ALSO persists its own observables/verdicts trail.
- Absence semantics hold under live conditions: an unknown answer is neither
  discarded (it retires the candidate and nudges per the priced direction)
  nor inflated (credibility 0.3, "not benign" in the analyst copy).
