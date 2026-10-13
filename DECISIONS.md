# Decisions — ratified, dated, one entry each

Re-debating a ratified entry requires explicitly overturning it here with a new
entry that references the old one.

**D-001 (2026-07-14) — Storage split: OpenSearch for search, Postgres for truth.**
Burhan proposed all-OpenSearch (drop Postgres). Overruled by Claude with
rationale, Burhan delegated the call: OpenSearch has no ACID transactions, no
atomic claim-first UPDATE (needed for approval settlement), ~1s refresh lag
breaks read-after-write chat flows, and doc updates are full reindexes.
Postgres = users/workspaces/sessions/messages/verdict-records/approvals/jobs.
OpenSearch = KB chunks, observables search, telemetry. Postgres is one
docker-compose service; operational cost ≈ zero.

**D-002 (2026-07-14) — Name & brand: Auspex.** Latin for the diviner who read
the future from bird flight — watching signals, prediction, the flock (ties to
the herd-immunity flagship). Tagline "The flock sees first." Palette + fonts in
CLAUDE.md. Chosen over Murmur (MurmurHash + Mumble-server collisions), bird
names (Falcon/Raven/Flock/Hive all taken in security), Quorum (Quorum Cyber
exists).

**D-003 (2026-07-14) — Docker-first.** Everything runs via docker-compose from
S1. `docker compose up` green = session may end.

**D-004 (2026-07-14) — ~~Shared OpenSearch cluster, strict prefix isolation.~~**
OVERTURNED same day by D-009.

**D-009 (2026-07-14) — Own OpenSearch, never SARA's.** Burhan's call: the shared
DO cluster is SARA's production telemetry and was probed read-only for schema
conventions ONLY (docs/probes/2026-07-14-opensearch-cluster.md stays as
reference). Auspex runs its own `opensearchproject/opensearch:2.19.x` container
in docker-compose (version-matched to the probe so behavior transfers). SARA's
cluster creds must not appear in Auspex runtime config. Managed/dedicated
cluster when we deploy beyond local.

**D-005 (2026-07-14) — Customer-supplied LLM, capability-negotiated runtime.**
No platform-paid inference. Every endpoint is probed at connect time; the agent
runtime compiles to the scorecard (native tools → prompted tools → plan-only).
Dev endpoint: Northflank vLLM (currently unauthenticated — accepted for testing
only, D-006).

**D-006 (2026-07-14) — Northflank endpoint stays keyless during testing.**
Burhan's call. Revisit before anything public.

**D-007 (2026-07-14) — Scope discipline for v1.** 6 response modes, ~4 analysis
agents, no billing, no i18n, no admin console until Phase 4. SARA's 16-mode/
16-agent surface is the cautionary tale, not the target.

**D-010 (2026-07-14) — Branch model: staging → main via /promote only.**
All session work lands on `staging`. `main` is only ever updated by the
`/promote` command (full checks fresh, PR when a remote exists, guarded
`--no-ff` merge before that). `main` = always-demoable; never commit to it
directly after S0. Custom commands live in `.claude/commands/`.

**D-011 (2026-07-14) — Personal GitHub identity only.** Auspex is Burhan's
personal project. Commits: `bh3082336888-cell
<bh3082336888-cell@users.noreply.github.com>` (set as repo-local git config;
the 3 pre-decision commits were rewritten before any push). Git transport: SSH
alias `github-personal` (~/.ssh/config → `~/.ssh/personal_git` key); remote
URLs use `git@github-personal:bh3082336888-cell/<repo>.git`. `gh` CLI: active
account must be `bh3082336888-cell` for this repo (`gh auth switch`); one-time
interactive `gh auth login` (SSH + personal_git) required before first PR.
Work identity (SIRP-Burhan / burhan@sirp.io) never touches this repo.
Session-start and /promote enforce this.

**D-008 (2026-07-14) — Workspace isolation from day one.** `workspace_id` on
every table and every index mapping, even while single-tenant. Retrofitting
tenancy is how SARA earned nine Tier-0 invariants the hard way.

**D-012 (2026-07-15) — Interim dev LLM = local Ollama while Northflank is down.**
Burhan's call (Northflank service down for days, restart is a human step).
Dev endpoint until then: local Ollama (`http://localhost:11434`, OpenAI-compat
`/v1`), model `llama3.1:8b` — closest same-family tool-capable fit for 12 GB
VRAM; free, keyless, no cloud signup. Purpose: unblock the S2 second half
(client-vs-snapshot, battery, harness). **The Llama-4-Scout go/no-go numbers
are still owed** — re-run battery + harness against the Northflank endpoint
when it returns; scorecards are keyed per endpoint fingerprint, so both
coexist. Live calls still probe/harness-only from the HOST (the compose app
can't reach localhost:11434 without host-gateway wiring — S3 concern, noted).

**D-012 addendum (2026-07-15).** Interim dev model bumped `llama3.1:8b` →
`qwen3:14b` after the S2 harness comparison (52.5 % vs 87.5 % loop completion,
native_tools verdict; docs/probes/2026-07-15-ollama-endpoint.md). 8B stays
pulled as the "weak endpoint" test case for the scorecard-driven mode ladder.

**D-013 (2026-07-15) — qwen3:14b is the primary dev LLM; Northflank demoted to backup.**
Burhan's call after the S2 comparison (100 % valid calls, 87.5 % loop
completion, native_tools verdict vs 8B's 52.5 %/prompted_tools — see
docs/probes/2026-07-15-ollama-endpoint.md). All building from S3 onward
targets local Ollama + qwen3:14b. The Northflank vLLM (Llama-4-Scout) is a
BACKUP/validation endpoint: when Burhan signals it's back up, re-run
`scripts/llm_harness.py` against it for a second scorecard row — its numbers
validate the capability-negotiated runtime against a second real endpoint,
they no longer gate anything. Product framing unchanged (D-005): customers
bring their own endpoint; the runtime compiles to the per-endpoint scorecard.

**D-014 (2026-07-15) — Writes gate on actual execution, never on model claims.**
Ratified from S2 harness evidence (docs/probes/2026-07-15-ollama-endpoint.md:
the 8B model fabricated "ticket created" claims 3 times without calling the
tool). Invariant: a write/destructive action counts as performed ONLY when its
tool call actually executed and returned a result — model-asserted completion
text ("ticket created", "action done", a made-up ID) is never treated as
execution, never persisted as an action record, never shown to a user as a
completed action. Enforced in code (permission gate, S3+), not prompts
(ADR 0006), with a pinned regression fixture using the exact fabricated
string from the harness run shipping alongside the first gate code.
Applies to every future action surface (S17 Actions SDK, S18 approvals).

**D-015 (2026-07-16) — Primary dev LLM switched to Llama-4-Scout (Northflank);
qwen3:14b demoted to secondary/offline.** Supersedes D-013's primary/backup
assignment (D-013's evidence + framing otherwise stand). Burhan's call: with
Northflank restored and Scout re-measured `native_tools` (100 % valid / 77.5 %
completion / ~90 tok/s, row `153e221a-…`), Scout is the primary dev endpoint —
it also matches CLAUDE.md's original stack (dev = Northflank vLLM Scout) and is
a second *real* endpoint for exercising the capability-negotiated runtime.
`.env` (gitignored) now points at Scout; the local Ollama `qwen3:14b` stays
pulled as the SECONDARY/offline endpoint (flip the commented block in `.env`).
Consequences: the LLM endpoint is now a public URL that resolves identically
from host and container, so `auspex.devhost` no longer pins `LLM_BASE_URL`
(.env is the single source of truth; DB/OpenSearch pins remain). The
session-start local-Ollama gate now validates the *secondary*. Product framing
unchanged (D-005): customers still bring their own endpoint.

**D-016 (2026-07-16) — Reasoning UX: universal two-pass fallback (customer-facing)
+ internal-only model switcher.** Two parts:
(1) *Universal reasoning (all environments, customer-facing).* A visible
"thinking" trace is a product selling point, produced by the platform itself
regardless of the endpoint. If the resolved endpoint emits native `reasoning`
(measured — new `native_reasoning` scorecard field, set from the basic probe) it
is streamed; otherwise a **two-pass** fallback runs — pass 1 a brief analyst
reasoning streamed to the Thinking pane, pass 2 the answer. Presented as the
platform reasoning; never names the model, never says "unsupported". Both passes
use the customer's own endpoint, so **D-005 holds** (we never pay for inference).
Safe default is two-pass (correct for any endpoint). Prompt shape probe-verified
on real Scout (docs/probes/2026-07-16-two-pass-scout.md). Reasoning stays
ephemeral (never persisted).
(2) *Model switcher is INTERNAL/dev-only.* Per the standing org policy that
multi-LLM / bring-your-own-LLM is internal infrastructure — not a marketed
customer feature — the switcher (`/api/models` + `endpoint_id` + dev-endpoint
registry) is honored only when `APP_ENV=dev`: `/api/models` 404s in prod,
`endpoint_id` is ignored in prod, the registry is `{}` in prod. This org policy
overrides the user's request to expose it to customers; it is distinct from
D-005 (which the user waived). Registry keys are referenced by env-var name,
never inlined and never sent to the browser; UI labels are brand-safe.

**D-017 (2026-07-16) — Verdict decay-curve semantics (first Living Verdicts
brick).** Every `verdicts` row carries, from day one: `label`
(malicious|suspicious|benign|unknown — closed set, DB CHECK),
`confidence_at_write` ∈ [0,1], `half_life_days` > 0, `floor` ∈
[0, confidence_at_write], `source` (writer identity, e.g.
`enrichment:OTX,ThreatFox`), `created_at`. Semantics:
- **Effective confidence at time t** = `floor + (confidence_at_write − floor)
  · 2^(−(t − created_at)/half_life_days)` — executable in
  `auspex/enrich/verdict.py::effective_confidence` (pinned by test), not just
  prose.
- **Decay never flips a label.** A decayed MALICIOUS renders as *stale*
  malicious (Slate in the D-002 palette), it does not become benign — new
  evidence, not the calendar, changes labels.
- **Append-only.** Re-enrichment writes a new row; the current verdict is the
  latest by `created_at`. The history is the substrate for S7 retro-hunts and
  falsification watchers — never UPDATE/DELETE verdict rows.
- **Default half-lives follow observable churn:** IPs 14 d (reassigned in
  days), domains/URLs/emails 30 d, hashes 365 d (a hash IS the artifact —
  its *relevance* decays, its maliciousness doesn't), CVE 365 d (future-proof;
  no CVE provider until S6+).
- **Floor is 0.0 for S5 enrichment writes.** S7 introduces raised floors
  (e.g. defanged-in-input ⇒ SUSPICIOUS floor — `Observable.defanged` already
  carries the signal).
- **v1 combining rule (provisional):** worst credible label wins; confidence =
  strongest signal of the winning label. Cross-provider agreement boosting and
  per-provider trust weights are parked in IDEAS.md, not silently improvised.

**D-018 (2026-07-17) — Embeddings are server-side: OpenSearch ML plugin,
all-MiniLM-L6-v2 v1.0.2, ONNX format (measured, resolves the S2 blocker).**
Probe: docs/probes/2026-07-17-opensearch-knn-ml.md. The pretrained
`huggingface/sentence-transformers/all-MiniLM-L6-v2` deployed on OUR
2.19.4 container answers in 25–30 ms warm (single text), ~8 ms/text
amortized at batch-16, dim 384, +0.5 GiB container RSS, 609 MB disk —
against a fallback (in-process sentence-transformers) that would add
~2.8 GB of wheels to an app image that has no torch, plus a second
RAM-resident model copy. **Format is pinned ONNX** — TORCH_SCRIPT of the
same model FAILS to deploy on 2.19.4 (`aten::scaled_dot_product_attention`
unknown to the bundled DJL engine). Consequences:
- Bootstrap code (idempotent, at service init) owns: cluster setting
  `plugins.ml_commons.only_run_on_ml_node=false`, model register+deploy
  when absent, `auspex-knowledge` index creation. A fresh volume re-runs
  all three; first boot needs outbound HTTPS to artifacts.opensearch.org
  (air-gapped path parked in IDEAS.md).
- `model_id` is volume-specific → always resolved by model name at
  startup, cached on app.state, never hardcoded/persisted in config.
- Model missing/undeployed at query time (404 "Failed to find model") →
  KB deferred copy (S5 breaker pattern); auto-redeploy after container
  restart is measured-good so this is a cold-volume/first-boot path.
- The in-process fallback stays a documented option, NOT a dependency:
  latency was deliberately not measured because footprint alone
  disqualifies it while the primary works. Revisit only if a customer
  cluster bans the ML plugin (that day: probe first).

**D-019 (2026-08-08) — ACH v1 shape: the matrix is code, the vocabularies are
closed, the tables are tested constants.** Probe:
docs/probes/2026-08-08-sara-ach-analogues.md (SARA has NO ACH engine — its
prompt-only version is structurally discarded by its own output template; the
patterns we adopt are its closed-vocab falsification guards and doctrine
tables). Ratified for S12 and binding on S13+ (evidence graph builds on this):
- **The ACH core is deterministic code, zero-LLM** (ADR 0006): hypothesis
  seeding, per-evidence cell vectors, matrix scoring, elimination, and
  next-lookup selection are pure functions over typed frozen dataclasses,
  pinned by fixture tests. The model may later PROPOSE hypotheses or evidence
  through a contract; it never decides a cell, a weight, a status, or the next
  lookup.
- **Closed vocabularies:** hypothesis keys (`true_positive`, `false_positive`,
  `benign_activity`, `test_activity`) and evidence kinds are StrEnums; cell
  tables (evidence kind → per-hypothesis −2..+2 or None) and outcome-likelihood
  tables (P(outcome|hypothesis) per lookup kind) are CODE constants extended
  via PR with a fixture test per row — the SARA doctrine-table pattern, never
  env vars, never model output.
- **Heuer-faithful scoring:** hypotheses are ranked by LEAST weighted
  inconsistency (consistency counts are display/tiebreak only — confirmation
  is cheap, disconfirmation is diagnostic); a cell of None means evidence
  UNAVAILABLE and is excluded from scoring (the absence-is-not-evidence
  doctrine already in enrich/types.py:8-11). Plausibility weights for the
  info-gain math derive as 2^(−inconsistency/half_life) — the D-017 decay
  idiom — and are documented as plausibility weights, NOT probabilities.
- **Honest rails (the S10/S11 philosophy):** zero evidence → all hypotheses
  surviving, no ranking claimed; zero DIAGNOSTIC evidence (identical cells
  across survivors) → no ranking claimed, named reason; a hypothesis is
  REJECTED only on sufficient weighted inconsistency including at least one
  high-credibility contradiction, with the reason stored.
- **Investigations live in Postgres** (not in-session): `investigations` +
  `hypotheses` + `ach_evidence` tables, workspace-scoped (D-008), following
  the SCHEMA_V0 idempotent path. In-session-only state would ride the
  unbounded fenced history (TD-014) and die with the chat; S13's evidence
  graph needs durable typed evidence rows anyway.
- **Surface v1 is a zero-LLM REST resource** (`/api/investigations`), not a
  seventh mode: ACH is a reasoning structure the analyst drives, not a render
  format for one turn (the NEXT-SESSION.md warning made this a decision, not
  a default). A model-rendered hypothesis summary through a contract is
  expected later; when added it follows the S10/S11 directive+pin pattern and
  must be live-verified.

**D-020 (2026-08-09) — Retro-hunt v1: a match is a reason to re-examine, the
sweep is a bounded indexed join, a flip is its own typed row.** Probe:
docs/probes/2026-08-09-s14-retrohunt-explain.md (query plans measured, not
assumed). Ratified for S14, binding on S15 (falsification watchers read this
trail):
- **A retro-hunt match NEVER changes a verdict.** `record_matches` contains no
  verdict write at all — the rail is structural, not a rule someone has to
  remember. If a sweep could flip a label, CISA's publishing schedule would be
  changing verdicts instead of evidence, which inverts D-017's "new evidence,
  not the calendar, changes labels". A match records the label as it stood AT
  MATCH TIME and stops; the API says `action: "re-examine"` in the payload.
- **Analyst acknowledgement is explicit,** including after a flip. A flip is the
  strongest sign the match was worth raising, so auto-closing it would hide the
  event exactly when it mattered most (the approvals-table precedent).
- **Trigger kinds are a closed set** (`kev-added`, `deleted`), not every
  DocChange. The NVD delta feed upserts ~770 docs/day and a re-scored CVSS
  vector is not news about an observable; a surface that cries wolf trains the
  analyst to ignore the one signal meant to be trusted. Extended via PR with a
  test, the doctrine-table pattern (D-019).
- **The sweep is ONE indexed join per batch, bounded by SWEEP_CHUNK, and the
  bound is chosen from a measured plan crossover** — not from taste. Feeds are
  platform-global, so the join runs across workspaces on `(type, value)` and
  each hit carries its own `workspace_id` into the row it writes; tenancy lives
  in the write and in every read (D-008), never in the sweep.
- **A verdict LABEL CHANGE is a first-class row** (`verdict_flips`), written
  inside the enrichment transaction by the only code that writes verdicts.
  `verdicts` records what was believed; it takes a diff of adjacent rows to see
  that belief changed, and neither an analyst nor a watcher should have to do
  that. `trigger` names why the re-look happened and `match_id` links the intel
  that prompted it. A first-ever verdict is NOT a flip — no previous belief
  existed to change, and that distinction is what makes the surface readable.
- **Ingest owns the trigger; there is no "run a hunt" endpoint.** A retro-hunt
  is something new intel does to you. The S7 `NullSink` seam is where it
  attaches, and ingest code was not modified to attach it.

**D-021 (2026-08-09) — Falsification watchers v1: typed conditions registered at
write time, evaluated by code, and a satisfied watcher upgrades an event rather
than changing a label.** Probes: docs/probes/2026-08-09-s15-watchers-explain.md
(plans measured across table sizes AND across the open/closed mix),
docs/probes/2026-08-09-s15-watchers-live.md. Ratified for S15, binding on S16
(the verdict timeline UI reads these rows):
- **A verdict registers what would falsify it AT WRITE TIME,** in the same
  transaction that writes the verdict. Asked later, the answer is
  rationalisation — you already know what happened. A verdict whose transaction
  committed without its conditions would be a claim with no way to be wrong,
  which is the thing this feature exists to prevent.
- **The vocabulary is a closed enum, never prose.** `kev_listing`,
  `record_withdrawn`, `provider_escalation`. A free-text falsifier ("watch for
  registrar changes") is a wish; a typed kind plus params is something code can
  evaluate against a feed. This is D-007 "specs over prompts" turned on our own
  reasoning rather than the model's. Extended via PR with a test, the
  doctrine-table pattern (D-019).
- **Every kind must have a checker, and the partition is asserted.**
  `CHECKED_ON_INGEST` and `CHECKED_ON_ENRICHMENT` split the enum with a test
  that the split is total and disjoint. A registered watcher nobody evaluates is
  WORSE than no watcher, because it reads as coverage.
- **Conditions are DERIVED IN CODE from the observable, label and signals** —
  never proposed by a model. Model-proposed falsifiers stay parked
  (D-019-later); if they ever land they come through a contract and are marked
  as proposed, because a falsifier the platform invented and cannot check is
  the most confident-sounding lie available to it.
- **Empty is a legitimate answer and is never padded.** A `malicious` CVE
  registers no `kev_listing` watcher: KEV agrees with that verdict. Manufacturing
  one would claim a self-check the platform does not perform.
- **A satisfied watcher NEVER writes a verdict** — D-020's rail, and it binds
  harder here: a fired watcher is the platform's own prediction coming true,
  which is precisely when skipping the analyst would feel safest. It UPGRADES
  the S14 re-open event for the same doc (`falsifies` on the existing payload)
  instead of minting a second notification, and it is acknowledged through that
  one event. Two inboxes for one fact means two half-read inboxes.
- **Claims belong to a verdict; a newer verdict supersedes them, never deletes
  them.** "We were watching for this and stopped" is how a dropped question is
  found. Supersession is scoped to OPEN watchers, so a claim that was
  contradicted survives the verdict that replaced it.
- **The ingest check is an indexed join per bounded chunk, and the watcher index
  is PARTIAL on `status='open'`** — satisfied and superseded rows accumulate for
  the life of a workspace and are never joined against. Measured: tripling the
  table to 75k rows with 50k closed left the check at 0.190 ms vs 0.174 ms at
  25k.
- **Watchers get their own sink, not an extension of the retro-hunt one.**
  Retro-hunt asks "does this touch anything we saw?"; a watcher asks "does this
  contradict a claim a verdict made?" Folding them together would make
  falsification coverage a silent function of `TRIGGER_KINDS`. A `FanoutSink`
  owns the isolation, so ingest still holds exactly one sink (S7's seam) and
  neither consumer can take the other down.
- **There is no endpoint to create or acknowledge a watcher.** Hand-registered
  falsifiers would make coverage a function of who was paying attention.

## D-022 — Staleness is a derived vocabulary over the D-017 curve, and decay never touches a label or a status (2026-08-10, S16)

**Context.** `effective_confidence` has been executable and pinned by a test
since S5 (D-017) and rendered by nothing since. Eleven sessions of surfaces have
shown month-old beliefs at the strength they had when written. S16 renders it,
which forces two questions S5 deferred: what counts as stale, and what a
falsification claim attached to a decayed verdict is worth (TD-020).

**Decided.**

- **Bands are measured in HALF-LIVES elapsed, never days.** `fresh` <0.5,
  `aging` 0.5–1.5, `stale` 1.5–3, `lapsed` ≥3, plus `held` for a verdict written
  with `floor >= confidence_at_write`. A 14-day IP verdict and a 365-day hash
  verdict are the same amount of stale after the same number of half-lives, and
  that is the only comparison worth showing an analyst. Days would have required
  a per-type table that drifts out of sync with `HALF_LIFE_DAYS`.
- **The edges live in exactly one module** (`auspex/timeline/staleness.py`) and
  travel to every consumer as data — the digest's crossing query takes them as a
  parameter, the payload ships the band descriptions, and the UI renders the
  server's answer. A client that recomputed staleness would be a second opinion
  about aging, and the two would diverge the first time an edge moved.
- **Nothing about decay is stored.** Every value is derived at read time from
  (confidence_at_write, floor, half_life_days, created_at), so a verdict's
  staleness cannot fall out of date with itself. A nightly job that stamped a
  band onto a row would be wrong between runs by construction.
- **Decay never changes a label.** A stale `malicious` verdict is still
  malicious; what aged is how much the platform stands behind its own
  confidence. The fix for a stale verdict is to re-enrich, never to re-label —
  the D-017/D-020 rail, applied to the one place it would have been easy to
  forget because no analyst is in the loop.
- **TD-020's answer: an open claim on a decayed verdict gets a derived
  `standing`, and `status` is left alone.** `status` answers "was this claim
  contradicted?"; `standing` answers "does the belief behind it still stand?".
  A claim guarding a stale verdict is `lapsed` — still open, still watched, and
  it will still fire. Expiring it into `status` would have been the tempting
  version and would have erased the difference between a claim nobody ever
  contradicted, one that was, and one a newer verdict superseded.
- **A quiet answer must be earned.** Every empty field in the digest is an
  absence claim, and S16 Step 0 executed what absence looked like: 50
  consecutive failed watcher checks were indistinguishable from 50 quiet ones.
  Each change consumer now counts consecutive failures (`auspex/checks.py`,
  the `enrich/breaker.py` shape minus the circuit — a failing checker should
  keep trying), and `Digest.trustworthy` requires a roster that is present AND
  healthy. An unknown roster is reported as untrustworthy rather than defaulted
  to healthy; `ever_succeeded` is reported but deliberately not required, since
  a checker only records success when a check actually ran.
- **Still no third notification shape.** The digest reuses `retrohunt_matches`,
  `verdict_flips` and `watchers` exactly as D-020 and D-021 require, and re-open
  events are still acknowledged at `POST /api/retrohunt/matches/{id}/ack`. A
  digest is the natural place to invent an inbox; it did not.

## D-023 — An action's contract is code, and destructive-without-undo is unrepresentable (2026-08-11, S17)
The first Phase 4 decision: what an Auspex action IS, before any action touches a
real system. `auspex/actions/`, ratified as built.

- **The declaration is the source of truth, and the prompt is generated from it
  (D-007).** One `@action` declaration compiles to the JSON-schema parameters on
  the wire, the planner directive, and the human-facing approval summary. This is
  the S9 `ModeContract` relationship applied to acting: we do not hand-write a
  sentence describing an action and hope it matches the code, because that pair
  drifts and the drift is invisible until an approver reads a description of
  something the action does not do.
- **Risk is not a new vocabulary — it IS `ToolLevel`.** `ActionRisk` is the same
  enum the D-014 permission gate already reads to decide allow-vs-propose. An
  action with its own notion of danger would be a second opinion about whether a
  human must approve it, which is the exact shape D-022 refuses for aging and S16
  Step 0 found in the falsifies link.
- **A destructive action with no undo cannot be CONSTRUCTED.** Not a lint rule,
  not a review checklist item, not a "respond with EXACTLY" instruction (D-006):
  `ActionSpec.__post_init__` raises, so the action is an ImportError at the
  moment someone writes it. The registry re-runs the identical validation,
  because the decorator must not be the only door. S14, S15 and S16 each spent a
  Step 0 on a rail that held only because everyone remembered it; this is what
  the lesson cost.
- **`dry_run` is required of every action, with no defaulting.** An action must be
  able to say what it WOULD do without doing it. Defaulting it for reads, or
  falling back to `execute` when absent, would turn the guarantee back into a
  convention. Also refused: a `dry_run` that IS the execute handler, and — found
  by running the contract rather than reading it — a `dry_run` that is some OTHER
  registered action's execute handler, which would really perform that action
  while reporting itself as a preview.
- **An undo declares what it CANNOT restore.** An undo that silently fails to
  restore something is worse than no undo, because the approval it unlocked was
  granted on its strength. `cannot_restore` travels in the declaration and into
  the planner text, and an action carrying one reports itself as not reversible.
  An undo that restores nothing is refused: that is a second action.
- **The planner manifest reuses the S13 capability decision.** `native_tools` →
  wire specs; `prompted_tools` → the same specs compiled to prose; `plan_only` →
  names and one-liners, nothing on the wire. The modes differ in how an action is
  DESCRIBED, never in whether approval is required. An endpoint that cannot be
  trusted with a tools array is not handed one, so a model that cannot call an
  action cannot believe it did.
- **S17 tells the loop about actions and gives it no way to call them.** An
  action's dispatch is the proposal round-trip S18 owns. Offering a callable name
  that resolves to `unknown tool` would invite the model to believe it acted, so
  the manifest reaches the system prompt while the wire array stays the
  ToolRegistry's. Revisit in S18, not before.
- **An empty action surface says so.** The same rule as an empty digest (D-022):
  "no actions are available" is a claim, and it is stated rather than left as
  silence the model fills in.

## D-024 — An approval is a decision about one declaration, claimed once (2026-08-15, S18)
The second Phase 4 decision, and the one that makes S17's contract load-bearing:
`auspex/actions/{proposal,settlement,builtin}.py` + `auspex/routes/proposals.py`,
ratified as built. D-023 said what an action IS; this says what a decision about
one is worth, and for how long.

- **Settlement is a claim, not a check.** One
  `UPDATE ... WHERE status='pending_approval' RETURNING` moves the row out of
  pending in the same statement that reads it, so a second approver's UPDATE
  matches zero rows and is told so. A read-then-write, an advisory lock, or a
  `SELECT ... FOR UPDATE` would all "work"; every one of them is a wider window,
  and D-001 put truth in Postgres precisely so this could be one statement. The
  same device claims the execution and the undo — "ran twice" is impossible for
  the reason "approved twice" is. Verified by racing eight distinct backends at a
  barrier, asserting the backend count as well as the winner count.
- **The card is compiled from the spec and then FROZEN.** Every field an approver
  reads comes from the declaration (D-007) or from the action's own `dry_run`
  against the real arguments — never from model prose. It is stored on the
  proposal row rather than re-rendered on read: re-deriving it later would show
  today's declaration for yesterday's decision, and an audit trail that silently
  updates itself is worse than not having one.
- **An approval does not survive a change to what was approved.** A spec
  fingerprint — a canonical hash of the declared facts a decision rests on: name,
  description, risk, scope, params, and what the undo does and does not restore —
  is stamped on the proposal and re-checked before execution, alongside a re-run
  of the D-014 gate on today's risk. An action approved an hour ago must not run
  against a declaration that changed under it. Handler identity is deliberately
  NOT part of it: function objects differ across processes, so hashing them would
  make the check fail for the wrong reason and mean nothing when it passed.
- **What the fingerprint cannot see is stated, not implied.** It cannot detect a
  changed handler BODY behind identical declared facts. That is deploy integrity,
  a different problem with a different solution, and claiming otherwise would make
  the rail look stronger than it is.
- **The platform executes only systems it owns.** `EXECUTABLE_SYSTEMS` is a code
  allow-list (today: `auspex`). A third-party action may be declared, proposed,
  approved and rendered, and will refuse to run — because a real external side
  effect needs a real credential and a real blast radius, which is not something
  to acquire as a side effect of the session that builds the approval flow.
  Widening the set is a code change and a review, never config.
- **Calling an action files a proposal — this is D-023's deferred half, resolved.**
  Actions are now on the wire, and only when a proposer is wired in: a callable
  name with nothing behind it is the failure S17 refused to ship. The result the
  model gets back is a proposal id, never an outcome, and it is told plainly that
  nothing was performed.
- **A refused execution is not a failed approval.** Winning the claim and then
  failing the re-check returns 200 with `executed: false` and the machine reason.
  The decision stands; the action did not run; an error status there would read as
  "your approval failed" and invite a retry that must not happen.

## D-025 — The guard asks whether an instruction is being ISSUED, not whether one is present (2026-08-15, S19)
The first Hardening decision, and the one that shapes every input rail after it:
`auspex/guard.py`, ratified as built.

Auspex has a problem most products with a prompt-injection filter do not: **our
legitimate traffic IS attack text.** An analyst pastes a phishing email whose
body says "ignore all previous instructions" *because that sentence is the
artefact under analysis*. A guard that matches injection strings and refuses
would block the core use case; one that does nothing leaves the platform open to
anyone who can get text in front of it. So the question the guard answers is not
"does this contain an injection?" but **"is this instruction being ISSUED to the
platform, or ANALYSED by it?"**

- **Format beats keywords — the classifier's rule, not a second one.** The
  carve-outs import `_is_email_paste` / `_is_alert_paste` / `_is_analytical`
  from `classify/classifier.py` rather than re-deriving them. A guard with its
  own opinion about what counts as a paste would mean the guard and the router
  see two different messages, which is the drift D-006 and the S16 staleness work
  exist to prevent. A pasted email is an email whatever its body says.
- **Position is the signal, not vocabulary.** Material is CONTENT when it is
  introduced for analysis — the framing must appear BEFORE the match. Otherwise
  the guard is bypassed by appending "is this phishing?" to any injection, and a
  carve-out that reads keywords anywhere is not a carve-out, it is an off switch.
- **Four ways to be content, all structural:** a recognized artefact format, a
  quoted or fenced block, an analysis framing that precedes the text, or a body
  long enough (≥600 chars) to be plainly a document. Every one is decidable from
  the text alone — a rail that depended on a model's judgement would be a
  suggestion (D-006).
- **Carve-outs are justified against the REAL corpora.** Every S11 `.eml` fixture
  is tested with the injection sentence spliced into its body, and the unmodified
  fixtures are asserted clean so the test measures the splice rather than a false
  positive we shipped. A carve-out justified by a hand-written example is one
  nobody has tested against the product.
- **It refuses before anything else looks at the text** — ahead of the 92/8 gate
  and of session creation, so a refused turn reaches no model, no KB and no
  transcript. 400 with copy naming the rule that fired and how to re-send.
- **What it explicitly does NOT do:** judge whether an answer was influenced.
  That is post-hoc validation (TD-012), and asking a model to police itself is
  what D-006 says not to rely on. The guard bounds the input; it does not certify
  the output.

## D-026 — A workspace's plan is data, its limits are code, and spend is claimed not checked (2026-08-15, S19)
The second Hardening decision: `auspex/limits.py` + the `usage_counters` table,
ratified as built. Closes TD-018, open since S14.

- **The ceiling is enforced in the statement that reads the counter.** A
  conditional UPSERT (`DO UPDATE SET used = used + n WHERE used + n <= limit
  RETURNING used`) either claims the spend or matches zero rows. This is D-024's
  settlement device applied to metering: "read the count, decide, then increment"
  is a window two concurrent turns fit through, and its failure mode is serving
  free inference. Raced with eight concurrent claims over one unit of headroom —
  exactly one wins.
- **The plan is a column; the tier list is code.** A limits table would make
  "unbounded inference" reachable by a bad UPDATE. Same posture as
  `EXECUTABLE_SYSTEMS`: which tier a customer is on is data, what a tier may do
  is a decision with a blast radius. **An unknown plan name resolves to the most
  restrictive plan, never to unmetered** — a typo must not be a way to buy
  unlimited inference (the D-014 default-to-gated instinct, applied to spend).
- **Calls, not turns and not tokens.** The call is what the customer's endpoint
  serves and what a runaway loop multiplies, so a two-pass turn claims 2 — metering
  it as 1 would under-count exactly the configuration that costs the most
  (D-016/TD-002). Tokens are the natural second meter and are deliberately absent:
  counting them honestly needs `usage` back from every endpoint, and an endpoint
  that omits it would silently meter zero.
- **A ceiling is not an outage.** The refusal is a 429 naming the meter, the
  ceiling and the reset time, and it says what still works — the LLM-free paths
  (IOC checks, CVE lookups, definitions) are unaffected because the claim happens
  after the 92/8 gate. Never a silent truncation, never a generic 500.
- **Unmetered still counts.** `enterprise` has no ceiling and is still measured;
  a plan that stopped counting could not answer "what did this workspace spend?",
  which is the whole point of a gating skeleton. This is NOT billing — nothing
  here prices anything (explicitly deferred).

## D-027 — What the input guard actually bounds, and who pays when the endpoint fails (2026-08-15, S20)
Ratified after the S20 Step-0 review executed against `auspex/guard.py` and
`auspex/limits.py` (record: docs/probes/2026-08-15-s20-step0-review.md).
**This EXTENDS D-025 and D-026 and overturns neither** — it names bounds those
entries left implied, and ratifies two behaviours that the review forced and
found correct.

- **Matching is done on a FOLDED copy of the message.** Invisible characters are
  deleted and Latin lookalikes mapped to ASCII before the patterns run, because
  "ig<ZWSP>nore" and "ignоre" (Cyrillic o) are the word to every reader and every
  tokenizer but not to `\b(?:ignore)\b`. Measured: before this, all four
  variants returned **CLEAN** — not CONTENT, invisible. `untrusted.flatten` is
  deliberately NOT reused: it *replaces* invisible runs with a space, which
  leaves "ig nore" just as broken. Same-looking operation, opposite requirement.
- **Carve-outs still measure the ORIGINAL text.** Folding is for matching only;
  positions map back. The carve-out detectors are the classifier's own and the
  router runs them on the raw message, so measuring position in a rewritten
  string would be the exact drift D-025 warns about.
- **Describing an attack is not issuing one — a fifth carve-out.** S19 justified
  the carve-outs against pasted artefacts, which always have a format to carve
  them out, and never tested the case with no artefact at all: an analyst
  writing ABOUT an injection in their own words. **Four of six such sentences
  were refused with a 400**, including "write a Sigma rule that fires on
  'ignore all previous instructions'". That is the failure D-025 exists to
  prevent, arriving through the door D-025 did not check. Reported speech is now
  content, checked in the PREAMBLE under D-025's position rule so an attribution
  stapled on the end is not an off switch.
- **The guard does not defeat an adversary, and now says so.** Every carve-out
  is decided by text the sender controls: two forged RFC-5322 header lines, a
  `{"k": "v"}` prefix, or 600 characters of padding each turn an issued
  imperative into CONTENT, all confirmed by execution. This is not a hole to be
  closed but a property of the design — a structural carve-out is forgeable by
  whoever writes the message. **What the rail actually bounds is accidents and
  naive attempts from an authenticated caller; the threat it genuinely answers
  is untrusted text arriving inside somebody else's paste.** Base64 and rot13
  wrappers are explicitly OUT OF SCOPE for the same reason: a guard that decoded
  every encoding an LLM can read would be a decoder, not a guard. A rail that
  claimed more than this would be worse than a narrow one.
- **Spend is claimed before the call and is NOT refunded when the call fails.**
  Forced and measured: the endpoint 502s after the claim and the workspace is
  charged 2 for 0 inference received; a client that disconnects mid-stream is
  charged likewise. This is deliberate. A refund-on-failure design means a
  failing endpoint costs a workspace nothing, which is precisely the retry storm
  a ceiling exists to bound, and the up-front claim of the FULL turn cost is
  what lets a turn either run completely or be refused cleanly — claiming
  per-pass would let a workspace be cut off mid-answer at 99/100. The
  over-charge on a failed turn is the price of never starting a turn we cannot
  finish, and it is documented rather than hidden.
- **The window is fixed, not sliding, and that is a real 2x burst.** Measured:
  `window_start` truncates to the hour, so a workspace can spend its full
  ceiling at 13:59:59 and again at 14:00:01 — 2x the hourly ceiling in two
  seconds of wall clock. Kept: truncation is what lets every replica agree on
  the boundary without coordinating, the burst is bounded (2x over two hours
  averages to the ceiling), and the refusal copy already names the exact reset
  time so an analyst is never guessing. A sliding window would trade that
  coordination-free property for a smoother curve nobody asked for.

## D-028 — CI runs `./ci.sh`, and nothing else (2026-08-15, S20)
The beta deploy pipeline. `.github/workflows/ci.yml`, ratified as built and
verified by running it.

Until S20 the gate was "Burhan runs `./ci.sh` locally and Claude reports green."
That is a real gate for one human who has agreed to a protocol, and it does not
survive a second contributor. It was also unprovable from outside: `gh pr checks`
reported **0 checks** on every promote PR from #1 to #19, so the promote ritual
asserted a green nobody could see.

- **The workflow calls `./ci.sh` and re-implements none of it.** A workflow that
  re-listed the steps would be a second definition of "green", and the first time
  someone edited one and not the other the gate would start lying. Same rule as
  the guard importing the classifier's detectors (D-025) and the tier list living
  in code beside `EXECUTABLE_SYSTEMS` (D-026): one source of truth per decision.
  `test_ci_runs_the_same_gate_a_developer_runs` fails if the workflow grows its
  own `ruff check`, `pytest` or `pip install`.
- **No secrets, and none referenced.** `auspex/devhost.py` already pins
  `KB_ENABLED` / `INGEST_ENABLED` / `ENRICHMENT_ENABLED` to false for host runs,
  so the suite reaches no feed, no provider, no LLM and no OpenSearch ML. A fork
  PR runs the identical gate. **S20 added zero env vars — seven sessions now.**
- **It is the gate on `main` and `staging`, both push and PR.** The
  always-demoable invariant is unchanged and now enforced by something other
  than a promise.
- **It paid for itself on the first run**, which is the reason this entry is
  ratified rather than proposed. Two defects that were green on the developer's
  laptop and red on a clean runner:
  1. **IPv6 identity was delegated to a stdlib formatting choice.**
     `observable_id` hashes the value, and the value came from `ip.compressed` —
     which CPython renders in mixed notation for IPv4-mapped addresses on newer
     patch releases. A silent interpreter upgrade would have forked every
     IPv4-mapped observable into a second identity and split its verdict history,
     which is precisely what Living Verdicts cannot survive. Now canonicalised in
     our own code, measured equal to the stdlib across **200,268 addresses** with
     every output re-parsing to its input.
  2. **Three tests depended on accumulated developer state** — a fixture SELECTed
     the `default` workspace and asserted it existed, which was only ever true
     because a laptop's long-lived dev database had one from an earlier login.
  Neither was findable locally. That is the argument for the pipeline, and it is
  evidence rather than assertion.
- **Branch protection is NOT set by this decision.** Requiring the check before a
  promote merge is a repository-settings change and the human's call, not a
  commit's — recorded in STATE.md as the one manual step left.

## D-029 — Carve-out scope: reported speech is a sentence, framing is an introducer (2026-08-15, S21)

**Context.** S20 widened the guard to admit an analyst *describing* an attack
(D-025's own thesis: our legitimate traffic IS attack text). The S21 Step-0
review attacked that widening by execution — record:
docs/probes/2026-08-15-s21-step0-review.md, harness
`docs/probes/s21-step0/probe_s20_review.py`. It found one regression and two
bounds. The regression is fixed. **These are the two bounds, ratified rather
than chased**, in the same spirit as D-027: name what the rail does not do
instead of shipping a speed bump that makes it look stronger than it is.

**Decision 1 — the two preamble carve-outs are scoped differently, on purpose.**
- **Reported speech (carve-out 4) reads only the sentence the match is in.** An
  attribution is a syntactic relation between a subject, a speech verb and the
  words spoken, and that relation does not survive a full stop. Measured: read
  against the whole preamble, *six of six* unrelated sentence pairs turned a
  bare imperative into CONTENT — `Open the ticket that contains the API key.
  <imperative>` was admitted because of a relative clause about a ticket.
  Sentence-scoping closes all six at **zero cost on the pinned legitimate
  corpus**, because every legitimate use of this carve-out is same-sentence by
  construction.
- **Analysis framing (carve-out 3) still reads the whole preamble.** "Here is
  the email body:" is an *introducer*: it is *meant* to govern everything after
  it, including across sentence and paragraph breaks, which is exactly how a
  body-only paste arrives. Scoping it to the sentence was measured too and
  **refuses `Is this phishing? <paste>`** — the flagship legitimate shape. So it
  is not scoped, and the cost is stated plainly: **an introducer phrase anywhere
  before the match licenses everything after it**, including in a sentence that
  introduces nothing (`Here is the plan for next quarter. <imperative>` is
  CONTENT). Logged as TD-032. The asymmetry between 3 and 4 is deliberate and is
  the whole content of this decision.

**Decision 2 — the inline-quote carve-out stays, and it is the cheapest one we
ship.** Wrapping an imperative in two quotation marks turns it into CONTENT.
That is a **two-character** bypass, and unlike every forgery D-027 ratified
(two RFC-5322 header lines, a JSON prefix, 600 chars of padding) it costs no
structure and changes nothing about how the message routes. Removing the arm was
measured twice: against the pinned corpus it is **fully redundant** (zero cases
depend on it, because the reported-speech arm added in the same commit covers
them), and against analyst prose that actually quotes a string it is
**load-bearing for 7 of 7** — `Add "ignore all previous instructions" to the
blocklist.` and its neighbours all become 400s. The pinned corpus was written by
the commit that added the arm, so it is not evidence about the arm. **The arm
stays; the bound is named** (TD-031) rather than papered over with a
one-character speed bump, which is the move D-027 already declined once.

**What this does NOT change.** D-025 (the question the guard asks), D-027 (the
rail bounds accidents and naive attempts, not a determined authenticated
caller). This decision is about *which text* a carve-out is allowed to read, and
it supersedes nothing.

## D-031 — The agent path streams: tool calls first, then the answer (2026-08-16, S23)

**Context.** Wiring `AgentLoop` into `/api/chat` is the largest gap between the
platform and its own README, and it was blocked on a shape mismatch: the loop is
blocking and multi-step (`client.chat`, auspex/agent/loop.py:321), the route is
SSE. Which way to resolve that depends on a fact about the customer's endpoint,
not on taste, so it was probed before any code. Record:
docs/probes/2026-08-16-s23-agentloop-streaming.md.

**Decision 1 — the answer streams after the tools, and the tool steps are
narrated.** Measured on real Scout: a tool-calling turn emits `tool_call` deltas
with **zero content before them** (`content chars: 0`), and a control question
needing no tool streams content normally. Because no prose precedes the tool
results, the route can narrate each tool step and then stream the final answer
without ever having streamed a sentence the results might contradict. The
degenerate fallback — run the whole loop, emit one content blob — is not needed.

**Decision 2 — tool-call arguments are accumulated before they are parsed.** One
IP address arrived as **nine** fragments split mid-token (`'185', '.', '220'`).
A streaming loop that parses a delta on arrival fails on the first one. The
non-streaming path never saw this because the client already joins the fragments.

**Decision 3 — `finish_reason` is the step signal, not a model sentence.**
`"tool_calls"` means another step follows; `"stop"` ends the turn. Code-owned, per
ADR 0006.

**Decision 4 — the usage claim moves inside the loop.** The route claims 1–2
inference calls up front (chat.py:506); a loop makes up to `DEFAULT_MAX_STEPS = 8`
plus a synthesis call. Wiring the loop without moving the claim would let a
workspace cause 9 calls while being charged 1, breaking exactly the guarantee
TD-018 and D-027 exist to hold. A refusal mid-loop synthesises from what was
gathered rather than failing the turn.

**Decision 5 — the output rail indexes what the turn actually issued.** D-030
decision 2 said only configuration WE issued is indexed; with a loop that set is
composed at runtime (`system_prompt + channel.system_prefix + _actions_prefix`),
so the index is built from the composed message rather than four fixed strings.
Tool **results** stay unindexed — they are data, like the analyst's paste. And
since the S23 Step-0 review made the scanner channel-aware, a tool result is its
own channel: a run spanning a tool result and the answer is not a leak.

**Consequence, stated because it is not a detail.** No `ToolRegistry` is populated
anywhere in the running app — the only callable surface is
`app.state.action_registry` with a single action. A loop wired in today has **zero
read tools**, so the platform's real capabilities (enrichment, CVE lookup, KB
retrieval) must be exposed as agent tools for an agent turn to be worth taking.
That is the substance of the work, and it is separate from the wiring.

**Scope of the measurement.** Native tool mode only. `prompted_tools` parses
`<tool_call>` tags out of **content**, which would stream to the analyst as prose
before the loop could strip them. It needs its own probe before being wired to a
streaming surface.

## D-030 — The output rail checks for our configuration coming back, not for obedience (2026-08-16, S22)

**Context.** Four entries now end with the same sentence — D-027, TD-031,
TD-032 and TD-033 each declined to tighten the input rail further and each
named post-hoc output validation as the real answer. Three sessions went into
`guard.py`; the output side had nothing at all. Record:
docs/probes/2026-08-16-s22-outguard.md.

**Decision 1 — the rail answers a question that is decidable in code.** Not
"was this answer influenced?", which is not decidable from the text and would
mean a model grading a model (the thing D-006 exists to refuse). It asks: **is
the platform's own configuration coming back out in the answer?** We hold both
halves of that — we know exactly what we sent — so a verbatim run of our
instructions in the output is recognisable without any vocabulary to maintain,
and therefore without anything to rot.

**Decision 2 — only configuration we issued is indexed.** Never the analyst's
pasted artefact (their own email quoted back is a *correct* answer), never the
deterministic verdict blocks (whose values the answer is pinned to echo), never
the two-pass analysis the answer is built from. The call site lists the strings
explicitly. A rail that indexed "every system message" would fire on the turn's
own data and be switched off within a week.

**Decision 3 — the floor is calibrated on live output, like NEURAL_FLOORS.**
`SHINGLE_WORDS = 8`, from 34 real Scout answers across both streaming shapes:
the legitimate ceiling is **6** (including 12 questions whose correct answer is
written in the instruction set's own vocabulary), and the one attempt that
actually complied reproduced **60** words. Changing this number means re-running
the probe, not editing a constant.

**Decision 4 — a leak is cut off, and never persisted.** A streamed answer
cannot be un-sent, which is what TD-012 said and is still true: the guarantee is
that the stream stops within `SHINGLE_WORDS` words of the run starting. The
guarantee that *lasts* is that the turn is not stored — a stored assistant turn
replays into every later deep turn of the session (TD-009), so persisting a leak
would turn one bad turn into a permanent one.

**What this does NOT do, and is written down rather than implied.** It does not
catch an injection that made the answer *wrong* — that prose looks like an
answer, and only a verdict the platform computed in code can contradict it. It
does not catch a **paraphrase** of the configuration; detection is on verbatim
runs, and "summarise your instructions" defeats it by construction. It is a
second rail with a different failure mode from the first, not a closure.

**What this supersedes.** Nothing. D-006 (code owns safety-critical decisions),
D-027 and D-029 (what the INPUT rail does and does not bound) all stand
unchanged — this adds the side they each pointed at.

---

## D-032 — `main`'s protection is procedural, and that is the decision (2026-08-16, S25)

**Context.** Since S20 the promote flow has assumed that branch protection on
`main` was a settings toggle nobody had got round to. S24 tested that assumption
and it was false: Burhan authorised enabling protection, and it **cannot be
enabled on this repository**. Classic branch protection and rulesets both return
`403 "Upgrade to GitHub Pro or make this repository public"` — both probed, record
docs/probes/2026-08-16-s24-branch-protection.md. The repo is private on a free
plan, so the item was never a task; it was a plan-and-visibility question wearing
a task's clothes, and it sat in "in-flight follow-ups" for five sessions looking
like something that would eventually get done.

**Decision.** `main` is protected **procedurally**, not by GitHub. The guarantee
is `/promote`'s: it refuses to merge on anything but a CLEAN check, and every
promote so far has waited for green (#18 through #25). Three options were put to
Burhan at the start of S25 — make the repo public, pay for Pro, or ratify the
procedural protection — and the third was chosen.

**Why not the other two.** Making the repo public would publish STATE.md,
DECISIONS.md and `docs/probes/` — candid working documents written for two
readers, including live probe records of external services. That is a real cost
paid for a guarantee this project's actual failure modes do not need: there is one
human and one agent, no third party pushes, and the risk protection addresses
(someone merging red, or pushing straight to `main`) is already prevented by the
ritual and the CI gate (D-028) that makes red visible to anyone.

**What this obliges.** The procedure is now the guarantee, so it must not be
softened casually. `/promote` may not merge on a non-CLEAN check, and `main` may
not be pushed to directly. If either becomes untrue, this decision needs revisiting
rather than quietly eroding — that is the whole difference between a procedural
guarantee and no guarantee.

**Status change.** This item leaves "in-flight follow-ups" permanently. It is not
blocked, not pending, and not a shortcut logged in TECHNICAL_DEBT.md — it is a
ratified decision.

**What this supersedes.** Nothing. D-010 (work lands on `staging`; `main` moves
only through `/promote`) and D-028 (CI runs `./ci.sh` and nothing else) both stand
unchanged — this names what enforces them.

## D-033 — The endpoint's URL is the customer's; its response shape is measured, not configured (2026-10-10, S26)

**Context.** The customer brings the LLM (D-005), but `auspex/llm/client.py`
hardcoded `/v1/chat/completions` and `/v1/models` under `LLM_BASE_URL`. That
held for the three endpoints we had (Ollama, vLLM, Scout) and broke on the first
provider whose API root is not `/v1`: Z.ai serves `https://api.z.ai/api/paas/v4`.
Worse than a clean failure, measured live: under that root `GET .../v1/models`
answers **200** while `POST .../v1/chat/completions` answers **404** — the
liveness check would have passed for an endpoint chat could not reach
(docs/probes/2026-10-10-zai-endpoint.md). Burhan proposed making the URL and the
response JSON part of the environment so nothing provider-specific is hardcoded.
The principle was accepted; the mechanism below was Burhan's choice between the
two put to him.

**Decision 1 — `LLM_BASE_URL` is the API root exactly as the provider documents
it for the OpenAI SDK.** The client appends only the operation (`/chat/completions`,
`/models`) — never a version segment. Every OpenAI-compatible provider publishes
that value (`https://api.openai.com/v1`, `https://api.z.ai/api/paas/v4`,
`http://localhost:11434/v1`), so a customer copies it rather than translating it.
**No new variable**: the existing one changes meaning. Pre-D-033 values (a bare
host) now 404 at `/models`, and the liveness note says what to fix rather than
reading like an outage.

**Decision 2 — response-shape variants are handled in code and detected by the
capability probe, never configured.** The known variance is small and named: the
thinking text arrives as `reasoning` (Ollama, newer vLLM) or `reasoning_content`
(Z.ai, DeepSeek, older vLLM). The client accepts both. A field-name variable was
rejected because the customer cannot be expected to know it, and getting it wrong
fails SILENTLY — reasoning reads as absent while the tokens are still billed —
which is exactly the *not-measured renders as not-present* collapse the
capability scorecard exists to prevent. Measurement already covers it:
`native_reasoning` is set from what the basic probe actually returned.

**Decision 3 — a request pass-through (`LLM_EXTRA_BODY`) is admissible, and only
on measurement.** Provider-specific *request* switches (Z.ai's `thinking`,
`reasoning_effort`, `tool_stream`) ARE the customer's to set — like `LLM_MODEL`,
they belong to their endpoint, not to us (D-026 governs tunables that are ours).
One optional JSON variable merged into every request body would cover any
provider. It is born only if a measurement shows the default request costs the
platform something it must not pay; until then it does not exist.

**What this supersedes.** Nothing ratified. D-005 (customer-supplied endpoint),
D-015's `.env`-is-the-single-source-of-truth and D-016's `native_reasoning` all
stand; this makes them true for endpoints whose root is not `/v1`.

## D-034 — Primary dev LLM: glm-4.5-air on Z.ai's general API (2026-10-10, S26)

**Supersedes D-015's primary assignment** (Scout on Northflank). D-015's
evidence stands as history; its endpoint does not exist — the Northflank
hostname is NXDOMAIN (measured 2026-10-10). qwen3:14b on local Ollama stays the
secondary/offline endpoint (D-013), now spelled `…:11434/v1` (D-033).

**How it was decided.** Burhan supplied a pay-as-you-go Z.ai key, asked for
GLM-5.2 to be tested, and delegated the choice: *"if you feel we can use some
other model that is cheap and efficient from their suite then use that."*
Four models ran the platform's own battery and 40-task harness through the real
client (docs/probes/2026-10-10-zai-endpoint.md):

| model | completion | wall | $/1M in/out |
|---|---|---|---|
| glm-4.5-air | 95.0 % | 348 s | 0.20 / 1.10 |
| glm-5.3-flash | 95.0 % | 1012 s | 0.15 / 0.50 |
| glm-5.2 | 92.5 % | 694 s | 1.40 / 4.40 |
| glm-4.7-flashx | 87.5 % | 757 s (1.6 tok/s) | 0.07 / 0.40 |

All 100 % valid calls, all `native_tools`. **glm-4.5-air** completes as much as
anything measured, in half the time of the next best, at a seventh of
GLM-5.2's input price. It is the best loop-completion rate any dev endpoint has
posted (qwen3 87.5 %, Scout 77.5 %).

**Constraints this carries.**
- **General endpoint only** (`https://api.z.ai/api/paas/v4`), **pay-as-you-go
  only.** The Coding Plan's terms forbid its quota behind our own application.
- **Dev only.** Z.ai processes in Singapore; under org policy no KSA-tenant data
  may ever route through it. Customers bring their own endpoint (D-005); this
  decision is about what WE build against.
- **glm-4.5-air is the oldest model in the catalog** (2025-07). No deprecation
  notice exists today; if one appears, glm-5.3-flash is the measured fallback
  (same completion, slower).
- **The key lives in `.env` as both `GLM_API_KEY` (Burhan's name for it) and
  `LLM_API_KEY`** — gitignored, never printed, never committed.
- **Prose precedes tool calls on this endpoint** (TD-036 triggered) and **the
  chat route only takes the native-reasoning path if the analyst's workspace has
  a scorecard** (STATE follow-up 9; a hand-seeded dev row covers it for now).
  Both are owed before the agent path is wired to `/api/chat` against it.

## D-035 — The default endpoint's scorecard is the deployment's (2026-10-10, S26)

**Context.** `LLM_BASE_URL` / `LLM_MODEL` configure ONE endpoint for the whole
deployment, but its scorecard was stored per workspace: the only writer
(`scripts/llm_harness.py`) saved to a workspace named `dev`, the only reader
(`_default_native_reasoning`, chat.py) read the analyst's. They never met. The
default endpoint therefore always read as "not a thinking model", and on a
thinking model the two-pass fallback it chose was measured broken through the
running app: the model's own thinking consumed pass 1's 256 tokens, the Thinking
pane stayed empty, and every deep turn paid for a second call that bought
nothing (docs/probes/2026-10-10-zai-endpoint.md). STATE follow-up 9 had carried
the symptom since S24 as a note. Burhan: "let's fix the bug".

**Decision.** A deployment-configured endpoint has a deployment-scoped scorecard.
It lives in one reserved system workspace, `__deployment__`
(`DEPLOYMENT_WORKSPACE`, auspex/llm/scorecard.py — the name's one home). The
harness writes there (`save_deployment_scorecard`); the chat route reads there
(`load_deployment_scorecard`). Unknown still reads as False — the safe two-pass
default (D-016) is unchanged for an endpoint nobody has probed.

**Why a reserved workspace and not a nullable `workspace_id`.** D-008 puts
`workspace_id` on every row of every table, and the schema test enforces it.
**Why not "look the fingerprint up in any workspace".** That is a cross-tenant
read: the first time a tenant configures or probes its own endpoint, its row
would decide another tenant's turn. The reserved workspace is read by every
analyst request but written by no tenant — `get_or_create_user` refuses the
name, so no user can ever be provisioned into it.

**What it does not do.** Nothing in a production deployment writes this
scorecard yet: the harness is a dev script. A fresh deployment still reads
"unknown" and takes two-pass until someone probes it — and two-pass is broken on
thinking models. Logged as TD-037 rather than solved here, because the fix
(probing the customer's endpoint at startup or on configuration) spends the
customer's inference without a turn asking for it, which is D-005's to decide.

**What this supersedes.** Nothing ratified. D-008 stands (the row keeps its
workspace); D-016's safe default stands. Pre-existing rows in workspace `dev`
are left as history: they are probes of endpoints, not of tenants, and nothing
reads them.

## D-036 — A two-pass turn whose endpoint thinks becomes a native turn (2026-10-10, S26)

**Context.** D-016 picks the reasoning path from the endpoint's scorecard: native
if it emits its own reasoning, else two passes (pass 1 a brief analysis →
Thinking pane, pass 2 the answer). An endpoint nobody has probed reads as
"unknown" and takes two passes — the D-035 fix made the scorecard findable, and
TD-037 records that nothing in a production deployment writes it. On a
**thinking** endpoint that two-pass is broken, measured on glm-4.5-air: its own
thinking fills pass 1's 256-token budget (`R×245 C×9`, `R×220 C×34`), the pane
shows a cut-off fragment or nothing, and the model's real thinking is
discarded. Two remedies were put to Burhan — probe the customer's endpoint
unasked, or make two-pass survive a thinking model. **He chose the second.**

**Decision.** The endpoint tells us inside the turn. If pass 1's FIRST text
event is the model's own reasoning, the endpoint thinks natively: the route
stops pass 1 at that event (closing the stream, so the endpoint stops
generating) and spends the turn's second claimed call on the **native** answer —
the turn's own messages, the answer budget, reasoning and content streamed on
their own fields through the same rail. If pass 1's first text is content, the
turn is an ordinary two-pass, exactly as before; a late reasoning event does not
switch it (the analyst is already reading that analysis).

**Why the first event and not a scorecard write.** Recording "this endpoint
thinks" from inside a turn would be an analyst request writing deployment-scoped
state (D-035's reserved workspace, which no tenant request writes). The signal
is cheap to re-read every turn: measured 1.3–2.2 s to the first event.

**Cost, stated.** No extra calls: two claimed, two made (pass 1 abandoned + the
native call) — the same count two-pass always claimed (TD-018). What remains is
one abandoned pass-1 per turn on an unprobed thinking endpoint: its prompt
tokens and the time to its first event. A probed endpoint (scorecard present)
skips pass 1 entirely, as before.

**What this supersedes.** Nothing. D-016 stands — the scorecard still chooses
first; this is what two-pass does when the stream proves the scorecard wrong.

## D-037 — Which deep turns take the agent path: any the code has not already decided, on an endpoint measured to call tools (2026-10-10, S26)

**Context.** D-031 settled *how* the agent path streams. Which turns take it was
left open behind one S25 observation: offered tools, Scout refused a question no
tool answers. The rule proposed on 2026-08-16 (agent path only when the
classifier found an observable) existed to keep such questions away from the
tools. Every measurement it rested on was of Scout, which no longer exists.
Re-measured on glm-4.5-air: docs/probes/2026-10-10-s26-routing-glm.md.

**Decision.** A DEEP turn takes the agent path if and only if

1. its mode is **not** `ALERT_TRIAGE` or `PHISHING_ANALYSIS`, **and**
2. the configured endpoint's **deployment scorecard** (D-035) compiles to
   `native_tools` (`decide_agent_mode`).

Every other deep turn takes the conversational path exactly as before (native or
two-pass, D-016/D-036). Shortcut turns are untouched: the 92/8 gate still runs
first, in code.

**Why the observable clause is dropped.** It protected nothing, and it cost
something:
- the refusal it guarded against did not happen in **0 of 25** tools-on runs,
  across S25's exact method, the 2×2, and the route's full composition. Scout's
  own record is 0 of 12 under the route's conditions;
- its positive case barely exists, because a short question carrying an observable
  is answered by the 92/8 shortcut before it is ever deep. The probe's own example
  was a CVE card;
- its negative case is where the tools helped most. On a KB-shaped question with
  no observable, the conversational path mislabelled an ATT&CK ID in 2 of 3 runs,
  while the agent path searched the KB and labelled all 3 correctly. Both paths
  conformed to the mode contract 3/3, in comparable time.

**Why clause 1 stays.** In those two modes the code has already computed the
verdict (the S10 alert scorer, the S11 phishing verdict), and validation pins the rendered answer to
it. The pasted alert or email is attacker-controlled, so on the agent path the
model would be drawing **tool arguments** from it. That combination has not been
measured, and it is not needed for those modes to work.

**Why clause 2 is the scorecard, and what each outcome means.**
- **Unprobed endpoint → conversational.** No assumption is made that an endpoint
  calls tools; this is the same fail-safe as `channel_for`.
- **`prompted_tools` → conversational**, until it is probed against a streaming
  surface (D-031 scope: its tags arrive in content).
- **`plan_only` → conversational.** A loop built with zero tools still sends
  "Use the provided tools", and that composition was measured inventing a tool
  call as prose. The loop never runs tool-less on this route.
- **Dev-switcher endpoints** carry no agent mode and stay conversational.

**Cost, stated.** A measured agent turn made **2–3** model calls where the
conversational path makes one. Each call is claimed against the workspace's
hourly ceiling as it is made (D-031 decision 4, TD-018), so the ceiling holds and
the turn's real spend is what gets counted. This is still the customer's
inference (D-005).

**What this supersedes.** Nothing ratified. The 2026-08-16 proposal was never
ratified, and STATE.md standing follow-up 10 closes with this entry.

## D-038 — The deployment probes its own endpoint, once per fingerprint (2026-10-10, S26)

**Context.** TD-037. The deployment scorecard (D-035) decides native vs two-pass
reasoning (D-016), and since D-037 also whether deep turns take the agent path.
Its only writer was a developer running `scripts/llm_harness.py`, so every
non-dev deployment read "unknown": two-pass on every deep turn, and no agent
path at all. Whether the platform may spend the customer's inference to measure
the endpoint unasked was left as a D-005 question. Burhan delegated the call
("do what you think is best").

**Decision.** At startup a background task runs the capability battery
(`auspex/llm/capability.py`) against the configured endpoint. It does this only
if the endpoint's fingerprint (base URL + model, never the key) has no
deployment scorecard, and records the result. The cost is about 15 requests,
once per endpoint.
- **A probe that measured nothing is not recorded.** That covers an unreachable
  endpoint and one where basic chat failed (a wrong key or model). The key is
  not in the fingerprint, so recording a wrong-key probe would pin plan_only
  even after the key was fixed. Such a probe is retried at 1m, 5m, 15m and 1h,
  because a scale-to-zero endpoint asleep at startup is normal.
- **Workers starting together probe once.** The probe runs under a Postgres
  advisory lock and re-checks for a scorecard under it.
- **The app never waits on the probe or fails because of it.** The port binds
  immediately, and deep turns stay on the safe default ("unknown") until the
  scorecard lands.
- **`LLM_AUTOPROBE_ENABLED` is the operator's say.** An operator who will not
  have the platform spend inference unasked turns it off and manages the
  scorecard with the harness. Host and test runs pin it off, like
  `INGEST_ENABLED`.

**Why.** The capability-negotiated runtime is flagship #1 in CLAUDE.md: "probe
the customer's LLM endpoint, compile the agent loop to what the model can
actually do". Without a writer it compiled nothing outside dev. Measuring once
per fingerprint is the smallest spend that makes it true, and it is
switchable.

**And the agent path needs one more measurement (same day, `48fb195`).**
`native_tools` is decided from a non-streaming probe, but the agent path only
exists streaming. D-037 clause 2 therefore also requires
`streaming_tool_deltas`.

**What this supersedes.** Nothing. D-036 still covers a two-pass turn on an
endpoint that thinks before its scorecard lands.

## D-039 — The agent sends third parties only indicators someone other than the model supplied (2026-10-10, S26)

**Context.** TD-039, from the review of the S26 wiring. D-037 clause 1 keeps
alert triage and phishing off the agent path, because their paste is
attacker-controlled and would steer tool arguments. The same paste reaches the
agent path whenever the mode resolver does not recognise it: "summarize this
report: <paste>" is BRIEF, and an unrecognised alert format falls through.
There, an injection can make the model **compose** an indicator, for example a
hostname whose label carries data from the session, and `enrich_observable`
would send it to third-party providers, some of which resolve what they are
asked about. Burhan delegated the call ("do what you think is best").

**Decision.** `enrich_observable` looks up an indicator only if someone other
than the model supplied it:
- the analyst, in **user** turns of this session, current or earlier; or
- a **knowledge-base record** returned by a tool this turn.

Anything else is reported as `not_checked`, with a reason the model can act on
(ask the analyst to paste it), and the enrichment service never sees it. The
model's own earlier answers supply nothing, because an injected turn 1 can make
the model write the composed indicator into its answer. A tool's echo of what
it was asked supplies nothing, because that would launder a request into a
supply.

**Why this and not more excluded modes.** Excluding modes one at a time (option
b) depends on the resolver recognising every shape a paste can take, and it
cannot. Accepting the bound (option c) leaves the channel open at 8 lookups
per turn. This closes the channel itself, and it costs one thing: the agent can
no longer look up an indicator it knows only from its own training, which is
also where its fabrications come from. S24's reason for allowing unsupplied
indicators ("a loop may reason its way to an indicator") is kept wherever the
reasoning ran through data the platform returned.

**Scope.** Only `enrich_observable` reaches a third party. `lookup_cve` and
`search_knowledge` still accept model-composed queries, because they go to our
own index. D-037 clause 1 stands unchanged, since those modes' verdicts are
code-owned for their own reasons.

**What this supersedes.** Nothing ratified. It reverses the S24 test
"enrichment also accepts an indicator the message never carried" and is
recorded in that test's docstring.

## D-040 — A thinking model's own thinking is held to a recitation floor (2026-10-10, S26)

**Context.** Before TD-038's extension could be indexed, it was calibrated on the
agent path (docs/probes/2026-10-10-s26-rail-calibration-glm.md: 12 hard-legit
questions plus 2 recitations, per channel, glm-4.5-air). The calibration found
a defect unrelated to TD-038. A thinking model reasons **by quoting its
instructions**: on a legitimate question its thinking quoted 19 words of the
DEFINITION mode directive, and on another 20 words of a tool description. D-030
decision 3's single floor, `SHINGLE_WORDS = 8`, was calibrated on Scout, which
had no native thinking. It cut those turns with LEAK_COPY and stored nothing,
on both native paths, before S26's wiring touched anything.

**Decision.** The output scanner takes per-channel floors. The model's own
thinking is scanned on a `thinking` channel at `THINKING_SHINGLE_WORDS = 40`.
That is about twice the legitimate ceiling measured (20) and under the
recitations measured (58 here, 60 in S22). Every other channel keeps 8: the
answer, the tool lines, the agent's narration (the model's prose, never seen
quoting instructions), and a two-pass analysis (content written under
PASS1_DIRECTIVE, which S22 calibrated).

**What it costs, stated.** A quotation of our configuration up to 39 words in the
Thinking pane is no longer cut. Such quotes are the model's normal reasoning,
and the rail's purpose (D-030) is the wholesale dump an injection produces,
which the floor still cuts. The run is still never persisted, because thinking
is never stored.

**Calibrated, like SHINGLE_WORDS.** n = 12 on one model. Re-run
`docs/probes/s26-step0/probe_calibrate_agent.py` to move it.

**What this supersedes.** D-030 decision 3 for the thinking channel only. For
every other channel it stands as ratified.

**D-040 addendum (2026-10-10, same day, live).** Through the app, the offending
question ×3 carried thinking runs of 19, **28** and 19 words, and all three
passed. The old floor would have cut all three. The legitimate ceiling is now 28,
and the margin under 40 is 1.4×. The floor is unchanged: recitations run 58 and
60. It is the number to re-measure first on any other model.

## D-041 — What a proposal's terminal states say (2026-10-10, S26)

**Context.** TD-028 (b/c/d) and TD-034, all four deferred since S19 to "terminal
state semantics". Four defects had one cause:
- a failed run reported "nothing happened" while its write was in the table (b);
- the cleanup that would remove exactly the orphan was gated shut (c);
- an approver could not tell two identical requests apart (d);
- a late answer could land on the wrong abandoned operation (TD-034).

Goal item 4 of S26; Burhan asked for it to proceed.

**Decision.**
1. **`failed` is a checked fact.** After a handler raises, the executor asks
   the action what of **this proposal's** effects exist, through a new
   optional `ActionSpec.observe` keyed on `proposal_id`.
   - Nothing → `failed`.
   - Something, no way to look, or a look that itself failed → **`incomplete`**.
   - The result records `effects: none | present | unknown`.
   - An action that cannot look is never `failed`. That is the shape the first
     third-party action will have, and the honest default for it.
2. **`incomplete` needs a human**, so it joins the approvals queue.
3. **A put-back may start where effects are unknown.** `undo` is allowed from
   `executed`, `incomplete` and `abandoned` (either operation). It is not
   allowed from `failed`, because nothing landed and `undone` would report a
   put-back of nothing. The claim moves the row only out of the exact status
   the read saw, and a failed put-back returns there, never to `executed`
   unless it started there.
4. **`abandoned` records what it gave up on** (`abandoned_from`), and a late
   answer lands only for that operation (TD-034).
5. **Identical requests are named, never merged.** Each pending card carries
   `identical_pending`: other pending requests in the workspace for the same
   action, arguments and declaration. Merging them would have the platform
   decide that a second intent was a mistake (D-014).

**Bound, stated.** A run a human abandoned whose handler was merely slow can be
put back while it is still alive, and a write it lands afterwards outlives the
put-back. Abandon needs a claim older than STALE_CLAIM_SECONDS, and every
executable action today is a single local statement. There is still no
idempotency key. That matters the day an action reaches a network (TD-025).

**What this supersedes.** S23's pin "an undo cannot start on a row abandoned
during execute", which kept TD-034 unreachable by keeping the cleanup shut.
TD-034 is now fixed structurally. Nothing ratified is overturned: D-024
(an approval is decided once) and the no-reaper rule (S21) stand.

**D-041 addendum (2026-10-10, same day — the review).** An adversarial review of
the four commits found eight defects. All eight are fixed, each with a test
that failed first. The design changed in three places:
- **A claim is a token, not a status.** Once undo could start from
  `abandoned`, two undos could be in flight on one row, and a late failure
  finished the fresh one's claim. The row said `executed` with nothing left.
  `claim_token` is minted by every claim, and a finish lands only for the token
  that holds the row. `abandoned_token` names the one claim whose late answer
  may still land: into its own column if empty, without moving the row. So a
  run that answers after its clean-up (this decision's stated bound) is now
  **recorded** on the `undone` row, not dropped.
- **`kept`** is a seventh exit. A human keeps what an incomplete run left
  (`POST /keep`). Without it an incomplete row of an action that declares no
  undo could never leave the queue. A kept run can still be put back.
- **`abandoned` stays out of the queue, deliberately.** Item 2 queues
  `incomplete` because nobody has decided about it yet. An abandoned row is
  itself a human's decision, and its put-back remains available.

Also fixed:
- a second status-CHECK block that stopped the app booting with one
  `incomplete` row;
- `observe` gets the undo slot's rails, and only an int 0 means "nothing";
- pre-S26 `failed` rows are no longer refused as "checked";
- the twin lookup is indexed (811 → 3.9 ms at 20k pending);
- the surface's copy now claims only what it knows.

**The bound is unchanged.** A merely slow handler on an abandoned run can land
after its put-back, and it is now visible when it does.

## D-042 — The deployment measures its endpoint again once the measurement is a week old (2026-10-10, S27)

**Context.** TD-041, D-038's logged shortcut. D-038 probes once per
fingerprint, and the fingerprint is base URL + model. A provider can change
what a model does under the same name: a silent update, thinking turned on
server-side, tool calling degraded. Nothing re-measured, so the scorecard kept
choosing the reasoning path, the agent path (D-037) and the rail's thinking
floor (D-040) from a measurement that might no longer be true. Burhan put it
in scope at the S27 start ritual ("dont park anything, do everything").

**Decision.**
1. **A measurement expires.** Once the newest deployment scorecard is older than
   `SCORECARD_MAX_AGE_SECONDS` (7 days), the endpoint is measured again, under
   the same advisory lock and with the same battery. The new row is recorded
   (history is kept, newest wins) and the outcome is `reprobed`.
2. **The running app looks.** The startup task no longer ends after its first
   cycle: `keep_scorecard_fresh` repeats the D-038 cycle every
   `REPROBE_CHECK_SECONDS` (6 hours). A look at a fresh scorecard costs one DB
   read. Both numbers are code constants (D-026).
3. **A re-probe that measures nothing changes nothing.** If the endpoint is
   unreachable, or basic chat fails, nothing is recorded, so the old scorecard
   stands. An old measurement is still better than "unknown", which would drop
   every deep turn to two-pass and off the agent path. D-038's retry schedule
   applies.
4. **A changed endpoint is said out loud.** If the re-probe moves the agent mode
   or any of `native_reasoning`, `native_tool_calling`, `streaming_tool_deltas`,
   `json_object_mode` or `json_schema_mode`, the app logs a WARNING naming each
   change. The log also says to re-measure the thinking floor, because D-040's
   number is calibrated per model and no probe re-calibrates it. Field names
   and booleans only; no endpoint output reaches the log.

**Cost.** About 15 requests of the customer's inference per endpoint per week,
on top of D-038's one-time cost. `LLM_AUTOPROBE_ENABLED` still turns off all
of it.

**Not done.** TD-041 also offered a trigger driven by behaviour: re-probe when
the agent path sees a run of `empty_answer` or tool-less turns. Not built: a
run of tool-less turns is also what an analyst asking tool-less questions looks
like, and the schedule bounds staleness without having to tell the two apart.

**What this supersedes.** D-038's "once per fingerprint", in that a
fingerprint is now probed once per week. Everything else in D-038 stands.

## D-043 — A code-decided verdict is never shown off its pin (TD-012(b)) (2026-10-10, S27)

**Context.** TD-012(b), carried since S9. The answer is validated against its
mode's contract only after it has streamed, so a non-conforming answer is
reported in the done frame and never repaired. TD-012 sketched the repair as a
non-streamed structured pass, validated before emit, re-asked once on failure,
using `json_schema_mode`. S27 measured first
(docs/probes/2026-10-10-s27-contract-drift.md):
- **Drift on security questions: 0 of 60**, every mode, both deep paths.
- **Laundering: 0 of 6.** Pastes written to steer the code-decided
  Risk/Verdict did not move glm-4.5-air off the pin.
- The only failures were the known non-security control (4/4). That is a mode
  resolver problem.
- The scorecard records `json_object_mode: true`, `json_schema_mode: false`
  (`json_schema` is silently ignored on this endpoint).

So on the dev endpoint the sketched repair would repair nothing, and it would
cost every answer its streaming. **The two failures are not the same size.** A
drifted narrative answer loses structure. A laundered alert or phishing
verdict replaces the one field the code exists to own (ADR 0006), and today
that is **detected after the analyst has read it** (the S12 honesty test pins
exactly that). That is the part worth a guarantee on any endpoint. Burhan put
TD-012(b) in scope as the S27 goal.

**Decision.**
1. **Held, then validated, for the code-decided modes only** (`alert_triage`,
   `phishing_analysis`). Thinking streams as before. The answer's content goes
   through the output rail as it arrives, but the analyst is sent it only once
   it is complete and has passed the contract and the code's pins.
2. **One re-ask on failure.** That covers a missing section, an out-of-enum
   value, an off-pin value, or no answer at all. The re-ask is the same
   messages plus a repair directive compiled from the contract and the pins,
   which carries **field names and the code's values only**. The failed draft
   and its tokens are model output, possibly steered by the paste, and never
   enter a system message. The re-ask is claimed like any other call (TD-018).
   Its thinking streams. Its content is held, scanned and validated in the
   same way.
3. **Then the code answers.** If the re-ask fails, is refused by the ceiling, or
   the endpoint errors, the analyst gets the contract's sections rendered by
   code from the deterministic verdict: the Risk or Verdict, the itemised
   signals or findings, and the recommendation. It opens with one sentence
   saying the written analysis was withheld. It conforms by construction, and
   a test asserts that.
4. **The done frame says what happened.** `contract_valid` now describes the
   answer the analyst received. A new `contract_repair` field is `null`,
   `"reasked"` or `"code_rendered"`. The first attempt's failure is logged with
   field names only.
5. **Narrative modes are unchanged.** `definition`, `ioc_enrichment`,
   `threat_intel` and `brief`, on both paths, keep streaming and keep
   reporting (measured 60/60). The existing "contract drift" log line is the
   trigger to revisit.
6. **No JSON mode.** The validator is the one compiled from the spec (ADR 0007)
   and works on any endpoint. `json_schema` does not work here. `json_object`
   would change an output format measured as conformant, for no measured gain.
7. **The repair directive is configuration we issue,** so it is in the rail's
   index from the start of the turn. A re-ask that recites it is cut and not
   persisted, like any other leak.

**Bounds, stated.**
- The model's thinking still streams for these modes, and it may quote the
  paste or weigh the steered value. The Thinking pane is process. The verdict
  is what is now guaranteed.
- A held answer arrives as one block, after thinking. Measured for these
  modes: medians of 315–487 chars of answer after 1.4–1.6k chars of thinking,
  in 5–6 s.
- A re-ask is a second call on the rare failing turn.

**What this supersedes.** The S11/S12 statement, in `auspex/phishing/render.py`
and in `test_phishing_verdict_cannot_be_laundered_below_the_floor`, that the
pin "DETECTS the launder — it does not prevent it". For these two modes it now
prevents the analyst from being shown it. No ratified decision is overturned.
TD-012's "re-ask once" is adopted for these modes; its structured pass is
declined, on measurement.

## D-044 — A deep question with no security signal is answered in a seventh mode, `general` (2026-10-11, S27)

**Context.** IDEAS (S26). With no threat-intel keyword, the resolver defaulted
to `threat_intel`. A non-security question could not meet that contract
(measured 4/4 at S26 and 4/4 at S27), and the conversational path half-refused
it. The S9 catalog calls any new mode "a scope decision, not a code edit".
Burhan put this in S27's scope at the start ritual. Record:
docs/probes/2026-10-11-s27-mode-fallback.md.

**Decision.**
1. **A seventh mode, `general`.** Its contract declares no sections, and its
   directive says so ("No section structure is required"). Its one rule is
   neutral: ask for the details only the analyst has, then help. It is not a
   code-decided mode, so on a native_tools endpoint it takes the agent path
   like the other narrative modes.
2. **The resolver's new last step.** After the existing tiers, a question
   becomes `general` only if it has **no** security, IT, identity or payments
   vocabulary (`_SECURITY_RE`) **and no observable**. Otherwise it stays
   `threat_intel`, as before. The vocabulary is generous on purpose: a word
   too many keeps today's behaviour, and a word too few costs a security
   question its structure.
3. **The operating point is measured on an independent battery and pinned.**
   On questions an independent agent wrote after the vocabulary was frozen:
   9 of 50 plain-language security questions resolve to `general`, 24 of 30
   non-security questions do, and none stays `threat_intel`. A test holds
   those bounds.

**Why accept 18% misroutes.** Live, misrouted security questions still got
security answers: ransomware named and grounded in the KB, isolation steps,
exfiltration and physical-breach handling. They lost only the
Summary/Key facts/Assessment structure. The alternative was today's state:
every non-security question forced into a structure it cannot meet, and
sometimes a refusal.

**Bounds, stated.**
- A misrouted security question is reported `contract_valid: true`, because
  `general` has nothing to drift from. Contract drift is not observable for
  those turns.
- The vocabulary is English and was measured on English questions.
- Approach 1 (security words alone, 15/40 misroutes out of sample) was the
  first of the two attempts the thrash brake allows. This is the second.

**What this supersedes.** The S9 catalog's "six modes ONLY", by adding a
seventh through the decision that rule asked for.

## D-045 — The chat agent may propose the platform's actions; a dry run that would change nothing is not filed (2026-10-11, S27)

**Context.** IDEAS (S26). S18 built the action proposer and the approvals
surface. D-037 put the agent loop on `/api/chat` with READ tools only, so the
agent could read and never propose (README honesty section; STATE follow-up
8). Burhan put it in S27's scope at the start ritual. Record:
docs/probes/2026-10-11-s27-chat-actions.md.

**Decision.**
1. **The chat agent gets the app's action manifest and proposer.** It is the
   same registry the approvals surface executes from, so a proposal filed in
   chat is one the executor can find. D-014 is unchanged: calling an action
   dry-runs it and files a pending proposal, and nothing in the turn can
   execute it.
2. **The turn shows the proposal.** The tool frame carries the proposal id and
   the card's dry-run summary, which is the sentence the approver will read,
   never the model's account. The summary is scanned on the tool channel
   before it is shown. The page shows it outside the Thinking pane, which
   folds away when the answer starts.
3. **A dry run that affects nothing is not filed** (`NothingToPropose`, in the
   proposer, for every caller). Such a card can only be rejected, and its
   execution can only fail, so it would spend a human's decision on nothing.
   The model is told the action's own dry-run sentence, so it can correct the
   call or say so. Only that deliberate, code-written reason crosses to the
   model; any other proposer exception is still reported by class alone.

**Why.** The approval gate, the card, the fingerprint re-check and the undo
rail (D-014, D-023, D-041) are what make a model-initiated action safe, and
all of them were already real. Offering actions from chat changes who can ask
for one, not what happens before one runs. Live: one explicit ask filed one
correct proposal, and two turns that did not ask filed none.

**Found on the way.** The real proposer returns the row's id as a UUID
object. The loop fed it back to the model inside JSON, and the turn died
(`9130c39`). Every earlier test had used a double that returned string ids.

**Bounds, stated.**
- A proposal can only target an observable the workspace already has. The
  agent path's enrichment does not persist observables; the 92/8 IOC check
  does.
- The rail does not scan the approvals surface, which serves the stored,
  code-rendered card.
- In the narrative modes an action-request turn may not match its mode's
  contract (live: `ioc_enrichment`, `contract_valid: false`). That is
  reported, not repaired.
- The proposal is filed before the tool frame is scanned. A turn the rail
  cuts at that frame can still leave a pending proposal, which the approvals
  queue shows like any other.

**What this supersedes.** Nothing ratified. It retires the README's "The
agent reads, it does not act" and STATE follow-up 8.

## D-046 — A tool may declare a per-turn budget; `search_knowledge` gets 3 (TD-043) (2026-10-11, S28)

**Context.** TD-043 (S27): on topics the curated KB covers thinly, agent turns
searched until the step cap, 9 inference calls for one turn. TD-043 named three
candidate fixes and chose none until the cause was measured. Record:
docs/probes/2026-10-11-s28-td043-search-budget.md.

**Measured first.** On S27's prompts, 0 of 31 re-searches were misses.
- Every search returned a full page of five, because the KB has no document
  about the entity asked for (no ATT&CK group or software pages). So it
  returns the nearest generic techniques, the same ones every time.
- The model never sees a miss, so it rewords until the cap.
- That ruled out "a miss that says rewording will not help" (it would never
  fire) and "count distinct-result calls" (27 of 31 searches added
  something).

**Decision.**
1. **A tool may declare `max_calls_per_turn`** (`Tool`, `ToolRegistry.add`).
   It is declared with the tool, because whether a repeat call can find
   something new depends on what the tool looks up. The default is no budget;
   the step cap still bounds everything.
2. **`search_knowledge` declares `SEARCH_KNOWLEDGE_MAX_CALLS = 3`.** It is a
   code constant (D-026). The id lookups (`enrich_observable`, `lookup_cve`)
   are bounded by their inputs and declare none.
3. **Enforced by structure.**
   - Once spent, the tool is no longer offered on the wire.
   - A call to it anyway is refused with `call_limit` without running the
     handler. glm-4.5-air made such a call from its history on every thin
     turn, so withdrawal alone is not the guarantee.
   - The result of the last allowed call says it was the last.
   - `run` and `run_stream` share the counting.
4. **The rail's index is unchanged.** No system or description text changed.
   The refusal and the notice are tool-result text, which D-031 leaves
   unindexed as data.

**Why.** Each call is the customer's inference (D-005), and the `default`
workspace's ceiling of 100 an hour was 11 such turns. On the same prompts:
- calls went 37 → 23;
- step-cap hits went 3 → 0;
- every answer still met its contract (6/6);
- the ATT&CK-shaped question that searched once is unchanged.

**The price, stated.** With three searches, the LockBit turns no longer reach
the T1566 Phishing page. Before, the model reached it at search 4–5 once its
queries moved to technique words.
- The Initial Access tactic page, returned first on every LockBit turn, names
  spearphishing, exploiting public-facing servers, valid accounts and
  external remote services.
- So the vectors are still grounded, just less specifically.
- De-duplicating results within the turn, and a budget of 5, were both
  measured and neither restored it. The cause is KB coverage (IDEAS).

**Bounds, stated.**
- A model that would have changed strategy at search 4 no longer gets to.
- A thinly covered topic still costs up to 5 calls: 3 searches, possibly 1
  refused call, then the answer.
- The refused call shows in the turn as `→ search_knowledge(…) · error`.

**What this supersedes.** Nothing ratified. It resolves TD-043.

## D-047 — The identity shortcut answers questions about who made the assistant and what it runs on; D-002 is kept (2026-10-11, S28)

**Context.** The S28 review of S27's code (docs/probes/2026-10-11-s28-s27-code-review.md)
sent four identity questions through the rebuilt container: "which company made
you", "what model are you running on?", "what LLM powers this platform?" and
"who trained you". None took the identity shortcut. All four went to the model
as `general` turns, and **4 of 4 answers said the platform is Claude by
Anthropic**.
- That is false: the dev engine is glm-4.5-air.
- It breaks D-002 (the brand).
- It is stored and replayed.

The shortcut's coverage predates S27.

**Burhan's calls at S28.**
- First: fix it, answering "I'm Auspex, powered by <the configured model>".
- That overturns D-002's "never leak the underlying model/provider name into
  user-visible strings", so per protocol the question was put back as
  overturn or drop. **Burhan chose to drop it: D-002 stands.**
- The identity answer names the platform's engine, never the model.

**Decision.**
1. **`_IDENTITY_RE` is widened by its own rule** (`auspex/classify/classifier.py`).
   - The whole message must be the question, at most 80 characters.
   - It must point at the assistant: "you", or "this assistant / co-analyst /
     chat / bot / platform".
   - New shapes: who made, trained, developed or owns the assistant; what
     model, LLM, engine or company is behind it; are you / is this <a known
     model or maker>; what is it built on.
   - Two precision rules came from hard negatives:
     - a bare "this" counts after an AI word ("which AI is this?") but not
       after a company, provider or vendor ("which company is behind this?"
       is a follow-up about a domain);
     - "is this X" fires on a model's own name, not a company's ("is this
       google?" may be about an IP range).
   - Errors still bias DEEP.
2. **The identity copy says what it runs on without naming it:** "I'm Auspex —
   a security intelligence co-analyst, running on the platform's engine." The
   shortcut-copy brand test, which forbids even the word "model", still holds.

**Judged on an independent, held-out battery (D-044's discipline).** Two
agents that never read the repo each wrote 45 identity questions and 45
confusable analyst questions. Battery A shaped the rule. Battery B was opened
once, after the rule was frozen. Logs: `docs/probes/s28-identity/`.

| Rule | A: identity caught | A: false positives | **B: identity caught** | **B: false positives** |
|---|---|---|---|---|
| before | 3/45 | 0/45 | **0/45** | **0/45** |
| D-047 | 45/45 (training) | 0/45 | **18/45** | **0/45** |

The operating point is pinned by
`test_the_identity_operating_point_on_the_held_out_battery_holds`. The four
live questions are pinned verbatim.

**Bounds, stated.**
- **27 of 45 held-out identity questions still miss** and reach the model,
  which may still name another vendor. Examples: "how were you trained",
  "what version are you", "is this openai", "ur made by google?", "Could you
  tell me which large language model you are?".
- Enumerated sentence shapes do not generalise far (A 45/45, B 18/45).
- A wider bag-of-words rule (any "you" plus any identity word) was considered
  and not built. It gives up "errors bias DEEP": "do you know who built this
  tool?" would become a canned bio.
- Any improvement claim now needs a fresh battery, because A and B are both
  known.
- Nothing guards the model's own self-description on a miss. That is the
  unowned brand gap (STATE follow-up 11), now in the answer as well as the
  Thinking pane.

**What this supersedes.** Nothing. D-002 is re-affirmed, not amended.

## D-048 — An approval no run ever started rejoins the queue, with two doors: run it now, or withdraw it (TD-042) (2026-10-11, S28)

**Context.** TD-042, found by the S27 review and reproduced in
`docs/probes/s27-review/probe_approved_wedge.py`. `approve` settles the row,
then runs it a few awaits later. If the process dies in between, the row is
`approved` with no claim:
- it is not in the queue;
- `reject`, `abandon` and `keep` all refuse it;
- the only execute path is approve, which needs `pending_approval`.

The same row is the honest end of an execute-time refusal (the declaration or
its risk changed since the approval). TD-042 left the door to a decision,
because running an approval given an hour ago is a question about what an
approval means once time has passed. D-045 lets the chat agent file proposals,
so this path will see traffic.

**Burhan's call at S28:** both doors, and a withdrawal is its own status.

**Decision.**
1. **The queue lists it once it is stale.** `pending()` now also returns an
   `approved` row with `claimed_at IS NULL` and `decided_at` older than
   STALE_CLAIM_SECONDS (300 s), the threshold `abandon` already uses. Before
   that, the approve request's own run may still be about to claim it.
2. **Run it now:** `POST /api/proposals/{id}/execute`
   (`ActionExecutor.run_stale_approval`).
   - No claim was ever taken, so no handler ever started: it is safe to run.
   - It is the same run approve makes, through one shared `_run_claimed`:
     `check_executable` again (approved, risk still gated, declaration
     unchanged), then the claim, then the handler.
   - The claim is the only difference:
     - it takes only a stale, unclaimed approval;
     - it writes the human pressing it to `resolved_by`/`resolved_at`.
     Running an old approval is a decision made now. The approval stays in
     `decided_by` (S27's rule).
   - A refusal is a 409 (404 for no such proposal), because nothing else
     happened in the request. That differs from approve's 200, where the
     approval itself did happen.
3. **Withdraw it:** `POST /api/proposals/{id}/withdraw`
   (`ProposalSettlement.withdraw`).
   - It moves to a new terminal status, `withdrawn`: approved, then retracted
     before anything ran.
   - Not `rejected`, because that is the decision not to approve, and this
     row was approved: `decided_by` keeps saying by whom.
   - The withdrawer lands in `resolved_by`.
   - Nothing ran, so there is nothing to put back. `undo` refuses it like any
     other row outside UNDOABLE_FROM.
4. **Both doors are claim-first and stale-only.** One UPDATE moves the row out
   of `approved` only if it is unclaimed and older than the threshold. Two
   humans pressing the two doors at once get exactly one answer, pinned by a
   race test. A fresh approval is refused by both: `not_stale`, or a 409 that
   says its own run may still be starting.
5. **One status-CHECK block, edited in place** (D-041's rule). `withdrawn` was
   added to the only block that defines `proposals_status_check`.
   `test_startup_survives_every_status_a_proposal_can_be_in` reads the live
   constraint, so it covers the new status unedited.

**Why both.**
- A row refused at execute time can never run again: its declaration changed.
  So withdraw must exist.
- A row orphaned by a crash was approved for a reason, and re-running it
  re-checks everything the approval was given under. So run-now earns its
  place.
- Making the human press it again, now, answers TD-023's worry about stale
  intent.

**Bounds, stated.**
- **A row refused at execute time must wait out the threshold** before it can
  be withdrawn, even though its refusal was immediate.
- **`resolved_by` is the latest human resolver.** A run started from this door
  that then goes `incomplete` and is kept or abandoned overwrites it with
  that later human.
- **There is no page UI for any approvals door yet** (as with `abandon` and
  `keep`). The doors are API routes.
- **TD-025 still stands.** There is no idempotency key, which matters the day
  an action reaches a network.

**What this supersedes.** Nothing ratified. It resolves TD-042.

## D-049 — What the agent looks up is recorded, the way the IOC check records it (2026-10-11, S28)

**Context.** IDEAS (S27), and D-045's first stated bound: a proposal can
target only an observable the workspace already has. Only the 92/8 IOC check
recorded observables and verdicts (`persist_enrichment`). An analyst who asked
the chat agent to check an indicator and annotate it got the check, and then
the annotate call was refused as `NothingToPropose`, unless they had run the
shortcut first. Burhan put it in S28's scope at the start ritual. Record:
`docs/probes/s28-candidates/`.

**Decision.**
1. **`enrich_observable` records what it looked up.**
   `build_capability_registry` takes a `record` callable, and the chat route
   passes the same `persist_enrichment` the IOC check calls, bound to the
   turn's workspace. The observable is upserted, and a verdict row and its
   falsification watchers are written when the signals synthesise one.
2. **Only what was looked up is recorded.** That means `outcome.enriched`,
   which only ever holds indicators D-039 let through: from the analyst, or
   from a knowledge-base record. The model cannot make the platform record an
   indicator it composed. Skipped indicators are not recorded, for example
   reserved address space, which enrichment does not look up. The IOC check
   behaves the same way.
3. **The model is told whether it was recorded** (`recorded: true/false` in
   the tool result). A failed write is logged and said, never claimed, and the
   computed results still return: the IOC check's S5 rule. With no `record`
   (probes, tests), nothing is recorded and nothing is said.
4. **The tool stays READ.** The write is the platform's own bookkeeping of a
   lookup it made, the same as on the shortcut path. It is not an action the
   model chose, so D-014's gate does not apply. The module docstring says so.

**Why.** Live through the rebuilt container: one turn named an IP the
workspace had never seen and asked for it to be checked and annotated.
`enrich_observable` recorded the observable, and the same turn filed the
annotate proposal (rejected as cleanup). Before D-049 that proposal could not
be filed.

**Bounds, stated.**
- **Every enrichment the agent runs now writes.** A turn that checks five
  supplied indicators adds five observables and their verdicts to the
  workspace, exactly as an IOC check of the same five would.
- The verdicts feed Living Verdicts (retro-hunts, falsification watchers) like
  any other.
- Indicators learned from a knowledge-base record this turn (D-039) are
  recorded too, if the agent looks them up.

**What this supersedes.** Nothing ratified. It retires D-045's first bound
and the IDEAS line.

## D-050 — A note request is a deep turn, and a note-only request gets its own mode, `action_request` (2026-10-11, S28)

**Context.** IDEAS (S27): live, "add a note to X" resolved to `ioc_enrichment`,
could not fill its sections and read `contract_valid: false`. Burhan put it in
S28's scope at the start ritual. Measured first, on two batteries written by
agents that never read the repo (`docs/probes/s28-candidates/`). The problem
was larger than the drift:
- **9–10 of 30 note-only requests took the IOC-check shortcut.** No model ran,
  the analyst got an enrichment answer, the note was never proposed, and
  nothing said so.
- 6 of 20 requests that asked for analysis AND a note took the shortcut too.
- The rest landed in narrative modes they could not fill.

**Decision.**
1. **A note request never takes the shortcut.** `asks_for_note` in the
   classifier finds the ask anywhere in the message (add/attach/leave/put/
   write/record a note or comment, annotate, jot/mark down on, record
   against, with a note, "pls note", update the notes on). It makes the turn
   DEEP, as the analytical-verb veto does: proposing the note needs the model.
2. **A message that LEADS with that ask is note-only and resolves to a new
   mode, `action_request`** (`is_note_request`, resolver step 2b, after the
   two format steps).
   - A mixed request asks its question first ("check X and add a note"), so it
     keeps its analysis mode.
   - The contract has no sections. Its directive says the change can only be
     proposed for a human to approve, and that the answer must never say it
     was made.
   - The directive is compiled into the turn and indexed by the rail like
     every mode directive.
3. **An eighth mode is a scope decision** (D-044's rule), made here.

**Judged on a held-out battery.** Battery B was opened once, after the rule
was frozen.

| | before | after |
|---|---|---|
| note-only → `action_request` | 0/30 | **19/30** |
| note-only → IOC shortcut | 9/30 | **3/30** |
| mixed → shortcut | 6/20 | **0/20** |
| mixed → `action_request` | 0/20 | **0/20** |
| not-action → `action_request` | 0/30 | **0/30** (routing unchanged) |

Battery A shaped the rule (training data): 29/30, and 0 false positives. The
operating point is pinned by
`test_the_action_request_operating_point_on_the_held_out_battery_holds`.

**Bounds, stated.**
- **11 of 30 held-out note-only phrasings still miss**, and route exactly as
  they did before. Examples: "append to the notes on X", "X — note: …",
  "remark on X", "INC-4520: attach a note…". 3 of those still take the
  shortcut.
- A note-only request is also routed to `action_request` when it asks for
  something the platform cannot do ("add a comment in Jira…"). Its contract
  then has the answer say why nothing could be proposed.
- A request that leads with the note and asks a question afterwards loses its
  analysis sections. That is structure, not substance (D-044's trade).
- Any improvement claim needs a fresh battery.

**What this supersedes.** Nothing ratified. It retires the IDEAS line.

## D-051 — Sessions run in three tracks: backend, front end and bugs (2026-10-12, between S28 and F1)

**Context.** On 2026-10-10, after S28's session-end ritual had committed the
S29 prompt, Burhan used the page by hand and said: "before moving on with more
backend development we need to improve on the FE so lets shift our focus there
and pause BE for a bit." He named two problems: deep turns' reasoning streams
very slowly, and an IP was said to be Amazon's when it is not (B-001). The
window that started on them died a minute later. Nothing reached the repo, so
the next session's prompt was all backend and nobody would have known
otherwise. Recovered on 2026-10-12 from the session transcript. Two structural
causes:
- There was one prompt file, so a pivot had to overwrite the backend plan or
  be lost. There was no place for a front-end or bug session to be queued.
- The session-end ritual ended at its summary, so a decision said after it had
  nowhere to go.

**Decision (Burhan's call; the shape proposed and the two open choices put to
him).**
1. **Three tracks, each with its own prompt and its own session ids.**
   - Backend: `NEXT-SESSION-BE.md`, renamed from `NEXT-SESSION.md`, ids S<n>
     (it continues at S29).
   - Front end: `NEXT-SESSION-FE.md`, ids F<n> from F1.
   - Bugs: `NEXT-SESSION-BUGS.md`, ids B<n> from B1.

   The rename is Burhan's choice: an unsuffixed file reads as "the" next
   session, and the old habit of pasting from it would quietly start backend
   work.
2. **`/session-start` takes the track**: `be`, `fe`, `bugs`, or an id whose
   prefix names it. **With neither it asks; it never picks** (Burhan's choice
   over defaulting to backend: a silent default is exactly the accident the
   tracks exist to prevent).
3. **Standing rules live once, in `SESSION-RULES.md`.** About 150 of the 198
   lines of the S29 prompt were not about S29. Three copies would drift.
4. **One `STATE.md`.** The code, the tests, `staging` and the promotes are
   shared by every track, so it gains a Tracks table (last closed, next id,
   focus) and stays the only home for moving numbers. A prompt points at
   STATE.md instead of copying them.
5. **`BUGS.md` is the bugs track's list**, and `/bug` adds to it mid-session
   without breaking scope lock. The repo has no GitHub issues to hold them.
6. **`/session-end` writes only its own track's prompt**, then fixes anything
   it made untrue in the other two. A scope or focus change said after the
   ritual is written down before the window closes.
7. **One session at a time.** All tracks share `staging`, the compose stack and
   the `analyst@auspex.dev` test user.

**Bounds, stated.**
- The ids are checked against STATE.md by a test (`tests/test_docs.py`), but
  the rules in `SESSION-RULES.md` are only as current as the sessions that
  edit them.
- The focus is recorded in STATE.md for information. `/session-start` reports
  it and does not enforce it: starting a paused track is allowed when Burhan
  picks it.

**What this supersedes.** Nothing ratified. It changes the CLAUDE.md working
protocol (one prompt file, rule 12) and the `/session-start`, `/session-end`
and `/briefing` commands.

## D-052 — The stream says what a turn is waiting on, and the page paints it paced within 200 ms (2026-10-12, F1)

**Context.** Burhan, 2026-10-10: deep turns' reasoning streams very slowly,
"we should perhaps increase the stream bit rate so it renders faster". F1
measured three layers on the same runs before changing anything
(docs/probes/2026-10-12-f1-stream-layers.md):
- **the server** adds about 1 ms per delta (p50; 4.6 ms at most);
- **the page** about 3 ms to paint (p50; 41 ms at most), with no long tasks;
- **the endpoint** is the rest. glm-4.5-air streams about 1000 chars/s in
  bursts, but an agent turn waits 1-3 s before each of its 3-5 model calls
  (once 12.9 s). qwen3:14b streams 139-171 chars/s.

What the analyst feels as slow is the silences: the page shows nothing
changing while the engine starts its next call, runs a tool, or (D-043) writes
an answer it is holding. No change to the stream or the painting makes the
endpoint faster.

**Decision (Burhan's call, from options F1 put to him; all four picked).**
1. **A `status` frame on `/api/chat`, sent before each wait.**
   - `{"status": {"phase": "engine"}}` before every model call: each agent
     step, the step cap's synthesis pass, the native call, both two-pass calls
     and a D-043 re-ask. It goes after the call's claim, so a refused call is
     never announced.
   - `{"status": {"phase": "tool", "tool": <name or null>}}` before each tool
     dispatch.
   - `{"status": {"phase": "held"}}` once, when a held answer's first delta
     arrives.

   The frames carry our literals only. A tool is named only when the loop
   offers it (`AgentLoop.knows`), because the name in a call is model output.
   So there is nothing for the output rail to scan. Frames keep emission order
   (D-031). Clients that do not know the frame ignore it.
2. **A working indicator on the page.** It runs from Send, and again during
   any silence over 1 s, ticking the seconds. It names the phase in fixed copy
   and never names the engine (D-002).
3. **Bounded pacing on the page.** Arrived frames go through one ordered
   queue. Text is released smoothly on animation frames, but **nothing waits
   longer than 200 ms**. Done, an error or the end of the stream flushes at
   once, and a hidden tab paints unpaced. Only already-scanned text is paced.
4. **The dev switcher's local endpoint is labelled "Local (slow)"**, not
   "Deep — shows reasoning". "Standard" shows its reasoning too, and the old
   label sent analysts to the slowest endpoint.

**Bounds, stated.**
- **Pacing adds up to 200 ms to every character on the screen.** Burhan chose
  it knowing that. The bound is what makes it acceptable, and a test holds it.
- **The indicator tells the analyst what is being waited on, not how long.**
  Nothing predicts the endpoint's latency.
- **A status frame is an announcement, not a result.** Whether the tool ran is
  still the `tool` frame's job.

**What this supersedes.** Nothing ratified. The SSE protocol gains a frame
kind, and `AgentStreamEvent` gains the `phase` kind.

## D-053 — Answers render a safe subset of markdown, with https links that show where they go (2026-10-12, F1)

**Context.** Answers are written in markdown (`## Risk`, `- **TTP**: …`,
`` `T1558.003` ``), and the page has shown them as raw text since S3. An
analyst reads `**` and `##` on every deep turn (seen in F1's screenshots).
Rendering markdown from model text was recorded as "a decision, not a
refactor" (SESSION-RULES.md, The page): until now, model text reached the page
only as text.

**Decision (Burhan's call; the subset and its safety bounds proposed, links put
to him).**
1. **The answer bubble only.** The Thinking pane stays plain text.
2. **The subset:**
   - headings `#`–`###`;
   - `-`/`*` and numbered lists;
   - `**bold**`;
   - `` `code` `` spans and fenced blocks, in JetBrains Mono (D-002);
   - paragraphs.

   Not rendered: italics (underscores in identifiers such as
   `enrich_observable` would garble), tables, images and raw HTML. They stay
   literal text.
3. **Links are clickable — Burhan's call, over the recommendation to leave them
   literal.**
   - Only `https:` URLs with no embedded credentials become links. They open
     in a new tab with `rel="noopener noreferrer"` and no referrer.
   - Every link shows its real host beside its text (`text ↗ host`), so anchor
     text cannot hide the destination.
   - Anything else (`javascript:`, `data:`, `http:`, `user:pass@`) stays
     literal text.
4. **Model text never becomes HTML.** A pure parser in the page's logic block
   produces a small tree, and the DOM is built from it with `createElement` and
   `textContent` only. An `<img onerror>` in an answer is visible text.
5. **Code spans are neutral.** They use the text colour on a faint Surface
   background, not Signal amber, which D-002 reserves for "suspicious".
6. **Streaming.** The bubble re-renders from the accumulated answer as it is
   painted (D-052), so an unclosed marker stays literal until it closes. What is
   stored is unchanged: the answer's markdown text.

**Bounds, stated.**
- **A poisoned answer can now put a clickable https link in front of an
  analyst.** The host shown beside it is the mitigation, not a prevention.
  The output rail (D-030) catches our configuration coming back out, not a
  malicious URL.
- The subset is what the contracts' answers use today. A model that writes
  tables gets them as text.

**What this supersedes.** Nothing ratified. It changes SESSION-RULES.md's rule
that model text reaches the page only as text: the answer bubble's text now
reaches it as text inside elements the page chose.

## D-054 — Every deep turn records what it spent, and the page shows it per answer and per chat (2026-10-12, F1)

**Context.** IDEAS: "Investigation cost ledger UI (token spend per verdict)".
The customer brings the LLM and pays for it, and the platform never knows the
price. A turn's usage reached the `done` frame and was then discarded. A turn
that ended badly carried none at all: the rail's cut, a ceiling refusal, an
endpoint error. B-002's stopped turns spent 4 engine calls each and left no
trace of it. Most verdicts are code-decided at zero engine calls (the IOC check,
and the alert and phishing scores of D-043), so "per verdict" was the wrong
unit for where the spend is.

**Decision (Burhan's call, from F1's options; both recommended ones).**
1. **The unit is the turn, totalled per chat.** One `turn_spend` row per deep
   turn. It records the chat and workspace, the stored answer when there is
   one, `engine_calls`, input and output tokens, and how the turn ended.
   - **Turns that store no answer are recorded too:** leak, ceiling refusal,
     endpoint error and empty answer.
   - **A shortcut turn records nothing**, because it spent nothing.
2. **Tokens and calls only, no money.**
   - `engine_calls` counts the model calls actually made, the same ones D-052
     announces (after each claim).
   - Tokens are the endpoint's own usage, summed over every call in the turn.
     Before this, the two-pass and switched paths kept only their last call's
     usage.
   - An endpoint that reports no usage leaves the tokens null, never zero.
3. **The page shows** a line under each answer from its `done` frame, and this
   chat's total at the composer. The total comes from
   `GET /api/chat/sessions/{id}/spend`, which is scoped to the caller's
   workspace (a foreign or unknown chat is a 404), so failed turns count.

**Bounds, stated.** A turn cut off by a dropped connection may not reach the
point where it records. The spend row is written at the turn's own ending.

## D-055 — The network a source names is kept beside the verdict, never as one (2026-10-12, B1)

**Context.** B-001: "dig deeper" on 34.187.179.218 answered that it is
Amazon's, "based on WHOIS". It is Google's. AbuseIPDB had named Google LLC on
turn 1 (isp, domain, usage type, country, hostname), and OTX had named
AS15169. The provider returned None on a low score, so the whole answer was
dropped and the IOC check said "unknown to them". On the conversational path,
with no tools and no owner in context, the model supplied one from memory.
Replayed with the owner in context, the answers went from an owner claimed
with no source in 4 of 6 (glm, two of them Amazon) and Amazon in 3 of 3 (qwen)
to Google in 9 of 9, none citing WHOIS (docs/probes/2026-10-12-b1-b001-fix.md).

**Decision (Burhan's call; the recommended option).**
1. **Who operates an address is its own field, `NetworkContext`**, kept on
   each enriched observable (`ObservableEnrichment.network`). A provider
   lookup may return it beside a signal, or alone.
2. **It is never a signal.** It is not synthesized into a verdict and not
   recorded as one. So it can neither supersede nor flip what the workspace
   believes about an indicator.
3. **The IOC check shows it** on its own line with its source, and does not
   say "unknown to them" about an address a source did name. The agent's
   `enrich_observable` result carries it as `network`.
4. **AbuseIPDB supplies it** on every answer that names a network, whatever
   the score.

**Rejected: a context-only signal** (`VerdictLabel.UNKNOWN`, as InternetDB's
open ports). It was one file instead of five, but every clean IP would then get
an `unknown` verdict row. An IP once rated malicious whose sources later say
nothing would flip malicious → unknown; today it keeps its verdict and decays.
That would change Living Verdicts for most IPs to fix a display gap.

**Bounds, stated.** Only AbuseIPDB supplies it (TD-049). The model can still
add what nobody supplied ("likely us-central1"). That is the deferred item on
fabricated specifics, not this decision.

## D-056 — The sign-in survives a reload in the tab's sessionStorage (2026-10-12, F2)

**Context.** F2's goal is that a chat survives a reload. The page held its
token in memory only (`auspex/static/index.html`, `let token = null`), so a
reload signed the analyst out as well as losing the chat, and B-003's fix makes
reloading normal after every deploy.

**Decision (Burhan's call; the recommended option).**
1. On sign-in the page stores the token in `sessionStorage` under
   `auspex.token`. It survives a reload in the same tab and is gone when the tab
   closes. The token's lifetime is unchanged (`jwt_ttl_minutes`, 12 h).
2. On load, a stored token is checked with `GET /api/auth/whoami`. A 401 clears
   it. Every storage call is in a try/catch, so blocked storage leaves the page
   as it was before.
3. A **Sign out** button clears it.

**Rejected.**
- *Sign in again after every reload:* no security change, one step per deploy.
- *localStorage:* the token would outlive the tab and be shared across tabs.
- *An httpOnly cookie:* scripts could not read it, but the server would read a
  cookie and every POST would need CSRF protection: more than F2.

**The risk this accepts.** Any script running on the page can read the token.
The page sends no Content-Security-Policy (`auspex/routes/ui.py` sets only
`no-cache`), so the one guard is D-053's rule that model and tool text never
become HTML. A CSP is TD-051.

## D-057 — The chat page carries a strict Content-Security-Policy (2026-10-12, F2)

**Context.** D-056 keeps the sign-in token in the tab's `sessionStorage`, where
any script running on the page can read it, and the page sent no CSP (TD-051).
TD-045's split moved every script and style rule out of the page, so a policy
needs neither `'unsafe-inline'` nor a hash per edit.

**Decision (Burhan's call; the recommended option).** `GET /` is served with
`default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com;
font-src https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:;
object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`.
- Scripts only from the page's own origin: an injected `<script>` or `on…=`
  does not run.
- Fetches only to the platform: an injected script that did run could not
  `fetch()` the token elsewhere. It could still carry it out by navigating
  (`location`, `window.open`, a link), which a CSP does not restrict; the
  guard against a script running at all is `script-src 'self'` and D-053.
- No framing, no `<base>`, no form posts, no plugins.
- The page's styles set through the CSSOM (`el.style.display`) are not governed
  by a CSP; the markup has no `style=` attribute.
- Links in answers (D-053) are navigation, which this does not restrict.

**Bounds, stated.** `/timeline` has no CSP yet: it still runs an inline script
(TD-051 narrows to it). A new external origin (a CDN, an analytics host) needs
a D-entry, not an edit to the header.

## D-058 — A thinking model may restate the answer it was told to write (2026-10-13, B2)

**Context.** B-002: "What are the practical differences between EDR and XDR
for a small SOC deciding what to buy?" resolved to `definition` and was cut by
the output rail in 3 of 4 agent-path turns at F1. The route logged a 40-word
match from the definition contract's section list on the `thinking` channel,
exactly `THINKING_SHINGLE_WORDS` (D-040). B2 measured why
(docs/probes/2026-10-13-b2-b002-reproduce-and-calibrate.md):
- **A thinking model plans its answer by restating the sections it was told
  to write** ("Let me structure this according to the requested format: …"),
  in every one of B2's six live runs of the question.
- **The rail's tokeniser drops punctuation, so a section list is ONE run.** It
  is 43 words for definition and 42 for threat_intel. D-043's re-ask,
  rendered for an empty draft, is 42 (alert_triage) and 44
  (phishing_analysis). Each is longer than the floor of 40.
- **Whether a turn is cut depends on one or two words.** At F1 the restatement
  was verbatim. At B2 it said "each term" and "meets them", so its longest run
  was 11 and 0 of 8 turns were cut. The configuration was byte-identical to
  F1's; the KB results the model read differed.
- **Today's legitimate ceilings** (36 turns, S26's battery and a blind one,
  today's issued text): thinking 28, every run above 20 a restated section
  list; against everything else we issue, **20**. Answer 5, narration 3, tool
  lines 3. A recitation ran **58**. S22's answer floor re-measured: 5 against 8.

**Decision (Burhan's call; the recommended option).**
1. **The directives that tell the model what to write are `answer_shape`**:
   the mode contract's directive and, on a held turn, D-043's re-ask
   (`auspex/routes/chat.py`).
2. **The thinking channel's index leaves `answer_shape` out.** Everything else
   we issue stays in it, at `THINKING_SHINGLE_WORDS = 40` (unchanged): the
   system message, every tool, parameter and action description, the history
   fence, the step-cap nudge, PASS1_DIRECTIVE.
3. **Every other channel still indexes `answer_shape`**, at `SHINGLE_WORDS = 8`
   (unchanged): the answer, narration, the tool lines, a two-pass analysis. A
   section list written into the answer is still a leak.
4. The scan is not skipped on any channel, and the guard regex is untouched
   (TD-031/032/033).

**Rejected.**
- **A thinking floor of ~50**, between the longest answer-shape run (44) and
  the recitation (58): about 1.15× each side, on one model. The next field
  added to a contract, or a plan that also restates the 16-word preamble
  ("Structure your answer with these plain-text sections …", 59+ words),
  reopens it.
- **Shortening the contracts under 40.** It changes what the model is told
  (and so the answers and the contract tests), fixes three instances rather
  than the class, and phishing_analysis is already at 39.

**What it costs, stated.** A recitation of ONLY the answer-shape directives
in the Thinking pane is no longer cut. That text describes the answer's
sections, which the answer itself shows. Thinking is never stored. A dump that
also reaches the system message or any tool description is still cut, and so
is the same text in the answer.

**What this supersedes.** D-040's thinking floor indexed everything D-031
decision 5 lists. For the thinking channel only, it now indexes that minus
`answer_shape`. D-040's floor and D-030 decision 3 stand.

**Proven.** Seven tests in `tests/test_chat_sse.py`. Three fail before the
fix: F1's exact logged run in the thinking, on the agent and the native path
(fixture `tests/fixtures/rail/b002_definition_section_list.json`), and an
empty draft's re-ask restated in the re-ask's thinking. Four guards pass before
and after: a control; the section list in the answer is still cut; and
recitations of the system message and of the 58-word tool description in
thinking are still cut. Four mutants, 4 caught: the old index, an empty
thinking index, `answer_shape` also left out of the answer's index, and the
re-ask not exempted.
