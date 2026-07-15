# Probe: two-pass reasoning prompt shape on real Scout (D-016 feature 1)

- **Date:** 2026-07-16
- **Endpoint:** Northflank vLLM, `nvidia/Llama-4-Scout-17B-16E-Instruct-FP8`
  (primary dev LLM, D-015; emits NO native `reasoning` field → needs the
  two-pass fallback).
- **Why:** before coding the two-pass path in `auspex/routes/chat.py`, verify
  Scout actually honors the intended prompt shape (reality over memory).
- **Method:** host-run scratch (`probe_two_pass_scout.py`), temperature 0.
  Pass 1 = brief analyst reasoning (max_tokens 256); pass 2 = final answer
  (max_tokens 2000), given pass-1 text as prior private analysis.

## Result — PASS (trailing system directive works)

Question: *"Alert A-1001 shows outbound beaconing from 203.0.113.7 on a finance
workstation. How worried should I be?"*

**Variant A — pass-1 directive as a trailing `role:"system"` message** (the
design choice):
- pass 1 → 99 tokens, `finish=stop`: *"Initial assessment: Outbound beaconing
  … possibly indicating exfiltration or C2 … without destination port/protocol/
  frequency it's difficult to gauge severity. Is 203.0.113.7 known-malicious…?"*
  — a genuine, useful analyst brief. ✅
- pass 2 → 36 tokens, `finish=stop`: *"I'm moderately concerned; further
  investigation is needed to determine the destination and intent…"* — concise,
  analyst-voice, did **not** restate the analysis verbatim. ✅

**Variant B — pass-1 directive folded into the user turn**: also works (113-token
brief, clean answer). Either shape is viable.

## Decision for the implementation

- Use **Variant A**: append `{"role":"system", "content": PASS1_DIRECTIVE}` for
  pass 1, and `{"role":"system", "content": pass2_directive(analysis)}` for pass
  2 (on top of the shared history). Scout honors it; no need for the user-turn
  fallback.
- `CHAT_REASONING_MAX_TOKENS = 256` is ample (observed 99–113).
- `CHAT_ANSWER_MAX_TOKENS = 2000` (unchanged from today's chat cap).
- Both passes hit the customer's own endpoint → D-005 intact.
