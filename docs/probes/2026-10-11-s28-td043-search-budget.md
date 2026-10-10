# S28 — TD-043 measured, fixed, re-measured: a per-turn search budget

_2026-10-11, S28. glm-4.5-air on Z.ai, from the host, no route. The prompts are
S27's three `threat_intel` prompts, verbatim
(`docs/probes/s27-td012/probe_contract_drift.py`), on the agent path, twice each.
Script: `docs/probes/s28-td043/probe_research_loop.py`. It wraps
`search_knowledge` to record every query and the documents it returned.
Raw logs: `docs/probes/s28-td043/raw-*.log`. Decision: D-046._

## Step 1 — what the re-searches returned (before)

`raw-before.log`. 6 turns, **37 inference calls**, 31 searches.

| Outcome of each search | Count |
|---|---|
| a miss (`results: []`) | **0** |
| only documents this turn already had | 4 |
| at least one new document | 27 |

- The two thin topics (LockBit initial access, RMM abuse) made 8, 8, 8 and 5
  searches. **Three turns hit the step cap** (9 calls each).
- The ATT&CK-shaped question searched once (2 calls).
- (The script's own `cap_hits` line in this log reads 6, which is a bug in the
  summary: it counted `final_answer` as a cap. Fixed before the next run. The
  per-turn lines say `stop=step_cap` three times.)

**Why it re-searches.** The KB has no document about LockBit: ATT&CK's group
and software pages are not ingested. An entity query can only return the
nearest generic techniques, and every search returns a full page of five.
- On every LockBit search, the same four generic ransomware pages (T1486,
  T1657, T1531, T1679) filled 3–4 of the 5 slots.
- The model never sees a miss, so nothing tells it to stop. It rewords until
  the cap.

That rules out two of TD-043's three candidate fixes:
- **"A miss that says rewording will not help"** would never fire: there were
  0 misses.
- **"Count distinct-result calls toward the cap"** would almost never fire:
  27 of 31 searches added something.

## Step 2 — the fix: a per-tool budget, enforced by structure

- A `Tool` declares `max_calls_per_turn`, and `search_knowledge` declares
  `SEARCH_KNOWLEDGE_MAX_CALLS = 3`.
- Once a tool has spent its budget, the loop stops offering it on the wire.
- A call to it anyway is refused with `call_limit`, and the handler does not
  run.
- `run` and `run_stream` share the counting.

## Step 3 — re-measured on the same prompts

| Run | Calls | Mean | Step-cap hits | Contract-valid | Thin-turn distinct docs |
|---|---|---|---|---|---|
| before | 37 | 6.2 | 3 | 6/6 | 16, 21, 18, 13 |
| budget 3 (`raw-after.log`) | 24 | 4.0 | 0 | 6/6 | 10, 12, 12, 10 |
| **budget 3 + last-call notice (shipped)** (`raw-after-notice.log`) | **23** | **3.8** | **0** | **6/6** | 10, 12, 12, 10 |

**Withdrawal alone is not the guarantee.** In `raw-after.log` every thin turn
called the withdrawn tool once more, from its history: 4 tool calls and 3
searches. The refusal caught each one, but each cost an inference call.
- So the result of the last allowed call now says it was the last.
- With that notice, the RMM turns stopped at 4 calls (2/2).
- The LockBit turns still made the refused call (2/2).
- This is the shipped code.

## The price, stated

- **Lost:** with three searches, neither LockBit turn reached the T1566
  Phishing page. In the before run it came back at search 4 and search 5, as
  the model's queries moved from the entity ("LockBit ransomware group") to
  technique words ("…phishing VPN RDP"). One before turn also found T1563.002
  (RDP Hijacking) and T1078 (Valid Accounts).
- **Not lost:** the Initial Access tactic page (TA0001) is the first result of
  the first search on every LockBit turn. Its text names targeted
  spearphishing, exploiting public-facing servers, valid accounts and
  external remote services. Those are the vectors the specific pages would
  have grounded.

## Tried and not shipped

- **De-duplicating within the turn** (`raw-after-dedupe.log`). Each search
  returned five documents the turn had not yet seen.
  - Distinct documents per thin turn rose to 15, and calls fell to 22.
  - It did not bring T1566 back: all three LockBit queries stayed on the
    entity, so the extra slots went to lower-ranked pages (T1558.003,
    T1003.004).
  - It also removes the one signal that, in the before run, came just before
    the model changed strategy: seeing the same results again.
  - Reverted: it fixed nothing it was brought in for, and it added per-turn
    state.
- **A budget of 5, with de-duplication** (`raw-after-dedupe-budget5.log`).
  30 calls, and still no T1566. The queries never left the entity, so
  searches 4–5 dug deeper into noise (T1069 Permission Groups Discovery, from
  "group").

Those were two approaches to the grounding loss, and neither restored it, so
the thrash brake stops it here. The cause is KB coverage, not the loop
(IDEAS: ATT&CK groups and software as documents).

## The rail

- The fix tells the model nothing new in the system message or in the tool
  descriptions. The budget removes a tool from the wire.
- The refusal (`call_limit`) and the last-call notice are tool-result text,
  which D-031 leaves unindexed by design ("tool results are left unindexed as
  data", `auspex/agent/capabilities.py`).
- `issued_instructions` and the leak index are unchanged.
