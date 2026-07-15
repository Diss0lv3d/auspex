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
