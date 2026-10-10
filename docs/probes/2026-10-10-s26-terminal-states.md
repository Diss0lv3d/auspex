# Probe: what a proposal's terminal states say — D-041 live (S26 goal item 4)

- **Date:** 2026-10-10
- **Scope:** TD-028 (b/c/d) and TD-034, fixed in `f263c1d` `203cccc` `1c6c9bd`
  `6811d45`; decision D-041.
- **Hermetic proof:** `tests/test_action_settlement.py`. 19 new tests and 2
  reversed or regeneralised, each failing before its fix. Mutants run: **8 of 8
  caught**.
  - (b): 4 mutants, covering failed vs incomplete, cannot-look, look-fails and
    the queue.
  - (c): 3 mutants, covering the claim from the status read, return-to-origin
    and nothing-to-undo.
  - (d): 1 mutant, tenant scoping of the twin lookup.
  - TD-034 had **no mutant run**. Its tests were watched failing before the fix
    (RED), which proves the same thing for that statement. (Corrected at
    session end: this line first said "11 of 11", which was a miscount.)
- **Live:** `docs/probes/s26-step0/probe_terminal_states_live.py`, against the
  rebuilt container (its migrations added `incomplete` to the status CHECK and
  the `abandoned_from` column). Raw: `raw/2026-10-10-terminal-states-live.log`.
  No HTTP route files a proposal, so proposals were filed with the real
  `ProposalSettlement` from the host, and every decision went through
  `/api/proposals`. Everything created was deleted afterwards.

## Live result

| step | result |
|---|---|
| two identical requests + one different | each twin's card names the other; the different one names nothing |
| reject twin A | 200; twin B now names nothing (not merged, still a real request) |
| a crashed run (approved, claim 1 h old, its note already landed) | in the queue as `executing` → **abandon** 200, `abandoned_from=executing` → **undo** 200, `undone`, removed 1, **0 notes left** |
| the ordinary path | approve 200 `executed` → undo 200 `undone` |
| undo of a `failed` (checked: nothing landed) | **409**: "the action failed and checked that nothing of it landed" |

## Not driven live

`incomplete` needs a handler that dies after its write, and there is no way to
inject one into the running container. It is covered hermetically, through the
real route, by `test_an_incomplete_run_is_put_back_through_the_surface` and
`test_the_approval_surface_says_what_landed_when_a_run_fails`.

## After the review (`cd44b4f`…`0a5c5b1`, container rebuilt)

An adversarial review found eight defects, all fixed (see the D-041 addendum).
The rebuilt container's migrations applied `claim_token`, `abandoned_token`,
the `kept` status and the twin index. Re-run, raw
`raw/2026-10-10-terminal-states-live-after-review.log`:
- every step above is unchanged;
- **new [5b]:** an `incomplete` run (its note landed, then it died) is queued
  as `incomplete`, then **keep** returns 200 `kept` and the row leaves the queue;
- a single-proposal read now says `identical_pending: null` (not looked), not
  `[]`.

Twin lookup cost (`probe_twin_lookup_cost.py`, dev DB, scratch workspace
deleted): **811.6 ms → 3.9 ms** median at 20 000 distinct pending rows,
limit 200.
