# S32 — The connector contract, the SDK and the catalogue (design)

_Session S32 (backend), owned fully by Hunaiza (D-059; Burhan handed it
2026-10-22, every call included). Written 2026-10-22. Builds on D-060 (the
words), D-062 (where connector code runs), D-063 (credential custody), D-064
(the contract v1) and D-065 (the jobs queue); the phase spec is
docs/superpowers/specs/2026-10-15-integration-phase-design.md. The baseline
this is written against: docs/probes/2026-10-22-s32-connector-baseline.md._

**How each decision is marked.** "D-0xx" means a ratified decision already
says it. **"Hunaiza's call"** means a question D-064 or the S32 prompt left
open: Claude proposed it, and Hunaiza took the proposal when Burhan's answers
did not come back (2026-10-22). Burhan may still overturn any of them before
the close.

## Why

The integration phase builds alerts and case management on **connectors**
(D-060): small packages that link the platform to a security tool (QRadar
first), so it can fetch alerts from it and act in it. Customers, MSSPs and
Auspex all write them (the phase spec), so S32 settles a contract other people
will build against. A contract changed after people build on it breaks their
connectors, which is why it is settled first, typed, and tested by rule.

S32 delivers four things and runs nothing: the **manifest** (what a connector
declares), the **SDK** (how one is written and built), the **catalogue** (which
connectors a workspace has), and one **reference connector** proving the path.
S33 runs connectors (Edge Agent, integrations, "Test connection").

## Goals (S32's done line, from the plan)

1. **Manifest v1 types**, exactly as D-064 lists them.
2. **`validate_manifest` refuses with exact reasons**, one table-driven test
   per rule.
3. **A manifest action compiles to an `ActionSpec`** that passes `validate_spec`
   unchanged; wire names are prefixed per integration; **the spec fingerprint
   includes the connector id and the package hash.**
4. **The SDK**: decorators, a typed context, an HTTP client limited to declared
   hosts with TLS pinning, logs that redact secrets, a local harness;
   **`auspex-sdk build` turns Python or YAML into the same manifest.**
5. **The catalogue**: an admin registers a content-hashed package in a
   workspace; first-party is set by the catalogue.
6. **A reference connector** passes the harness against a mock HTTP service,
   built both ways to the same manifest.
7. **Structural tests**: the app never imports connector code; the core never
   reads YAML.

## Non-goals (scope lock; S33 and later)

- Running anything a connector ships: no Edge Agent, no job handlers for
  connector kinds, no integrations table, no "Test connection" (S33).
- Configuring a connector in a workspace (an **integration**, S33), its
  secrets (D-063, S33) and its grants (S34).
- Fetch schedules, alerts and routing (S35), QRadar itself (S36).
- Any page (F5).

## Anti-goals (it fails even if it "works" when…)

- **Connector code runs in the app process**, or the app imports it (D-062).
- **The core reads YAML** or trusts anything a connector declares about
  itself that the catalogue should decide (first-party, D-064).
- **A secret value** can be written into a manifest, a log line, or a
  catalogue row (D-063: secrets are names).
- **TLS verification can be turned off** by any spelling (D-064).
- **The same connector built from Python and from YAML** gives two different
  manifests. (Their content hashes DO differ, rightly: the `.py` files differ,
  and the hash is the code's identity. See decision 10.)
- **An approval survives a change to a connector's code** (D-064 closes D-024's
  handler-body gap for connectors).

## Who writes connectors (from the phase spec)

Customers, MSSPs and Auspex. The first are Auspex's own (QRadar, S36), so the
SDK is built for a capable Python developer first and documented so a
customer's engineer can follow it. **Python-first and YAML are both v1**
(D-064).

## Decisions

### 1. Where the SDK lives, and who owns the manifest types — Hunaiza's call

- **A second distribution in this repo:** `sdk/`, its own `pyproject.toml`,
  distribution name `auspex-sdk`, import package `auspex_sdk`, console script
  `auspex-sdk`. Installed with `pip install ./sdk` (editable in dev). Python
  3.12, like the core. Dependencies kept small: `httpx` (already the core's)
  and `PyYAML` (YAML authoring only).
- **The manifest types and `validate_manifest` live ONCE, in
  `auspex_sdk.manifest`**, pure Python with no I/O. **The core depends on
  `auspex-sdk`** and imports `auspex_sdk.manifest` to read and validate
  `manifest.json`. One definition serves the author's build and the core's
  registration (D-064 "specs over prompts": nothing written twice). The core
  never imports the SDK's build, YAML, harness or runtime modules (a
  structural test, Goal 7).
- **The Edge Agent image (S33) carries the SDK**, because a connector's
  handlers import it at run time (decorators, context, HTTP client).
- `ci.sh` installs both; the Dockerfile installs `./sdk` before the core; the
  module-count and package-list rules (SESSION-RULES.md) apply to both.

### 2. What a package's content hash covers — Hunaiza's call

- **A package** is a zip produced by `auspex-sdk build`, holding
  `manifest.json` plus the connector's Python files and any data files under
  its package directory. Excluded: the YAML source (it compiled into
  `manifest.json`), tests, caches (`__pycache__`, `*.pyc`), dotfiles.
- **The content hash is a tree hash, not the zip's bytes**: SHA-256 over the
  sorted list of `"<posix path>\0<sha256 of the file's bytes>\n"` lines for
  every file in the package. Zip quirks (timestamps, compression, ordering)
  therefore cannot change a connector's identity, and the core and S33's agent
  each recompute it from the files. `sha256:<hex>` is how it is written.
- **The core never trusts a hash it was given**: on registration it recomputes
  the hash from the zip's contents (reading bytes, never importing or
  executing), and refuses a package whose `manifest.json` is missing, invalid,
  or carries files outside the rules (absolute paths, `..`, symlinks, more than
  a size cap). Caps are code constants (D-026): **5 MB per package, 1 MB for
  `manifest.json`, 500 files.**
- **A changed package is a new identity** whatever its semver says (D-064);
  registering the same `id` and `version` with a different hash is refused
  ("bump the version"); the same hash twice is a no-op.

### 3. The catalogue, and whether a provider offers connectors to its clients — Hunaiza's call

- **Table `connector_packages`**: `id`, `workspace_id` (D-008: every row
  belongs to one workspace), `connector_id` (`ibm.qradar`), `version`,
  `content_hash`, `manifest` (jsonb, as validated), `package` (bytea, the zip,
  for S33's pull-by-hash), `first_party` (bool), `offered_to_clients` (bool),
  `registered_by`, `created_at`; unique on (`workspace_id`, `content_hash`) and
  on (`workspace_id`, `connector_id`, `version`).
  - Storing the zip in Postgres is the simplest path at 5 MB; object storage
    is logged as debt with its trigger (package count or size).
- **Registering** (`POST /api/connectors`, `Admin`; a multipart zip): validates
  as decision 2, then inserts into the **caller's active workspace**. A
  connector never declares itself first-party (D-064): the route always writes
  `first_party = false`.
- **First-party** packages are registered by the CLI only
  (`docker compose exec app python -m auspex.connectors register --first-party
  <zip>`), into the reserved `__deployment__` workspace, which no person can
  enter (D-035, D-068). **They are listed in every workspace.**
- **A provider may offer its connectors to its clients** (the open question):
  a provider workspace's admin registers with `offered_to_clients = true`
  (refused on any non-provider workspace); **every client workspace of that
  provider lists it, read-only**. A client can use an offered connector in an
  integration (S33) but never change or remove it. Restricted clients are
  included: a listing is code, not access to any client's data, and
  configuring an integration from it is still the client admin's own act.
- **Listing** (`GET /api/connectors`, `AnyRole`): the active workspace's own
  packages, its provider's offered ones, and the first-party ones, each marked
  with where it comes from. The set is built by one function in
  `auspex/connectors/catalogue.py`, so S33's integration form and S34's grant
  checks ask the same question TD-023 asks ("which connectors does this tenant
  have?").
- **Tenancy tests**: a foreign workspace's package is never listed; an
  offered package reaches only that provider's clients; a client cannot
  register `offered_to_clients`; `first_party` cannot be set over HTTP;
  `tests/test_tenancy_roles.py`'s route walk passes without widening.

### 4. Commands become job kinds — Hunaiza's call

- **Five generic kinds**, named in code (`auspex/connectors/jobs.py`), typed
  in S32, handled by S33:
  `connector.test`, `connector.fetch`, `connector.action.dry_run`,
  `connector.action.execute`, `connector.action.undo`.
- **One payload type** for all of them: `integration_id`, `content_hash`
  (what the agent must run, D-062), `command` (or `action` name),
  `arguments` (typed by the manifest), and, for `fetch`, `cursor` and
  `limit`. The job row's `integration_id` scopes the claim (S31's
  `ClaimScope`).
- One kind per manifest action is refused: it would make kinds tenant data and
  grow the code-declared list with every upload.

### 5. A manifest action compiles to an `ActionSpec` (D-064, with the open parts settled)

- `compile_action(manifest, action, *, prefix, dispatch)` in
  `auspex/connectors/compile.py` returns an `ActionSpec` whose `dry_run`,
  `execute` and `undo` are **three distinct closures** over `dispatch` (a
  coroutine S33 provides: enqueue the job, await its validated result). So
  `validate_spec` passes **unchanged**. S32's tests pass a fake `dispatch`.
- **Wire names**: `<prefix>__<action>`, where `prefix` is wire-safe and names
  the integration (S33 mints it from the integration; S32 only requires it to
  be a wire identifier of at most 24 characters, so the whole name stays a
  valid tool name).
- `scope` is one `ActionScope(system=<connector id>, writes=<risk is not
  read>, detail=<integration prefix>)`.
- **The fingerprint**: `ActionSpec` gains an optional
  `origin: ConnectorOrigin(connector_id, content_hash) | None` (None for
  built-in actions). `canonical_spec` adds `"origin"`, and
  **`FINGERPRINT_VERSION` becomes 2**, so `matches_older_scheme` reports
  stored v1 fingerprints of built-in actions as a scheme change, not a changed
  action. The settlement test that pins the key set gains `origin`.
- What the model reads (descriptions) is composed by code from typed fields
  and capped (D-064). Measuring customer text against the output rail (TD-044)
  is S34's, as D-064 says.

### 6. What a result may carry — Hunaiza's call

- **The SDK refuses to emit** a result the queue cannot store: its JSON
  encoder runs with `allow_nan=False`, and a string holding `\x00` is refused
  with the field's path. A tuple becomes a list (S31's `_clean_json` gap).
- **The core validates again** against the command's output schema before
  storing, showing or handing anything to the model (D-062): that check is
  S33's, named here so it is not lost.

### 7. B-026: undeclared arguments are refused when a proposal is filed — Hunaiza's call

- **For every action**, built-in and compiled: when a proposal is filed, an
  argument key the spec does not declare is refused, with its name, before the
  dry run. That closes B-026 (an undeclared key named like a platform keyword
  was approved, then failed into `incomplete`) at the one place every action
  passes through.
- It touches the approvals path, so it gets a fresh-agent review before the
  close (SESSION-RULES.md), with a test that fails first on B-026's exact
  input (`tests/fixtures/`).

### 8. The manifest v1 (D-064, made concrete)

- **Identity**: `schema_version: 1`; `id` (lowercase dotted,
  `^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+$`, e.g. `ibm.qradar`); `version`
  (semver); `name`; `description`.
- **Config**: a list of typed fields: `string`, `integer`, `boolean`, `url`
  (https only), `enum` (with its values), `secret` (a **name** the agent
  resolves, D-063; the manifest can never hold a value), `tls` (`verify`, or a
  pinned CA PEM, or a certificate SHA-256; **there is no off**). Each field has
  a name, a label, `required`, and an optional default (never for a secret).
- **Hosts**: patterns templated from config (`{base_url}`), https only.
- **Commands**: `test` → `{ok, detail}`; `fetch(cursor, limit)` →
  `{items, next_cursor}`, each item with `external_id`, `kind` (`alert` or
  `source_case`), timestamps, the `AlertEnvelope` fields, a capped `raw`, and
  `routing_key` (required when the manifest declares `serves_many_clients`).
- **Actions**: wire-safe `name`, `description`, `risk` (`read`, `write`,
  `destructive`; the `ActionRisk` vocabulary), primitive `params` (the
  `ParamType` four; arrays wait for TD-023(d)), a **required** `dry_run`, an
  `undo` with `restores` and `cannot_restore`, an `output` schema, and
  `targets` (the param naming the external item, for S34).
- **`validate_manifest` refuses**, each with an exact reason and its own
  table-driven test: destructive without undo; an undeclared host (a URL field
  or handler host outside `hosts`); TLS off in any spelling; a missing dry run;
  a fetch without `routing_key` while `serves_many_clients`; a name that is not
  wire-safe or an id that is not dotted; an unknown field or param type; a
  secret with a default; `schema_version` other than 1; a duplicate name. Plus
  the D-064 caps (description and `raw` lengths) as code constants.

### 9. The SDK (D-064, made concrete)

- **Python-first**: `@connector` on a config class (`Secret`, `Tls` field
  types), `@command("test")`, `@command("fetch")`, `@action(risk=…,
  dry_run=…, undo=…, targets=…)`. Each handler receives a typed **context**:
  the config (secrets resolved by the runtime, never in the manifest), an
  HTTP client, a logger.
- **YAML**: a hand-written manifest naming Python handlers (`module:function`).
  `auspex-sdk build` checks that each named handler exists with parameters
  matching the declared params, then writes the same `manifest.json`.
- **The HTTP client** (on `httpx`) sends only to the manifest's declared hosts
  (resolved from config), refuses plain http, and verifies TLS (system trust,
  a pinned CA, or a certificate SHA-256 checked on the live connection).
- **Logs redact secrets**: a logging filter replaces every resolved secret
  value with `[secret:<name>]`.
- **The harness**: `auspex-sdk run <command> --config <file> --fixture
  <recorded.json>` runs a handler against recorded HTTP exchanges (httpx's
  mock transport); no network.
- **`auspex-sdk build`** writes `dist/<id>-<version>.zip` and prints the
  content hash; the same input always gives the same zip and hash.

### 10. The reference connector

`examples/connectors/mock_siem/`: a small SIEM-shaped connector (`test`,
`fetch` with a cursor, one `write` action with a dry run, an undo and an
observe) written **both** Python-first and as YAML. Tests build both and assert
**byte-identical `manifest.json`**; each build's hash is deterministic (the
same build twice gives the same hash), and the two hashes differ because their
code differs. Every command of both builds runs through the harness against a
recorded mock-service fixture. _(Builder check Q1; Claude's call.)_

### 11. Where the core code goes

A new package `auspex/connectors/`: `catalogue.py` (registration, the listing
function, the package checks), `compile.py` (decision 5), `jobs.py` (decision
4), `routes.py` (`/api/connectors`), `__main__.py` (the first-party CLI). One
migration adds `connector_packages`. Every new table and route gets a
cross-tenant test (SESSION-RULES.md).

## Settled after the builder check (Claude's calls unless marked)

- **Shared vocabularies (Q3).** `auspex_sdk.manifest` owns the manifest's
  vocabulary as plain string enums: the risk levels (`read`, `write`,
  `destructive`), the param types (`string`, `integer`, `number`, `boolean`),
  the wire-name rule and the platform keywords. The core keeps its own
  `ToolLevel`, `ParamType`, `_WIRE_NAME` and `PLATFORM_KEYWORDS` (D-014's gate
  is not touched), and **one test asserts the two sets are equal**, so they
  cannot drift. That is the one place the vocabulary is written twice, by
  necessity (the SDK cannot import the core), and the test is what keeps it
  honest.
- **What actions return, and the output schema (Q2).** `dry_run`, `execute`
  and `undo` return a **platform envelope**: `would` (one line), `affects`
  (strings), `reversible` (bool), `detail` (an object). The core turns it into
  today's `ActionOutcome`. An action's `output` schema covers **`detail` only**,
  and it is a **closed typed-field list** (name, type, required, the
  `ParamType` four plus `string[]`), not JSON Schema: no validator dependency,
  and the same shape as params. `test` and `fetch` have fixed output types
  (decision 8).
- **Hosts (Q4).** Each `hosts` entry is `https://` plus a host, either literal
  (`api.vendor.example`, an optional literal `:port`) or a single placeholder
  naming a declared `url` config field (`{base_url}`, which contributes its
  host and port). No wildcards. `validate_manifest` refuses a placeholder that
  names no `url` field, and a `url` field that no host entry uses. The SDK's
  HTTP client resolves the entries from the integration's config and refuses
  any request to another host.
- **Duplicate connector ids (Q6).** Integrations bind to a content hash
  (S33), never an id. Registration refuses a `connector_id` that a first-party
  package already uses, and a client refuses an id its provider offers, so a
  workspace cannot list a look-alike next to (or in place of) the trusted one.
  The listing marks each entry's source (`first_party`, `provider`, `own`).
- **The fetch item (Q7).** A connector supplies `external_id`, `kind`,
  `title`, `severity` (`low`/`medium`/`high`/`critical`, the
  `AlertEnvelope` vocabulary), `observed_at` and `updated_at` (ISO-8601 UTC),
  optional MITRE technique ids, a capped `raw` (string, 64 KB) and
  `routing_key`. **The core derives** IOCs and signals with its own extractor
  and scorer: a connector never hands the core an `Observable` or a verdict.
  `serves_many_clients` is declared on the `fetch` command.
- **Observe (Q8).** An action may declare an optional, read-only `observe`
  (returns how many effects landed). Compiled, it becomes `ActionSpec.observe`,
  a fourth distinct dispatcher and job kind (`connector.action.observe`).
  Without one, a failed execute settles as `incomplete` (effects unknown),
  stated in the reference connector's docs.
- **Idempotency and the SDK version (Q9).** The job payload carries
  `proposal_id` and `idempotency_key` (S31's `operation_key`); the SDK context
  exposes `ctx.idempotency_key`, so a connector can de-duplicate on the
  vendor's side. `manifest.json` records the `sdk_version` that built it
  (informational); `schema_version` is the compatibility gate.
- **The fingerprint bump (conflict 2).** `canonical_spec(version=1)` omits
  `origin`, so `matches_older_scheme` still recognizes a stored v1 fingerprint
  as a scheme change. As D-024 intends, a built-in proposal approved but not
  yet run when version 2 deploys is refused with that reason; it is
  re-proposed.
- **`__deployment__` (conflict 3).** It is reserved by D-035 and D-068. The row is created on demand
  (`auspex/llm/scorecard.py`), so the first-party CLI creates it if missing,
  with the same upsert.
- **Packaging (conflict 4).** The Dockerfile copies `sdk/` and runs
  `pip install ./sdk` **before** its deps-only layer installs the core, so
  that layer still caches. `ci.sh` installs `./sdk` and lints `sdk/` and
  `examples/` too. These are real changes to two gate files, not one line.

## Hunaiza's two security calls (after the builder check, 2026-10-22)

- **An MSSP's offered connector may run on its clients' own agents: D-071.**
  D-062 says "a customer-written connector runs only on that customer's own
  agent (v1)". **D-071 reads "customer" as a provider together with its
  clients**: a connector a provider registers with `offered_to_clients` may
  run on its clients' agents. The bounds that keep it safe:
  - the client's admin chooses to configure an integration from it (S33);
  - the agent runs it only after its hash matches the one the job names
    (D-062), so it is byte-for-byte what the provider registered;
  - it never runs on Auspex's own infrastructure (D-062's sandbox rule
    stands);
  - a provider cannot offer to anyone but its own clients.

  D-071 is written in DECISIONS.md in S32, citing D-062 as the decision it
  reads, not supersedes.
- **A certificate pin replaces the chain check.** `tls` takes one of three
  forms:
  - `verify`: system trust, chain and hostname checked;
  - a pinned **CA PEM**: the chain must lead to that CA, and the hostname is
    checked;
  - a pinned **certificate SHA-256** (of the leaf certificate's DER bytes):
    the connection is trusted **only if** the live leaf certificate's hash
    equals the pin, whoever issued it and whatever name it carries. It
    replaces the chain and hostname checks. This is what lets an on-prem,
    self-signed QRadar be reached securely, and any other certificate is
    refused.

  Changing a pin is a config change, made by an admin (S33/F5).

## Structural tests (Goal 7)

- No module under `auspex/` imports `yaml`, `auspex_sdk.build`,
  `auspex_sdk.harness`, `auspex_sdk.runtime`, or anything under `examples/`.
- No module under `auspex/` calls `importlib`/`exec`/`zipimport` on package
  contents; the catalogue reads zip members as bytes only.

## S31's other open end

The worker's `except` around a failing `fail` gets its own test
(monkeypatch `fail` to raise), as STATE.md #30 asks. It is small and in the
jobs code S33 builds on.

## What is left to the builder

The exact module layout inside `auspex_sdk`; the CLI's flags beyond those
named; the tree-hash line format's encoding details (UTF-8, posix paths); the
migration's index choices; how the multipart upload is capped before reading;
the reference connector's field names. Each settled one is noted in the plan.
