# S25 — do the capability tools' descriptions work as PROMPTS?

_Probed 2026-08-16 (S25). Harness: `docs/probes/s25-step0/probe_tool_choice.py`.
Endpoint: primary dev LLM, Llama-4-Scout-17B-16E-Instruct-FP8 via Northflank
(D-015). Live, not fakes._

## Why this had to be measured

S24 shipped three READ tools and verified the **handlers** against the real
services. Every one of those calls was made **directly**. Nothing had ever
established that a model, shown only the descriptions in
`auspex/agent/capabilities.py`, would pick the right one — and a tool whose
description a model cannot act on is a tool that does not exist.

This is a property of the **endpoint**, not of our code, which is D-014's
capability-negotiation premise. So it belongs in a probe, and its result is true
of Scout rather than true in general.

## Method

The three real specs (`registry.specs()`, asserted to be exactly the three) are
offered to the live endpoint with one prompt per case, `temperature=0`,
`max_tokens=600`. The tool NAME and its ARGUMENTS are both recorded — picking
`lookup_cve` with the wrong ids is not a success.

**Control:** one prompt no tool can answer. If the model called a tool for that,
"it picks well" would not be what the other rows measured.

## Result — 8 of 8

| prompt | expected | called | arguments |
|---|---|---|---|
| "Is 185.220.101.5 malicious?" | `enrich_observable` | ✅ same | `["185.220.101.5"]` |
| "How bad is CVE-2021-44228?" | `lookup_cve` | ✅ same | `["CVE-2021-44228"]` |
| "What is Kerberoasting?" | `search_knowledge` | ✅ same | `"Kerberoasting"` |
| "EPSS score and KEV status for CVE-2023-4863" | `lookup_cve` | ✅ same | `["CVE-2023-4863"]` |
| "reputation on evil-tracker.example.com" | `enrich_observable` | ✅ same | `["evil-tracker.example.com"]` |
| **CONTROL** — "status update for my manager" | **no call** | ✅ **no call** | — |
| "Check these three: a, b, c" | `enrich_observable` | ✅ same | **three separate items** |
| "Are any of 8.8.8.8, 1.1.1.1, 9.9.9.9 malicious?" | `enrich_observable` | ✅ same | **three separate items** |

Arguments were correct in every case, including the `lookup_cve` /
`search_knowledge` boundary the descriptions call out explicitly ("Not for looking
up a specific CVE id; use lookup_cve for that").

## D-031's streaming shape, independently re-confirmed

Every tool-calling turn: `finish_reason=tool_calls`, **`content_chars=0`**. The
control turn: `finish_reason=stop`, content present. This is the measurement
D-031 Decision 1 rests on, taken again on a different day against the same
endpoint — the answer may stream after the tool steps because no prose precedes
them.

## The control did more than pass — it found something the wiring needs

Asked a question no tool answers, Scout did not answer in prose. It said:

> "I am unable to fulfill this request as the functions provided are insufficient."

That is a **refusal shaped by the tool list**, not an answer. The probe's system
message already said "If no tool applies, just answer" and it refused anyway. An
analyst who asks the platform a general question and is told the functions are
insufficient is being shown our plumbing.

**Consequence for the wiring:** offering tools changes what the model does with
questions the tools do not cover, so the agent path cannot be the only path.
Either the 92/8 classifier keeps such turns off the agent path, or the composed
system message has to make answering-without-a-tool explicit — and whichever is
chosen needs its own measurement, because this one shows the obvious instruction
was not enough.

## What this does NOT establish

- **One endpoint, one temperature, eight prompts.** Scout picks well from these
  descriptions. Another customer endpoint is a different measurement — that is
  what D-014 says.
- **Nothing about multi-step behaviour.** Every case here is one call. Whether the
  model chains tools, or stops when it has enough, is unmeasured.
- **Nothing about `prompted_tools`.** Still deliberately unmeasured (it parses
  `<tool_call>` tags out of content, which would reach the analyst as prose).
- **The silent-drop defect is LATENT here, not absent.** Scout sent three separate
  array items for "check these three", so it does not reach the `parsed[0]`
  collapse S25 fixed. The collapse is still reachable by construction through the
  bare-string shape `_as_list` exists to accommodate — see the Step-0 review record.
