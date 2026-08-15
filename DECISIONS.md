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
