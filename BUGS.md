# BUGS — what is broken, found by using the platform (D-051)

The bugs track works from this list, top open entry first unless Burhan says
otherwise. Add entries with `/bug` mid-session; the session that finds a bug
does not fix it. Not ideas (IDEAS.md), not deliberate shortcuts
(TECHNICAL_DEBT.md).

Each entry: id · found (date, by whom, where) · what happened · evidence ·
status. Status is `open`, `fixing (B<n>)` or `fixed <commit> (B<n>)`. Entries
are never deleted.

## B-001 — the platform named the wrong owner for an IP, and said where it got it

- **Found:** 2026-10-10, Burhan, by hand in the chat page.
- **What happened:** "what do you know about this IP: 34.187.179.218" got the
  IOC check: no signal from 5 sources. A follow-up, "dig deeper", answered
  that the IP belongs to **Amazon.com, Inc.** "based on WHOIS and geolocation
  data", with an AWS hostname. The registry says **Google LLC**. The turn made
  no lookup, and the platform has no WHOIS or reverse-DNS source. It ran on
  the local endpoint (qwen3:14b), on the conversational path.
- **Evidence:** docs/probes/2026-10-12-b001-ip-owner-claim.md (the stored
  turns, the server log, the RDAP result).
- **Status:** fixing (B1).

## B-002 — a definition question on the agent path is stopped as a leak

- **Found:** 2026-10-12, F1 (Claude), by the stream-layer probe against the
  default endpoint (glm-4.5-air, agent path).
- **What happened:** "What are the practical differences between EDR and XDR
  for a small SOC deciding what to buy?" resolved to `definition` and was
  stopped by the output rail in 3 of 4 agent-path turns: `finish:
  output_guard`, `output_valid: false`, no answer, and the analyst reads the
  "stopped mid-stream" copy. The route logged a 40-word match from the
  definition contract's own section spec ("definition one or two sentences
  stating what the term means in practice how it shows up in an investigation
  …"). 40 words is the `thinking` channel's floor (`THINKING_SHINGLE_WORDS`,
  D-040), the floor TD-044 says to re-measure. The same question on the
  conversational path passed twice; two threat_intel questions on the agent
  path passed 3 of 3.
- **Evidence:** docs/probes/2026-10-12-b002-definition-rail-trip.md (the runs
  and the route's log line); docs/probes/fe-stream/raw-layers-glm-default.log.
- **Status:** open.
