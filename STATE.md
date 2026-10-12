# STATE — Auspex

_Last updated: 2026-10-12 — **B1 CLOSED** (session-end ritual run), after F1.
`./ci.sh` green at B1's close: **1323 tests, 120 modules**. `/api/health/ready`
200. `./scripts/demo.sh` exited 0 at B1's close. Branch `staging`.
**F2 in flight:** promote #31 (`7ac1900`, back-merge `730332a`) shipped at
F2's Step 0 with F1's and B1's work, after B-007 (GitHub's Node prints TAP;
fixed `b8ee7fd`) turned its first run red. **Promote slate: IDEAS-only** (two
F2 entries)._

## Tracks (D-051) — read this first

| Track | Prompt | Last closed | Next | Status |
|---|---|---|---|---|
| backend | `NEXT-SESSION-BE.md` | S28 (2026-10-11) | S29 | paused |
| front end | `NEXT-SESSION-FE.md` | F1 (2026-10-12) | F2 | **focus** |
| bugs | `NEXT-SESSION-BUGS.md` | B1 (2026-10-12) | B2 | ready: B-002 on top; B-004, B-005, B-006 open |

- **Focus: front end.** Burhan, 2026-10-10, after S28's ritual: "before moving
  on with more backend development we need to improve on the FE so lets shift
  our focus there and pause BE for a bit."
- **The 2026-10-12 two-window collision is over.** F1 and B1 ran at once that
  morning, and both ran Step 0's `/promote`. B1 opened PR #30 while F1's
  `ci.sh` ran, and merged it 4 s before F1's merge; the promote is correct
  (F1 verified it). Burhan paused B1, F1 closed, then B1 resumed in its own
  window and closed. **One session at a time (D-051).** Running two at once is
  parked in IDEAS ("Parallel tracks"); adopting it needs a new D-entry that
  overturns D-051's rule.
- **That pivot was nearly lost** (2026-10-10). Recovered from the session
  transcript; evidence in docs/probes/2026-10-12-b001-ip-owner-claim.md.
- Standing rules every track obeys: `SESSION-RULES.md`. Bugs: `BUGS.md`.

## B1 — what happened (bugs track's first session)

B1 ran 2026-10-12, in two halves around F1 (above). Burhan made two calls:
where the owner lives (D-055), and ending after B-001 rather than taking
another bug.

1. **Promote #30** (Step 0): see the collision note above.
2. **Goal: B-001, the invented IP owner — fixed (`a90e18a`).** Record:
   docs/probes/2026-10-12-b1-b001-fix.md; scripts and logs in
   docs/probes/b1-b001/.
   - **Reproduced through `/api/chat`, both endpoints, 3 runs each.**
     - glm-4.5-air took the agent path and looked the IP up: 0/3 invented an
       owner.
     - qwen3:14b took the conversational path with no tools: **Amazon 3/3**,
       claiming WHOIS and Shodan.
   - **Why no tools.** "dig deeper" resolves to `general`, because the
     resolver reads only the current message (`auspex/modes/resolver.py:129`).
     Dev-switcher endpoints carry no agent mode, so they stay conversational
     (D-037), as does a customer endpoint that is not `native_tools`.
   - **Replayed one variable at a time.** The mode did not decide it:
     `ioc_enrichment` said Amazon 2/3 on glm. The owner in context did: 9/9
     Google.
   - **Root cause: the platform had the owner and threw it away.** On turn 1,
     AbuseIPDB named Google LLC (isp, domain, hostname) and OTX named
     AS15169. A low AbuseIPDB score returned None, so the echo said "unknown
     to them".
   - **Fix (Burhan's call, D-055).** A lookup may return a `NetworkContext`
     beside its signal, or alone. It is never a verdict, so it is never
     recorded and cannot flip one. The IOC check shows it and the agent's
     tool result carries it.
   - **Proven.** 8 new tests (six failed before; two pin unchanged
     behaviour), with the exact offending answer pinned in
     tests/fixtures/enrich/b001_ip_owner_claim.json. 3/3 mutants caught.
     Full gate green.
   - **Live, rebuilt container:** qwen names **Google LLC 3/3** (was Amazon
     3/3). glm 3/3, and its agent turn now makes one lookup instead of two
     (~3.1k tokens, was ~4.1k).
3. **Found and logged, not fixed:**
   - **B-005:** on the conversational path glm forges the `⟦DATA⟧` fence
     and writes invented "platform data" inside it;
   - **B-006:** a follow-up on a no-signal IP calls it "clean", because the
     follow-up resolves to `general`.
4. **Bounds.**
   - Only AbuseIPDB supplies the owner (TD-049).
   - The model still adds what nobody supplied ("likely us-central1"). That
     is the deferred fabricated-specifics item, not re-scoped.

About 25 inference calls on Z.ai, plus local qwen runs.

## F1 — what happened (front-end track's first session)

F1 ran 2026-10-12. At the start ritual Burhan named nothing else he had seen on
the page, and added **all three candidates** to the goal. Mid-session he
picked from options four times (the stream, links, the panel's shape, the
ledger's unit) and asked for B-003 to be fixed in F1.

1. **Promote #30**, with the collision above.
2. **Goal: where a deep turn's reasoning loses its speed — measured first**
   (docs/probes/2026-10-12-f1-stream-layers.md). Three layers on the same
   runs, plus the page in a real browser, both endpoints:
   - the server adds ~1 ms a delta (p50; 4.6 ms max);
   - the page ~3 ms to paint (p50; 41 ms max), with no long tasks;
   - **the endpoint is the whole of it**. glm-4.5-air bursts at ~1000
     chars/s with 1-13 s silences between an agent turn's calls. qwen3:14b
     runs 139-171 chars/s.

   B-001's 3 min 13 s qwen turn was not reproduced (a cold start is 4.7 s).
3. **D-052 (Burhan picked all four options):**
   - a `status` frame before every model call, tool and held answer;
   - a working line ("Thinking · 3 s");
   - pacing bounded at 200 ms (live max 200.4 ms);
   - the switcher's local endpoint relabelled "Local (slow)".
4. **D-053, safe markdown in answers.**
   - A pure parser plus a DOM builder, with no `innerHTML` anywhere.
   - Links are clickable, https only, and show their real host. That was
     Burhan's call, over the recommendation to leave them literal; the risk
     is stated in D-053.
   - Code spans are neutral.
   - Live: an `<img onerror>`/`<script>` in an answer is text and never runs.
5. **The approvals panel** (docs/superpowers/specs/2026-10-12-approvals-panel-design.md).
   - Every door the API has, by status. Two clicks for the doors that run
     something, disarming after 5 s. Decided cards stay for the session.
   - Live on real proposals: approve → done → undo → undone, and a reject
     (docs/probes/2026-10-12-f1-approvals-panel-live.md).
   - Fixed during the run: the open panel covered Send, and a rejected card
     still showed its undo line.
6. **D-054, the cost ledger.** One `turn_spend` row per deep turn, failed
   turns included. Each answer gets a line, and the chat its total
   (`GET /api/chat/sessions/{id}/spend`). Live, a 4-call turn's row matched
   its line exactly.
7. **B-003 fixed** (`4693084`): the pages are served `no-cache`, so a deploy
   reaches an open browser. A page cached before the fix needs one reload.

**Found and logged, not fixed:** B-002 (the rail stops a definition question on
the agent path 3 of 4 times: TD-044's trigger, live) and B-004 (a note on a
recorded indicator is refused as "doesn't exist").

**How the work was proven.**
- The page's logic lives in a `// <page-logic>` block, run under Node by
  `tests/js/page_logic.test.mjs` (32 tests) inside the pytest gate
  (`tests/test_page_logic.py`).
- The test element factory is frozen, so a builder that edits an element
  after creating it fails as it would on a real DOM. That caught a real bug.
- Mutants were run on every guard: the loop 2/2, the route 4/4, the page
  3/3 + 3/3.
- Every page change was checked in headless Chromium against the rebuilt
  container.
- About 60 inference calls on Z.ai, plus local qwen runs.

## S28 — what happened (backend track's last session)

S28 ran 2026-10-11. At the start ritual Burhan answered the candidates question
with **"all"**, so all three candidates joined the goal. Mid-session he made
three more calls:
- fix the identity leak;
- keep D-002 (put back to him as overturn or drop: dropped);
- both doors for TD-042.

Everything is recorded where it lives:

1. **Promote #29** (`31f7fc1`) shipped the S27 slate (D-042…D-045), with the
   back-merge `08bebdf`.
2. **An adversarial second-pass review of S27's own code** (record:
   docs/probes/2026-10-11-s28-s27-code-review.md). Three findings:
   - `831dedc`: an undo that lost its row and got it back said "moved from
     incomplete to incomplete". It now refuses as `contended`.
   - `3a09fcd`: a real action call was logged as `<unregistered>`.
     `AgentLoop.knows()` fixes it.
   - **Live, 4/4 identity questions that missed the shortcut were answered
     "I'm Claude, by Anthropic".** That is false and breaks D-002. It became
     D-047 (item 5).

   Cleared: D-043's hold, D-042's re-probe, D-044's contract, D-045's
   proposal path, and `922f30c`/`9458518`. Two bounds were stated (tool-result
   text is unindexed by D-031's design; a leaking held draft ends the turn).
3. **Goal: TD-043 → D-046, measured first.**
   - **0 of 31 re-searches were misses.** Every search returns a full page,
     because the KB has no entity documents.
   - `search_knowledge` now has a per-turn budget of 3. It is withdrawn from
     the wire once spent, and a call from history is refused (glm-4.5-air
     made one every thin turn). The last allowed result says it was the last.
   - S27's prompts went **37 calls → 23**, with no step-cap hits and 6/6
     conformant.
   - Price: the LockBit turns no longer reach T1566. TA0001, found first,
     names the same vectors.
   - De-dup and a budget of 5 were measured and not shipped (thrash brake).
     Record: docs/probes/2026-10-11-s28-td043-search-budget.md.
4. **Goal: TD-042 → D-048 (Burhan: both doors).**
   - An `approved` row with no claim, older than STALE_CLAIM_SECONDS, rejoins
     the queue.
   - `POST /{id}/execute` re-runs `check_executable` and records the human in
     `resolved_by`.
   - `POST /{id}/withdraw` moves it to the new status `withdrawn`, added to the
     one status-CHECK block in place.
   - Both doors are stale-only and claim-first, with a race test. 6/6 mutants
     were caught. Live through the container (docs/probes/s28-td042/).
5. **D-047, identity.** The widened shortcut was judged on a held-out battery
   written blind: **0/45 → 18/45 caught, 0/45 false positives.** The copy says
   it runs on "the platform's engine", never the model (D-002 kept).
6. **Candidate → D-049.** What the agent looks up is recorded like the IOC check
   (`record` → `persist_enrichment`), and the model is told
   `recorded: true/false`. Live: one turn checked a never-seen IP, recorded it,
   and filed its note proposal.
7. **Candidate → D-050.** A note request never takes the IOC shortcut. One that
   leads the message resolves to an eighth mode, `action_request`, with no
   sections. Held out:
   - note-only → `action_request`: 0/30 → **19/30**;
   - note-only → shortcut: 9 → 3;
   - mixed → shortcut: 6 → 0;
   - **0 false positives.**

   Live: `contract_valid: true`.
8. **Candidate: alert JSON keys, measured against the published ECS and
   Microsoft Graph schemas** (docs/probes/2026-10-11-s28-alert-json-keys.md).
   - **An ECS alert was named after its host** (`host.name` before
     `rule.name`). Fixed (`e2af082`), and `source.ip`/`destination.ip`/
     `processCommandLine`/`createdDateTime` are now read.
   - The S27 MEDIUM was the scorer, not the keys. Documented credential-theft
     alerts score **LOW 35** (IDEAS).

**How the work was proven.**
- Every fix and feature shipped with tests, and each one was shown to fail
  before the change.
- Mutants were run: TD-043 3/3, TD-042 6/6, D-049's route wiring.
- Classifier/resolver changes were judged on batteries written by agents that
  never read the repo, with the held-out one opened once after freezing.
- Live checks went through the rebuilt container.
- About 70 inference calls on Z.ai, well under a dollar.
- **One gate went red in between and was fixed before commit:** a comment in
  `classifier.py` said "requests", and the structural test that forbids that
  library's name in the classify package caught it. Targeted test runs had
  skipped that file; the full gate did not.

## Where we are

Phase 4:
- contract (S17);
- decision loop (S18);
- hardened input and spend (S19);
- pipeline/docs/demo (S20);
- beta debt (S21);
- output rail (S22–S24);
- tools as prompts and a streaming loop (S25);
- the agent path live in chat (S26);
- verdicts the code decides held on screen, and the agent proposing (S27);
- **S28: the agent's spend bounded per tool, an approval that never ran given
  doors, the agent's lookups recorded, note requests routed to a mode they can
  meet, and the engine no longer naming another vendor on 18/45 held-out
  identity questions;**
- **F1 (front end): the endpoint measured as the whole of the slowness; the
  page saying what a turn waits on and pacing what arrives (D-052); answers in
  safe markdown (D-053); every approvals door on the page; and every deep
  turn's spend recorded and shown (D-054);**
- **B1 (bugs): the network a source names reaches the analyst and the model,
  beside the verdict, never as one (D-055, B-001).**

The ROADMAP through S20 is complete; S21–S28, F1 and B1 were each scoped by a
decision or a bug.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: IDEAS-only.** Promote #31 (`7ac1900`, back-merge
   `730332a`) shipped F1's and B1's work and B-007's fix at F2's Step 0.
   Since then staging holds only F2's two IDEAS entries.
   - **The first session of any track runs `/promote` as its Step 0 — but
     only ONE window at a time** (the 2026-10-12 collision).
   - Read `git diff origin/main..staging --stat`, never the commit list.
   - **The two untracked overview files stay untracked — Burhan's call,
     2026-10-10.** `Auspex-Product-Architecture-Overview.pdf` and
     `docs/auspex-overview.html` are his; never commit, move, publish or delete
     them, and do not ask again.
2. **S28's own code has had no second-pass review.** Each change was
   mutant-checked or battery-judged by its author, but nobody else has read it
   adversarially:
   - D-046's budget (`_on_offer`, `_dispatch_within_budget`, the notice);
   - D-048's two doors (`run_stale_approval`, `withdraw`, the shared
     `_run_claimed`, the queue clause);
   - D-049's `record`;
   - D-047's `_IDENTITY_RE`;
   - D-050's `_NOTE_ASK_RE`/`_NOTE_REQUEST_RE` and the `action_request`
     contract;
   - the alert-name precedence (`e2af082`);
   - the review fixes `831dedc` and `3a09fcd`.

   The S27 review of S27's code (closed at S28) found three.
3. **TD-036's trigger FIRED at S28 — the analyst reads the answer twice.** In
   2 of 3 D-049 probe turns, glm-4.5-air wrote a full answer before its
   annotate call. It passed the 400-char hold, streamed as answer, and then the
   real answer followed. The route logged the TD-036 line both times. Not
   fixed: re-measure the longest pre-tool narration on action-calling turns
   first.
4. **The rail's index keeps growing (TD-044; its trigger fired again at S28).**
   - `SHINGLE_WORDS = 8`: re-run `docs/probes/s22-outguard/probe_calibrate2.py`.
   - **`THINKING_SHINGLE_WORDS = 40`** (D-040): re-run
     `docs/probes/s26-step0/probe_calibrate_agent.py`. **Its margin is only
     1.4×** over the live legitimate ceiling of 28, so re-measure it **first**
     on any model change. D-042 logs a WARNING when the endpoint changes under
     the same name; that line is the trigger.
   - S27 added D-043's repair directive and D-045's action surface. S28 added
     D-050's `action_request` directive.
   - Every live S28 turn read `output_valid: true` (about 8 turns). The
     legitimate ceiling has not been re-calibrated.
   - **F1: the trigger fired as a live false positive (B-002).** A definition
     question on the agent path was cut 3 of 4 times. The match was 40 words
     of the definition contract's section spec on the THINKING channel, at
     exactly `THINKING_SHINGLE_WORDS`. The re-calibration is now a bug's
     evidence, not a precaution.
5. **The card stream still emits only new cards, never status changes.** A
   client watching `/stream` is not told when a claim goes stale, or when a row
   becomes `incomplete`/`kept`/`withdrawn`, or rejoins the queue as a stale
   approval (D-048). The polled list is where those surface, and **F1's
   approvals panel polls it every 5 s** (TD-046).
6. **TD-031 / TD-032 / TD-033 are ratified bounds, not a backlog.** Do **not**
   re-open the guard regex.
7. **TD-005 trigger, still armed:** cve pool > 300k chunks, curated pool > 5k,
   any new doc_type, any embedding-model change, **or before any
   free-text-over-CVEs surface ships** (TD-027 is a HARD GATE). The IDEAS line
   "ingest ATT&CK groups and software" would be a new doc_type.
8. **Test usage isolation is designed for test_chat_sse.py (autouse refund) and
   incidental elsewhere.** Any other file whose tests spend inference calls has
   the 29-unit problem waiting; the `default` workspace has an hourly ceiling of
   100. All S28 chat tests live in test_chat_sse.py.
9. **The agent proposes; the bounds that remain.**
   - **D-049 retired the first** (an action could only target an observable
     the shortcut had recorded).
   - The approvals surface serves the stored, code-rendered card unscanned.
   - A turn the rail cuts at a tool frame can still leave a filed proposal.
   - `prompted_tools` is still unwired, and the narration hold is
     native-only.
   - **New, live (D-050):** a note-only request on an indicator the workspace
     has never seen is refused (`NothingToPropose`) and answered honestly. The
     agent does not look the indicator up first, which would record it and let
     the proposal file (IDEAS).
   - **F1, live: B-004.** A note-only request in a new chat on an indicator the
     workspace HAS recorded was refused as "doesn't exist". That is false.
10. **D-041's bound, and TD-025.**
    - A merely slow handler on an abandoned run can land after its put-back.
      It is recorded on the row, not prevented.
    - There is no idempotency key: **both matter the day an action reaches a
      network.**
    - TD-042 is closed (D-048). Its own bound: `resolved_by` is the LATEST
      human resolver.
11. **Brand, partly owned now (D-047).** The identity shortcut catches 18/45
    held-out identity questions. **The other 27 reach the model, which named
    another vendor 4/4 times live.** Nothing guards the model's
    self-description in the answer or the Thinking pane. D-030/D-040 check for
    OUR configuration, not the model's claims about itself.
12. **D-043's drift log is cleaner but not clean.** D-050 sends note-only turns
    to `action_request` (no sections). A **mixed** request ("check X and add a
    note") stays in its analysis mode, and 11/30 held-out note-only phrasings
    still miss. Either can still log drift honestly.
13. **Three classifier/resolver operating points are pinned:**
    - D-044: `test_the_measured_operating_point_on_the_independent_battery_holds`;
    - D-047: `test_the_identity_operating_point_on_the_held_out_battery_holds`;
    - D-050: `test_the_action_request_operating_point_on_the_held_out_battery_holds`.

    Every battery behind them is training data now. **Any improvement claim
    needs a fresh, independently written battery.**
14. **D-046's price.**
    - Thin-topic turns reach fewer documents. The LockBit turns lost T1566;
      TA0001 still grounds the vectors.
    - A refused over-budget call shows in the turn as `· error`.
    - The cause is KB coverage (IDEAS: ATT&CK groups and software).

15. **Model-written links are clickable now (D-053, Burhan's call).** They are
    https only, show their real host, and open with `noopener noreferrer`. A
    poisoned answer can still put a clickable link in front of an analyst; the
    host beside it is the mitigation, not a prevention.
16. **The page's logic is a tested block; the page is one 808-line file**
    (TD-045). Split it into modules past ~1000 lines, as its own change, with
    no-cache on the scripts too (B-003).
17. **The spend ledger (D-054) counts what a turn's own ending records.** A turn
    cut by a dropped connection may record nothing (TD-048).
18. **An address's network now comes from one source (D-055, TD-049).** Only
    AbuseIPDB supplies it, and it is key-gated. A deployment without its key
    is back on B-001's path. OTX's keyless `asn` is still dropped.
19. **The conversational path is where the model invents (B1).** With no
    tools, glm forged a `⟦DATA⟧` block with invented platform lines (B-005).
    Both models added specifics nobody supplied. Every customer endpoint that
    is not `native_tools` takes this path (D-037).

**Closed at B1, so they leave this list:** none of the above closed. B1 added
#18–#19.

**Closed at F1, so they leave this list:** none of the above closed. F1 added
#15–#17.

**Closed at S28, so they leave this list:**
- the old #2, "S27's own code has had no second-pass review" (done; three
  findings);
- TD-042 (D-048) and TD-043 (D-046);
- the IDEAS lines for agent-path persistence (D-049), the action-request mode
  fit (D-050), and alert-normaliser key coverage (measured; the remaining
  issue is the scorer, now in IDEAS).

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** is a hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Open debt.**
   - Still open: TD-014 … TD-025, TD-027, TD-029, TD-030, TD-031/032/033,
     TD-035 (the two-pass path only), **TD-036 (trigger fired, S28)**,
     **TD-044 (trigger fired again, S28; live false positive at F1: B-002)**,
     F1's TD-045 … TD-048 (the page in one file, the panel polling, a full
     response per page load, spend unrecorded on a dropped connection), and
     B1's TD-049 (only AbuseIPDB names an address's network).
   - **Closed at S28:** TD-042, TD-043.
   - Closed earlier: TD-012, TD-018, TD-026, TD-028, TD-034, TD-037…TD-041.
3. **The KB bootstrap needs outbound HTTPS once per fresh volume**, and ingest
   needs NVD/CISA/FIRST/GitHub reachability. Failures degrade honestly.
4. **The corpus keeps growing while the container runs.** TD-011 tracks the
   index rollover trigger.
5. **Two rails, and neither is a closure.**
   - The INPUT guard bounds accidents and naive attempts (D-027, D-029).
   - The OUTPUT rail (D-030) catches our configuration coming back out, but not
     a paraphrase, and not an injection that merely made the answer wrong.
   - D-043 prevents a wrong code-decided verdict from being shown. It cannot
     prevent a wrong narrative answer.
   - Three defects in three sessions (S23, S24, S26). **Assume a fourth
     exists.**
6. **An intermittent, unattributed test failure was observed once in S22.** Not
   reproduced in any later full run, including about ten at S28. Still recorded
   rather than dismissed.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`.
- Ollama 0.34.0 on :11434 (root `http://localhost:11434/v1`, D-033); models
  qwen3:14b / llama3.1:8b / mistral:latest. The S28 start gate passed.
- **Primary dev LLM is glm-4.5-air on Z.ai (D-034)** — `https://api.z.ai/api/paas/v4`,
  pay-as-you-go key in `.env` as both `GLM_API_KEY` and `LLM_API_KEY`. **Never the
  Coding Plan endpoint.**
  - Thinking is on by default and billed inside `completion_tokens`.
  - **Prose precedes tool calls** (TD-036, triggered again at S28).
  - **It calls a tool withdrawn from the wire if it is in its history** (S28,
    D-046).
  - **It calls itself "Claude by Anthropic" when asked** (S28, D-047).
  - `json_schema` is silently ignored; `json_object` works.
  - glm-4.7-flash (free) answered 429 "overloaded"; glm-4.7-flashx hung once
    past 180 s. Rate limits are console-only.
- **Scout on Northflank is GONE** — `p01--new-llm--…code.run` is NXDOMAIN (2026-10-10).
- **S28 session-end (2026-10-11):** staging, identity `bh3082336888-cell`. The
  `gh` switch was re-run before every call. All three containers are healthy,
  `./ci.sh` is **green, 1292 tests, 120 modules**, `/api/health/ready` returns
  **200**, and `./scripts/demo.sh` **exits 0**.
- **`gh` flips to the work account unpredictably** (S16, S18, #27). Re-check
  before EVERY call: `gh auth switch --hostname github.com --user bh3082336888-cell`.
- **`gh pr merge` works.** `gh pr edit` still fails with a Projects-classic
  GraphQL deprecation — use `gh api -X PATCH repos/.../pulls/N`.
- **`gh pr merge --squash` printed NOTHING on success at S24, S25, #27, #28
  AND #29** — do not read silence as failure; verify with
  `gh pr view <n> --json state,mergeCommit`.
- **`./ci.sh | tail` HIDES THE EXIT CODE.** Redirect to a file and read `$?`.
- **Run the suite the way `ci.sh` does** — `.venv`, where the package is installed
  editable.
- **Run the FULL gate before calling a change done.** S27's `e96e27c` and S28's
  D-050 comment both passed every file they touched and broke one they did not.
- **This repo HAS GitHub Actions** (S20, D-028) — `.github/workflows/ci.yml` runs
  `./ci.sh` on push and PR. PR #29 ran it; SUCCESS.
- **Local `main` ref goes stale every promote.** `git fetch origin` and read
  `git diff origin/main..staging --stat`, never the commit list.
- **The app container runs the BUILT IMAGE, not the working tree** —
  `docker compose up -d --build app`. In-container probes: `docker compose cp`
  the script in, then `docker compose exec -T app python /tmp/<script>.py`.
- **Editing code while `./ci.sh` runs puts the edit in its container build.**
  Pytest imports at collection, so the test phase is not affected, but the
  build is. Wait, or re-run.
- **qwen3:14b is SLOW to first token** — budget 1500 tokens and run it in the
  background.
- **Live probes run from `.venv`** against the app's own constructors (S27/S28
  probe dirs) or through `/api/chat` from the host (`probe_app_*.py`).
- **Enrichment skips reserved address space** (TEST-NET etc.): a probe that
  needs an indicator recorded must use a routable one (S28, D-049 run 1).
- **Independent batteries:** to judge a classifier/resolver change honestly,
  have a subagent write TWO batteries WITHOUT reading the repo. Build on one,
  and open the other once after the rule is frozen (S28: D-047, D-050).
- **Startup autoprobe (D-038/D-042):** the dev scorecard (row `a8113b41…`,
  probed 2026-10-10 09:33 UTC) expires **2026-10-17**. After that the running
  container re-probes it (~15 calls). If it logs the "endpoint changed"
  WARNING, re-measure D-040's thinking floor first.
- **Do NOT run pytest during live `/api/chat` probes.** The suite purges the
  shared `analyst@auspex.dev` user.
- **All dev-login users share the `default` workspace**, hourly ceiling 100
  inference calls. See standing follow-up 8.
- **Probe residue is expensive.** Probes that file proposals must reject them,
  and probes that create observables delete only what they created (S28
  probes do both).
- **THE DEMO IS ONE COMMAND: `./scripts/demo.sh`** (~3 min, end to end).
- **F1 session-end (2026-10-12):** staging, identity `bh3082336888-cell`.
  `./ci.sh` **green, 1315 tests, 120 modules**, `/api/health/ready` **200**,
  `./scripts/demo.sh` **exits 0**.
- **Node is part of the gate now.** `tests/test_page_logic.py` runs
  `node --test tests/js/page_logic.test.mjs`. Node missing is a failure, not
  a skip. Local Node is v24, and GitHub's ubuntu runner ships it.
- **The Playwright MCP writes to `.playwright-mcp/`** (gitignored since F1).
  It can only save screenshots under the repo. Use
  `browser_run_code_unsafe` when an action and its screenshot must be one step:
  the working line and armed doors live for seconds.
- **A page cached before B-003's fix needs one reload**; after it, every load
  asks. `FileResponse` sends a full 200 even to a matching ETag (TD-047).
- **Measuring the stream:** `docs/probes/fe-stream/probe_layers.py` runs the
  app in-process (:8011) with the endpoint stamped, so the endpoint and route
  layers are timed on one completion. `page_paint.js` is the page layer.
- **Two windows on one repo collide** (2026-10-12). Check `ps` for a second
  `claude` in this directory when something moves that you did not move.
- **B1 session-end (2026-10-12):** staging, identity `bh3082336888-cell`.
  `./ci.sh` **green, 1323 tests, 120 modules**, `/api/health/ready` **200**,
  `./scripts/demo.sh` **exits 0**.
- **A dev-switcher endpoint always takes the conversational path** (D-037: it
  carries no agent mode). To test what a customer's non-`native_tools`
  endpoint does on the dev endpoint, replay at it with the route's own
  composition: docs/probes/b1-b001/probe_replay_conversational.py.
- **The B-001 route test purges the observable 34.187.179.218** in every
  workspace, as the S5 IOC test does for its IP.

## Reference intelligence (from the SARA Open architecture study)
Base: `/home/burhan/sara-open/` — key snapshots in docs/probes/:
- ACH analogues (S12): 2026-08-08-sara-ach-analogues.md
- Phishing/header/typosquat (S11): 2026-07-18-sara-phishing-header-patterns.md
- Alert additive scorer (S10): 2026-07-18-sara-alert-triage-scorer.md
- DEFERRED rail (S9): 2026-07-18-sara-orchestrator-deferred.md
- Fast classifier / 92-8: 2026-07-16-sara-fastpath-pattern.md
- RRF retrieval + ID bypass: 2026-07-17-sara-rrf-retriever-pattern.md

## Next session should
**Pick a track (D-051); the Tracks table at the top has the ids.** Paste the
prompt file of the track you mean. `/session-start` with no track asks.
One window at a time (D-051).
- **F2, front end, the focus** (`NEXT-SESSION-FE.md`):
  - promote first;
  - then Burhan uses F1's page by hand, and his list outranks the rest;
  - then the goal, a chat that survives a reload: a list of your chats, and
    opening one shows its stored turns and spend.
- **S29, backend, paused** (`NEXT-SESSION-BE.md`): the review of S28's code,
  TD-036 and TD-044, as written at S28's close. B-002 is now TD-044's live
  evidence.
- **B2, bugs** (`NEXT-SESSION-BUGS.md`): promote first, then ask Burhan which
  open bug. The default is B-002, the top open entry, a rail false positive
  on the definition contract; B-004, B-005 and B-006 follow.
