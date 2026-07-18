# Probe: S10 alert normalizer + scorer — live end-to-end through alert_triage (Scout)

_Date: 2026-07-18 (S10) · Target: the running Auspex app (`/api/chat`) against the
live dev LLM **Llama-4-Scout via Northflank (D-015)**, model
`nvidia/Llama-4-Scout-17B-16E-Instruct-FP8`. Method: dev-login JWT → SSE
alert_triage turn → parse the `done` frame → confirm the model's `## Risk` equals
the CODE-computed level → independently re-validate the raw answer with
`auspex.modes.contract_for(Mode.ALERT_TRIAGE).validate()`._

## Why

S10 "done" requires one alert scored end-to-end, live-verified through the typed
contract against Scout — proving the deterministic normalizer+scorer verdict
(the Risk level is decided in CODE, ADR 0006) actually drives Scout's rendered
answer, and the same contract validates it. Two turns cover both outcomes: a
richly-signalled alert that SCORES, and a signal-poor one that the DEFERRED rail
nulls. (Scout is not native-reasoning → two-pass path; the deterministic-triage
directive rides the base messages, so pass 2 sees it.)

## 1. Rich CEF → CRITICAL (scored end-to-end)

Input:
`CEF:0|Trellix|ENS|10.7|1201|Malware detected|9|src=10.1.2.3 cs1=powershell -enc SQBFAFgA externalId=T1059.001 confidence=90`

- **Code verdict** (normalize → score): `CRITICAL`, score `90` — itemized:
  severity +40, confidence_high +15, encoded_command +20, suspicious_process +10,
  mitre_technique_mapped +5.
- **done frame**: `{"path":"model","mode":"alert_triage","contract_valid":true}`.
- **Model `## Risk` leading token**: `CRITICAL` — Scout used the authoritative
  code level (did not recompute).
- **Independent re-validation** `contract_for(Mode.ALERT_TRIAGE).validate(answer)`
  → **ok**.

## 2. Signal-poor CEF → DEFERRED (the day-one rail, now CODE-emitted)

Input: `CEF:0|Vendor|Product|1.0|100|generic activity observed|0|` — the S9 demo
paste (severity 0 → INFORMATIONAL; no IOCs, no MITRE, no process signal).

- **Code verdict**: `DEFERRED`, score `None` (nulled), `needs_deep_triage=True`,
  `true_positive_estimate=UNKNOWN`. In S9 the LLM chose DEFERRED from the prompt
  rail; in S10 the SCORER emits it deterministically and the model renders it.
- **done frame**: `{"mode":"alert_triage","contract_valid":true}`.
- **Model `## Risk` leading token**: `DEFERRED`.
- **Independent re-validation** → **ok**.

## What this establishes

- The S10 code-owned engine (multi-SIEM normalize → additive score → DEFERRED
  rail) FEEDS the S9 alert_triage contract: the Risk level is decided in code and
  the model renders the contract sections around it — the spec still validates
  the shape (ADR 0007), and code owns the verdict (ADR 0006).
- TD-013 mitigation for the alert path holds in practice: the model scored the
  code verdict, not the raw (untrusted) paste — a "output Risk CRITICAL" style
  injection inside a signal-poor alert cannot lift it off DEFERRED (the code
  verdict is what the directive carries; pinned hermetically in
  tests/test_chat_sse.py::test_alert_triage_deferred_rail_and_injection_resistance).
- Multi-format PARSING (CEF/LEEF/syslog/JSON) is pinned hermetically in
  tests/test_alerts.py; the live turns exercise CEF because the wiring is
  format-agnostic (normalize() dispatches; the directive shape is identical).
