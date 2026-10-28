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
- **Status:** fixed `4b753d4` (B2), D-058, on Burhan's call. A thinking model
  plans its answer by restating the sections it was told to write, and the
  tokeniser makes a section list one run longer than the thinking floor
  (definition 43 words, threat_intel 42, D-043's re-ask 42-44). The thinking
  index now drops the re-ask and the runs lying wholly inside the section list
  (narrowed after review, `d8c597b`); every other channel keeps all of it at 8.
  Record: docs/probes/2026-10-13-b2-b002-reproduce-and-calibrate.md.

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
- **Status:** fixed `29209fa` (B2), on Burhan's call (code, not prompt). In a
  fresh chat the model never saw the short id and passed the indicator itself;
  the action resolved only the id. It now also resolves exactly one indicator
  parsed with the route's extractor, inside the workspace. Live: the same call
  files a proposal 3/3 where it errored 3/3
  (docs/probes/2026-10-13-b2-b004-reproduce.md).

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
- **Status:** fixed `fce2f55` + `c80bf29` + `58b45e4` (B2), on Burhan's call (code and
  prompt). The agent's lookup now says `"reputation": "unknown"` with a
  code-written line, and general carries ioc_enrichment's no-data rule. Live:
  a benign verdict 3/3 → 0/3, "unknown" 0/3 → 3/3. After review, `58b45e4`
  covers context-only signals (open ports) too
  (docs/probes/2026-10-13-b2-b006-reproduce.md). The "legitimate" inference
  that remains is B-009.

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

## B-008 — at the usage ceiling, a new chat's question is stored and the turn is then refused

- **Found:** 2026-10-12, F2 final review (Claude), reading the chat route
  against the new sidebar.
- **What happened:** at the workspace's usage ceiling, a NEW chat's question
  is stored (`auspex/routes/chat.py` ~662) and the turn is then refused 429
  (`auspex/routes/chat.py` ~832) with no session frame and no ledger row. The
  page never learns the chat's id, so each retry leaves another sidebar chat
  that reads "No answer was stored", and the `usage_refused` copy ("No answer:
  the workspace's usage limit was reached") never appears on this path. The
  ordering is older than F2; the chat list makes it visible.
- **Evidence:** from reading the code only, not reproduced live.
- **Status:** fixed `4680bf6` (B2), on Burhan's call (discard on refusal). A
  refused turn now deletes the question it stored, and the chat if it created
  it. Reproduced at the route; live at a set ceiling: 429, nothing stored, no
  chat added (docs/probes/2026-10-13-b2-b008-ceiling-refusal.md).

## B-009 — the agent calls a no-signal IP "legitimate" infrastructure, from who operates it and from the absence of signals

- **Found:** 2026-10-13, B2 (Claude), live right after B-006's fix (`fce2f55`,
  `c80bf29`). Dev endpoint (glm-4.5-air), agent path, mode `general`, B1's
  two turns: "what do you know about this IP: 34.187.179.218", then "dig
  deeper".
- **What happened:** the tool result the model read said `"reputation":
  "unknown"`, with "no signal from 5 connected sources: reputation unknown,
  which is not a benign verdict". The answers said unknown 3/3, but 3/3 also
  called the address legitimate:
  - "legitimate Google infrastructure" and "a legitimate Google-owned IP
    address" (3/3);
  - runs 1 and 3 drew it partly from the absence of signals: "The absence of
    any threat intelligence signals suggests this is a legitimate Google-owned
    IP address";
  - run 3 also wrote "despite the clean threat intelligence results".

  Nobody supplied "legitimate". AbuseIPDB named only the operator and the usage
  type. Related to the deferred fabricated-specifics item (SESSION-RULES.md,
  Deferred) and to B-005. A fix that checks what the model writes goes to
  Burhan first.
- **Evidence:** docs/probes/2026-10-13-b2-b006-reproduce.md (the fix section
  and its table); docs/probes/b2-b006/raw-repro-after.jsonl (the three answers
  verbatim).
- **Status:** open.

## B-010 — two older classify rules backtrack on a long whitespace run, and stall the chat route's event loop

- **Found:** 2026-10-14, S29 (Claude), the Step 0 adversarial review of S28's code; same class as the two S28 rules fixed in `8187925`, but older.
- **What happened:** `extract()`'s refang rules (`auspex/classify/observables.py:120-121`,
  from `8e03985`) and `_GREETING_RE` (`auspex/classify/classifier.py`, from
  `b7eaa04`) backtrack quadratically on a run of whitespace.
  `extract("x" + " " * 31998 + "x")` took 3.65 s; the greeting rule took 1.1 s
  at 8,000 characters (~18 s at the 32,000-character message cap). Both run
  synchronously on the route's event loop, so one message stalls every request
  on the worker.
- **A third, found by the review of S29's fixes:** `_DOMAIN_CAND_RE`
  (`auspex/classify/observables.py:181`) is quadratic on `"a." * n`:
  `extract` took 89 ms at 8,000 characters and 1.4 s at 16,000, and
  `classify("a." * 16000)` (32,000 characters) took 5.7 s. `_EMAIL_RE`
  (`:153`) took 92 ms on the same input. A plain possessive would stop
  matching "evil.com." at the end of a sentence; candidates must start only at
  the beginning of a dotted run.
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md, finding 8; docs/probes/s29-review/classify/redos.py.
- **A fourth, found by B3's review of the fix:** `_ANALYTICAL_INITIAL_RE`
  (`auspex/classify/classifier.py`) took 64.3 s on `"." + " " * 31998 + "x"`.
  Fixed inside B-010 (Hunaiza's call).
- **Status:** fixed `0207b4a` (B3). The refang rules take whitespace only from
  where its run begins; the greeting and analytical rules are possessive; the
  domain and e-mail rules are searched by linear scans that skip only the
  positions proven to fail. The worst message at the cap went from 101 s to
  12 ms, and what every rule matches is unchanged (0 differences on 200,501
  inputs). Record: docs/probes/2026-10-19-b3-b010-b024.md. GitHub #38.
  **This closes the classify pass only.** The chat route runs the input guard
  first, and two of its rules had the same shape: B-029, fixed in B3 after
  Burhan's review of PR #41. The pinned inputs now run through the route's
  whole text pass (guard, extract, classify), each under 1 s.

## B-011 — a request to analyse or draft that leads with "Note" or "write a note" resolves to `action_request`

- **Found:** 2026-10-14, S29 (Claude), the Step 0 adversarial review of S28's code.
- **What happened:** each of these resolves to `action_request` (executed:
  `resolve_mode`), whose directive tells the model its job is to record
  something on an indicator:
  - "Note - this came from the CEO's mailbox. Is hxxp://evil[.]net/x malicious?"
  - "Note 203.0.113.9 appeared in three alerts; is it a C2?"
  - "note how the attacker pivoted from fin-ws-12 to dc01 and explain the TTPs"
  - "write a short note to the CISO summarizing the qakbot incident"
  - "add comments to this sigma rule explaining each condition"
  - "annotate this powershell for me: powershell -enc SQBFAFgA"
  - "log comments show 203.0.113.9 failed 400 logins"

  D-050's stated bounds cover "leads with the note, then asks" and asks the
  platform can't do, not "Note" meaning "observe this", nor drafting for
  people. On the agent path the model may file an `annotate_observable`
  proposal nobody asked for (a human still approves it); elsewhere the analysis
  is replaced by "why nothing could be proposed" (inferred, not run live).
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md, finding 9; docs/probes/s29-review/classify/note_fp.py.
  A rule change is judged on blind batteries (SESSION-RULES.md), and the D-050
  operating point is pinned.
- **Status:** open.

## B-012 — the identity shortcut answers questions about bots, AI and providers under investigation

- **Found:** 2026-10-14, S29 (Claude), the Step 0 adversarial review of S28's code.
- **What happened:** each returns the canned identity copy (executed:
  `classify`): "who is behind this bot?", "who owns this bot?", "who created
  this chat?", "which ai made this?", "what llm made this?", "which model did
  this?", "which provider do you use?", "what engine do you use?", "is this
  gemini?". In a SOC these are botnet, Telegram and Teams-phishing questions,
  attribution of AI-made lures, a follow-up on the enrichment echo (which names
  its providers), and a phished exchange. The classifier's own rule is that a
  wrong shortcut is a wrong answer.
- **Burhan's call in part:** D-047 counts "chat / bot / platform" as meaning
  the assistant. A bare "this" after a maker verb was excluded for the same
  reason these would be.
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md, finding 10; docs/probes/s29-review/classify/ident_fp.py.
  The D-047 operating point is pinned; a change is judged on blind batteries.
- **Status:** open.

## B-013 — a fully flattened ECS export is not detected as an alert, and reaches the model raw

- **Found:** 2026-10-14, S29 (Claude), the Step 0 adversarial review of S28's code (the detection gap predates S28).
- **What happened:** an ECS alert whose keys are all dotted
  (`{"@timestamp": …, "rule.name": "LSASS memory dump", "host.name": "dc01",
  "source.ip": …, "event.severity": 73}`) resolves to `ioc_enrichment`, format
  unknown, `parsed=False`. Adding one plain `"message"` key gives
  `alert_triage` with every field right. `_JSON_KEY_RE` is `"\w+"\s*:`
  (`classifier.py:64`, `normalizer.py:29`), and `\w` excludes `.` and `@`. The
  paste skips code-owned triage and the DEFERRED rail, which TD-013's
  mitigation is meant to prevent.
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md, finding 11; docs/probes/s29-review/classify/alerts.py.
- **Status:** open.

## B-014 — the `action_request` contract passes any answer, a claim that the note was added included

- **Found:** 2026-10-14, S29 (Claude), the Step 0 adversarial review of S28's code.
- **What happened:** `contract_for(Mode.ACTION_REQUEST).validate(...)` returns
  `ok=True` for "Done — I've added the note to 203.0.113.9.", for "   " and for
  "## Risk\nHIGH" (executed). So the done frame reports `contract_valid: true`
  for an answer that breaks the mode's only rule. No action can be faked (a
  proposal only comes from a tool call), but the stored answer can say the
  change was made. The test
  `test_the_action_request_contract_asks_for_no_sections_and_never_a_claim_of_done`
  (`tests/test_modes.py`) never checks the claim its name promises.
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md, finding 12.
- **Status:** open.

## B-015 — the agent's `recorded: true` claims more than was written

- **Found:** 2026-10-14, S29 (Claude), the Step 0 adversarial review of S28's code (D-049's payload).
- **What happened:** one `enrich_observable` call over a routable IP with no
  signal, `10.0.0.5` and an unsupplied `8.8.4.4` returned a top-level
  `"recorded": true` (executed with fakes). No verdict was written for any of
  them, and the last two were never recorded at all. The IOC check says
  "Verdicts are recorded" only when an item has signals. And when every
  requested item is skipped, no `recorded` key appears, so D-049's "the model
  is told whether it was recorded" does not hold there.
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md, finding 13; docs/probes/s29-review/d049/probe1.py.
- **Status:** open.

## B-016 — approvals wording: a lost claim says "executed", and a just-refused approve reads as still starting

- **Found:** 2026-10-14, S29 (Claude), the Step 0 adversarial review of S28's code (D-048).
- **What happened (by reading; deterministic paths):**
  - Approve's own run that loses its claim to a withdraw (a stall of more than
    300 s between its read and its claim) returns `already_running`: "this
    proposal is already executing or has executed". The row is `withdrawn`.
  - After an approve-time refusal (for example `spec_changed`), the card sits
    in Decided with "Run now" and "Withdraw". Withdraw answers 409 "approved
    less than 300s ago — its own run may still be starting", which is false:
    the run was refused and the page just said so. Run-now repeats the true
    reason. The page half belongs to the front-end track.
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md, finding 14 (the reviewer's repro sketches are there).
- **Status:** open.

## B-017 — a non-string tool name from the endpoint crashes the agent turn

- **Found:** 2026-10-14, S29 (Claude), the Step 0 adversarial review of S28's code; predates S28.
- **What happened:** a tool call named `["lookup_ip"]` (a list) raises
  `TypeError: unhashable type: 'list'` in the loop (executed with
  `FakeLLMClient`). The client assigns any truthy `function.name`
  (`auspex/llm/client.py:388-389`). The endpoint is the customer's, so its
  output is not trusted to be well-formed.
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md, finding 15.
- **Status:** fixed `59d9a7c`, `0d6f980` (B4): a tool call's id, name, arguments, index and list are read through `_wire_text`/`_as_dict` (auspex/llm/client.py), so a malformed call is an unknown tool. The wider envelope is B-035. Record: docs/probes/2026-10-28-b4-b017.md.

## B-018 — a URL pasted with credentials keeps them, and they are sent to a provider and stored

- **Found:** 2026-10-14, S29 (Claude), the Step 0 adversarial review of S28's code; predates S28, and D-049 widened it to agent lookups.
- **What happened (by reading):** `http://user:pass@host/` keeps `user:pass`
  in the observable's `value` (`auspex/classify/observables.py:207-218`). The
  URL is looked up at URLhaus and upserted into `observables`. Credentials in
  a pasted artefact are exactly what the org's data-handling rules say never to
  echo or store. The model cannot invent one (D-039).
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md, finding 16.
- **Status:** fixed `d78bc43`, `42ffd65` (B4): the userinfo is dropped by text before the URL is parsed (`_drop_userinfo`, auspex/classify/observables.py). Its limit is TD-070; the stored message and pre-fix rows are B-033. Record: docs/probes/2026-10-28-b4-b018.md.

## B-019 — a call refused for budget reads as a real search on the page and in the turn log

- **Found:** 2026-10-14, S29 (Claude), the Step 0 adversarial review of S28's code (D-046).
- **What happened (by reading):** the `phase` event makes the page say
  "Searching the knowledge base" for a call refused without running, and the
  turn log names calls without their status, so a refused call cannot be told
  from an executed search there. D-046 accepted only the `· error` line.
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md, finding 17.
- **Status:** open.

## B-020 — after a lookup that found only context, the answer doesn't say the workspace's earlier verdict still stands

- **Found:** 2026-10-14, S29 (Claude), the review of S29's own fix `14bafba`.
- **What happened (by reading):** `14bafba` keeps a stored `malicious` (or
  any known) verdict when a later lookup finds only context, as D-055 says.
  But what the analyst and the model are told did not change with it: the IOC
  check prints "no reputation verdict — context: InternetDB: open ports …" and
  "Verdicts are recorded and decay over time", and the agent's tool result says
  `"reputation": "unknown"` with `"recorded": true`. Nothing says the earlier
  `malicious` verdict stands, so "recorded" reads as "recorded as unknown",
  while the timeline shows `malicious`. Before `14bafba` the two agreed because
  the store was wrong.
- **Evidence:** docs/probes/2026-10-14-s29-s28-code-review.md (the fix
  review); `auspex/enrich/echo.py:26,51-55,78-79`,
  `auspex/agent/capabilities.py` (`recorded`), `auspex/enrich/store.py`.
  Related: B-015.
- **Status:** open.

## B-021 — a re-homed person's audit event shows the new organization's admins the OLD organization's name

- **Found:** 2026-10-15, S30 (Claude), the fresh review of the final review's
  fix wave (`b75c5d3`, `rehome-person`).
- **What happened (reproduced by the fix's own test):** `admin.rehome_person`
  records `person.rehome` with `details={"from": <old org name>, "to": <new org
  name>}` in every workspace of the NEW organization
  (`auspex/tenancy/admin.py:402-404`), and `GET /api/audit` returns it to that
  organization's admins (`auspex/tenancy/audit.py`, `list_events`). So one
  customer reads another customer's organization name — e.g. a client learns
  that a sibling client exists under the same MSSP. The spec keeps exactly that
  out of the 409 ("without naming it", S30 design §3). The test pins the leak
  as behaviour: `tests/test_tenancy_cli.py:136`.
- **Fix sketch:** the event in the new organization keeps only `to`; the old
  organization's name goes to the operator's CLI output only (the CLI prints
  no email). Same change: a second concurrent rehome of one person answers
  `NotFound` instead of waiting (`admin.py:384-391` locks the user JOIN
  organizations row; lock `users` alone, then read the name), and `admin.py`'s
  docstring overclaims that every membership write takes the workspace lock
  (`provision_dev_user` does not).
- **Burhan's call (2026-10-15):** promote S30 now, fix in the next backend
  session (S31's Step 0) unless B3 takes it first.
- **Status:** fixed `b1fa61e` (S31). The event keeps only `to`; the CLI
  prints the old home (`Rehomed.previous_org`); the rehome locks `users` alone,
  so a second one waits and moves the person on (test-pinned, 4/4 mutants).
  The docstring names `provision_dev_user` as the write that holds no
  workspace. The fresh review found nothing the new home's admins can read
  that names the old one; its test gap was pinned (`3d5007b`), and the older
  race it found in `entry.py` is B-025.

## B-022 — the output rail stops a note-only request when the model's thinking quotes the note tool's description

- **Found:** 2026-10-16, F4 (Claude), the live walk of F2's page on `default`
  (glm-4.5-air, agent path), in headless Chromium.
- **What happened:** in a chat that had just looked 45.155.205.233 up, "Add a
  note to 45.155.205.233: reviewed in the F4 live walk." was stopped
  mid-stream. The page showed the rail's sentence ("This answer was stopped
  mid-stream: it began reproducing the platform's own instructions…"). The
  Thinking pane ended quoting `annotate_observable`'s description: "Calling
  one of these FILES A PROPOSAL for a human to approve. It does not perform
  the action, and nothing in this turn can: the result you get back is a
  proposal id, never an outcome. Say that you have proposed it and what it
  would". No proposal was filed; 1 engine call, tokens not reported. The same
  intent phrased "check 45.155.205.233 again, and add a note that…" filed the
  proposal on the next turn. Looks like TD-044's still-unmeasured
  action-request case (thinking floor, D-040).
- **Evidence:** docs/probes/2026-10-16-f4-shell-live.md ("F2's page with live
  turns"); the reopened turn reads "No answer: stopped by the platform's output
  check".
- **Status:** open.

## B-023 — a `lapsed` staleness pill on the timeline has no colour

- **Found:** 2026-10-16, F4 (Claude), Task 8's code review of the timeline's
  pill classes (pre-existing; F4 kept the behaviour).
- **What happened:** for a verdict whose band is `lapsed`, the page builds a
  pill with class `lapsed`, but `auspex/static/css/timeline.css` colours
  `.lapsed-band` (the `.malicious, .lapsed-band` rule) and has no `.lapsed`
  rule, so the pill shows in the default text colour while every other band
  has its own. Read from the code; not yet seen on screen (no lapsed verdict in
  the dev database during F4).
- **Evidence:** `auspex/static/css/timeline.css` (the `.lapsed-band` rule) and
  `auspex/static/js/timeline.js` (`pill(band, band)` with the server's
  `staleness`); `LABEL_CLASSES` in `auspex/static/js/timeline-logic.js` passes
  `lapsed` through unchanged.
- **Status:** open.

## B-024 — arrow keys on the closed workspace switcher may switch at every step

- **Found:** 2026-10-16, F4 (Claude), the final whole-branch review (reasoned
  from the code; **not reproduced**).
- **What happened (expected, unverified):** the switcher is a native `<select>`
  that switches on `change` (`auspex/static/js/shell.js`, `showSignedIn` /
  `switchTo`). On Windows and Linux browsers, arrow keys on a closed, focused
  select change its value and fire `change` at each step, so a keyboard user
  would be reloaded into each client they pass on the way to the one they want
  (WCAG 3.2.2). The live checks used pointer selection only.
- **Evidence:** none observed yet; the review's reasoning is in the F4 session
  record. Reproduce with a keyboard in Chrome on Windows or Linux before
  fixing.
- **Note:** a fix (a Switch button, or handling the keys) changes the
  switcher's UX, which is Burhan's call.
- **Reproduced at B3:** in headless Chromium on Linux, three arrow presses on
  the closed switcher made three switches and three reloads.
- **Status:** fixed `2bc5eec` (B3). Hunaiza's call (the UX went with the
  handoff): a Switch button. Choosing only selects; the button switches, and
  is disabled for the active workspace and while the page is held. Live: three
  arrows made no switch; Tab and Enter, or a click, made exactly one. Record:
  docs/probes/2026-10-19-b3-b010-b024.md. GitHub #39.

## B-025 — a sign-in that races a rehome shows the old organization's admins the NEW organization's name

- **Found:** 2026-10-16, S31 (Claude), the fresh adversarial review of B-021's
  fix (`b1fa61e`). Older than that fix; not in its lines.
- **What happened (reproduced, forced order):** `enter()` decides access, then
  reads the person's home organization in a separate query
  (`auspex/tenancy/entry.py:24-27`). When the membership is removed and the
  person rehomed between the two, the `workspace.enter` event lands in the OLD
  home's workspace stamped with the NEW home as `actor.organization`, and the
  old organization's admins read that name through `GET /api/audit`: another
  customer's. The window is milliseconds and needs an admin and the operator to
  act during one sign-in or switch.
- **Evidence:** docs/probes/2026-10-16-s31-b025-enter-race.md (script
  `docs/probes/s31-b025/race_enter.py`; output `client1's trail, newest:
  workspace.enter actor.organization = t-s31-b021rev-othercustomer`).
- **Fix sketch (the review's):** read the home and the access in one statement,
  or lock the person's row `FOR SHARE` and re-check inside one transaction.
- **Status:** fixed `6310550`, `e145583` (B4): `enter()` runs in one transaction with the person's row locked `FOR SHARE` first (auspex/tenancy/entry.py); login and switch races pinned. The membership API's same-class path is B-034. Record: docs/probes/2026-10-28-b4-b025.md.

## B-026 — an action argument named like a platform keyword is approved, then the run fails and reads "incomplete"

- **Found:** 2026-10-16, S31 (Claude), the fresh review of the idempotency key
  (`c0af959`); reproduced by the session before logging. The class is older:
  `proposal_id` and `workspace_id` collided before S31, and S31 added
  `idempotency_key` to it.
- **What happened (reproduced):** a note proposal whose arguments carry an
  extra key named `idempotency_key` (or `proposal_id`) beside the declared
  ones dry-runs, files and is approved. The approved run then raises
  `TypeError: …run() got multiple values for keyword argument
  'idempotency_key'`, and the row reads `incomplete` with effects `unknown`
  ("It failed, and cannot tell whether any of it landed") although no note was
  written. `validate_spec` refuses a DECLARED parameter with such a name (S31);
  an undeclared argument key is not dropped or refused at propose time, and
  the note action's dry run accepts it in `**_`. A tool call's arguments come
  from the model.
- **Evidence:** docs/probes/2026-10-16-s31-jobs-live.md ("Found here,
  logged"), script `docs/probes/s31-live/probe_platform_keyword_arg.py`:
  `[idempotency_key] row: status=incomplete result={"error": "TypeError",
  "effects": "unknown"} notes=0`, and the same for `proposal_id`.
- **Fix sketch (the review's):** refuse or strip undeclared argument keys (at
  least the platform's own keywords) when a proposal is filed.
- **Status:** fixed `c0b30de`, `19282ae` (S32). `propose` refuses any argument key the action
  does not declare (`UndeclaredArgument`, auspex/actions/settlement.py), before the dry
  run and before any row.

## B-027 — `extract()` checks every match against every earlier span, so many observables take most of a second

- **Found:** 2026-10-19, B3 (Claude), the fresh review of B-010's fix.
  Outside B-010: this is not backtracking.
- **What happened (measured by the review, not by B3):** `_spans_overlap`
  (`auspex/classify/observables.py`) walks a list of spans for each match, so
  the pass is O(matches × spans). `extract("a@b.co " * 4571)` took 234–835 ms
  (load-dependent); `"http://a 1.2.3.4 " * 1882` 377 ms; `"http://a b.co " *
  2285` 489 ms. All run on the chat route's event loop.
- **Fix sketch (the review's):** walk the spans in sorted order, or bisect.
- **Status:** fixed `be208f4`, `3ca52d7` (B4): a sorted, disjoint `_Spans` index answers each overlap by bisection (auspex/classify/observables.py); growth pinned in CPU time. Record: docs/probes/2026-10-28-b4-b027.md.

## B-028 — a failed switch, after a re-check rebuilt the header with one workspace, throws on a null picker

- **Found:** 2026-10-19, B3 (Claude), the fresh review of B-024's fix
  (reasoned from the code; not reproduced). It predates B3.
- **What happened (expected):** while a switch request is out, a `recheck()`
  can re-render the header through `showSignedIn`. If `/me` then lists only
  one workspace, `picker` becomes null; when the switch then fails,
  `switchTo`'s recovery sets `picker.value` and throws
  (`auspex/static/js/shell.js`, the lines after `switching = false`), leaving
  the status at "switching…".
- **Status:** open, not placed. Burhan's.

## B-029 — the input guard still stalls the chat route on a crafted whitespace or newline run

- **Found:** 2026-10-20, Burhan's review of PR #41 (B3), written by Claude in
  his window; reproduced in B3 before fixing.
- **What happened (reproduced):** `POST /api/chat` runs `guard.inspect()`
  before `classify()` (`auspex/routes/chat.py`). Two guard rules
  (`auspex/guard.py`) start with `(?:^|[.!?]\s+|\n)\s*` (`persona_override`)
  and `(?:^|\n)\s*` (`role_marker_injection`), so a run of whitespace is
  re-scanned from every newline in it, and split every way after a full stop.
  `inspect()` runs each rule over the folded and the raw text. At the
  32,000-character cap: `inspect("\n" * 31999 + "x")` took 130.7 s,
  `inspect("." + spaces + "x")` 67.4 s, `inspect("\n " * 16000)` 59.0 s.
  It predates B3; B-010's goal is not met until it is fixed.
- **Burhan's call (2026-10-20):** "Do NOT re-open the guard regex" protects
  what the guard flags. A speed-only fix is allowed if every verdict and every
  span stays identical. SESSION-RULES.md records the exception.
- **Evidence:** docs/probes/b3-b029/before.txt (`guard_timings.py`).
- **Status:** fixed `8c51cb4` (B3). The two rules are searched by a scan that
  tries them where `finditer` would and skips only the later starts of a run
  whose first start failed; persona_override's prefix is possessive.
  `inspect()` at the cap went from 130.7 s to 11–15 ms. Every verdict and span
  is unchanged: 0 differences on 200,501 inputs against the guard at
  `9475752` (docs/probes/b3-b029/diff_fuzz.py). SESSION-RULES.md records the
  speed-only exception (`e3665d9`).

## B-030 — the guard's quote-line carve-out is quadratic on a newline run

- **Found:** 2026-10-20, Burhan's re-review of PR #41 (B3), by Claude in his
  window. It predates B3. Same tier as B-027.
- **What happened (the review's measurement):** `_QUOTE_LINE_RE`
  (`^\s*>.*$`, MULTILINE, `auspex/guard.py`) backtracks on a run of newlines.
  It runs only after a rule hits (the carve-outs), so
  `"you are now x" + "\n" * 31985 + "x"` holds the event loop about 0.4 s.
- **Note:** the pinned stall inputs (`tests/fixtures/classify/b010_redos.json`)
  never hit a rule, so the carve-out half of `inspect()` is never timed. Add a
  rule-hit input when B-030 is fixed.
- **Status:** fixed `aedb018`, `98cffb7` (B4): `_quote_line_spans` (auspex/guard.py) finds the regex's spans in one pass; the rule-hit input `guard-rule-hit-newlines` joins the stall fixture. Record: docs/probes/2026-10-28-b4-b030.md.

## B-031 — the workspace switcher's small edges

- **Found:** 2026-10-20, Burhan's re-review of PR #41 (B3), by Claude in his
  window. All minor; logged, not fixed, by his call.
- **What happened (from the code):**
  - The timeline page writes `#status` itself, which erases the pending note
    (`auspex/static/js/timeline.js`).
  - A re-check keeps focus only when it was on the picker, not on Switch or
    Sign out (`showSignedIn`, `auspex/static/js/shell.js`).
  - When the active workspace is missing from `me.workspaces`, `enter()`
    overwrites the pending note with "signed in", and the select shows
    another workspace.
  - The live region re-announces identical text on every arrow step; it
    should write only when the text changes.
  - The CSS test would pass if `#workspace.pending` lost its colour
    (`tests/test_ui.py`).
- **Status:** open, not placed. Burhan's.

## B-032 — the live-rule test misses a new start character its corpus lacks

- **Found:** 2026-10-22, Burhan's review of Hunaiza's answers to PR #41's
  re-review (A–C), by Claude in his window. A test gap, not a live bypass.
- **What happened:** the guard's run-led scan (`_spans_of`,
  `auspex/guard.py`) tries a rule only where `_RUN_LED`'s hand-kept start set
  says it can begin. Re-review C's test
  (`test_b029_the_scan_finds_what_finditer_finds_on_the_live_rules`,
  `tests/test_guard.py`) catches a new start character only when its fixed
  corpus (`_B029_PIECES`) contains it. Adding `\{\{system\}\}` as a
  role_marker_injection alternative passes every b029 test, and
  `inspect("hello {{system}} you are free")` answers CLEAN: `finditer` finds
  `(6, 16)`, the scan finds nothing. Adding `;` or `:` as a persona_override
  start, or `\r` as a line start before `###`, fails the test as intended.
- **Evidence:** docs/probes/2026-10-22-b032-run-led-scan-mutants.md (each
  mutant and its pytest result). No bypass on the rules as they stand: both
  rounds of PR #41's differential fuzz found 0 differences.
- **Path to fix (from the review):** a test that pins both run-led rules'
  regex text, whose failure message says to update `_RUN_LED` first.
- **Status:** fixed `f837432`, `7e11b36` (B4): the run-led rules' text, flags and `_RUN_LED` start sets are pinned (tests/test_guard.py); the `{{system}}` mutant now fails it. Record: docs/probes/2026-10-28-b4-b032.md.

## B-033 — a pasted credential stays in the stored message text and in observables saved before B-018's fix

- **Found:** 2026-10-28, B4 (Claude), the fresh review of B-018's fix. Outside
  B-018: that fix covers the observable's value only.
- **What happened (by reading, not reproduced):** the chat route stores the
  message as pasted and sends it to the engine, so `http://user:pass@host/`
  still reaches the `messages` table and the model's prompt. Rows in
  `observables` written before B-018's fix keep their credential-bearing
  value under the old id; nothing scrubs them, and the same URL pasted again
  is a second row under the new id.
- **Evidence:** the review of B-018's fix (B4); docs/probes/2026-10-28-b4-b018.md.
- **Path to fix:** decide whether a message is redacted before it is stored
  and sent (a product call), and a one-off scrub of old `observables` rows.
- **Status:** open, not placed. Burhan's.

## B-034 — a membership change stamps the actor's home read at the start of the request

- **Found:** 2026-10-28, B4 (Claude), the fresh adversarial review of B-025's
  fix. Same class as B-025, a different path; outside B4's scope.
- **What happened (by reading, not reproduced):** `resolve_user`
  (`auspex/auth.py:100`) reads the person's home in one statement and decides
  access in another (`:103`); `auspex/routes/workspace.py:31` stamps that early
  home on `membership.add`/`role`/`remove` events, and `_hold`
  (`auspex/tenancy/admin.py:186-191`) re-checks access inside the write but
  never re-reads the home. Three admin actions inside one request (remove,
  rehome within the same provider family, re-add) stamp the old home.
- **Impact:** stale attribution between a provider and its own client, not
  another customer's name. Needs a re-read of the home `FOR SHARE` inside
  `_hold`, used for the actor.
- **Evidence:** the review of B-025's fix (B4); docs/probes/2026-10-28-b4-b025.md.
- **Status:** open, not placed. Burhan's.

## B-035 — a reply envelope in the wrong shape still crashes the parsers, and an unknown tool's name is echoed unbounded

- **Found:** 2026-10-28, B4 (Claude), the fresh review of B-017's fix. The
  same trust boundary as B-017 (the customer's endpoint), a wider class:
  B-017 covered the tool calls themselves.
- **What happened (executed by the review, throwaway scripts):** in
  `auspex/llm/client.py`, `choices`, `choices[0]`, `message` or `delta` that
  is not an object raises (AttributeError/TypeError/KeyError) in both
  parsers; a streamed `content` or reasoning that is not a string raises on
  `+=`, and `parse_completion` passes a non-string `content` through; a body
  or chunk that is a JSON list or string, or a non-object `usage`, raises;
  non-streaming `tool_calls: 5` raises, and `tool_calls: "abc"` becomes three
  empty calls. A non-string `finish_reason` passes through unaudited. The
  loop's unknown-tool feedback (`auspex/agent/loop.py`, and the prompted
  `<tool_result name="…">`) echoes the name unbounded, control characters and
  `<tool_result` included.
- **Path to fix:** one "coerce the envelope" pass at the top of both parsers,
  fixtures from the review's exact inputs; truncate and escape the echoed
  name.
- **Evidence:** the review of B-017's fix (B4); docs/probes/2026-10-28-b4-b017.md.
- **Status:** open, not placed. Burhan's.

## B-036 — credentials outside an http(s) URL are stored, a bare one as an email

- **Found:** 2026-10-28, Burhan's review of PR #50 (B4). Already true on
  `staging`; outside B-018, which covers http(s) URLs only.
- **What happened (the review's examples):** `ftp://admin:S3cret@files.example.com/x`
  (not matched by `_URL_RE`, http(s) only) and a bare
  `admin:S3cret@mail.example.com` store the password as the email
  `s3cret@mail.example.com` (`auspex/classify/observables.py`, the email pass).
- **Path to fix:** decide which schemes and bare `user:pass@host` shapes are
  credentials, and drop them before any observable is made; it may sit next to
  B-033 (the pasted message itself).
- **Evidence:** Burhan's comment on PR #50.
- **Status:** open, not placed. Burhan's.

## B-037 — a membership removed while its person signs in still gets an entry event and a first token

- **Found:** 2026-10-28, Burhan's review of PR #50 (B4), from B-025's race
  test. Same family as B-025; B-025's fix locks only the person's row.
- **What happened (by reading; B-025's test interleaving shows it):**
  `enter()` (`auspex/tenancy/entry.py`) locks `users` `FOR SHARE`, not the
  membership. A membership deleted between the access decision and the event
  still gets a `workspace.enter` event and the route mints a first token. Every
  request re-checks access (`resolve_user`), so that token is refused on its
  next use; the harm is an audit event for an entry that did not hold.
- **Path to fix:** lock the membership row (or re-check it) inside `enter()`'s
  transaction before the event, or record the event only once the first
  authenticated request succeeds.
- **Evidence:** Burhan's comment on PR #50; docs/probes/2026-10-28-b4-b025.md.
- **Status:** open, not placed. Burhan's.

## B-038 — a URL with `\` before an `@` is read with a different host downstream than a browser uses

- **Found:** 2026-10-28, B4 (Claude), the fresh review of B-018's third fix.
  Already true on `staging` (the value is kept as is there too).
- **What happened (executed by the review):** for http(s) a browser reads `\`
  as `/`, so `http://10.0.0.5\@evil.com/x` goes to `10.0.0.5`. The extracted
  value keeps that text, and `auspex/enrich/filters.py:31` and
  `auspex/phishing/victims.py:30` take its host with `urlsplit(...).hostname`,
  which does not treat `\` as a delimiter and answers `evil.com`. So an
  internal URL skips `INTERNAL_URL_SKIP` and is sent to URLhaus. Separately,
  `_normalize_url` lowercases the whole netloc, which with `\` runs into what
  a browser reads as path.
- **Path to fix:** one host-of-URL helper that follows WHATWG for every
  consumer, or canonicalise `\` to `/` in a URL's scheme and authority in
  `_normalize_url`.
- **Evidence:** the review of B-018's third fix (B4).
- **Status:** open, not placed. Burhan's.

## B-039 — a tab, newline or quote inside a pasted URL cuts its match short

- **Found:** 2026-10-28, B4 (Claude), the fresh review of B-018's third fix.
  Pre-existing in `_URL_RE` (`auspex/classify/observables.py`, `[^\s<>"']+`).
- **What happened (executed by the review, and on `staging`):**
  `http://u:secret\n@evil.com/` extracts the URL `http://u:secret` and the
  domain `evil.com`, so the user and password reach an observable's value; a
  browser strips tabs and newlines, so `http://paypal.com\t@evil.com/` goes to
  `evil.com` while the value says `paypal.com`. `"`, `'` and `<` cut it too
  (`http://u:p<x@evil.com/` also yields the email `x@evil.com`). `http:/\evil.com/`
  is not a URL at all (`_URL_RE` requires `://`).
- **Path to fix:** decide how a pasted URL's boundary is found when it holds
  WHATWG-stripped characters; it is a regex-boundary question, not B-018's.
- **Evidence:** the review of B-018's third fix (B4).
- **Status:** open, not placed. Burhan's.
