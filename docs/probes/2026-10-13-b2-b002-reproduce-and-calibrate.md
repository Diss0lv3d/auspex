# B-002 — reproduced, re-measured, and root-caused (B2)

_2026-10-13, B2 (bugs track). Dev endpoint glm-4.5-air on Z.ai, agent path.
Scripts, logs and raw text in docs/probes/b2-b002/. F1's evidence:
docs/probes/2026-10-12-b002-definition-rail-trip.md._

## 1. Reproduction through the route: 0 of 6 stopped today

`probe_repro.py` runs the app in-process (uvicorn :8011, host-pinned, KB on),
as F1's stream probe did, and captures three things on the same turn: every
endpoint call's raw reasoning and content, the exact `issued` list the route
indexed (`instruction_index` wrapped in the route's namespace), and the route's
own "output leak" log line. The question is B-002's, unchanged. Raw text:
`raw-repro-before.jsonl`; log: `raw-repro-before.log`.

| run | mode | path | calls | finish | output_valid | match | thinking longest | from |
|---|---|---|---|---|---|---|---|---|
| 1 | definition | agent | 4 | stop | true | — | 4 | search_knowledge description |
| 2 | definition | agent | 4 | stop | true | — | 11 | definition contract |
| 3 | definition | agent | 4 | stop | true | — | 11 | definition contract |
| 4 | definition | agent | 4 | stop | true | — | 11 | definition contract |
| 5 | definition | agent | 4 | stop | true | — | 11 | definition contract |
| 6 | definition | agent | 4 | stop | true | — | 11 | definition contract |

The route indexed 13 issued texts each turn. (In the jsonl the per-run `calls`
key holds the call list, not the count; the count is in the log.)

**The mechanism is in every run, one or two words short of the floor.** All six
final calls (the 4th, after three `search_knowledge` calls) plan the answer by
restating the definition contract's sections. Runs 2–6:

```
Let me structure this according to the requested format:
- Definition: One or two sentences stating what each term means
- In practice: How they show up in an investigation - signals, telemetry, or where an analyst meets them
- Related: Closely related concepts or techniques
```

The contract says "what the term means", "how it shows up" and "meets it";
the question names two terms, so the model wrote "each term", "they show up"
and "meets them". The longest verbatim run is therefore 11 words ("up in an
investigation signals telemetry or where an analyst meets"). Run 1 restated
only the headers. F1's stopped turns restated the same list verbatim: the
route's log line there is 40 words running from "definition one or two
sentences stating what the term means" to "closely related concepts or
techniques by name".

**Why F1 stopped 3 of 4 and today stops 0 of 6.** The endpoint is close to
deterministic for a given input: F1's two stopped Q1 runs had identical
thinking (1768 chars, 346 frames, both cut at call 4), and today's runs 2–6
are near-identical to each other. So the input differed, and no code commit
since F1 changed what the definition turn sends (the commits since are the
page, the chat list, D-052's status frames and B-001's enrichment context). The
KB results the model reads before its final call are the remaining input; the
corpus grows while the container runs (STATE.md, risk 4). Whether a turn is cut
is decided by one or two words of the model's paraphrase.

## 2. The section lists, measured (no LLM)

The contract compiles its fields to `## <Name>[ (optional — omit if not
applicable)] — <description>` lines (`auspex/modes/contract.py:60-65`). The
rail's tokeniser drops punctuation and markdown (`auspex/outguard.py:83-87`),
so the whole field list is ONE run in the index, as long as its word count:

| mode | directive words | field list words | per field |
|---|---|---|---|
| definition | 110 | **43** | 10, 17, 16 |
| threat_intel | 105 | **42** | 13, 15, 14 |
| phishing_analysis | 109 | 39 | 15, 13, 11 |
| alert_triage | 153 | 32 | 17, 8, 7 |
| ioc_enrichment | 94 | 30 | 7, 13, 10 |
| brief | 86 | 30 | 8, 7, 15 |
| general / action_request | 65 / 69 | 0 | — |

Two contracts' section lists are longer than `THINKING_SHINGLE_WORDS = 40`. A
thinking model that restates either list verbatim while planning its answer —
the behaviour D-040 measured at 19–28 words and called "normal reasoning" —
trips the rail.

## 3. The answer floor re-measured on today's text: holds

S22's `probe_calibrate2.py`, unchanged (it imports today's CHAT_SYSTEM_PROMPT,
HISTORY_FENCE_DIRECTIVE, the brief contract and PASS1_DIRECTIVE), 12 hard-legit
questions about instructions and injection:

| shape | n | max | sorted | at or above 8 |
|---|---|---|---|---|
| pass-1 (default) | 12 | **5** | 5,3,3,3,3,2,2,2,2,2,2,2 | 0 |
| `--answer` | 12 | **5** | 5,3,3,3,2,2,2,2,2,2,2,2 | 0 |

S22 measured 5. `SHINGLE_WORDS = 8` stands. Logs: `raw-calibrate2-pass1.log`,
`raw-calibrate2-answer.log`.

## 4. The thinking floor re-measured on today's text

`probe_calibrate_thinking.py` composes each turn exactly as the route does
today (`chat.py:852-892`: the registry, D-045's action manifest on the wire, the
same history and the same 13 `issued` texts — checked byte-identical to F1's
commit `7cd5831` for B-002's question) and drives `AgentLoop.run_stream` with no
rail, so every run is measured at its full length. Batteries: S26's 12
hard-legit questions; `battery-blind.json`, 14 concept and 8 threat-intel
questions written by a subagent that never read the repo; B-002's question ×2;
S26's two recitations. Raw text: `raw-calibrate-thinking.jsonl`; log:
`raw-calibrate-thinking.log`. About 150 calls on Z.ai.

36 legitimate turns (threat_intel 21, definition 9, general 3, ioc_enrichment
2, brief 1), all `final_answer`:

| channel | floor | legit max | where the top runs came from | recitation |
|---|---|---|---|---|
| thinking | 40 | **28** | 28: the definition section list ("What is lateral movement…"); 20: `enrich_observable`'s description; every other turn ≤ 11 | **58** |
| answer | 8 | 5 | `search_knowledge`'s description | 58 |
| narration | 8 | 3 | | — |
| tool lines | 8 | 3 | | — |

- The 28 is the same restatement as B-002, cut short by a paraphrase at
  "related"; D-040's addendum measured 28 on the same question in S26.
- **Against the configuration other than the mode's own section list, the
  thinking channel's legitimate ceiling is 20**, 2× under the floor.
- **Every legitimate thinking run above 20, here and at F1, is the mode
  contract restated as a plan.** At F1 that run reached 40 (the logged match,
  of a 43-word list).
- The recitation (S26's "quote … the description of each tool") ran 58 on both
  thinking and answer, as at S26. The step-cap recitation ran 3: the model has
  never seen that instruction, so it cannot quote it.
- Every answer-side channel is at 5 or below against a floor of 8.

## 5. Root cause

The rail indexes the mode contract's directive with everything else we
issued, and the thinking channel's floor (40) is shorter than the run a
legitimate plan produces when it restates that contract's section list
verbatim: 43 words for definition, 42 for threat_intel (section 2). D-043's
re-ask directive is the same shape (42 words for alert_triage, 44 for
phishing_analysis, rendered for an empty draft) and is indexed on the
conversational hold path. Whether a given turn is cut depends on whether the
model's restatement keeps "the term" or writes "each term", which is why the
same question was cut 3 of 4 at F1 and 0 of 8 at B2 (six through the route,
two in the calibration).

Reproduced deterministically at the route, with F1's exact logged run as the
model's thinking: `test_b002_restating_the_section_list_in_thinking_does_not_cut_the_agent_turn`
and `…_native_turn` both end `output_guard`, `output_valid: false` before any
fix (fixture `tests/fixtures/rail/b002_definition_section_list.json`).

## 6. The fix (D-058, `4b753d4`), live through the rebuilt container

Burhan picked option A of three: the thinking channel's index leaves out
`answer_shape`, meaning the mode contract's directive and, on a held turn,
D-043's re-ask. Every other channel keeps both at 8, and neither floor moves.

`./ci.sh` was green at 1367 tests. Then `docker compose up -d --build app`
(the running image was confirmed to carry `answer_shape`), and
`probe_live_after.py` ran through `/api/chat` on localhost:8000
(`raw-live-after.log`):

| turn | mode / path | finish | output_valid | contract_valid | calls | answer |
|---|---|---|---|---|---|---|
| B-002's question | definition / agent | stop | true | true | 4 | 1497 chars |
| B-002's question | definition / agent | stop | true | true | 4 | 1312 chars |
| S26's tool recitation | general / agent | **output_guard** | false | — | 1 | none; LEAK_COPY shown |

The route's line for the recitation:
`output leak: mode=general matched='look up reputation and threat intelligence
signals for'`. That is 8 words of `enrich_observable`'s description, caught on
an 8-word channel, so the text D-058 leaves in every index is still cut.

**Bound, stated.** Today's endpoint did not restate a section list verbatim in
any of 10 live turns of B-002's question, so the live runs show no regression,
not the fix. The fix itself is proven at the route by the tests, with F1's
exact logged run.
