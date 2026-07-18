# Probe: S9 response modes — live end-to-end through typed contracts (Scout)

_Date: 2026-07-18 (S9) · Target: the running Auspex app (`/api/chat`) against the
live dev LLM **Llama-4-Scout via Northflank (D-015)**, model
`nvidia/Llama-4-Scout-17B-16E-Instruct-FP8`. Method: dev-login JWT → SSE deep
turn → parse the `done` frame → independently re-validate the raw answer with
`auspex.modes.contract_for(...).validate()`._

## Why

S9 "done" requires at least one mode running end-to-end live through a typed
contract that validated real Scout output. Scout is not native-reasoning, so
these turns take the two-pass path; the mode directive lives in the base
messages, so pass 2 (the answer) sees it.

## 1. BRIEF mode — `give me a brief on the Log4Shell vulnerability`

- `done` frame: `{"path":"model","mode":"brief","contract_valid":true}`,
  usage prompt_tokens=522 (vs 276 on the pre-wiring container — the compiled
  contract directive + TD-009 fence directive are in the prompt).
- Raw Scout answer carried all three sections: `## Bottom line`, `## Details`,
  `## Watch items` (the last is optional in the contract; Scout produced it).
- Independent re-validation `contract_for(Mode.BRIEF).validate(answer)` → **ok**.

So the contract COMPILED to the prompt that shaped real Scout output, and the
SAME contract VALIDATED that output — the spec drove both ends (ADR 0007).

## 2. ALERT_TRIAGE mode — signal-poor alert → DEFERRED (the day-one rail)

Input: `CEF:0|Vendor|Product|1.0|100|generic activity observed|0|` — a CEF
envelope with no real signal (severity 0, no IOCs, no MITRE mapping).

- `done` frame: `{"mode":"alert_triage","contract_valid":true}`.
- Raw Scout answer:
  ```
  ## Risk
  DEFERRED
  ## Reasoning
  Insufficient context to determine risk; …"generic activity observed".
  ## Recommendation
  Pursue enrichment: review system logs, check threat intelligence feeds, …
  ```
- The Risk is **DEFERRED, not a defaulted LOW** — "no data ≠ low risk" (SARA's
  DEFERRED rail, docs/probes/2026-07-18-sara-orchestrator-deferred.md), enforced
  from day one via the contract's Risk enum (which includes DEFERRED) + the hard
  rule compiled into the directive. Contract validated ok.

## Notes / reality bites

- The done frame's `contract_valid` is post-hoc observability — a streamed
  answer can't be blocked; the enum/section checks are code-owned (ADR 0006),
  not trusted to the model.
- Format-beats-keywords held: the CEF paste routed to ALERT_TRIAGE by the
  classifier's alert-paste detector, not by any keyword.
- Both turns took the two-pass path (Scout is non-native-reasoning) — the mode
  directive is in the base messages so both passes see it. TD-002 (two-pass
  cost) unchanged.
