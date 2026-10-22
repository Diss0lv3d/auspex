# S32 Step 0 — the code the connector contract plugs into (2026-10-22)

_Session S32 (backend), run by Hunaiza (D-059, handed fully). Read at
`da7986a` (staging after promote #42). CLAUDE.md rule 4: the design is written
against this, not against memory. No engine calls._

## Actions today (D-023, D-024)

- **`ActionSpec`** (`auspex/actions/types.py:180`): `name`, `description`,
  `risk: ActionRisk`, `scope: tuple[ActionScope, ...]`, `params:
  tuple[ActionParam, ...]`, `dry_run`, `execute`, `undo: UndoSpec | None`,
  `observe: EffectsProbe | None`.
  - `ActionHandler = Callable[..., Awaitable[ActionOutcome]]` (`:61`);
    `EffectsProbe = Callable[..., Awaitable[int]]` (`:65`).
  - `ActionParam` (`:102`): `name`, `type: ParamType`, `description`,
    `required`, `enum`. **`ParamType`** (`:84`) is the primitives only:
    `string`, `integer`, `number`, `boolean` (arrays wait for TD-023(d)).
  - `UndoSpec` (`:123`): `description`, `handler`, `restores`,
    `cannot_restore`. `ActionScope` (`:143`): `system`, `writes`, `detail`.
    `ActionOutcome` (`:165`): `would`, `affects`, `reversible`, `detail`.
- **`validate_spec`** (`:256`) refuses, as registration errors:
  - a non-wire name (`_WIRE_NAME`: ASCII letters, digits and `_`, no leading
    digit);
  - an empty description;
  - an `execute` that is not callable, or a missing `dry_run`;
  - a `dry_run` that IS `execute`;
  - destructive with no undo;
  - an undo on a read action, a non-callable undo, an undo that restores
    nothing, or an undo that is `execute` or `dry_run`;
  - `observe` that is `execute`, `dry_run` or the undo.

  The checks are identity checks on callables. So **distinct dispatcher
  callables pass unchanged**, as D-064 says.
- **The fingerprint** (`auspex/actions/proposal.py`).
  - `FINGERPRINT_VERSION = 1` (`:40`).
  - `canonical_spec` (`:43`) covers `v`, `name`, `description`, `risk`,
    `scope[]` (system, writes, detail), `params[]` (name, type, description,
    required, enum) and `undo` (description, restores, cannot_restore).
  - It does **not** cover handler bodies (D-024's stated gap), nor any
    connector identity: there is none yet.
  - Its key set is asserted against the dataclass fields
    (`tests/test_action_settlement.py`), so adding the connector id and the
    package hash is a deliberate, versioned change. `matches_older_scheme`
    (`:103`) reports a version bump as a version bump.
  - `fingerprint` (`:95`) is the SHA-256 of the sorted, compact JSON of
    `canonical_spec`.
- **The registry** (`auspex/actions/registry.py:44`): `register`,
  `register_all`, `get`, `names`, `risk`, `requires_approval`, and
  `manifest(agent_mode)` → `ActionManifest` (`:166`: `wire_specs`,
  `directive`, `summary`).
  - **One process-wide registry**, built at startup from the built-in actions
    (`auspex/app.py:76-77`).
  - The chat route hands the agent `action_registry.manifest("native_tools")`
    (`auspex/routes/chat.py:920`).
  - So actions are in-process and workspace-blind today. That is TD-023's open
    question, "which actions does this tenant have?", which S32's catalogue
    answers.

## The nearest thing to a connector today

- **`Provider`** (`auspex/enrich/providers/base.py:24`), an in-process
  enrichment source:
  - `name`, `region` (declared in the class body, `tests/test_region_guard.py`)
    and `accepts`;
  - `async lookup(...)`.

  It runs in the app process and is first-party code. A connector differs on
  both counts: it never runs in the app process (D-062), and it may be
  customer-written.

## The jobs queue S33's agents will meet (S31, D-065)

- **`JobKind`** (`auspex/jobs/queue.py:31`): `name`, `handler`,
  `lease_seconds=60`, `max_attempts=5`. Kinds are declared in code.
- **`ClaimScope`** (`:159`): `kinds`, `workspace_ids` (None means every
  workspace), `integration_ids` (None means jobs bound to no integration).
- **`claim(pool, scope, claimer=...)`** (`:179`): the next ready job in scope,
  with a fresh token, a lease and one more attempt.
- So a connector's `test`, `fetch` and `actions[]` can become job kinds whose
  scope names an integration. S32 only types them; S33 runs them.

## Packaging

- One distribution, `auspex` (`pyproject.toml`), with an explicit package list
  and package-data. There is no second distribution yet.
- A new package directory needs `pyproject.toml` and the Dockerfile skeleton
  (SESSION-RULES.md). A separate SDK distribution, installable by a connector
  author, is a design question for S32.

## Open ends from S31 that S32 is asked about (STATE.md #30)

- **What a job may store:** `complete` stores only what JSON carries. A tuple
  holding NUL, NaN or Infinity fails it, and the job re-runs.
- **B-026:** an undeclared action argument named like a platform keyword is
  approved, then fails into `incomplete`.
- **The worker's `except`** around a failing `fail` has no test of its own.
