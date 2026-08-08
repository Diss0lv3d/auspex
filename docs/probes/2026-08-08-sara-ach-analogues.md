# Probe: SARA's ACH / hypothesis-reasoning analogues (S12 reference)

_Date: 2026-08-08 (S12) · Target: `/home/burhan/sara-open` source (read-only
architecture study, per the standing rule: patterns, never code). Method: a
4-agent recon workflow; the SARA reader swept the orchestrator loop, triage/
summary/enrichment agents, and the whole repo by grep for hypothesis/ACH/
information-gain vocabulary. Every claim below carries file:line; negatives
carry the grep that established them._

## Headline

**SARA has no ACH engine.** No data structure ever holds more than one
hypothesis, no per-evidence-versus-alternatives matrix exists, and no lookup is
ever chosen by expected value or information gain. What it has instead are five
partial analogues — three of them worth stealing as *patterns*, two of them
cautionary tales.

## The cautionary tales (what S12 must NOT repeat)

1. **Prompt-only ACH, structurally discarded.** `analysis_summary.py:248-266`
   instructs the LLM to list alternative hypotheses with per-hypothesis
   confidences ("Most likely: … 70% / Alternative: … 20% / Cannot rule out:
   … 10%"). But the STRICTLY ENFORCED output template (`:305-341`) has exactly
   one `Most likely hypothesis (NN% sure)` slot — no alternatives section — and
   the downstream parser (`extract_llm_pct_or_none`, `:2403`) extracts only the
   single NN% figure. Grep over agents/, core/, routes/ finds **no consumer,
   storage field, or trace key for alternatives anywhere**. ACH is requested of
   the model and thrown away by the contract. *Lesson: if the matrix isn't a
   code-owned structure, it doesn't exist (ADR 0006/0007 said this already).*
2. **"Next-step value" as prompt prose.** The closest thing to
   which-lookup-next-by-discrimination in the whole repo is a prompt section
   (`analysis_summary.py:277-281`) ranking investigation priorities
   ("[Highest value] Actions that confirm/refute hypothesis…"). No code
   computes or enforces it.

## The patterns worth reusing

3. **One-direction falsification guards (code).** `fp_contradiction_guard.py:
   38-162` deterministically pits the FP/benign explanation against asserted
   attack vocabulary (with negation windows and hedge detection);
   `contradiction_detector.py:78-118` runs 12 closed-vocab evidence-vs-verdict
   axes, detection-only. Both weigh evidence against ONE hypothesis — ACH
   generalizes exactly this to N hypotheses, and the closed-vocab axis list is
   the shape our evidence-kind enum should take.
4. **Doctrine tables for lookup gating (code constants).**
   `enrichment_plan.py:48-72,465-580` resolves (category × artifact_type) →
   allowed capability classes by set intersection — a hand-authored, tested,
   closed-vocab table. Our per-hypothesis cell tables and outcome-likelihood
   tables should live the same way: code constants, extended via PR with a
   fixture test, never env vars or LLM judgment.
5. **Additive single-hypothesis scoring + DEFERRED rails.**
   `alert_triage.py:1267-1580` — already ported as our S10 scorer. Its only nod
   to a benign alternative is negative space (#1587: bare dual-use shells score
   0 without a cmdline co-signal). ACH is the structure that makes that
   alternative first-class instead of a withheld point.

## Adjacent machinery (understood, not adopted)

- **disposition_recommender** (`disposition_recommender.py:92-96,296-328,
  400-445`): a history base-rate prior (modal disposition of ≥3 similar
  incidents at ≥0.6 agreement, bandit-ledger corroboration, tenant-memory
  bonus, capped 0.75). A prior over dispositions — never an enumeration of
  explanations for the CURRENT evidence. Could someday seed ACH prior weights;
  out of S12 scope.
- **Adaptive Planner** (`planner.py:35-93`, `plan_models.py:55`): dynamic
  lookup selection exists but is LLM judgment against a category checklist,
  with a SINGLE `hypothesis: str` field ("working theory the plan tests" —
  audit/UX only). Re-plan principle: "try alternatives for failures".
- **Thompson-sampling bandit** (`rl/bandit.py:1-60`, `learning.py:1-60`): the
  only posterior math in the repo — Beta(α,β) per (policy, context, arm) over
  plan SHAPES, shadow-only. Learns which plan works per tenant/category, not
  which hypothesis is true.
- **Verdict arbitration** (`verdict_floor.py:29-36`, `ioc_enrichment_v2.py:
  1341-1343,1426-1446,3465-3484`): conflicting evidence resolved by rank
  clamping (floors only raise; doctrine BENIGN ceiling; single-source cap at
  SUSPICIOUS) — fixed precedence, no likelihood weighting.
- **agent_confidence** (`agent_confidence.py:228-236,287-352`): weighted-mean
  confidence in ONE verdict (grounding 2.0, contradictions 1.5, …); missing
  signals omitted, never zeroed — the honest-absence idiom we already follow.

## Verified negatives (the greps)

- `grep -rniE '\bACH\b|competing hypoth|analysis of competing|diagnosticity|disconfirm'`
  over `*.py|*.md|*.yaml` in `sara/` → **zero hits**. Every `hypothes` hit is a
  singular working-theory string.
- `grep -rniE 'information.gain|expected.value|expected.utility|entropy|bayes|log.?odds'`
  (non-test) → only `ppa_template/generator.py`'s `expected_value` (a string
  equality check in extraction validation) and the rl/bandit plumbing. Nothing
  computes value-of-information for a lookup.

## What this means for the S12 design

ACH v1 is **greenfield with strong local precedent**: closed-vocab hypothesis
catalog and evidence kinds (pattern 3), cell/likelihood tables as tested code
constants (pattern 4), honest rails for no-evidence/no-discrimination (pattern
5 + our S10/S11 DEFERRED philosophy), and the matrix + information-gain math as
deterministic, fixture-pinned code — the exact thing SARA's prompt-deep version
lacks. The model may later PROPOSE hypotheses/evidence through a contract; it
never decides a cell, a weight, or the next lookup.
