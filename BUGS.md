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
- **Status:** fixed `a90e18a` (B1). The platform had the owner and dropped
  it: AbuseIPDB named Google LLC on turn 1 and a low score returned None. The
  network a source names is now kept beside the verdict (D-055), shown in the
  IOC check and handed to the agent. Live, qwen3:14b names Google LLC 3/3 where
  it said Amazon 3/3 (docs/probes/2026-10-12-b1-b001-fix.md). Bound: only
  AbuseIPDB supplies it (TD-049).

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
- **Status:** fixed `4693084` (F1). Both pages are served `Cache-Control:
  no-cache`. A page cached before the fix needs one reload.

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

## B-005 — the model forges the platform's data fence and writes invented "platform data" inside it

- **Found:** 2026-10-12, B1 (Claude), replaying B-001's turn 2 straight at
  glm-4.5-air with the route's own conversational composition (general mode).
  This is the path a customer endpoint that is not `native_tools` takes; the
  dev endpoint itself takes the agent path on the route.
- **What happened:** the answer opened with a copy of the `⟦DATA⟧…⟦/DATA⟧`
  fence that wraps replayed assistant turns (`auspex/routes/chat.py:118-135`),
  so the markers reached the answer, and added lines the IOC check never
  produced:
  - without the owner in context, 2 of 3 answers added
    `geolocation: United States (US)`, `ASN: AS15169 Google LLC`,
    `hostname: 34.187.179.218`, `reputation: neutral`;
  - with the owner in context, 3 of 3 did, adding `additional context:` and
    `geolocation: United States (likely California, …)` lines.

  It reads as if the platform returned it. Not seen on the agent path (0/3)
  or on qwen3:14b (0/6).
- **Evidence:** docs/probes/b1-b001/raw-replay-glm.log and
  docs/probes/b1-b001/raw-replay-glm-owner.log (the answers verbatim), made by
  docs/probes/b1-b001/probe_replay_conversational.py.
- **Status:** open.

## B-006 — a follow-up on an IP its sources knew nothing about calls it "clean"

- **Found:** 2026-10-12, B1 (Claude), live through `/api/chat` on the dev
  endpoint (glm-4.5-air, agent path), running B-001's two turns.
- **What happened:** turn 1 was the IOC check on 34.187.179.218: no signal
  from 5 sources. Turn 2, "dig deeper", ran in mode `general` (the done
  frame, 3 of 3 runs), and every answer called the IP clean:
  - "The IP appears to be clean according to the current threat intelligence
    data available." (runs 1 and 3)
  - "The IP appears clean according to current threat intelligence data"
    (run 2)

  The `ioc_enrichment` contract's rule, "absence of data is 'unknown', not
  'benign'" (`auspex/modes/catalog.py`), is not in the general directive.
  The same turns after B-001's fix still say "Clean reputation" (3 of 3).
- **Evidence:** docs/probes/b1-b001/raw-before-default.log (the three runs
  verbatim, with their done frames), made by
  docs/probes/b1-b001/probe_app_dig_deeper.py.
- **Status:** open.

## B-007 — the page-logic gate fails on GitHub, where Node prints TAP

- **Found:** 2026-10-12, F2 (Claude), at Step 0's promote: PR #31's CI went
  red on both runs (38210286431, 38210290164) while `./ci.sh` passed locally.
- **What happened:** `tests/test_page_logic.py` ran `node --test` without
  naming a reporter, then looked for the spec reporter's `ℹ pass 32` line.
  All 32 Node tests passed on the runner, but its Node (the one
  `ubuntu-latest` ships; `ci.yml` installs none) printed TAP (`# pass 32`)
  because its output was captured. Local Node v24 prints spec either way.
  F1's work had never run on GitHub before this push.
- **Evidence:** the failed run's log (`1 failed, 1322 passed`; the captured
  output ends `# pass 32`). Reproduced in `node:20-alpine` and
  `node:22-alpine`: the default prints `# pass 32`;
  `--test-reporter=spec` prints `ℹ pass 32`.
- **Status:** fixed `b8ee7fd` (F2), on Burhan's call: the promote could not land red.
