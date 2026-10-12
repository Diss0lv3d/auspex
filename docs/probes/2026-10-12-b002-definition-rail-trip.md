# B-002 — a definition question on the agent path stopped by the output rail (evidence)

_2026-10-12, F1. Found by the stream-layer probe (`docs/probes/fe-stream/probe_layers.py`),
which runs the app in-process against the default endpoint (glm-4.5-air on
Z.ai, agent path). The route's own log line is the only copy of the matched
run, so it is saved here. Observed, not diagnosed._

## The question

`What are the practical differences between EDR and XDR for a small SOC deciding what to buy?`

## Agent-path turns on the default endpoint (`raw-layers-glm-default.log`)

| run | question | mode | calls | finish | output_valid |
|---|---|---|---|---|---|
| harness check (06:50 UTC+5) | Q1 | definition | 4 | stop | True |
| 1 | Q1 | definition | 4 | output_guard | False |
| 2 | Q2 | threat_intel | 4 | stop | True |
| 3 | Q3 | threat_intel | 4 | stop | True |
| 4 | Q1 | definition | 4 | output_guard | False |
| re-run for the log line (06:53 UTC+5) | Q1 | definition | 4 | output_guard | False |

Q1 on the agent path: **3 of 4 stopped.** No content frame reached the client
on any of the three, and one endpoint reasoning delta had no matching frame
at the client. The same question on the conversational path
(dev entry `glm-native`, runs 1 and 4 of `raw-layers-glm-glm-native.log`)
finished `stop`, `output_valid: true`, both times.

## The route's log line (re-run, our text only)

```
2026-10-12 06:53:45,423 auspex.chat WARNING output leak: mode=definition matched='definition one or two sentences stating what the term means in practice how it shows up in an investigation signals telemetry or where an analyst meets it related optional omit if not applicable closely related concepts or techniques by name'
```

The matched run is 40 words. The scanner reports a run of exactly the
channel's shingle length (`auspex/outguard.py:193-203`); only the `thinking`
channel's is 40 (`THINKING_SHINGLE_WORDS`, D-040), every other channel's is 8.
