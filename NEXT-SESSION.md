# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**S26 resumes in a fresh window after a detour that replaced the dev LLM.**
S26 Step 0 ran on 2026-08-16 (1 defect fixed, the anti-drift pin strengthened);
the session then stopped mid goal-item-1 for eight weeks. On 2026-10-10 Scout's
Northflank host was **NXDOMAIN**, and the day went to replacing it:
**D-033** (`LLM_BASE_URL` is the provider's documented API root; thinking read
as `reasoning` OR `reasoning_content`), **D-034** (dev LLM = **glm-4.5-air on
Z.ai's general pay-as-you-go API** — 95–97.5 % loop completion, the best any dev
endpoint has posted), **D-035** (the default endpoint's scorecard is the
deployment's — the chat route finally finds it), **D-036** (a two-pass turn whose
endpoint thinks becomes a native turn). Three adversarial review workflows (33
agents) went over the code; every finding was fixed or recorded. **Promote #27
merged it all** (`8631307`, back-merged `856c1da`). 1109 tests, 119 modules.
**Goal item 1 — the routing decision — has not moved since 2026-08-16, and every
measurement it had was taken on a model that no longer exists.**)_

---

SESSION S26 of Auspex (resumed). Working dir must be /home/burhan/auspex-new — run
`/session-start S26` first (full ritual). Primary dev LLM is **glm-4.5-air on
Z.ai's general API (D-034)** — `LLM_BASE_URL=https://api.z.ai/api/paas/v4`, key in
`.env` as `LLM_API_KEY` (and `GLM_API_KEY`). Local Ollama `qwen3:14b` is the
secondary/offline endpoint (D-013), root now **`http://localhost:11434/v1`**
(D-033), and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
**it had flipped at the 2026-10-10 promote** (also S18, S16; not S17, S13–S15,
S19–S25), so assume it has and re-check before every `gh` call; `gh auth switch
--hostname github.com --user bh3082336888-cell` fixes it. `gh pr edit` fails on
this repo with a Projects-classic GraphQL error — use `gh api -X PATCH
repos/.../pulls/N`. **`gh pr merge --squash` printed nothing on success at S24,
S25 and #27** — verify with `gh pr view <n> --json state,mergeCommit`. Local
`main` goes stale every promote — `git fetch` and read `git diff
origin/main..staging --stat`, **never the commit list**. The app container runs
the built image — live verification needs `docker compose up -d --build app`.
**Run the suite the way `ci.sh` does** (`.venv`, package installed editable), and
**never pipe `./ci.sh` into `tail`** — the pipeline reports `tail`'s exit code.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **Nothing to promote** — #27 emptied the slate. Confirm with `git fetch origin &&
  git diff origin/main..staging --stat` (expect empty or only session commits).
- **Two untracked items predate this work and need Burhan's call, not yours:**
  `Auspex-Product-Architecture-Overview.pdf` and `docs/auspex-overview.html`
  (dated 2026-09-08, not from any session record). Ask once: commit, move, or
  delete. Do not publish or commit them unasked.
- **No fresh-eyes review is owed** for the 2026-10-10 commits — each change was
  reviewed adversarially by a 10–12-agent workflow the same day and every real
  finding was fixed with a mutant-proven regression. One latent item was
  recorded and deliberately NOT fixed: in `auspex/routes/chat.py` the `aclosing`
  closes now run inside the `try/except LLMError` whose handler yields, so a
  future client whose CLOSE raises `LLMError` could mask a leak report. The
  shipped client cannot (httpx close errors are not mapped). Leave it unless you
  touch that client.

Goal — **wire the agent path into `/api/chat` (D-031).** The design (S23), the
tools (S24), the tools as prompts (S25) and the streaming mechanism (S25) exist.
**What is left is the route.**

1. **Re-measure the routing question on glm-4.5-air FIRST — the old evidence is
   for a dead model.** Three probes sit UNCOMMITTED in `docs/probes/s26-step0/`,
   all written against Scout on 2026-08-16:
   - `probe_refusal_cause.py` — the 2×2 (S25 system message vs the loop's; tools
     on vs off). On Scout it got **0 refusals in 12** through `run_stream` with
     the loop's own message — S25's "Scout refuses" may never have held under the
     route's real conditions.
   - `probe_s25_refusal_replay.py` — S25's exact cell ×6. Never confirmed run.
   - `probe_routing.py` — the proposed rule: **agent path iff mode is not
     ALERT_TRIAGE / PHISHING_ANALYSIS AND the classifier found an observable the
     tools can act on**, plus the first MULTI-STEP measurement (does the model
     chain tools and stop when it has enough?).
   Re-run all three on glm-4.5-air (they read `.env`; check each still builds its
   client from settings, and that probe_routing's devhost/KB/enrichment pins still
   apply), save a probe record, THEN decide the rule. Commit the probes with it.
2. **The wiring:** consume `run_stream`; map its events onto the SSE protocol;
   narrate `tool` events; build the leak index from
   **`loop.system_message(loop.wire_specs())`** (D-031 decision 5); leave tool
   results **unindexed** and scan them on **one literal channel**; pass a `claim`
   that calls `UsageLimiter` per call (TD-018 — **TD-035 dissolves the moment it
   moves**); persist the `done` event's `text` as the assistant turn.
   **AND implement the TD-036 buffer — it is no longer optional.** On Z.ai prose
   precedes tool calls on four of five models, and the measurement TD-036 said
   was owed is taken (probe record 2026-10-10, Finding 9): reasoning, then ONE
   sentence of narration in content, then the whole tool call in one delta. Hold
   content deltas until the step is known tool-free (`finish_reason`), release or
   drop. Both TD-036 consequences apply: ordering, and `done.text` holding only
   the last call's content.
3. ~~Check which path actually runs~~ — **answered**: dev's default endpoint has a
   deployment-scoped scorecard (D-035, row `a8113b41…`) and runs NATIVE; an
   unprobed thinking endpoint switches to native from pass 1 (D-036). The agent
   path must make the same choice deliberately — it has no two-pass.
4. **TD-028 (b/c/d) + TD-034 together.**
5. **TD-012(b)** — contract-conformance repair, the original S9 entry.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic.
- **Inference now costs real money.** Z.ai is pay-as-you-go (glm-4.5-air
  $0.20/$1.10 per 1M tokens; thinking is ON by default and billed inside
  `completion_tokens`). Budget probes; a full 40-task harness run is ~5–6 min.
- **General endpoint only, pay-as-you-go only, dev only.** Never
  `api/coding/paas/v4` (Coding Plan terms forbid app use). Z.ai processes in
  Singapore — **no KSA-tenant data, ever** (org policy).
- **Do not run pytest while running live `/api/chat` probes.** The suite's
  teardown purges the shared `analyst@auspex.dev` user; a live turn in flight
  dies on a foreign-key violation at persistence (measured 2026-10-10).
- **Re-probe after any LLM_MODEL / LLM_BASE_URL change:** the deployment
  scorecard is per fingerprint (D-035). Host-side harness runs against local
  Ollama need `--deployment-base-url http://host.docker.internal:11434/v1`.
- **The tool-results scanner channel must be ONE LITERAL, not one per call.**
- **`prompted_tools` is deliberately unmeasured** — probe it before wiring it to
  a streaming surface.
- **Any new test that spends inference calls must refund them.**
  test_agent_stream.py is fakes only — keep it that way.
- **Do NOT re-open the guard regex.** TD-031/032/033 are ratified.
- **`SHINGLE_WORDS` is a calibrated number** — re-run
  `docs/probes/s22-outguard/probe_calibrate2.py` before touching it. It was
  calibrated on Scout/qwen output; native GLM thinking now streams through the
  reasoning channel (no trip in six live native turns — not a calibration).
- **Two sessions found a defect in the output rail (S23, S24); S26's switch
  added a new branch to it and its review drove every exit.** Assume another
  exists — the route wiring runs straight through it.
- **Reuse caps, never re-declare them.**
- **The CI gate is real (D-028)** — `.github/workflows/ci.yml` runs `./ci.sh` only.
- **The README is a promise** pinned by `tests/test_docs.py` — **including its
  test count**, which must equal the collected count on a full run. Every
  test-adding commit updates it.
- **`./scripts/demo.sh` must keep running end to end.**
- **Any new assertion over an EXTRACTED set needs a floor.**
- DECISIONS.md entries are immutable once ratified; overturning one is a NEW
  numbered decision naming which it supersedes. D-032…D-036 are ratified.
- Brand is locked (D-002). **Never leak the underlying model or provider name**
  into user-visible strings — now including "glm", "zhipu", "z.ai" (they are in
  `FORBIDDEN_ENGINE_NAMES`). A thinking model may name itself in its reasoning,
  and the Thinking pane is user-visible — no guard exists for that (D-030 checks
  for OUR configuration, not the model's name). Recorded, not owned yet.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth. S26 added
  one (`GLM_API_KEY`, Burhan's). A tunable that belongs to us is a code constant
  (D-026).
- New package directory? → `pyproject.toml` packages AND the Dockerfile skeleton
  (**119 modules**).
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 19×); TD-014; TD-015; TD-016;
  TD-017; TD-019; TD-020; TD-021; TD-022; TD-023; TD-024; TD-025; **TD-027 (HARD
  GATE)**; TD-029; TD-030; TD-031/032/033; **TD-037 (LOW — probing the customer's
  endpoint unasked is D-005's call)**; the card stream emitting status changes;
  model-PROPOSED hypotheses/evidence and falsifiers (D-019-later, D-021); the
  model fabricating incident specifics the contract validator passes (probe
  record 2026-10-10, observed on every run).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
  Tired human = short session; rituals anyway.
- End with `/session-end`.
