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

## B-003 — after a deploy, the browser keeps running the old chat page

- **Found:** 2026-10-12, F1 (Claude), live-checking D-052's page change in a
  real browser against the rebuilt container.
- **What happened:** `docker compose up -d --build app` shipped a new
  `index.html` (a curl of `/` showed its new `// <page-logic>` block). A
  Playwright browser that had loaded the page about 25 minutes earlier then
  navigated to `http://localhost:8000/`, signed in and ran a turn. The
  turn ran on the **old** page.
- **Evidence:** observed in that browser:
  - `performance.getEntriesByType('navigation')[0].transferSize` was `0`;
  - `typeof indicatorText` was `"undefined"`;
  - `send.toString()` did not contain `createPacer`.

  The page's response headers (curl GET `/`, same time) were
  `HTTP/1.1 200 OK`, `last-modified: Mon, 12 Oct 2026 02:20:02 GMT` and
  `etag: "cfd58c52621be79d7de8d54fed5fa25d"`, with **no `cache-control`**.
  `auspex/routes/ui.py` serves `index.html` and `timeline.html` with
  `FileResponse` and no extra headers. Re-checkable at any time with
  `curl -s -D - -o /dev/null localhost:8000/`.
- **Status:** open.

## B-004 — a note on a recorded indicator is refused as "doesn't exist"

- **Found:** 2026-10-12, F1 (Claude), live through the page while testing the
  approvals panel (Standard, agent path).
- **What happened:** turn 1 in one chat ran `enrich_observable` on
  `185.220.101.52` and filed a note proposal on `ipv4-9bf483a1`. In a new chat
  (page reloaded, no history), "Add a note to 185.220.101.52 saying the
  beaconing stopped after fin-ws-12 was reimaged." got "I cannot add a note to
  185.220.101.52 because this observable doesn't exist in the current
  workspace." The observable existed. No proposal was filed. The log line was
  `mode=action_request steps=2 tools=['annotate_observable']`.
- **Evidence:** docs/probes/2026-10-12-b004-note-on-recorded-indicator.md (both
  turns, the answer, the log line, the observable's row). Related but
  different: S28's IDEAS line about a note-only request on an indicator the
  workspace has never seen.
- **Status:** open.
