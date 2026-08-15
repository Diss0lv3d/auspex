# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**Three commits are waiting to promote:** `a3b431b` (S18 Step-0 fixes),
`b536f1e` (the review record + TD-024) and `c21beb8` (the approval flow) — plus
this session-end commit. **`gh` DID flip to the work account at S18 start**, so
assume it has again. **One thing changed under us this session: the KB corpus
crossed 30 000 docs (27,475 → 31,819) because ingest ran — the TD-005 re-battery
trigger has fired for the first time.** S18 shipped: Step 0 refuted its own
strongest lead by measurement (2000 half-life families cost 12 ms), verified two
suspicions sound, and found three defects nobody had listed — an undo could be
another action's EXECUTE, parameter names were unvalidated, and an action could
silently shadow a tool the loop dispatches. Then the approval flow: a proposal is
claimed exactly once (proven against eight racing Postgres backends), its card is
compiled from the spec and frozen, and an approved action re-checks both the D-014
gate and a spec fingerprint before it runs. **Something really executes now, and
its undo really runs.** CI-green 801 tests, 114 modules.)_

---

SESSION S19 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S19` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
it DID at S18 and S16, did not at S17 or S13–S15, so assume it has and re-check
before every `gh` call. `gh pr edit` fails on this repo with a Projects-classic
GraphQL error — use `gh api -X PATCH repos/.../pulls/N`. Local `main` goes stale
every promote — `git fetch` and read `git diff origin/main..staging --stat`, never
the commit list. And: **the app container runs the built image, not the working
tree** — a new migration needs `docker compose up -d --build app`, not `restart`.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **`/promote` first.** `a3b431b`, `b536f1e`, `c21beb8` and the S18 session-end
  commit are on staging and not on `main`. Confirm the gh ACTIVE account is
  `bh3082336888-cell` immediately before the call, then back-merge and assert the
  tree is unchanged.
- **TD-005 IS TRIPPED — this is the real work of Step 0, not a checkbox.** The
  corpus was 27,475 docs at S17 end and is **31,819** now: ingest added ~4.3k
  during S18 and crossed the 30k line for the first time. Mix at S18 end: cve
  30,553 · technique 1,248 · tactic 15 · concept 3 — **no new doc_type, no
  embedding-model change**, so this is the size trigger alone.
  **Re-run the labeled retrieval battery before trusting any RAG-backed answer**,
  and re-check the per-doc_type neural floors that were calibrated at S8 on a much
  smaller corpus (`fix(kb): TD-005 resolved — per-doc_type neural floors
  calibrated on the live grown corpus`, 114b5e2). What matters is whether recall
  and the honest-miss behaviour still hold at 1.16× the corpus the floors were
  fitted to — a floor that was right at 27k and lets noise through at 32k is
  exactly the failure TD-005 exists to catch. Record the result either way;
  "still good" measured is a finding, "still good" assumed is not.
  (`curl -s "localhost:9200/_cat/indices/auspex-knowledge?v"`.)
- **Fresh-eyes review of the S18 commits** — scope: `a3b431b` (the Step-0 contract
  fixes), `c21beb8` (`auspex/actions/{proposal,settlement,builtin}.py`,
  `auspex/routes/proposals.py`, the loop round-trip), plus `b536f1e` for what was
  claimed. Angles S18 did NOT test:
  - **(the fingerprint's blind spot — strongest lead) `canonical_spec` is a
    hand-written field list.** Its own comment says a new `ActionSpec` field "must
    be considered here on purpose" — and NOTHING enforces that. Add a field to
    `ActionSpec`, confirm the fingerprint does not change, and decide whether a
    structural check (dataclass field set vs canonical key set, asserted in a
    test) belongs here. Related: `FINGERPRINT_VERSION` exists and has never been
    bumped — work out what actually happens to approved-but-unexecuted proposals
    when it is, because today the answer is "they all refuse with spec_changed",
    which may be right but is undocumented and untested.
  - **(the status machine has no reaper) `executing` and `undoing` are claims with
    no timeout.** A process that dies between the claim and the handler leaves a
    row stuck forever: it can never be executed, undone or rejected, and nothing
    reaps it. Kill the app mid-execution and see exactly what the approvals
    surface then says about that proposal.
  - **(partial effects) `execute` marks `failed` and re-raises**, but whether the
    note was written depends on WHERE it raised. TD-025 names idempotency and
    partial effects as unwritten. Force a failure after the INSERT and establish
    what state the world is in — and whether `undo` can still clean up (it is
    keyed on `proposal_id`, so it might; verify rather than assume).
  - **(the stream) tenancy and the reconnect path.** `stream()` closes over
    `auth.workspace_id` at connect time — prove a second workspace's proposals can
    never appear in it. And nothing in the repo consumes this stream yet, so the
    `{"reconnect": ...}` frame at `STREAM_MAX_TICKS` has never been driven by a
    real client.
  - **(the round-trip's honesty) a model that calls one action twice in a turn**
    files two proposals for the same thing, and nothing dedupes. Decide whether
    that is correct (two intents) or a defect (one intent, double-charged to a
    human's attention).
  Verify findings BY EXECUTION before fixing; fix with regressions.

Goal (scope-locked, from ROADMAP.md S19 — Hardening, **Phase 4**):

S18 made the platform able to act. S19 makes it safe to point at the internet:
everything an untrusted string can do, and everything a workspace can spend.

1. **Input guard — injection patterns with security-content carve-outs.** The hard
   part is not the patterns, it is that Auspex's legitimate traffic IS attack text:
   an analyst pastes a phishing email containing "ignore previous instructions"
   because that is the artefact under analysis. A guard that cannot tell "content
   being analysed" from "instruction being issued" will either block the product's
   core use case or do nothing. Code-owned, per D-006 — not a prompt asking the
   model to be careful. The S13 paste boundary and `auspex/untrusted.py` are the
   existing seams; extend them rather than adding a second vocabulary.
2. **Rate limits.** Per-workspace, and the one that actually matters is **TD-018:
   there is no bound on the NUMBER of inference calls a workspace can cause** —
   the roadmap has said S19 owns this since S14. A loop that fans out is a bill.
3. **Usage-based plan gating skeleton.** Skeleton, not billing: the seam where a
   workspace's plan decides what it may spend, with the counters that make it
   enforceable later. Do NOT build billing (explicitly deferred).

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic.
- **The guard's carve-outs need real fixtures, not invented ones.** Use the
  phishing corpora already in the repo (S11 fixtures) and the ACH/alert paste
  paths — a carve-out justified by a hand-written example is a carve-out nobody
  has tested against the actual product.
- Rate limits must degrade honestly: a workspace at its ceiling gets a clear,
  analyst-calm refusal that says what limit was hit and when it resets. Never a
  silent truncation, and never a generic 500 (the S16/S17 lesson about surfaces
  that cannot tell absence from failure).
- The dark-first brand palette is locked (CLAUDE.md Brand, D-002) — Night
  `#0A0D12`, Aurora `#4FF2C0`, Signal `#FFB454`, Ember `#FF5D5D`, Slate `#8B93A7`.
  Space Grotesk / Inter / JetBrains Mono. Never leak the underlying model or
  provider name into user-visible strings.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth. (S14–S18 each
  added zero; rate limits and plan gating will probably break that streak — that
  is fine, just do it at birth.)
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly if you forget — do
  not work around it. (114 modules now.)
- Plan assertions must VACUUM first, and only at sizes where a scan would cost
  something. **Delete seeded probe workspaces before running the suite.**
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 12× now); TD-012 (post-hoc
  validation); TD-014 (unbounded history); TD-015 (brand/confusable coverage);
  TD-016 (ACH surface bounds); TD-017 (chat-side NUL hardening); TD-019
  (retro-hunt v1 bounds); TD-020 (watcher v1 bounds); TD-021 (timeline v1 bounds);
  TD-022 (durable checker heartbeat); TD-023 (remaining items: grant-checked
  scope, array params); **TD-024 (the decay-read crossover — a costed, measured
  fix is written down and deliberately not taken; do not pick it up casually, and
  if you do, it needs the mis-ordering test described there)**; TD-025 (approval
  flow v1 bounds — the proposal TTL is the cheapest and most misleading one);
  model-PROPOSED hypotheses/evidence and model-PROPOSED falsifiers (D-019-later,
  D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
  Tired human = short session; rituals anyway.
- End with `/session-end`; S19 done = a pasted phishing email containing
  instruction-shaped text is still analysed correctly while an actual injection
  attempt against the platform is refused in CODE, a workspace cannot cause
  unbounded inference calls, and a plan ceiling is enforceable rather than merely
  recorded.
