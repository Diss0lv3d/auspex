# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: S12 is COMPLETE — Step 0 promoted #13 to main; the ACH
hypothesis engine v1 shipped on `staging`, hardened by a same-session 16-finding
verification workflow, live-verified in-container, CI-green (572 tests) — but
NOT yet promoted. S13 starts with a FRESH-EYES review + promote #14, then the
evidence graph. The S12 demo, zero-LLM: POST an alert/email paste to
`/api/investigations` → 4 competing hypotheses scored in CODE (Heuer
least-inconsistency; FP+BENIGN rejected with named reasons on the typosquat
email; TP/TEST honestly tied at 1.0 bit — lookalikes don't separate a phish
from a simulation); POST `/{id}/lookups` executes the engine's
highest-information-gain lookup through live keyless enrichment and folds the
answer back in. The live gain figure matched the independently hand-computed
fixture to 6 decimals.)_

---

SESSION S13 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S13` first (full ritual). Primary dev LLM is **Llama-4-Scout
via Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline
endpoint (D-013) and is what the session-start local-Ollama gate validates.
Any mismatch → STOP and tell me. (D-011: `gh` flips to the work account
between AND mid-session — it DID at S12 start; re-check before every `gh`
call.)

Step 0 (carried follow-up, do BEFORE new scope):
- **Fresh-eyes review of S12's feature work** — scope: the 17 commits
  `5d3d2dc..staging` (~3,094 insertions): `auspex/ach/` (types.py the closed
  vocabularies + catalog, evidence.py the cell-vector doctrine tables + three
  adapters, matrix.py the Heuer scorer + rails, gain.py the likelihood rows +
  entropy/Bayes + candidate hygiene, store.py), `auspex/routes/
  investigations.py`, the 3 new tables in migrations.py, tests/test_ach.py,
  tests/test_investigations.py. IMPORTANT CONTEXT: this code already survived
  a same-session 4-lens adversarial verification workflow — 16 findings (13
  unique), every one verified by execution, all fixed (commits 2616b24,
  7a72a96, add7ef2, e1435a5, b90ec00). So do NOT re-run the same lenses —
  review with FRESH angles: (analyst-design) are the curated numbers
  defensible — the cell vectors in evidence.py `_CELLS`, the likelihood rows
  in gain.py, TEST_ACTIVITY's whole treatment (is a phishing-simulation prior
  of mal=.08 honest?), REJECT_AT=3.0, the 2.0 plausibility half-life;
  (security) two-real-workspace tenancy through the routes; adversarial jsonb
  subject values round-tripped through Postgres; can a crafted paste make
  `_subject_snapshot` lie about itself? (correctness) matrix edges the lenses
  missed — duplicate hypothesis keys, hand-edited cells jsonb (strings?
  floats? out-of-range ints?), empty hypothesis tuples via the store;
  (honesty) do the API field names say what they mean (`weight` is a
  plausibility weight, not a probability — does the response say so
  anywhere?). Verify findings BY EXECUTION before fixing; fix with
  regressions; then **`/promote`** (#14). Only then start S13 scope.

Goal (scope-locked, from ROADMAP.md S13 — Evidence graph + cited output):

1. **Typed evidence objects.** The substrate EXISTS: `ach_evidence` rows
   (kind, statement, credibility, cells, source, obs_id — append-only,
   workspace-scoped) were designed in S12 for exactly this. Decide what the
   GRAPH adds: edges evidence→observable (obs_id already links), evidence→
   verdict rows (the S5 trail), evidence→KB docs? Keep it minimal and typed;
   probe what S14 (retro-hunt) will need before over-building.
2. **Every generated claim carries a citation.** This REJOINS the LLM path:
   when the model renders an investigation summary (or any deep answer that
   draws on evidence), each claim must cite the evidence row / verdict /
   KB doc it stands on. Reuse the S10/S11 pattern: code compiles the evidence
   list into an AUTHORITATIVE directive with stable citation ids; the model
   renders around them.
3. **Output guard rejects uncited claims.** The contract validator grows a
   citation check (code-owned, post-hoc like the rest — TD-012 honesty:
   detected, not prevented; say so in the copy). Decide the failure surface:
   contract_valid=false reason, or a stricter structural check.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic — citation
  compilation and the guard are ZERO-LLM, pinned by fixtures.
- The rendering path MUST be live-verified against Scout before session end
  (probe file) — this is the first LLM-path feature since S11; the S10/S11
  directive+pin pattern applies (AUTHORITATIVE directive, untrusted fields
  through auspex.untrusted.flatten, validator pin for anything code-decided).
  ACH evidence statements are capped at 300 chars in _make for exactly this
  moment — but they still carry attacker-authored text: flatten them at the
  directive boundary.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth (S12
  added zero — D-019 made the tables code constants; keep that bar).
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): the
  ioc_check→KB-CVE-context stretch (parked 6× now — but NOTE: the S13
  evidence graph is allowed to make KB docs CITABLE, which is adjacent;
  re-scope deliberately if it collapses into the same work); TD-012 (post-hoc
  validation, no re-ask); TD-014 (unbounded history); TD-015 (brand/confusable
  coverage); TD-016 (ACH v1 surface bounds — top-20 ranked cap means
  body.obs_id can only run surfaced candidates, no list/close endpoints);
  role-aware ACH likelihoods (IDEAS.md); model-PROPOSED hypotheses/evidence
  (D-019 allows it later, through a contract — only if S13 scope demands it).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers,
  move on. Tired human = short session; rituals anyway.
- End with `/session-end`; S13 done = evidence rows are citable objects with
  stable ids, one model-rendered path emits claims with citations through a
  contract, the code guard flags uncited claims on the done frame, pinned by
  fixture tests, live-verified against Scout.
