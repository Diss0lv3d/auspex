# S18 approval flow, run in-container against the installed distribution

_2026-08-15. Zero LLM. Every line below is real output from the compose stack,
not a transcript of intent — the fourth session running where executing the thing
found what reading it would not (see the bottom of this file)._

## 1. Propose — the card is compiled, the dry run writes nothing

```
DRY RUN : Attach an analyst note to domain mail.paypa1.com (18 characters).
PROPOSAL: 224519e2-d70f-4c8d-9a41-56f712d4d2c6 status = pending_approval
CARD    : {
  "action": "annotate_observable",
  "risk": "write",
  "summary": "Attach an analyst note to domain mail.paypa1.com (18 characters).",
  "systems": [{"detail": "observable_notes in this workspace",
               "system": "auspex", "writes": true}],
  "reversible": true
}
FPRINT  : c6824a0e08a2985e ...
```

The summary is the ACTION's sentence about the real target, not the model's:
`mail.paypa1.com` was resolved from the workspace and the character count
measured. No row was written by the dry run.

## 2. Approve — through the real HTTP surface

```
--- APPROVE ---
settled= approved executed= True
did: Attached an analyst note to domain mail.paypa1.com.
status: executed

--- NOTE IN DB ---
S18 live demo note|action:annotate_observable
```

## 3. A second approval is refused, not repeated

```
--- SECOND APPROVE (must be 409) ---
HTTP 409
{"detail":"already executed — someone else decided this one"}
```

One note in the table, not two.

## 4. Undo — actually run, not merely declared

```
--- UNDO ---
undone= True | Removed 1 note(s) this approval added. | status: undone

--- NOTES AFTER UNDO ---
0
```

TD-023 asked for exactly this: an undo that ships with a test that runs it. It is
keyed on the proposal id, so a colleague's note written in between survives (test:
`test_the_undo_removes_only_what_this_approval_added`).

## 5. The blast-radius rule, demonstrated rather than asserted

A DESTRUCTIVE action scoped to a third-party system, filed and approved by a human,
still refuses to run:

```
filed      : 7dac4b0a-744b-4570-87e4-11ed9094c4d5 risk = destructive
approved   : True — a human CAN approve a third-party action
refused    : system_not_executable
detail     : isolate_host touches edr, which Auspex does not own — it may be
             proposed and approved, and it will not be run from here
```

This is the S18 constraint in code: an action that needs a real credential and a
real blast radius stays proposal-only until there is a sandbox to point it at.

## 6. The exactly-once claim, actually raced

`docs/probes/s18-step0/probe_race.py` — eight DISTINCT Postgres backends released
into the same `UPDATE ... WHERE status='pending_approval' RETURNING` at one
barrier, five trials:

```
  trial 1: 8 distinct backends, 1 winner(s), final status='approved'
  trial 2: 8 distinct backends, 1 winner(s), final status='approved'
  trial 3: 8 distinct backends, 1 winner(s), final status='approved'
  trial 4: 8 distinct backends, 1 winner(s), final status='approved'
  trial 5: 8 distinct backends, 1 winner(s), final status='approved'
```

The probe asserts the backend count as well as the winner count, because a race
that quietly serialised onto one connection would pass a winner-count check while
proving nothing.

---

## What running it caught that reading it did not

**A module-global pool.** `builtin.py` first kept its `asyncpg.Pool` in a module
global bound by `build_builtin_actions()`. It read fine. The moment a test built a
registry against its own pool while the app held another, the second binding
silently replaced the first and asyncpg answered:

    InterfaceError: cannot perform operation: another operation is in progress

— one pool driven from two event loops. The fix removed the global: the factory
returns specs whose handlers CLOSE OVER the pool they were built with. It also
removed a thing that should never have been on offer, since a third-party action
must not receive a handle to our database just by existing.

**An unbounded SSE generator.** `/api/proposals/stream` looped `while True` with
`request.is_disconnected()` as its only exit. That condition does not reliably
flip, and the test suite hung on it — a server-side generator with an exit
condition that might never fire is a leak with a polite name. Now bounded by
`STREAM_MAX_TICKS` with a `{"reconnect": ...}` frame, which SSE clients handle
natively.

Both were found by execution, in the session that wrote them.
