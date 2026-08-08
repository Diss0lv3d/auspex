# S13 live verification — cited investigation summary against real Scout

_Date: 2026-08-09 · Endpoint: the D-015 primary (Llama-4-Scout via
Northflank), in-container, through `POST /api/investigations/{id}/summary`.
Subject: the flagship typosquat email (paypa1.com, failed auth, .ru
reply-to). Two runs — the first caught two real defects, the second is
clean. This is the first LLM-path feature since S11._

## Run 1 — drift caught live (the point of the exercise)

Contract: **valid** (sections + pinned `TRUE-POSITIVE` honored, 400
completion tokens). Citation guard: **failed, for the right and wrong
reasons at once**:

1. **Guard bug (ours):** Scout grouped citations as `[E-a, E-b, E-c]` in one
   bracket pair — a legitimate reading of "citation id(s)". The
   bracket-per-id regex refused the group, flagging three fully-cited lines
   as uncited. Fix: the guard now matches the label token itself (with or
   without brackets) — it checks resolvability and presence, never
   typography. Regression: `test_guard_accepts_grouped_citations_in_one_bracket`.
2. **Directive gap (ours):** on the two REJECTED hypotheses Scout rendered a
   literal `[ ]` — nothing told it which evidence drives a hypothesis's
   standing, and rejected rows have no obvious id to cite. Code knows
   exactly which rows bear on each hypothesis (the nonzero cells), so the
   directive now names `bearing evidence: E-…` per hypothesis row and
   forbids empty citation brackets. Regressions:
   `test_directive_names_bearing_evidence_per_hypothesis`,
   `test_directive_says_when_no_evidence_bears_on_a_hypothesis`.

Zero fabricated ids in both runs — Scout never invented a citation; every
id it used resolved to a real `ach_evidence` row uuid.

## Run 2 — clean (post-fix container rebuild)

- `contract_valid: true`, pin `TRUE-POSITIVE` honored as the leading token.
- Citation guard: `ok: true` — **19 valid citations, 0 fabricated, 0
  uncited claim lines** across the citable sections.
- Every hypothesis line (including both rejected ones) cites its bearing
  evidence; `## Key evidence` lines each cite the row they describe;
  `## Next lookup` carries the engine's recommendation verbatim
  (mail.paypa1.com, 0.181584 bits — the S12 hand-verified figure).
- Usage: 1198 prompt + 591 completion tokens; finish_reason `stop`.

## What is structural vs. asked-of-the-model (honesty)

- Structural (code): the matrix, the plan, the pin token, the citation
  labels (uuid-derived, stable), statement flattening at the directive
  boundary, and the post-hoc checks. A laundered leading hypothesis or a
  fabricated citation ALWAYS fails the response's `contract_valid` /
  `citations.ok` — detected, never prevented (TD-012: the answer has
  already been produced).
- Asked of the model: narrating around the facts and citing where told.
  Run 1 shows exactly what that boundary looks like when the ask is
  underspecified — and that the guard catches it.

## Cleanup

Both probe investigations deleted from the dev workspace
(88f9b916…, 7731a37a…). No new env vars; no summary persistence (like every
other read, a summary recomputes from stored inputs on demand).
