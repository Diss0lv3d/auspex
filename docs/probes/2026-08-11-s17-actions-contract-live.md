# S17 — Actions SDK contract, live-verified in-container

_Date: 2026-08-11. Run against the **installed distribution**
(`/usr/local/lib/python3.12/site-packages/auspex/actions/`), from `/tmp` so the
source tree cannot shadow it — the same discipline `ci.sh`'s installed-dist gate
enforces, and the reason two real packaging defects were caught at S14._

Zero LLM, zero DB, zero network. The contract is code; this is the proof it is
code that got installed and behaves as declared.

## What was executed

```
installed from: /usr/local/lib/python3.12/site-packages/auspex/actions/__init__.py

1. a destructive action WITHOUT an undo cannot even be declared:
   REFUSED: wipe_host: destructive actions require an undo. Declare one, or
   declare the action write-risk if it does not actually destroy state

2. the same action WITH an undo registers:
   registered: ['isolate_host'] | approval required: True

3. what the planner is TOLD (compiled from the spec, native endpoint):
You may PROPOSE these actions. A proposal is a request for human approval, not
an execution — nothing happens until a person approves it, so never report an
action as completed.

- isolate_host(host_id: string) — Isolate a host from the network at the EDR.
  RISK destructive: requires human approval before it runs (you may propose it,
  never perform it). Touches: edr (writes). Undo: Release the host from
  isolation. Undo does NOT restore: sessions dropped while isolated.

4. same registry, a weak endpoint (plan_only) — nothing on the wire:
   wire specs: []
   You may NAME these actions in a plan for a human to run. You cannot perform
   them and no mechanism here will: describing one as done would be false.

5. the capability row a panel renders:
   {'name': 'isolate_host', 'risk': 'destructive', 'requires_approval': True,
    'reversible': False, 'undo': 'Release the host from isolation',
    'cannot_restore': ['sessions dropped while isolated'], 'systems': ['edr'],
    'callable_by_model': False}
```

Note `reversible: False` on an action that HAS an undo — because that undo
declared `cannot_restore`. The platform does not claim it can put back what the
author said it cannot.

## What the run found that reading had not

The demo script included a fourth case: pass **another action's** `execute` as
this action's `dry_run`. It printed nothing — no refusal. The spec's own check is
`dry_run is execute`, which compares one spec against itself, so
`dry_run=some_other_action` sails past it. A copy-paste of that shape would give
an action a "preview" that really performs a different live action.

The registry sees every spec, so it can see what a spec cannot. It now tracks
which callable executes what and which merely previews, and refuses the collision
**in both registration orders** so order cannot decide whether the mistake is
caught. Two actions sharing one `dry_run` is still legal — a shared "would do
nothing" preview is a real pattern, and only execute-vs-dry_run confusion is
dangerous.

This is the third session running in which executing the thing found something
reading it did not (S15: sink order; S16: the permanent silent link loss; here:
cross-action handler confusion). Recorded because the check would look like
paranoia to a reader who had not seen it fire.

## Checks at S17 end

- `./ci.sh` green: ruff clean, **772 tests**, container build, installed-dist gate
- **110 modules** installed (106 at S16 end) — `auspex.actions` declared in
  `pyproject.toml [tool.setuptools] packages` AND the Dockerfile deps-layer
  skeleton, so `tests/test_packaging.py` passes rather than being worked around
- `/api/health/ready` 200
- Zero new env vars (S14, S15, S16 and S17 have each added none)
- Nothing executes: 32 hermetic contract tests, every `execute`/`undo` handler in
  them raising if called, and a test asserting `ActionRegistry` and
  `ActionManifest` expose no method named execute/run/perform/invoke/call/apply
