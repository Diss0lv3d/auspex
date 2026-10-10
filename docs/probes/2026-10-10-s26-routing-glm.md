# Probe: which deep turns take the agent path — re-measured on glm-4.5-air

- **Date:** 2026-10-10 (S26 goal item 1, resumed)
- **Why:** the routing rule proposed on 2026-08-16 rested on measurements of
  Llama-4-Scout, which no longer exists (NXDOMAIN, D-034). NEXT-SESSION required
  all three of its probes to be re-run on the new dev model before any rule is
  decided.
- **Target:** glm-4.5-air on Z.ai's general pay-as-you-go API (D-034). Synthetic
  prompts only. The KB and enrichment run live from the host (`auspex.devhost` pins
  plus `KB_ENABLED`/`ENRICHMENT_ENABLED`).
- **Harness:** `docs/probes/s26-step0/` — `probe_s25_refusal_replay.py`,
  `probe_refusal_cause.py`, `probe_routing.py` (all three adapted for a thinking
  model, see each docstring), and `probe_routing_baseline.py` (new). Raw output
  is under `docs/probes/s26-step0/raw/2026-10-10-glm-4.5-air-*.log`; each log was
  scanned for the API key before saving and none was found.
- **Cost:** about 50 model calls in total, all at glm-4.5-air pay-as-you-go rates.
- **Depends on this:** D-037 and the `/api/chat` agent-path wiring.

---

## The rule under test (proposed 2026-08-16)

    A deep turn takes the AGENT path iff
      (1) mode is not ALERT_TRIAGE / PHISHING_ANALYSIS, AND
      (2) the classifier found an observable the tools can act on.

Clause (2) existed for one reason: at S25, Scout refused a question no tool
answers ("the functions provided are insufficient") once tools were offered.

## Finding 1 — the refusal does not reproduce. 0 in 25 runs with tools offered

| probe | method | tools ON | tools OFF |
|---|---|---|---|
| `probe_s25_refusal_replay.py` | S25's exact cell: non-streaming, S25's system message, `max_tokens=600` | **0/6** refused, 0 calls | — |
| `probe_refusal_cause.py` | 2×2 through `run_stream`: S25's message vs the loop's | **0/6** refused, 0 calls | **0/6** |
| `probe_routing.py` [A] | loop message, `run_stream` | **0/3**, 0 calls | **0/3** |
| `probe_routing_baseline.py` [A] | the full route composition (fence + contract directive) | **0/1**, 0 calls | — |

On every run the model asks for the week's details. One cell differs in a way
worth recording: with S25's wording and **no** tools it writes a fill-in
template (3/3), and once tools are offered it asks for details instead (3/3).
Offering tools changed the answer's form but never turned it into a refusal.
The record from 2026-08-16 is consistent with this: Scout itself refused 0 of 12
times under `run_stream` with the loop's message. S25's single refusal was never
reproduced under the conditions the route actually uses, on either model.

**Clause (2) protects nothing on this endpoint.**

## Finding 2 — clause (2) almost never fires, because the 92/8 shortcut handles observables first

Step [0] ran with no model involved: the code's routing of each prompt.

| prompt | category | deep? | mode | observables | rule says |
|---|---|---|---|---|---|
| A "status update for my manager" | deep | yes | threat_intel | — | conversational |
| B "Is 185.220.101.5 involved in anything related to CVE-2021-44228? Check … whether they connect." | **cve_lookup** | **no** | — | IP, CVE | never deep |
| C "scheduled task created by an Office macro … which ATT&CK techniques … what next?" | deep | yes | threat_intel | — | conversational |

The positive case the rule was built around does not reach the deep path at all.
It contains under 20 words of residual text (`CVE_RESIDUAL_MAX_WORDS`), so it is
answered by a **CVE card**, and the IP and the question itself are dropped. An
observable reaches a deep turn only inside a longer narrative (measured with no
model: two ~25-word narratives carrying 185.220.101.5, one of them naming
`${jndi:…}`, both classified `deep`). The relational-question gap is parked
in IDEAS.md, because it touches calibrated 92/8 thresholds.

## Finding 3 — clause (2) holds back the KB on the questions where it helped most (case C)

Case C is a security question with no observable. Clause (2) sends it down the
conversational path, which does no retrieval. The fair comparison is the route's
own two compositions (`probe_routing_baseline.py`), ×3:

| | wall | calls | contract | technique IDs |
|---|---|---|---|---|
| **conversational** (today: CHAT_SYSTEM_PROMPT + fence + user + directive) | 12.0 / 14.1 / 14.3 s | 1 | 3/3 valid | ungrounded; **2/3 mislabel one**: "T1059.001 … Office Application Macro" (T1059.001 is PowerShell), "T1059.007 (… VBScript)" (T1059.007 is JavaScript) |
| **agent** (loop message + [fence, directive] + user, tools on) | 19.1 / 12.1 / 12.1 s | 3 / 2 / 2 | 3/3 valid | `search_knowledge` 1–2×, then T1053.005, T1137.001, T1059.005 (Visual Basic), **all correctly labelled** |

The agent path conformed to the mode contract just as often, took about the same
time on 2 of 3 runs, and was the only one of the two that grounded its answer.

`probe_routing.py` [C] also ran the comparison through the loop with tools OFF,
and that composition is **not** today's path. The loop's system message says "Use
the provided tools" even when none are offered. It gave one `empty_answer`
(`finish=length` with 8471 chars of thinking: the 2000-token budget went entirely
to reasoning), one answer that **wrote a fake tool call as prose**
(`` ```python get_attck_techniques()``` ``), and one answer with a wrong ID
(T1543.003 labelled as a scheduled task). That composition is not used anywhere,
but it is what `AgentLoop` sends whenever it is built with zero tools. The wiring
must never run the loop tool-less (see Consequences).

## Finding 4 — multi-step works: parallel lookups, then sequential chaining, then a stop

- **B** (forced through the agent path ×3): 3/3 runs make the **same two parallel
  calls in step 1**, `enrich_observable(['185.220.101.5'])` and
  `lookup_cve(['CVE-2021-44228'])`, both `executed`, then answer in step 2.
  The answer is written from the tool **data** (AbuseIPDB 100 % / 378 reports, the
  Tor-exit hostname `berlin01.tor-exit.artikel10.org`, CVSS 10.0, KEV).
- **C** (tools on, ×6 across both probes): 1–2 `search_knowledge` calls. When
  there are two, they are **sequential** (step 1, then a refined query in step 2),
  which is the first measured *chained* turn. Every run stopped by itself at step
  2 or 3 under a cap of 4 (and the shipped cap is 8).
- STATE.md blocker 3 ("every measured turn is one tool call") is answered on
  this model.

## Finding 5 — TD-036 holds on every tool-calling turn. The buffer is required, and now has a size

Each tool-calling step put prose in `content` **before** its tool call:

| case | narration in the tool-calling step |
|---|---|
| B ×3 | 91, 169, 169 chars: "I'll check both the IP address and the CVE…" |
| C ×3 (step 1) | 182, 182, 201 chars: "Let me search for information about Office macros and scheduled tasks" |
| C ×3 (step 2) | 1 char (`"\n"`) |

Together with Finding 9 of the endpoint record (58–80 chars on single-tool
probes), the measured range of narration is **1–201 chars**, and it is always
intent ("I'll check…"), never a verdict. The answer's own content always arrives
after the last tool event (`tools before the answer: True`, 3/3).

## Finding 6 — a thinking model can spend the whole answer budget on thinking

One run of 12 in `probe_routing.py` [C] (the tool-less loop composition) ended
`empty_answer`, with `finish=length` after 8471 chars of reasoning at
`max_tokens=2000`. No run in the route's own compositions hit it (0/6). The
route's existing `empty_answer` handling covers the case: nothing is persisted
and `contract_valid` is null. The finding is recorded because the agent path pays
this budget once per call, not once per turn.

---

## What this establishes, and what it does not

- **Establishes** on glm-4.5-air: offering tools does not cause refusals; the
  agent path is as contract-conformant as the conversational path and better
  grounded on a KB-shaped question; multi-step works and stops; and narration
  precedes every tool call.
- **Does not establish** anything about a customer endpoint that refuses with tools on.
  Scout did so once, under a message the route never sends, and never again in
  12 tries under the route's conditions. Either way, the scorecard gate is what
  protects such an endpoint (D-037), not clause (2).
- **Not measured:** prompted_tools (still deliberately unwired; D-031), and
  alert/phishing pastes on the agent path (excluded by clause (1), which stands).
- Sample sizes are small (3 per cell). These are decisions about which way to
  route, not benchmarks.
