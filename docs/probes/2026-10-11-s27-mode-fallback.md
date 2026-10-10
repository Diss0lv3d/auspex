# S27 — the mode resolver's fallback, measured on independent batteries

_2026-10-11, S27, added to scope by Burhan at the start ritual. Scripts and logs:
`docs/probes/s27-modes/`. The resolver is code-only, so every battery number
here costs nothing to re-run._

## The problem

A deep question with no threat-intel keyword resolved to `threat_intel` by
default. For a non-security question ("write me a status update for my
manager") that contract cannot be met: `contract_valid: false` 4/4 at S26 and
4/4 in S27's drift battery. On the conversational path the engine half-refused
("I'm Auspex, a threat intelligence analyst. I'm not able to write…").

## The design question, and why it needed held-out data

A fallback mode helps only if the resolver can tell "no security signal" apart
from "a security situation described in plain words". So the measurement that
matters is **how many real security questions it misroutes**. A vocabulary
judged against questions its author has seen will always look good, so each
approach was judged on a battery written by an independent agent that never
saw the code.

| battery | written by | role |
|---|---|---|
| in-sample (20 security + 10 non) | me, alongside approach 1 | training |
| `heldout-battery.json` (40 + 20) | independent agent #1 | out-of-sample for approach 1, then training for approach 2 |
| `heldout2-battery.json` (50 + 30) | independent agent #2, after approach 2 was frozen | **out-of-sample for approach 2** |

## Results

Deep turns only; the 92/8 shortcut answered a few non-security questions first.

| approach | battery | security → `general` (misroute) | non-security → `general` | non-security → `threat_intel` |
|---|---|---|---|---|
| before (default threat_intel) | in-sample | 0/20 | 0/10 | 9/10 |
| 1: security vocabulary | in-sample | 1/20 | 9/10 | 0/10 |
| 1: security vocabulary | held-out #1 | **15/40** | 16/19 | 0/19 |
| 2: + IT, identity and payments vocabulary | held-out #1 (now training) | 0/40 | 16/19 | 0/19 |
| **2** | **held-out #2** | **9/50 (18%)** | **24/30 (80%)** | **0/30** |

- **Approach 1 failed out of sample.** 15 of 40 security situations written
  without jargon ("an admin account was created at 3am…") fell to `general`.
  That is one of the two attempts the thrash brake allows.
- **Approach 2 is what shipped.** It adds the words an analyst uses to
  *describe* a security situation: accounts, logins, laptops, servers,
  mailboxes, payments, buckets, isolate, escalate. It was frozen before battery
  #2 existed. Its misroutes on #2 are situations with no IT vocabulary at all:
  a ransom note on a share, a printer emailing scans out, a text to customers,
  tailgating, a LinkedIn screenshot, a mobile redirect, a Dropbox copy, a SaaS
  questionnaire, and one more.
- The remaining non-security questions that do not reach `general` go to
  `definition` or `brief` through the existing opener and brief tiers ("What's
  17.5% of…"). That predates S27 and is not changed here.

## What a misroute costs — live, through the running app

`probe_app_general.py`, raw `raw-app-general.log`, against the rebuilt
container (agent path, glm-4.5-air):

| turn | mode | tools | what the answer did |
|---|---|---|---|
| status update (the S26 control) | general | — | asked for the week's details and offered the structure; no refusal |
| slow 200k-row Excel | general | — | concrete, correct advice |
| **misrouted:** ransom note on a share | general | search_knowledge | named it ransomware (T1486, from the KB), said isolate and do not pay |
| **misrouted:** printer emailing scans out | general | — | treated it as possible exfiltration: isolate, preserve, check config and logs |
| **misrouted:** tailgating | general | — | treated it as a physical-security breach: footage, report, controls |

**A misroute costs the section structure, not the security substance**, under
the neutral directive. That directive is the reason approach 1's rule ("do not
force a security framing onto a question that has none") was removed before
anything shipped. On a misrouted question it would have argued against the
substance. `contract_valid` on a `general` turn is true whenever there is an
answer, because the mode declares no sections. So drift on misrouted security
questions is not observable through the contract.

## Pinned

`tests/test_modes.py::test_the_measured_operating_point_on_the_independent_battery_holds`
asserts approach 2's point on battery #2: misroutes at most 9 of 50, at least
24 of 30 to `general`, and no non-security question kept in `threat_intel`.
Floors check that nothing was silently skipped. A vocabulary edit has to keep
that point or move it with a new probe log, and if it improves the point it
needs a fresh, independently written battery to prove the improvement.
