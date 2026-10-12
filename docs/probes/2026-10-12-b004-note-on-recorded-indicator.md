# B-004 — a note on a recorded indicator refused as "doesn't exist" (evidence)

_2026-10-12, F1, during the approvals panel's live test through the page.
Standard (glm-4.5-air, agent path), user `fe-probe@auspex.dev`, workspace
`default`. Saved before the probe's cleanup deletes the observable and before
a container restart drops the log. Observed, not diagnosed._

## Turn 1 (first chat), ~03:09 UTC

> We saw 185.220.101.52 beaconing every 60s from the finance workstation
> fin-ws-12 since Tuesday. Check it, and add a note to it saying it was seen
> beaconing from fin-ws-12, so the next analyst has the context.

Tool lines the page showed:
```
→ enrich_observable(185.220.101.52) · executed
→ annotate_observable(ipv4-9bf483a1, Seen beaconing every 60s from finance workstation fin-ws-12 since Tuesday) · proposed
```
Proposal `bc4b468d` was then approved and undone from the panel.

## Turn 2 (new chat after a page reload: no history), ~03:12 UTC

> Add a note to 185.220.101.52 saying the beaconing stopped after fin-ws-12
> was reimaged.

Answer (complete):
> I cannot add a note to 185.220.101.52 because this observable doesn't exist
> in the current workspace. The system returned an error indicating that there
> is no observable with that ID available.

No proposal was filed. Container log:
```
2026-10-12 03:12:03,515 auspex.chat INFO agent turn: mode=action_request steps=2 tools=['annotate_observable'] stop=final_answer
```

## The observable existed at the time (Postgres, read after turn 2)

```
observables: obs_id=ipv4-9bf483a1  type=ipv4  value=185.220.101.52  first_seen=2026-10-12 03:09:21 UTC  workspace=default
```
