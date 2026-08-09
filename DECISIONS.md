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
