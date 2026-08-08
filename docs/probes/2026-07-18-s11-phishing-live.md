# Probe: S11 phishing_analysis — live end-to-end through the contract (Scout)

_Date: 2026-07-18 (S11) · Target: the running Auspex app (`/api/chat`) against
the live dev LLM **Llama-4-Scout via Northflank (D-015)**, model
`nvidia/Llama-4-Scout-17B-16E-Instruct-FP8`. Method: dev-login JWT → SSE
phishing turn → parse the `done` frame → confirm the model's `## Verdict` sits
within the CODE-computed allowed set → independently re-validate the raw answer
with `contract_for(Mode.PHISHING_ANALYSIS).validate(answer, pinned={"Verdict":
allowed})`. Harness: scratchpad/live_phishing.py (this session)._

## Why

S11 "done" requires one email analyzed end-to-end, live-verified through the
typed contract against Scout — proving the deterministic header/domain engine
(the Verdict is decided in CODE, ADR 0006) actually drives Scout's rendered
answer, and the same contract validates it. Two turns cover both poles: a
spoofed auth-failing email pinned to MALICIOUS, and an all-auth-pass email that
the code lets read BENIGN. (Scout is not native-reasoning → two-pass path; the
deterministic-phishing directive rides the base messages, so pass 2 sees it.)

## 1. Spoof + auth-fail + typosquat → MALICIOUS (floor-locked)

Input (abridged): `From: "PayPal Support" <security@paypa1.com>`,
`Reply-To: recover@account-verify.ru`, `To: victim@acme.com`,
`Authentication-Results: … spf=fail; dkim=fail; dmarc=fail`, body links
`http://paypa1.com/verify`.

- **Code verdict** (parse → decide): `MALICIOUS`, score `100`, `allowed=("MALICIOUS",)`
  — findings: spf_fail, dkim_fail, dmarc_fail, reply_to_mismatch,
  display_name_spoof, typosquat_near_miss (paypa1 ~ paypal, distance 1).
- **done frame**: `{"path":"model","mode":"phishing_analysis","contract_valid":true}`.
- **Model `## Verdict` leading token**: `MALICIOUS` — within the allowed set
  (which here is the singleton floor; no downgrade possible).
- **Independent re-validation** with the floor pin → **ok**.
- The rendered `## Indicators` listed the code findings AND model-read content
  signals (suspicious link, urgent 24-hour tone) — the intended division:
  code drives the Verdict, the model may add content observations around it.
  It did NOT name the recipient's own domain (acme.com) as an indicator
  (victim-filter directive held live).

## 2. All auth pass, no findings → BENIGN (positive-evidence gate)

Input (abridged): `From: Alice Carter <alice@example.com>`, `To: bob@acme.com`,
`Authentication-Results: … spf=pass; dkim=pass; dmarc=pass`, ordinary body.

- **Code verdict**: `BENIGN`, score `0`, `allowed=("BENIGN","SUSPICIOUS","MALICIOUS")`
  — BENIGN is reachable ONLY because auth positively passed and zero findings
  fired (the S10 rail: absence would have been DEFERRED, never BENIGN).
- **done frame**: `{"mode":"phishing_analysis","contract_valid":true}`.
- **Model `## Verdict` leading token**: `BENIGN` (within allowed; the model
  could have raised to SUSPICIOUS/MALICIOUS on content, chose not to).
- **Independent re-validation** → **ok**.

## What this establishes

- The S11 code-owned engine (parse → auth/spoof/lookalike findings → verdict
  FLOOR) FEEDS the phishing_analysis contract: the Verdict is decided in code
  and the model renders the sections around it (ADR 0006 + 0007).
- TD-013's phishing portion is closed in practice: the model rendered the code
  verdict; the pasted body was not free attacker prose it weighed to a
  disposition. The FLOOR PIN (validator, `pinned={"Verdict": allowed}`) is what
  enforces it — a launder below the floor (rendering BENIGN on a MALICIOUS
  floor) fails the contract in code, pinned hermetically in
  tests/test_chat_sse.py::test_phishing_verdict_cannot_be_laundered_below_the_floor;
  a permitted raise above a DEFERRED floor validates (…::test_phishing_model_may_raise_above_the_floor).
- Victim-domain IOC filtering holds live: the recipient domain was withheld
  from the directive's indicator list and Scout did not surface it.
- Multi-shape parsing (auth placement, display-name-spoof address recovery, IDN
  homograph, near-miss/TLD-swap) is pinned hermetically in tests/test_phishing.py
  against fixture emails; the live turns exercise the wiring, which is
  shape-agnostic (parse_email → decide_verdict → directive is identical).
