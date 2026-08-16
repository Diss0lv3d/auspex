# Probe — the agent capability tools against the REAL services, in the container

**Date:** 2026-08-16 (S24) · **Why:** the 27 unit tests drive duck-typed fakes
(`FakeKnowledgeService`, `FakeEnrichmentService`). A fake that has drifted from
the class it stands in for is exactly what "reality over memory" exists to catch
— green tests say nothing about whether `search_definition` still accepts the
arguments the wrapper passes it. So the same registry was built against the
services the running app builds (`KnowledgeService.from_settings`,
`EnrichmentService.from_settings`) and every tool was actually called.

Harnesses: `docs/probes/s24-step0/probe_live_tools.py`,
`docs/probes/s24-step0/probe_live_miss.py` (run inside `auspex-app-1`).

## Reality at probe time

```
kb.active=True  enrichment.active=True
enrichment providers accept: ['domain', 'ipv4', 'ipv6', 'md5', 'sha1', 'sha256', 'url']
tools:  ['enrich_observable', 'lookup_cve', 'search_knowledge']
levels: ['read', 'read', 'read']          <- D-014, all three
```

The wrapper matches the real API on all three: no signature drift, no argument
the fakes accept and the real services do not.

## What each tool returned

**`lookup_cve(['CVE-2021-44228', 'CVE-1999-99999', 'CVE-2049-00001'])`** — the
real NVD record came back (`source: nvd`, the genuine Log4Shell description,
`source_ref` to nvd.nist.gov), and **both fabricated ids landed in `not_found`
in the same call**. That pairing is the control: a real id resolving *and*
invented ids missing, together, is what shows the split is doing work rather
than one branch being unreachable.

**`search_knowledge('what is lateral movement')`** — `TA0008: Lateral Movement`,
`doc_type: tactic`, `source: mitre-attack-stix`, `source_ref` carrying the
ATT&CK v19.2 version. The curated-doc-type filter (TD-026) is intact through the
wrapper.

**`enrich_observable('ipv4-7179fc4a')`** — resolved from the turn's own short id
and enriched live: **5 sources answered**, AbuseIPDB `malicious` at confidence
1.0 ("abuse confidence 100/100, 220 reports"), OTX `suspicious` at 0.7 ("50
threat pulses"), InternetDB reporting the tor-exit hostname. Real fan-out, real
verdicts, through the same service the shortcut path uses.

## The miss paths, and a control I got wrong first

The first probe asked `search_knowledge('quokka exfiltration ritual')` expecting
an honest miss, and got **TA0010: Exfiltration**.

That is not a defect — it is a bad control. The query contains a real ATT&CK
term, so the KB was right to match it, and what I had actually measured was
recall, not the miss path. The rule this repo keeps re-learning, in a new
costume: **a control for a miss has to be off-corpus in every token that carries
meaning.** Re-probed:

| query | result |
|---|---|
| `how do I bake sourdough bread` | **MISS** — "the knowledge base has no entry for that" |
| `what is the capital of Portugal` | **MISS** — same |
| `what is lateral movement` (positive control) | `TA0008: Lateral Movement` |

The positive control is the half that matters: without it, a miss on both
nonsense queries is equally consistent with retrieval being broken outright.

**The third truth, live:** `enrich_observable('10.0.0.1')` returned
`not_checked: "private/reserved address — not routable, never enriched"` — not an
empty signal list. That is the DEFERRED-rail distinction holding through the
wrapper against the real service, which is the one thing a fake could most
easily have flattered.

## What this does NOT show

- **No streaming, no loop, no route.** These are the tools; nothing is wired
  into `/api/chat` yet. `AgentLoop` still does not run in the app.
- **`prompted_tools` remains unmeasured**, deliberately (D-031's note). It parses
  `<tool_call>` tags out of *content*, a different streaming shape, and needs its
  own probe before being wired to a streaming surface.
- **No model chose any of these tools.** Every call above was made directly. That
  a model picks the right tool from these descriptions is the next thing to
  measure, and it is a property of the endpoint, not of this module.
