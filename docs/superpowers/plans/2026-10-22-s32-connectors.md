# S32 — The connector contract, the SDK and the catalogue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A connector is a typed `manifest.json` plus Python handlers, written Python-first or in YAML with the new `auspex-sdk`, registered content-hashed in a workspace's catalogue, and its actions compile to today's `ActionSpec` — while nothing a connector ships runs in the app.

**Architecture:** A second distribution `sdk/` (`auspex-sdk`, import `auspex_sdk`) owns the manifest types, `validate_manifest`, the package/tree-hash rules, the runtime (decorators, context, HTTP client, redaction), the build CLI and the harness. The core (`auspex/connectors/`) imports only `auspex_sdk.manifest`, `auspex_sdk.vocab` and `auspex_sdk.package` (pure, no I/O beyond bytes), adds the catalogue table, routes and first-party CLI, compiles manifest actions to `ActionSpec`, and declares the connector job kinds S33 will run.

**Tech Stack:** Python 3.12, FastAPI, asyncpg/Postgres, httpx, PyYAML (SDK build only), pytest; Node is not involved.

**Spec:** `docs/superpowers/specs/2026-10-22-s32-connectors-design.md` (decisions 1–11, "Settled after the builder check", "Hunaiza's two security calls"). Baseline: `docs/probes/2026-10-22-s32-connector-baseline.md`.

## Global Constraints

- Work on branch `s32-connectors`; commit locally per task; **nothing is pushed until the session's close**, then one PR into `staging` (Hunaiza, 2026-10-22).
- Commit messages `feat|fix|chore(scope): summary` only (CLAUDE.md rule 10), ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. One concern per commit; never amend.
- **Nothing a connector ships runs in the app process** (D-062): the core reads package bytes, never imports, `exec`s or `zipimport`s them, and never imports `yaml`, `auspex_sdk.build`, `auspex_sdk.harness`, `auspex_sdk.runtime` or `examples/`.
- `manifest.schema_version == 1`; connector id `^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+$`; semver `version`.
- Package caps (code constants, D-026): **5 MB per package, 1 MB `manifest.json`, 500 files**; fetch item `raw` ≤ **64 KB**; integration wire prefix ≤ **24** chars and a wire identifier.
- Content hash: `sha256:` + SHA-256 over sorted lines `"<posix path>\0<sha256 hex of file bytes>\n"` (UTF-8). Excluded from packages: YAML source, tests, `__pycache__`, `*.pyc`, dotfiles.
- TLS forms: `verify` | CA PEM (chain + hostname) | leaf-certificate DER SHA-256 pin (replaces chain and hostname checks). **No off.**
- Every new table and route gets a cross-tenant test; `tests/test_tenancy_roles.py`'s allowlists are not widened.
- `FINGERPRINT_VERSION` becomes **2**; `canonical_spec(version=1)` omits `origin`.
- Run tests from `.venv` with Node 22 first on PATH (`export PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH`); every test-adding commit updates the README's single test count.
- Fresh-agent adversarial review before the close for the approvals-path change (Task 9) and its fixes (SESSION-RULES.md).

## Review Focus

1. A package zip carrying `../x.py`, an absolute path, a symlink, or a duplicate member name must be refused at registration with the member named — Task 3 owns the test.
2. A manifest whose `hosts` placeholder names a `url` field typed as `string` (not `url`), or a `url` field defaulting to `http://`, must be refused — Task 2 owns the test.
3. A pinned-certificate connection to a host whose live leaf differs by one byte must fail closed, and `verify` must never accept a self-signed cert — Task 4 owns the test (local TLS server fixture).
4. A secret's resolved value appearing inside an exception message or an `extra=` log field must still be redacted — Task 4 owns the test.
5. Registering in a client workspace with `offered_to_clients=true`, or an id a first-party package already uses, must be refused even when the caller is that workspace's admin — Task 10/11 own the tests.

---

### Task 1: The SDK distribution, its vocabulary, and the packaging around it

**Files:**
- Create: `sdk/pyproject.toml` (name `auspex-sdk`, version `0.1.0`, `requires-python >=3.12`, deps `httpx>=0.27`, `PyYAML>=6.0`, script `auspex-sdk = "auspex_sdk.cli:main"`), `sdk/auspex_sdk/__init__.py`, `sdk/auspex_sdk/vocab.py`
- Modify: `pyproject.toml` (core depends on `auspex-sdk`), `Dockerfile` (copy `sdk/`, `pip install ./sdk` before the deps-only layer), `ci.sh` (`pip install -q -e ./sdk` before the core; ruff over `sdk examples` too)
- Test: `tests/test_connector_vocab.py`

**Interfaces:**
- Produces: `auspex_sdk.vocab.RISKS: tuple[str,...] = ("read","write","destructive")`, `PARAM_TYPES = ("string","integer","number","boolean")`, `WIRE_NAME: re.Pattern`, `PLATFORM_KEYWORDS: frozenset[str]`, `CONNECTOR_ID: re.Pattern`.

- [ ] **Step 1:** Test `test_the_sdk_vocabulary_equals_the_cores`: `set(RISKS) == {l.value for l in ToolLevel}`; `set(PARAM_TYPES) == {t.value for t in ParamType}`; `WIRE_NAME.pattern == _WIRE_NAME.pattern`; `PLATFORM_KEYWORDS == core PLATFORM_KEYWORDS`. Run: fails (no `auspex_sdk`).
- [ ] **Step 2:** Create the distribution and `vocab.py`; install editable; update `pyproject.toml`, `Dockerfile`, `ci.sh`.
- [ ] **Step 3:** Run the test → PASS; `docker compose build app` succeeds; `./ci.sh` green.
- [ ] **Step 4:** Commit `chore(sdk): the auspex-sdk distribution and its vocabulary, pinned equal to the core's`.

### Task 2: The manifest v1 types and `validate_manifest`

**Files:**
- Create: `sdk/auspex_sdk/manifest.py`
- Test: `sdk/tests/test_manifest.py` (run by the gate: add `sdk/tests` to pytest `testpaths`)

**Interfaces:**
- Consumes: `auspex_sdk.vocab`.
- Produces: frozen dataclasses `Manifest`, `ConfigField(name,label,type,required,default,values)`, `Tls`, `Action(name,description,risk,params,dry_run,undo,observe,output,targets)`, `Param`, `Undo(restores,cannot_restore)`, `OutputField`, `Fetch(serves_many_clients)`; `class ManifestError(ValueError)` with `.rule: str` and `.path: str`; `def parse_manifest(data: dict) -> Manifest` (refuses unknown keys); `def validate_manifest(m: Manifest) -> None`; `def manifest_to_json(m: Manifest) -> bytes` (sorted keys, compact, UTF-8, trailing `\n`).

- [ ] **Step 1:** Table-driven test `test_each_rule_refuses_with_its_reason`, one row per rule with `(mutation, rule, path)`: `destructive_without_undo`, `undeclared_host` (placeholder naming no `url` field; `url` field used by no host), `tls_off` (any of `"off"`, `false`, `"none"`, `{"verify": false}`), `missing_dry_run`, `shared_fetch_without_routing_key`, `bad_name` (non-wire action name; non-dotted id), `unknown_type` (config and param), `secret_with_default`, `schema_version`, `duplicate_name`, `http_url_default`, `description_too_long`. Plus `test_the_reference_shape_is_valid` and `test_unknown_keys_are_refused`. Run: fails.
- [ ] **Step 2:** Implement per spec decision 8 and "Settled… Hosts / output / fetch item / observe".
- [ ] **Step 3:** Run → PASS. Commit `feat(sdk): the manifest v1 types and validate_manifest, one refusal per rule`.

### Task 3: Packages and the content hash

**Files:**
- Create: `sdk/auspex_sdk/package.py`
- Test: `sdk/tests/test_package.py`

**Interfaces:**
- Produces: `MAX_PACKAGE_BYTES = 5*1024*1024`, `MAX_MANIFEST_BYTES = 1024*1024`, `MAX_FILES = 500`; `def tree_hash(files: dict[str, bytes]) -> str` (`sha256:<hex>`); `def build_zip(files: dict[str, bytes]) -> bytes` (sorted, fixed 1980-01-01 timestamps, deflate, no extra attrs); `class PackageError(ValueError)` with `.member`; `def read_package(data: bytes) -> tuple[Manifest, str, dict[str, bytes]]` (checks caps, member paths, symlinks, duplicates, excluded files, parses + validates `manifest.json`, returns manifest, hash, files).

- [ ] **Step 1:** Tests: `test_the_hash_ignores_zip_bytes` (same files, different timestamps/order → same hash); `test_any_file_change_changes_the_hash`; `test_build_zip_is_deterministic`; `test_bad_members_are_refused_by_name` (`../x.py`, `/abs.py`, symlink, duplicate, `__pycache__/x.pyc`) — Review Focus 1; `test_caps_are_enforced`; `test_a_missing_or_invalid_manifest_is_refused`. Run: fails.
- [ ] **Step 2:** Implement with `zipfile` reading bytes only.
- [ ] **Step 3:** PASS. Commit `feat(sdk): packages, their caps and the tree content hash`.

### Task 4: The SDK runtime — decorators, context, HTTP client, redaction, results

**Files:**
- Create: `sdk/auspex_sdk/runtime.py`, `sdk/auspex_sdk/http.py`, `sdk/auspex_sdk/redact.py`, `sdk/auspex_sdk/results.py`
- Test: `sdk/tests/test_runtime.py`, `sdk/tests/test_http.py` (local TLS server fixture with a self-signed cert generated in-test)

**Interfaces:**
- Produces: `Secret`, `Tls` field markers; `@connector(id, version, name, description, serves_many_clients=False)` on a config dataclass; `@command("test"|"fetch")`; `@action(name, risk, dry_run, undo=None, observe=None, targets=None, output=())`; `class Context(config, http: ConnectorHttp, log: logging.Logger, idempotency_key: str | None)`; `class ConnectorHttp` (`get/post/...`, `allowed_hosts`, `tls`); `class HostNotDeclared(Exception)`; `def redacting_filter(secrets: dict[str,str]) -> logging.Filter`; `def encode_result(value) -> bytes` (`allow_nan=False`, refuses `\x00` with the path, tuples → lists); `def collect(module) -> Manifest` (introspects decorators).

- [ ] **Step 1:** Tests: undeclared host refused; `http://` refused; `verify` rejects the self-signed server; CA-PEM pin accepts it with the right hostname and rejects a wrong hostname; certificate-SHA-256 pin accepts it whatever the hostname and **rejects a one-byte-different pin** (Review Focus 3); secrets redacted in message, args, exception text and `extra` (Review Focus 4); `encode_result` refuses NaN, Infinity, NUL; `ctx.idempotency_key` is passed through. Run: fails.
- [ ] **Step 2:** Implement (pin check: read the peer certificate's DER from the httpx stream's `ssl_object` and compare SHA-256 before any request body is sent).
- [ ] **Step 3:** PASS. Commit `feat(sdk): the runtime -- decorators, context, a host- and TLS-bound HTTP client, redaction, safe results`.

### Task 5: `auspex-sdk build` — Python-first and YAML to one manifest

**Files:**
- Create: `sdk/auspex_sdk/build.py`, `sdk/auspex_sdk/cli.py`
- Test: `sdk/tests/test_build.py`

**Interfaces:**
- Consumes: `collect`, `validate_manifest`, `manifest_to_json`, `build_zip`, `tree_hash`.
- Produces: `def build(source_dir: Path) -> tuple[Path, str]` (writes `dist/<id>-<version>.zip`, returns path and hash); YAML form: `connector.yaml` with handlers as `module:function`; `def check_handlers(manifest, source_dir)` refuses a missing handler or a parameter mismatch; `main()` with `build` and `run` subcommands; manifest records `sdk_version`.

- [ ] **Step 1:** Tests: a Python-first sample and its YAML twin build to **byte-identical `manifest.json`**; each build twice → same hash; YAML naming a missing handler → refused with its name; YAML param set ≠ function params → refused; the zip excludes `connector.yaml`, tests and caches. Run: fails.
- [ ] **Step 2:** Implement (`build` imports the author's module — allowed: this is the SDK on the author's machine, never the core).
- [ ] **Step 3:** PASS. Commit `feat(sdk): auspex-sdk build turns Python or YAML into the same manifest and a hashed package`.

### Task 6: The harness

**Files:**
- Create: `sdk/auspex_sdk/harness.py`
- Test: `sdk/tests/test_harness.py`

**Interfaces:**
- Produces: `def run_command(source_dir: Path, command: str, *, config: dict, secrets: dict, fixture: Path, arguments: dict | None = None) -> dict`; fixture format: `{"exchanges": [{"request": {"method","url"}, "response": {"status","headers","json"|"text"}}]}`; an unmatched request fails naming it; `cli run` wraps it.

- [ ] **Step 1:** Tests: a fixture-backed `test` returns `{ok, detail}`; an unmatched request fails with its URL; a request to an undeclared host fails before the fixture is consulted. Run: fails.
- [ ] **Step 2:** Implement on `httpx.MockTransport` plugged into `ConnectorHttp`.
- [ ] **Step 3:** PASS. Commit `feat(sdk): a harness that runs a command against recorded exchanges`.

### Task 7: The reference connector

**Files:**
- Create: `examples/connectors/mock_siem/python/mock_siem.py`, `examples/connectors/mock_siem/yaml/{connector.yaml,handlers.py}`, `examples/connectors/mock_siem/fixtures/*.json`, `examples/connectors/mock_siem/README.md`
- Test: `tests/test_reference_connector.py`

**Interfaces:**
- Consumes: Tasks 4–6.
- Produces: connector `example.mock_siem` 1.0.0: config `base_url: url`, `api_token: secret`, `tls: tls`; `hosts: ["{base_url}"]`; `test`; `fetch` (cursor, `serves_many_clients=false`); action `close_alert` (`write`, param `alert_id: string`, dry run, undo, observe, `targets="alert_id"`).

- [ ] **Step 1:** Tests: both builds give byte-identical `manifest.json`; every command of both runs green through the harness; `validate_manifest` passes; `read_package` accepts both zips. Run: fails.
- [ ] **Step 2:** Write the connector both ways, and the README (how to build, run, register).
- [ ] **Step 3:** PASS. Commit `feat(examples): the mock SIEM reference connector, Python-first and YAML`.

### Task 8: Compiling a manifest action, the fingerprint, and the job kinds

**Files:**
- Create: `auspex/connectors/__init__.py`, `auspex/connectors/compile.py`, `auspex/connectors/jobs.py`
- Modify: `auspex/actions/types.py` (`ActionSpec.origin: ConnectorOrigin | None = None`; `ConnectorOrigin(connector_id: str, content_hash: str)`), `auspex/actions/proposal.py` (`FINGERPRINT_VERSION = 2`; `canonical_spec` adds `"origin"` only when `version >= 2`), `pyproject.toml` + `Dockerfile` skeleton (new package)
- Test: `tests/test_connector_compile.py`; extend `tests/test_action_settlement.py`'s key-set test

**Interfaces:**
- Produces: `async def Dispatch(kind: str, payload: ConnectorJobPayload) -> dict` (protocol); `def compile_action(manifest: Manifest, action: str, *, content_hash: str, prefix: str, dispatch) -> ActionSpec`; `CONNECTOR_KINDS = ("connector.test","connector.fetch","connector.action.dry_run","connector.action.execute","connector.action.undo","connector.action.observe")`; `@dataclass(frozen=True) ConnectorJobPayload(integration_id: UUID, content_hash: str, command: str, action: str | None, arguments: dict, proposal_id: UUID | None, idempotency_key: str | None, cursor: str | None, limit: int | None)`.

- [ ] **Step 1:** Tests: the compiled spec passes `validate_spec`; its `dry_run`, `execute`, `undo`, `observe` are four distinct callables that call `dispatch` with the right kind; the wire name is `<prefix>__<action>`; a non-wire or >24-char prefix is refused; the envelope maps to `ActionOutcome`; two specs differing only in `content_hash` have different fingerprints; a built-in spec's v1 fingerprint is recognized by `matches_older_scheme` (returns 1); the key-set test includes `origin`. Run: fails.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** PASS (full `tests/test_action*` too). Commit `feat(connectors): manifest actions compile to ActionSpec; the fingerprint names the connector and its hash (v2)`.

### Task 9: B-026 — an undeclared argument is refused when a proposal is filed

**Files:**
- Modify: `auspex/actions/settlement.py` (`propose`, before the dry run)
- Create: `tests/fixtures/actions/b026_undeclared_platform_keyword.json` (the exact arguments from BUGS.md B-026)
- Test: `tests/test_action_settlement.py` (or the proposal tests file holding `propose`)

**Interfaces:**
- Produces: `class UndeclaredArgument(ProposalRefused-or-ValueError)` with `.names: tuple[str,...]`, raised by `propose` for any argument key not in `spec.params`.

- [ ] **Step 1:** Tests: the B-026 fixture is refused naming the key, with **no row written and no dry run called**; declared arguments still file; the route answers the refusal in words (422). Run: fails.
- [ ] **Step 2:** Implement in `propose` (one check, all actions).
- [ ] **Step 3:** PASS; mutants (remove the check; check only platform keywords) caught. BUGS.md B-026 → `fixed <commit> (S32)` in the same commit. Commit `fix(actions): a proposal with an undeclared argument is refused before its dry run (B-026)`.

### Task 10: The catalogue — table, registration, listing, first-party CLI

**Files:**
- Create: `auspex/connectors/catalogue.py`, `auspex/connectors/__main__.py`
- Modify: `auspex/migrations.py` (an `S32_CONNECTORS` block: `connector_packages` as spec decision 3, with the two unique constraints)
- Test: `tests/test_connector_catalogue.py`, `tests/test_tenancy_isolation.py` (the new table's cross-tenant row)

**Interfaces:**
- Consumes: `read_package`.
- Produces: `async def register(pool, *, workspace_id: UUID, data: bytes, registered_by: UUID | None, offered_to_clients: bool, first_party: bool = False) -> CatalogueEntry`; `async def available(pool, *, workspace_id: UUID) -> list[CatalogueEntry]` (own + provider-offered + first-party, each with `source: "own"|"provider"|"first_party"`); `class RegistrationRefused(ValueError)` with `.reason`; CLI `python -m auspex.connectors register --first-party <zip>` (creates `__deployment__` with the scorecard's upsert if missing).

- [ ] **Step 1:** Tests: register → listed in own workspace; same hash twice → same entry; same id+version, different hash → refused ("bump the version"); `offered_to_clients` refused on a non-provider workspace (Review Focus 5); a provider's offered package listed in each of its clients (restricted included), not in another provider's clients; first-party listed everywhere; an id a first-party package uses refused; an id a client's provider offers refused in that client; a foreign workspace's own package never listed. Run: fails.
- [ ] **Step 2:** Implement (tenancy queries reuse `organizations.parent_id`/`kind`, never a raw id from input).
- [ ] **Step 3:** PASS. Commit `feat(connectors): the catalogue -- content-hashed packages per workspace, offered to clients, first-party by CLI`.

### Task 11: The `/api/connectors` routes

**Files:**
- Create: `auspex/connectors/routes.py`; Modify: `auspex/app.py` (include the router)
- Test: `tests/test_connectors_api.py`

**Interfaces:**
- Consumes: `register`, `available`.
- Produces: `POST /api/connectors` (`Admin`; multipart `package` file, form `offered_to_clients: bool = false`; body read with a hard cap of `MAX_PACKAGE_BYTES + 64 KB`; `first_party` never accepted) → 201 entry; `GET /api/connectors` (`AnyRole`) → `{"connectors": [...]}`; refusals as 413/422 with the reason in words.

- [ ] **Step 1:** Tests: an analyst cannot register (403); an admin can; an oversize upload is 413 before parsing; a `first_party` form field is ignored; a client admin's `offered_to_clients=true` is 422 (Review Focus 5); listing per role and workspace; `tests/test_tenancy_roles.py` passes unchanged. Run: fails.
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** PASS. Commit `feat(connectors): POST and GET /api/connectors, admin-registered, workspace-scoped`.

### Task 12: Structural tests and the worker's failing-`fail` test

**Files:**
- Test: `tests/test_connector_structure.py`, `tests/test_jobs_worker.py` (or the worker test file)

- [ ] **Step 1:** Tests: no module under `auspex/` imports `yaml`, `auspex_sdk.build|harness|runtime|http|cli`, or `examples`; no module under `auspex/connectors` calls `importlib`, `exec(`, `eval(` or `zipimport`; the worker survives a handler failure whose `fail` raises (monkeypatched), and the next job still runs. Run the structural tests against a mutant (add `import yaml` to `catalogue.py`) → fails.
- [ ] **Step 2:** PASS. Commit `chore(tests): the core never imports connector code or YAML; the worker survives a failing fail`.

### Task 13: D-071, live check, records

**Files:**
- Modify: `DECISIONS.md` (D-071, spec "Hunaiza's two security calls"), `docs/probes/2026-10-22-s32-connectors-live.md` (create), `TECHNICAL_DEBT.md` (package bytes in Postgres; trigger: count or size)
- Modify at session end (by `/session-end`): STATE.md, ROADMAP.md, NEXT-SESSION-BE.md (S33's prompt), BUGS.md

- [ ] **Step 1:** D-071 entry; commit `chore(decisions): D-071 -- a provider and its clients count as one customer for D-062`.
- [ ] **Step 2:** Full gate `./ci.sh` green; rebuild the container; live: build the reference connector, register it as an admin through `POST /api/connectors`, list it from a client of an offering provider, register first-party with the CLI, see it everywhere; delete what the probe created. Record it.
- [ ] **Step 3:** Fresh-agent review of Task 9 (and Task 8's fingerprint change); fix what it finds with failing tests first.
- [ ] **Step 4:** Commit the record and debt entry `chore(probe): S32 live -- a reference connector built, registered, offered and listed`.
