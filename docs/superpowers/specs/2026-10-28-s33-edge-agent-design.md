# S33 design — integrations, the Edge Agent, and "Test connection" end to end

_2026-10-28. Owner: Hunaiza (Burhan handed S33 fully, D-059). The contract is
the phase spec (docs/superpowers/specs/2026-10-15-integration-phase-design.md:
D-062, D-063, D-064) and the S33 entry in `NEXT-SESSION-BE.md`. This document
settles what those leave open. Each call is marked **Hunaiza's** or
**Claude's** (taken where the docs were silent, by her standing instruction to
go with Claude's suggestion then). Baseline: docs/probes/2026-10-28-s33-baseline.md._

## Goal

An admin configures an integration (a connector from the catalogue, in one
workspace), enrolls an Edge Agent, and presses "Test connection": a
`connector.test` job is claimed by that agent's container, run in a
subprocess against the reference connector, and its validated result is
shown. Nothing a connector ships runs in the app process (D-062).

## Scope

**In.** Integrations (table, admin API); Edge Agent enrollment and
credentials; the edge API (claim, results, heartbeat, package by hash); the
agent image and its runner; "Test connection" end to end; health from
heartbeats; S32's carries that Test connection needs (the runner's
`ctx.config`, redaction of stdout/stderr, re-hashing, the core importing the
SDK's validators); the `connector.registered` audit event (TD-068); S33's
promote.

**Out (Hunaiza's call: S34, as the plan says).** Running connector ACTIONS:
the action dispatcher, `check_executable` admitting connector systems, and an
approval bound to its integration. `connector.action.*` jobs are not enqueued
in S33. `fetch` schedules are S35's.

## Decisions

1. **An integration names one Edge Agent** (Hunaiza's). The admin picks the
   agent when creating or editing the integration; only that agent may claim
   its jobs, and its health is the integration's. A job never lands on an
   agent that cannot reach the SIEM.
2. **An integration is disabled, never deleted** (Hunaiza's). "Remove" sets
   `disabled_at`; the row stays, and its `prefix` is unique in its workspace
   for ever (a unique index that ignores `disabled_at`), so an approval can
   never later point at a different integration under the same wire name.
   This answers S32's carry "an approval bound to `integration_id`, or a
   prefix never reused" for S34.
3. **The SDK version is not part of a package's identity** (Hunaiza's, D-072;
   PR #43 review #10).
4. **The integration row** (Claude's): `id`, `workspace_id`, `name`,
   `prefix` (a wire identifier ≤ 24, D-064), `connector_id`,
   `content_hash` (pinned: the package this integration runs, chosen from
   what `available()` lists for the workspace; changing it is an edit), `config`
   (jsonb: values for non-secret fields, `secret:<name>` for secret fields,
   D-063), `agent_id`, `enabled`, `created_by`, `created_at`, `disabled_at`.
   `config` is validated against the pinned manifest's config schema on every
   write; a secret field accepts only `secret:<name>`, a value never.
5. **Enrollment** (Claude's, on the `api_keys` pattern the spec names): an
   admin creates an agent (`POST /api/edge/agents` → a one-time enrollment
   token, shown once, valid 24 h). The agent exchanges it once
   (`POST /api/edge/enroll`) for its credential (a random secret, stored hashed
   like `api_keys`), and the token is spent. Revoking an agent
   (`POST /api/edge/agents/{id}/revoke`) refuses its credential at once.
6. **The edge API** (Claude's): authenticated by the agent credential only
   (`Authorization: Bearer <agent credential>`), and reaching only:
   - `POST /api/edge/claim`: a long-poll (holds up to 25 s, retrying the S31
     claim each second) scoped to the agent's workspace and the integrations
     that name it (`ClaimScope(workspace_ids={ws}, integration_ids={…})`);
   - `POST /api/edge/jobs/{id}/result`: the result, with the claim token; the
     core validates it with the SDK's validators before `complete`;
   - `POST /api/edge/heartbeat`: liveness; it also extends the agent's held
     leases (TD-064);
   - `GET /api/edge/packages/{content_hash}`: the package bytes, only for a
     hash one of the agent's integrations pins.
   An agent credential reaches nothing else, and a person's token reaches none
   of these (tests both ways).
7. **Health** (Claude's): from the last heartbeat. Online under 60 s, stale
   under 5 min, offline after. "Test connection" on an integration whose agent
   is offline is refused in words, not queued forever.
8. **The agent** (Claude's): `auspex/edge/`, a separate entry point and image
   (`Dockerfile.edge`) carrying the SDK and the runner, never the core's routes
   or database code (a structural test). A compose service `edge` under a
   `dev` profile. It reads `AUSPEX_URL`, `AUSPEX_AGENT_TOKEN` (or a token file)
   and `AUSPEX_SECRETS_FILE` (a JSON object, mode 0600, name → value; a
   looser mode is refused at start).
9. **The runner** (Claude's): for each job, fetch the package by hash into a
   cache keyed by hash, re-hash it with the SDK's `read_package` and refuse a
   mismatch; then run the command in a subprocess (`python -I -m
   auspex_sdk.run …`, a new SDK entry point the harness and the agent share),
   with a timeout (60 s for `test`), a clean environment, and the secrets
   passed on stdin, never argv or env. `ctx.config` is built the way the
   harness builds it. The subprocess's stdout/stderr are redacted with the
   same secrets before anything leaves the host. A missing secret fails naming
   the secret and the agent, never a value (D-063).
10. **Test connection** (Claude's): `POST /api/integrations/{id}/test`
    enqueues one `connector.test` job (idempotency key per press), answers
    202 with the job id; `GET /api/integrations/{id}/test/{job_id}` answers
    `queued | running | ok | failed`, with the validated result or the error
    in words.
11. **Audit** (Claude's, a new D-entry, TD-068): `connector.registered`,
    `integration.created|updated|disabled`, `edge_agent.created|enrolled|revoked`,
    each recorded in its workspace, in the same transaction as the write.

## Safety, stated

- Tenant isolation: every new table carries `workspace_id`; every route and
  the edge API get cross-tenant tests; an agent never claims, reads or posts
  outside its workspace and its integrations.
- No secret value in any response, log or row: tests scan responses and logs
  for the test secret (D-063).
- The agent is outbound-only; the app never calls it.
- Package integrity: the agent runs a package only after its hash matches the
  job's (D-062); a mismatch fails the job naming both hashes.

## What the plan tasks will be (sizes, not code)

1. The `connector.registered` audit event and D-entry (TD-068).
2. `integrations` table and admin API (config validated, secret names only,
   disable-not-delete, prefix never reused), cross-tenant tests.
3. `edge_agents`: create, enroll, revoke; credential auth; cross-tenant tests.
4. The edge API: long-poll claim, result (validated), heartbeat (leases),
   package by hash.
5. The SDK's shared runner entry point (`auspex_sdk.run`) and public
   validators (moved out of the harness, the harness importing them).
6. `auspex/edge/`: the agent loop, package cache with re-hash, subprocess
   runner, secrets file, redaction of output.
7. `Dockerfile.edge`, the compose `edge` service (dev profile), env vars
   documented.
8. "Test connection" routes and health; structural tests.
9. End to end: the live check through the agent container against the
   reference connector; adversarial review (tenancy, agent auth); promote.

## Settled after the builder check (all Claude's calls; none changes what Hunaiza decided)

1. **The job carries what the agent runs.** A `connector.test` job's payload is
   S32's `ConnectorJobPayload` (`integration_id`, `content_hash`, `command`)
   plus the integration's `config` as stored: plain values and `secret:<name>`
   references, never a secret value (validated at the integration's write, so
   a job row can hold nothing more). The claim response returns the job (id,
   kind, claim token, payload). There is no config endpoint. The agent
   re-validates the config against the pinned manifest before running.
2. **Two kinds of "failed", told apart.** A connector that answers
   `{"ok": false, "detail": …}` is a completed job: the poll says `failed` with
   the connector's `detail` ("the SIEM said no"). A job that could not run (a
   timeout, a hash mismatch, a missing secret, an invalid result, the agent
   offline) is a failed job: the poll says `error` with the reason in words
   ("we could not ask"). The test result is checked with the SDK's
   `check_test` (`{ok: bool, detail: str}`, harness.py:129, made public).
3. **Retries.** `connector.test` is a `JobKind` with `max_attempts = 1` and
   `lease_seconds = 90`: a test is a question asked now, so it is never
   re-run later. The subprocess timeout (60 s) is under the lease. A
   heartbeat extends only the leases this agent holds. A result for a job the
   agent no longer holds (lease lost, or the agent revoked) is refused with
   S31's token check, and the job's own state stands.
4. **One agent, one workspace, one credential.** An agent row has
   `workspace_id`; its credential has no rotation but revoke-and-create. An
   integration may name only an agent of its own workspace (refused
   otherwise, tested). The enrollment token row records its workspace, who
   created it, and when it expires.
5. **Edits against work in flight.** Disabling an integration, changing its
   agent or its pinned hash: queued `connector.test` jobs of that integration
   are cancelled in the same transaction; a running one finishes, and its
   result is still shown. "Test connection" on a disabled integration is
   refused in words. A package is served only for a hash an ENABLED
   integration of this agent pins. Revoking an agent leaves its integrations
   pointing at it, unusable ("agent revoked") until an admin picks another.
6. **Roles and surface.** The integration and agent routes are `Admin`;
   reading integrations and their health is `AnyRole`. The enrollment token
   is returned once, in the create response only. Health is a field on the
   integration and agent reads. No page in S33: the page is F5's.
7. **What the live check reaches.** A small stub SIEM in compose (`mock-siem`,
   dev profile) that serves the reference connector's `/api/health` over
   HTTPS with a self-signed certificate made at start. The live check pins
   that certificate's SHA-256 in the integration's config, so it also proves
   D-071's pin path. The `edge` container shares the dev network with it. The
   subprocess's clean environment means no inherited env vars or proxies, not
   a network sandbox: egress control is the host's (D-062's bound).
8. **Idempotency and ownership.** Each press makes a new job (the key is
   server-made, `test:<integration>:<uuid>`). At most one queued or running
   test per integration: a press while one is in flight answers 409 with that
   job's id. The poll checks that the job belongs to that integration in the
   caller's workspace.
9. **Secrets file and the runner's contract.** The agent re-reads the
   secrets file per job (a rotation needs no restart) and refuses a mode
   looser than 0600. `auspex_sdk.run` reads one JSON object on stdin:
   `{command, config, secrets, arguments}`, and writes one JSON object on
   stdout: `{result}` or `{error}`. Redaction is by value, with the SDK's
   existing minimum secret length (a shorter secret is refused at start).
10. **Audit.** `connector.registered` is written on each `register` that
    inserts a row, in the registering workspace, the actor the registering
    user (or the CLI for first-party). `edge_agent.enrolled` is recorded with
    the agent as the actor (no user), in its workspace.
