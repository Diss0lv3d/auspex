# Probe: SARA orchestrator loop + DEFERRED rail (reference for S9 modes)

_Date: 2026-07-18 · Source: sara-open (read-only reference; paths verified live
this session). Snapshotted because the worktree path gets cleaned._

## 1. Bounded adaptive loop (Plan→DAG→Judge)

Source: `.claude/worktrees/1359-chain-surface/sara/core/orchestrator_loop/runner.py`
(120 lines, read in full 2026-07-18).

Shape (ADR 0058 Phase 1 there):

```
run chain -> Governor judges -> stop or bounded re-plan
```

Load-bearing rails, verbatim semantics:

- **Modes `off|shadow|enforce`** — `off` returns None; in `shadow` the caller
  logs but does NOT act; only `enforce` drives. Rollout is a config choice,
  not a code branch scattered around.
- **Injected `chain_fn` + `judge_fn`** — the loop is pure control flow,
  testable with fakes. No LLM/network inside the runner.
- **`plan_hash()` stuck detection** — deterministic sha256 over the sorted
  agent-set only. A re_plan that produces an identical plan ⇒ forced
  `escalate` with `[stuck:no_plan_change]` prefixed to the reasoning and an
  `overrides_applied` audit entry. Escalates AT the current iteration (no
  increment) — "no progress" is attributed to where it happened.
- **Loops-exhausted backstop** — a `re_plan` decision that survives to
  `max_loops` must NEVER be the final action; the runner force-escalates with
  `[runner:loops_exhausted]` + `overrides_applied` entry, regardless of what
  judge_fn said. Safety lives in the runner, not in the judge's goodwill
  (code over prompts).
- **HITL pause short-circuits BEFORE the judge** — `chain_result["paused"]`
  (destructive action deferred for analyst approval) breaks out before
  judging: "a partial run is NOT a verdict"; a paused run can never become
  recommend_close/escalate. `paused` is a loop terminal distinct from the
  Governor's vocabulary.
- **Structured feedback only** — the judge's `decision.details` dict is the
  only thing fed back to the next chain iteration (no full-context re-feed);
  cumulative `cost_usd` vs `cost_ceiling` is probed each iteration.
- Default decision if the loop never judges: `escalate` ("loop did not
  produce a decision") — errors bias toward escalation, never silence.

## 2. DEFERRED rail — "no data ≠ low risk"

Source: `sara/agents/alert_triage.py:1414-1580` (read live 2026-07-18).

Two conditions, both ending in the same DEFERRED shape:

**(a) sara-open#1168 — signal-poor envelope.** All of: severity missing/
UNKNOWN (including the descriptive "Unable to determine — insufficient alert
data" sentinel — a reopened bug taught them sentinel drift silently regresses
the rail), AND no enrichment has run, AND no scoring contribution other than
the bare severity default. Previously emitted a hardcoded `LOW/10/TP=LOW/
"verify with asset owner"` template — a 100-alert live audit showed it firing
on 99/100 differentiated alerts. Fix: the agent says it CANNOT honestly
triage.

**(b) sara-open#1499 — severity-only pending enrichment.** Severity IS known,
enrichment has NOT run, IOC artifacts exist in the payload, and nothing but
severity contributed. (The SEV1-WannaCry shape: the only real evidence is the
hash verdict, which only materialises after enrichment — bare severity floors
it at LOW/MEDIUM.) The DEFERRED copy names the actual reason and counts the
un-enriched IOCs so the brief doesn't read "no IOCs" when there ARE IOCs.

The DEFERRED shape (both branches):
- `risk_level = "DEFERRED"`, rendered `Risk Score: — (DEFERRED)` — the score
  is NULLED (0 for int-typed consumers; the old 10 was a fallback constant,
  not a measurement).
- `true_positive_estimate = "UNKNOWN"`.
- `needs_deep_triage = True` — a machine-readable flag the orchestrator (and
  chain-internal logic) branches on; the escalation is data, not prose.
- Recommendation copy states explicitly what is missing and what to run next
  (escalate to enrichment + classification, then re-triage).

Plus the **pending-enrichment tail**: any non-LOW score computed WITHOUT
enrichment context gets " · ⏳ pending enrichment — … score may shift"
appended (DEFERRED already says it; don't double up).

## 3. What Auspex S9 takes from this

- `alert_triage` mode ships with a DEFERRED outcome in its **typed contract**
  from day one: signal-poor input ⇒ `risk_level: DEFERRED`, score null,
  `needs_deep_triage: true`, copy naming what's missing — never a defaulted
  LOW. Validator enforces it (specs over prompts, ADR 0007 spirit); resolver/
  renderer code enforces the score-nulling (code over prompts, ADR 0006).
- Distinguish the two DEFERRED reasons (nothing-to-score vs
  evidence-pending-enrichment) in copy AND in a machine-readable field.
- Mode loop rails belong in code: stuck detection, iteration ceilings, and
  "partial output is not a verdict" short-circuits are runner logic, not
  prompt instructions.
- Errors/absence bias toward escalation-or-DEFERRED, never toward a
  confident-looking default.
