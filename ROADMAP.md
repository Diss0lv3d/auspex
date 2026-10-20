# Auspex Roadmap — sessions & deliverables

One session = one focused working window. A session is DONE only when the
CLAUDE.md session-end ritual is complete. Order may flex; scope of a session
may not grow mid-session (IDEAS.md exists for that).

Since D-051 (2026-10-12) sessions run in three tracks. The phases below are the
backend track (S<n>). The front-end track (F<n>) and the bugs track (B<n>, from
BUGS.md) have their own sections at the end, before "Later".

## Phase 0 — Foundations & de-risk

- [x] **S1 — Scaffold.** FastAPI app factory, config module (env-driven,
  `.env.example` + `docs/ENV_VARS.md`), docker-compose (app + Postgres),
  Postgres schema v0 (workspaces, users, api_keys, chat_sessions, messages —
  `workspace_id` on EVERY table from day one), Google OAuth + JWT + hashed API
  keys, pytest + ruff CI script, health endpoints. `docker compose up` serves
  `/api/health`.
- [x] **S2 — LLM provider layer + capability probe.** ⚠ De-risks the #1 blocker.
  _Done 2026-07-15 against interim local endpoint (D-012): 98.7 % valid calls,
  52.5 % loop completion, mode → prompted_tools. Scout numbers still owed when
  the Northflank endpoint returns (one command: `scripts/llm_harness.py`)._
  OpenAI-compat client (base_url + model + api_key, streaming, streaming
  tool-call deltas). Probe battery: native tools? parallel calls? JSON mode?
  schema adherence? usable context? tok/s? Persisted capability scorecard per
  endpoint. Harness: 30–50 scripted multi-step tool tasks against the Northflank
  endpoint; measure valid-call rate + loop completion. Save results to
  docs/probes/. **Go/no-go data decides how hard we lean on ReACT vs plan-only.**
- [x] **S3 — Agent loop v1 + chat SSE.** ReACT loop (native tools primary,
  prompted `<tool_call>` fallback chosen by scorecard), tool registry with
  read/write/destructive levels, permission gate skeleton, SSE chat endpoint
  (single-key JSON event protocol), minimal functional UI shell.
  _(Done 2026-07-16: `auspex/agent/{registry,permissions,loop}.py`,
  `auspex/routes/{chat,ui}.py`; D-014 gate + proposals; 79 tests;
  live-verified vs qwen3:14b. Step 0 networking fully closed — containerized
  app streams real /api/chat over host.docker.internal.)_

## Phase 1 — Intelligence core

- [x] **S4 — Fast classifier (92/8 split).** IOC regex patterns (defang-aware),
  query classifier, shortcut handlers (greeting/identity/ioc_check/cve_lookup/
  definition), deep path stub. No LLM on the shortcut path.
  _(Done 2026-07-16: `auspex/classify/{observables,classifier,shortcuts}.py`;
  stretch step 4 shipped too — /api/chat classifies before the model, done
  frame carries `path: shortcut|model`; 8-angle adversarial review applied;
  177 tests; shortcut path verified LLM-free + network-free in-container.)_
- [x] **S5 — Enrichment fan-out + verdict store.** Direct provider clients
  (AbuseIPDB, OTX, GreyNoise community, URLhaus, ThreatFox, Shodan InternetDB,
  CIRCL hashlookup), submit-all/poll-all parallelism, per-provider circuit
  breaker, `verdicts` table **with decay curve fields from day one**
  (first Living Verdicts brick), observables table keyed by normalized IOC.
- [x] **S6 — KB/RAG on OpenSearch.** `auspex-knowledge` index design (mapping
  probe first), chunking, embeddings (probe own-container ML-plugin server-side; fallback
  in-process MiniLM), BM25 + kNN + client-side RRF, CVE/MITRE ID-query neural
  bypass, regime-aware score floors.
  _(Shipped 2026-07-17: server-side embeddings ratified D-018 — ONNX pinned,
  TORCH_SCRIPT broken on 2.19.4; idempotent bootstrap incl. 14-chunk seed
  corpus (5 live-fetched NVD CVEs + ATT&CK/concept seed summaries);
  cve_lookup + definition shortcuts consult the KB with zero LLM; live verify
  caught 2 fabrication bugs — absolute neural floor 0.6 + neural-as-relevance-
  gate now regression-pinned; 320 tests, CI green.)_
- [x] **S7 — Ingestion 1.** NVD delta + CISA KEV + FIRST EPSS merged into one
  enriched doc per CVE; `ingest_state` table + startup catch-up scheduler.
  _(Done 2026-07-17: `auspex/ingest/` package, probe-pinned feed clients,
  watermarks advance per-window after ingest, KB bootstrap moved into the
  scheduler task (TD-008 resolved), DocChange→NullSink hook for S14. Also:
  S6 review verified inline (10 fixes) + promote #7. Live: simulated 2-day
  gap → 1 844 chunks; fresh CVE answers with KEV+EPSS, zero LLM. The TD-005
  spot-check caught HNSW-recall + floor-erosion at ~2.5k chunks — fixed via
  doc_types-filtered retrieval; full calibration is an S8 gate. 357 tests.)_
- [x] **S8 — Ingestion 2 (core).** MITRE ATT&CK (lazy + cached), Sigma rules, abuse.ch
  quartet; auto-promotion to KB on miss.
  _(Done 2026-07-18: S7 adversarial review — 18 verified findings across 5
  lenses, 13 fix commits (KEV cursor data loss, bootstrap-brick, page
  streaming, NaN wedge, rejected-CVE deletion, orphan pruning, boundary-
  honest EPSS copy, lookup-truncation false miss, UBQ first-run refresh) —
  then promote #8. ATT&CK STIX feed: index-as-cursor, 712 live docs
  (697 techniques + 15 tactics) replace the hand seeds; T1059 + never-seeded
  sub-techniques + tactic definitions answer live with STIX provenance.
  TD-005 RESOLVED: 14-query labeled battery on the 3,417-chunk corpus
  re-caught fabrication live (quantum→T1090.002 at 0.617 after ATT&CK grew
  the pool) → per-doc_type floors (curated 0.65 / cve 0.70) regression-
  pinned. 412 tests. Sigma + abuse.ch + auto-promotion-on-miss → IDEAS,
  not reached — fold into a later ingestion slot.)_
- [x] **S9 — Response modes.** 6 modes only (definition, ioc_enrichment,
  threat_intel, alert_triage, phishing_analysis, brief), code-owned priority
  resolver (format beats keywords), typed output contracts that compile to
  prompts + validators. _(Reviewed (S10 Step 0: 4 fix commits — resolver
  common-domain exemption, validator header/enum/empty robustness, drift log,
  honest docs) → **promote #11**. Live-verified against Scout.)_

## Phase 2 — Analysis

- [x] **S10 — Alert normalizer + risk score.** Multi-SIEM format detection
  (CEF/LEEF/syslog/JSON) → typed closed-vocab envelope; additive 0–100 score
  with itemized, named contributions; **DEFERRED rail** (no data ≠ low risk,
  both SARA conditions). Code-owned parse+score (no LLM); feeds the S9
  alert_triage mode with the AUTHORITATIVE verdict. _(Reviewed at S11 Step 0
  — 8 findings fixed with regressions — and promoted #12 to main.)_
- [x] **S11 — Phishing/header agent.** Deterministic SPF/DKIM/DMARC/typosquat/
  homograph checks injected as AUTHORITATIVE; LLM narrative on top; victim-domain
  IOC filtering. _(`auspex.phishing`: regex header parse → typed EmailEnvelope →
  named auth/spoof/lookalike findings → additive Verdict FLOOR; BENIGN gated on
  positive auth evidence, absence/unparseable → DEFERRED; victim-domain + internal
  IPs withheld from indicators; validator pin extended to an ALLOWED SET so the
  model may raise above the floor, never launder below it. Format-beats-keywords
  email→DEEP gate added to the classifier. Live-verified on Scout (MALICIOUS floor
  + BENIGN gate). MITIGATES the phishing portion of TD-013. Reviewed at S12
  Step 0 — 9 findings (A–I) verified by execution and fixed with regressions,
  incl. body-prose BENIGN manufacture, BEC sender victim-filtering, ccTLD brand
  false positives, ARC relay passes — and promoted #13 to main.)_
- [x] **S12 — Hypothesis engine v1 (ACH).** Competing hypotheses per
  investigation, per-evidence scoring against each hypothesis, next-lookup
  chosen by expected information gain. _(`auspex/ach` + `/api/investigations`,
  D-019: closed 4-hypothesis catalog per subject kind; evidence adapters over
  the S5/S10/S11 typed shapes with curated cell-vector doctrine tables; Heuer
  least-inconsistency matrix with hard-contradiction rejection + honesty
  rails; expected-information-gain lookup ranking with curated P(outcome|H)
  rows, executed live through the S5 fan-out. Zero LLM end-to-end — model
  rendering deferred to S13 by design. Hardened by a same-session 4-lens
  verification workflow: 16 findings, all verified by execution, all fixed.
  Live-verified in-container; the live gain figure matched the hand-computed
  fixture to 6 decimals. On staging, awaiting S13 Step-0 review + promote #14.)_
- [x] **S13 — Evidence graph + cited output.** Typed evidence objects; every
  generated claim carries a citation; output guard rejects uncited claims.
  _(Step 0 first: fresh-eyes review of the S12 diff — 7 findings, every one
  verified by execution, all fixed with regressions; promote #14 PR opened
  (merge pending, human-gated). Then: ach_evidence row uuids became the
  stable citation identity (E-<hex8> labels, collision-extending);
  `POST /api/investigations/{id}/summary` renders the first LLM output on
  the surface through an investigation_summary contract — code compiles the
  authoritative directive (matrix, per-hypothesis bearing evidence,
  flattened statements, top lookup), the leading hypothesis is PINNED, and
  the post-hoc citation guard names fabricated ids and uncited claim lines
  (TD-012: detected, not prevented). Live-verified against Scout twice: run
  1 caught a guard bug (grouped [E-a, E-b] citations refused) and a
  directive gap (rejected rows had nothing to cite) — both fixed with
  regressions; run 2 clean: 19 valid citations, 0 fabricated, 0 uncited.
  KB-doc citability deliberately NOT picked up — the parked ioc_check→KB
  idea stays parked. 597 tests green.)_

## Phase 3 — Living Verdicts (flagship)

- [x] **S14 — Retro-hunt.** On-ingest sweep of historical observables (indexed
  join, never scan), re-open notifications, verdict flip events.
  _(Done 2026-08-09: Step 0 — independent adversarial review of the S13 cited-
  summary commits, 4 findings all verified by execution before fixing (citation-
  shaped tokens in attacker text poisoning the guard; the uncited check tuned to
  one model's markdown, failing 3 of 4 faithful renderings; the pin broken by
  bold on hyphenated tokens; a 200-row directive costing ~13.5k prompt tokens),
  1 named angle confirmed sound. Then S14: the S7 NullSink seam got its consumer
  — `auspex/retrohunt/` sweeps CVE observables for kev-added/deleted changes
  through ONE indexed join per 50-id chunk, chunk size chosen from a MEASURED
  plan crossover (EXPLAIN caught the first spelling as
  `Seq Scan … Rows Removed by Filter: 19760`); re-open events are typed rows
  that never touch a verdict (D-020 rail, held in code); verdict label changes
  become provenanced `verdict_flips` rows naming the doc that prompted the
  re-look. 3 zero-LLM routes with explicit analyst ack. Live-verified
  in-container against a genuinely KEV-listed CVE, which also exposed two
  long-standing packaging defects — `auspex.modes`/`auspex.retrohunt` absent from
  the installed distribution and EVERY `__init__.py` installed at 0 bytes since
  the Dockerfile was written, both masked by uvicorn's cwd shadowing
  site-packages. 643 tests; zero new env vars.)_
- [x] **S15 — Falsification watchers.** Verdicts register "what would flip me";
  watchers monitor feeds/enrichment for exactly that.
  _(D-021. Every verdict registers typed falsification conditions AT WRITE TIME
  in the same transaction — a closed enum of three kinds, derived in code from
  the observable/label/signals, never prose and never model-proposed. Each kind
  is owned by a checker and the partition is asserted, so a watcher nobody
  evaluates cannot be added. Ingest checks them through an indexed join per
  bounded chunk on a PARTIAL index (closed watchers accumulate forever and are
  never joined against — measured flat at 75k rows, 50k closed); enrichment
  checks escalation by SEVERITY, not inequality. A satisfied watcher never
  writes a verdict: it upgrades the S14 re-open event with the claim that
  stopped being true. Live-verified in-container end to end. Also fixed a
  circular import that resolved only by lucky import order. 676 tests; zero new
  env vars.)_
- [x] **S16 — Verdict timeline UI.** Decay/staleness surfaces, flip history,
  "your past got re-scored" view.
  _(Step 0 first: fresh-eyes review of the S15 commits — 4 angles, 1 defect,
  1 confirmed gap, 2 sound. The analyst-facing `falsifies` link survived only by
  the order `FanoutSink` happened to be built in, and its loss was silent AND
  permanent; executing the lead also found that a retro-hunt failure loses it
  with the order intact, which ruled out "enforce the order" and made the link
  derived at read time. Then S16: `auspex/timeline/` + `auspex/checks.py` +
  `/api/timeline/{obs_id}` + `/api/timeline/digest` + a `/timeline` page.
  `effective_confidence` renders for the first time since S5; staleness is a
  band vocabulary in half-lives (D-022); TD-020's open question answered with a
  derived `standing` that never touches `status`; and a quiet digest now has to
  be earned — a checker that has failed every cycle no longer looks like one
  with nothing to do. 720 tests; zero new env vars; zero LLM.)_

## Phase 4 — Platform

- [x] **S17 — Actions SDK contract.** `@action` decorator (semantics/scope/risk),
  **undo required for destructive**, dry_run required, registration API,
  planner manifest integration. _Ratified D-023. Destructive-without-undo is
  unrepresentable (the spec cannot be constructed, and the registry re-checks);
  `dry_run` required of everything with no defaulting; an undo declares what it
  CANNOT restore; risk IS `ToolLevel` so the D-014 gate stays the only opinion
  about approval; the manifest reuses the S13 capability decision. The loop is
  told about actions and given no way to call one — dispatch is S18's proposal
  round-trip. Also this session: Step-0 review of S16 fixed 3 defects, incl.
  the digest's decay read at 143 ms → 4.6 ms (TD-021 closed on that item)._
- [x] **S18 — Approval flow.** Approval cards over SSE, atomic claim-first
  settlement, permission re-check at execute time. _Ratified D-024. Settlement is
  one `UPDATE ... WHERE status='pending_approval' RETURNING`, verified by racing
  eight distinct Postgres backends at a barrier; the card is compiled from the
  spec (never model prose) and FROZEN on the row, because re-rendering it would
  show today's declaration for yesterday's decision; execute re-checks both the
  D-014 gate and a spec fingerprint, so an approval does not survive a change to
  what was approved (TD-023's two hardest items closed). The executor allow-lists
  systems we own, so a third-party action can be proposed and approved and still
  refuses to run. Calling an action now files a proposal — D-023's deferred
  round-trip, resolved. Also this session: Step-0 review of S17 fixed 3 contract
  defects (the unguarded undo slot, unvalidated parameter names, action/tool name
  shadowing) and bounded the S17 decay-read crossover (TD-024)._
- [x] **S19 — Hardening.** Input guard (injection patterns + security-content
  carve-outs), rate limits, usage-based plan gating skeleton. **Done (D-025,
  D-026):** the guard asks whether an instruction is being ISSUED or ANALYSED —
  carve-outs reuse the classifier's own format detectors and are justified
  against the real S11 `.eml` corpus, so a pasted phishing body containing
  "ignore all previous instructions" is still analysed while the same sentence
  issued bare is refused in code (400) before the model, the KB or the
  transcript. **TD-018 closed:** per-workspace inference-call ceilings claimed by
  a conditional UPSERT (raced, 8-way), a two-pass turn charged 2, a 429 naming
  meter/ceiling/reset, LLM-free paths unaffected. Plan gating skeleton = plan on
  the workspace + limits in code + `/api/usage`; no billing (deferred).
  Step 0 also re-ran the TD-005 battery (>30k trigger, first fire) and reviewed
  the S18 commits — TD-026/027/028 opened.
- [x] **S20 — Beta.** Deploy pipeline, docs pass, demo script. CI runs `./ci.sh`
  itself (D-028) and caught two defects green-on-laptop/red-on-runner on its first
  run — IPv6 observable identity delegated to a stdlib formatting choice, and three
  tests depending on accumulated dev-DB state. README written (the repo had none),
  with an honest "what Auspex does not do yet". `scripts/demo.sh` consolidates the
  demo turns from nine STATE.md revisions into one runnable script that ends on
  real refusals. Step 0 promoted S19 (PR #19) and reviewed it: the guard was
  refusing 4 of 6 legitimate SOC questions (D-027).
- [x] **S21 — beta debt paid down.** _Not a planned entry: the roadmap ended at S20,
  so this session was scoped by a decision and is recorded here after the fact._
  **TD-026 CLOSED** — the definition path renders the page the question is about,
  3/7 → **7/7** positives and 4/4 honest misses, live-verified. Two mechanisms:
  `rrf_fuse_docs` gives a page one rank per leg instead of one per chunk, and
  `auspex/kb/canonical.py` adds the signal neither leg had — whether title and
  question are *about each other*, as a harmonic mean of both directions, because
  each direction alone was observed picking a wrong page. **TD-028a CLOSED** — a
  claim orphaned by a dead process is now visible in the queue with its age, and
  `POST /api/proposals/{id}/abandon` is the door out, guarded on claim age in the
  same UPDATE. **Deliberately no reaper**, reversing the S19 note: a timer cannot
  know whether the handler ran, so every status it could pick asserts something
  nobody knows (D-014 reserves that call for the human). Step 0 reviewed S20 and
  found the sharpest defect of the session: **S20 fixed one invisible-character hole
  by opening its inverse** — folding deletes invisibles and deletion welds words, so
  `previous<ZWSP>instructions` returned CLEAN (18 escapes measured); matching now
  unions the folded and raw passes. Also fixed: reported speech was read over the
  whole preamble so an attribution two sentences back licensed a bare imperative
  (6/6), an inch mark opened a covering quote span, and a docs test passed with its
  entire input removed. Two bounds ratified rather than chased (**D-029**,
  TD-031/032) — the real answer to both is TD-012. 964 tests; 117 modules; zero new
  env vars.
- [x] **S22 — the output side.** _Also unplanned: scoped by a decision, recorded
  after the fact._ **TD-012(a) SHIPPED (D-030)** — `auspex/outguard.py`, the rail
  the repo had pointed at four times (D-027, TD-031, TD-032, TD-033 each ended
  "the real answer is TD-012") and never built. It does not ask whether an answer
  was *influenced* — undecidable from text, and a model grading itself is what
  D-006 refuses — but whether **the platform's own configuration is coming back
  out**, which is decidable because we hold both halves. Verbatim-run detection
  over only the configuration we issued (never the analyst's paste, never the
  pinned verdict blocks, never the two-pass analysis). `SHINGLE_WORDS = 8`
  **calibrated on 34 live Scout answers** like NEURAL_FLOORS: legitimate ceiling
  6, the one extraction attempt that complied reproduced 60 — and the model
  refused 3 of 5, which is exactly why a rail is needed rather than trust. A leak
  is cut off mid-stream and **not persisted** (a stored turn replays forever,
  TD-009). Live-verified through the rebuilt container. Step 0 reviewed S21 and
  found **the S21 sentence-scoping fix closed only one of three spellings**: a
  newline and an end-of-input full stop both left the defect open, 6/6 each, and
  deleting one space undid it — four designs measured against the real 129-test
  corpus, not a hand-written one. Also fixed: **a late handler overwrote the human
  who abandoned it** (`abandoned` → `executed`, with `decided_by` still naming the
  abandoning human), raced with a real handler rather than simulated. TD-033
  ratified. 1014 tests; 118 modules; zero new env vars — nine sessions running.

- [x] **S23 — the S22 review, and the ground under the agent path.** _Step 0 was
  the session's substance; the chosen goal (wire AgentLoop into `/api/chat`)
  landed its groundwork, not its implementation._ Promote #23 merged the whole
  S22 slate. The fresh-eyes review found **two real defects in the day-old output
  rail**, both confirmed by execution before anything was changed: **a leak in
  pass 1 did not stop the turn** — `break` left only its own loop, and a tripped
  scanner returns `None` by design, so pass 2 made a second inference call and
  streamed a whole answer **completely unscanned** (S22's two leak tests both used
  `native_reasoning=True`, so the two-pass path — the one a customer endpoint
  actually takes — had no leak coverage at all); and **the scanner's carry crossed
  the reasoning/answer boundary**, tripping on a run that existed in neither, which
  is a false positive on the deep path's most ordinary shape. Both fixed with
  regressions **proven to fail pre-fix**. **TD-034** ratified: the late-write is one
  column short of its own intent but unreachable, and the reachability is now
  pinned by a test rather than by luck. 34 assertions pinned sound — including the
  question the brief asked, that an answer reproducing a whole deterministic verdict
  block stays CLEAN. Then **D-031**: the agent path's streaming shape **measured on
  real Scout** before a line of wiring — tool calls arrive with **zero content
  before them** (so the answer can stream honestly), arguments come **fragmented
  across nine deltas** split mid-token (so they must be accumulated), and
  `finish_reason` is the step signal. Three hard constraints recorded with it: the
  app populates **no ToolRegistry at all** (zero read tools today), the usage claim
  must move inside the loop or TD-018 breaks, and the rail's index must follow the
  composed system message. 1021 tests; 118 modules; zero new env vars — ten
  sessions running.
- [x] **S24 — the S23 review, and the agent finally has something to do.** _Step 0
  again the session's substance; the goal's first half landed in full and its
  second half was deliberately not started._ Promote #24 merged the S23 slate (the
  commit list showed **281 commits**; the real change was 16 files — read the
  diff). The fresh-eyes review found **three defects in day-old code**, each
  confirmed by execution first. **S23's fix was itself defective**: dropping the
  scanner's carry on a change of channel stopped a false positive, and a drop
  loses things — the carry was one shared slot, so any delta of the other kind
  evicted it, and a leak split across two chunks of the **same** pane, separated by
  one interleaved delta, walked through the rail in **both** directions. Fixed with
  a carry **per channel**, so the boundary guarantee and the chunking guarantee
  hold at once instead of being traded, and shipped with the over-correction
  control that proves it. **The TD-034 pin guarded the wrong statement** — it
  asserts the racy pre-check while its docstring credits the atomic claim, and
  loosening that claim left **all 34 settlement tests green**; the new pin drives a
  stale read and fails with `DID NOT RAISE` when the claim goes. **The usage refund
  was opt-in and did not hold** — measured, the 30 tests that never asked for it
  left **29 unrefunded units** against a ceiling of 100, and the file looked clean
  only because the fixture DELETEs the row and the 3 that use it run last; now
  `autouse`, residue 29 → 0. **TD-035** accepted: a pass-1 leak is charged for the
  call it prevented — it over-charges, TD-030 already covers it, and it dissolves
  when the claim moves inside the loop rather than being patched first. Then the
  goal: **enrichment, CVE lookup and KB retrieval are agent READ tools** (D-014),
  wrapping the same services and the same fetch sizing rather than re-implementing
  them, returning **data rather than the renderers' prose**, keeping the DEFERRED
  rail's three truths distinct, and reusing the existing caps instead of declaring
  new ones. **Live-verified against the real services**, not just fakes — real NVD
  Log4Shell record with fabricated ids in `not_found` in the same call, real ATT&CK
  TA0008, live enrichment with 5 sources answered, and a private address returning
  `not_checked` with its reason. **The "agent has no tools" blocker, open since
  S23, is closed.** Wiring the loop into `/api/chat` was **not started** — Step 0
  ate the session and a half-wired route is worse than none. 1052 tests; 119
  modules; zero new env vars — eleven sessions running.
- [x] **S25 — the review found two more, and the loop learned to stream.** Promote
  #25 merged the S24 slate (17 files, +1921/-300; the commit list again showed
  ~280 — read the diff). The fresh-eyes review found **two defects in the
  day-old capability tools**, both in the same boundary: model-controlled tool
  arguments. **`_resolve` kept only the first observable per argument item**, so
  an analyst's "check these three" came back answered about ONE, with `unresolved`
  empty and nothing saying so — *not-checked* rendering as *no-signals*, which is
  the collapse that module's own docstring exists to prevent, and its own promise
  ("never dropped") inverted. Measured **latent** on Scout (which sends separate
  array items) but reachable by construction through the bare-string shape
  `_as_list` exists to accept. **A bare number raised `TypeError`**, which the loop
  degraded to an unactionable "tool raised TypeError". Both fixed with arithmetic
  controls and proven to fail pre-fix. **Four suspicions were checked and CLEARED**
  and recorded as such — autouse is sound (no test in the file asserts a limit;
  pytest runs serially), the stale-read pin cannot leak, provider failures are
  fixed literals so no configuration reaches a tool result, and the "unbounded
  model string" lead dissolves against `max_tokens=2000` plus term-not-query-string
  clauses. **D-032 ratified**: `main`'s protection is procedural — it *cannot* be
  enabled (private repo, free plan) and the item leaves in-flight follow-ups
  permanently. Then goal item 2, which nothing had ever measured: **the tool
  descriptions work as PROMPTS** — live, 8 of 8, right tool and right arguments,
  and the control earned its keep by revealing that **Scout REFUSES a question no
  tool answers** rather than replying in prose. Finally the goal's mechanism half:
  **`AgentLoop.run_stream`** implements all five D-031 decisions — tool steps
  narrated before the answer streams, arguments folded through the same code
  `accumulate_stream` uses, the usage claim **per model call** including the
  synthesis pass, and `system_message()` made public so the rail indexes the
  composed message. Proven by three neutralisations, each hitting exactly its own
  tests. **Live-verified end to end** against Scout and the real services: 1 tool
  step, 79 content deltas, 2 claims for 2 calls, ordering held. **The route was
  deliberately NOT touched** — Burhan's call, so `/api/chat` is unchanged and main
  stays deployable. TD-036 logged. 1073 tests; 119 modules; zero new env vars —
  twelve sessions running.

- [x] **S26 — a new engine, the agent path wired, and what a decision's end
  states mean.**
  - **Detour.** Resumed after eight weeks to find the dev LLM gone (Scout's host
    NXDOMAIN). The day went to replacing it:
    - **D-033:** the base URL is the provider's documented root.
    - **D-034:** glm-4.5-air on Z.ai's general pay-as-you-go API.
    - **D-035:** the default endpoint's scorecard is the deployment's.
    - **D-036:** a two-pass turn whose endpoint thinks becomes a native turn.
    - Promote #27 shipped all four.
  - **Goal item 1, re-measured on the new model:** 0 refusals in 25 tools-on
    runs. The proposed "only with an observable" clause protected nothing and
    held back the KB from the questions it helps most (the agent labelled
    ATT&CK IDs right 3/3; the conversational path mislabelled one in 2 of 3).
    **D-037:** any deep turn the code has not already decided takes the agent
    path, on an endpoint measured to call tools natively and stream them.
  - **Goal item 2: `/api/chat` runs the agent loop.**
    - Per-call usage claims, live: units == calls.
    - The rail indexes the composed message.
    - Tool steps stream as server-rendered lines, scanned on one literal channel.
    - The narration that precedes a tool call is held and shown as process
      (TD-036).
    - The README honesty section is pinned to the code.
    - Two adversarial reviews: 8 defects fixed, including unbounded third-party
      enrichment per turn.
  - **Burhan delegated TD-037–040; all four resolved.**
    - **D-038:** the deployment probes its own endpoint once per fingerprint
      (LLM_AUTOPROBE_ENABLED).
    - **D-039:** the agent sends third parties only indicators someone other
      than the model supplied.
    - Brand-safe endpoint errors (TD-040).
    - Tool descriptions indexed after calibration (TD-038).
    - The calibration found a live rail defect: a thinking model quotes its
      instructions while reasoning (19–28 words), and the floor of 8 cut those
      legitimate turns. **D-040** gives thinking its own floor of 40.
  - **Goal item 4 → D-041, what a proposal's terminal states say.** `failed` is
    checked (`observe`), anything uncertain is `incomplete`, and a human can put
    it back or keep it; identical requests are named, never merged; claims are
    tokens. A review found 8 more defects, all fixed, including one HIGH: a
    second migration block that stopped the app booting with one `incomplete`
    row.
  - Every change was verified live through the running app. Goal item 5
    (TD-012b) was not started.
  - 1217 tests; 120 modules; two new env vars (GLM_API_KEY, LLM_AUTOPROBE_ENABLED).
- [x] **S27 — the goal measured before it was built, and everything parked
  done.** Burhan's call at the start ritual: "dont park anything, do everything"
  — all three candidates joined the goal.
  - **Step 0.** Promote #28 shipped the S26 slate (D-037…D-041). A fresh-eyes
    review of the D-041 review's own seven fixes found three more defects, all
    fixed with tests that failed first:
    - the queue said "no twins" where nobody had looked;
    - keep and abandon erased who approved a run;
    - a lost undo claim said "already being undone" about a row nobody was
      undoing.

    It cleared four commits, stated one bound (twin index vs numeric scale), and
    logged TD-042.
  - **Goal, TD-012(b) → D-043, measured first.**
    - Drift was 0/60 on security questions across both deep paths, and
      laundering 0/6 on glm-4.5-air.
    - So the repair guards the one field that matters: an alert or phishing
      verdict is held until it passes, re-asked once, then rendered by code.
      The analyst is never shown a verdict off the code's.
    - Narrative modes keep streaming. The JSON pass was declined on
      measurement.
    - Live through the container.
  - **TD-041 → D-042.** A deployment scorecard expires after a week, and the
    running app re-measures. A changed endpoint is logged field by field.
  - **Mode fallback → D-044.** A seventh mode, `general`, for deep questions
    with no security signal.
    - Judged on batteries written by independent agents: approach 1 failed
      (15/40 misroutes); approach 2 holds at 9/50 misroutes and 24/30 to
      general.
    - Live, a misroute costs structure, not substance.
  - **Actions on the chat agent path → D-045.** The agent may propose. A call
    files a pending proposal shown in the turn, and a no-op dry run is not
    filed. Live: one ask filed one sensible proposal, and no ask filed none.
    Wiring it found a latent bug: a real proposal id (a UUID) killed the turn.
  - Logged: TD-042 (an approved run that never started has no door), TD-043 (a
    thinly covered topic spends the agent's whole step cap: 9 calls a turn).
  - 1257 tests; 120 modules; no new env vars.
- [x] **S28 — the S27 slate promoted, its code read by someone else, both goals
  measured first, and every candidate done.** Burhan's call at the start
  ritual: all three candidates joined the goal.
  - **Step 0.** Promote #29 shipped the S27 slate (D-042…D-045). An
    adversarial second-pass review of S27's code found three things:
    - an undo said "moved from incomplete to incomplete";
    - a real action call was logged as `<unregistered>`;
    - live, the engine called itself another vendor's product when asked who
      made it.

    The first two are fixed. The third became D-047 on Burhan's call, with
    D-002 kept: "powered by <model>" was asked for, put back as overturn or
    drop, and dropped.
  - **TD-043 → D-046, measured first.** 0 of 31 re-searches were misses. A
    per-tool budget (`search_knowledge`: 3) cut S27's six turns from 37 calls
    to 23, with no step-cap hits and 6/6 conformant. The grounding cost is
    stated, and two attempts to win it back were measured and not shipped.
  - **TD-042 → D-048 (Burhan: both doors).** An approval no run ever started
    rejoins the queue once stale. It can be run now (re-checked like approve)
    or withdrawn to the new status `withdrawn`. Live through the container.
  - **D-047, identity:** identity questions caught on a held-out battery went
    0/45 → 18/45, with 0 false positives.
  - **Candidates.**
    - **D-049:** what the agent looks up is recorded like the IOC check. Live,
      one turn checked a never-seen IP and filed its note proposal.
    - **D-050:** a note request never takes the IOC shortcut, and a note-only
      one gets an eighth mode, `action_request`. Held out: 0/30 → 19/30, no
      false positives. Live: `contract_valid: true`.
    - **Alert keys:** measured against the published ECS and Graph schemas. An
      ECS alert was named after its host; fixed. The S27 MEDIUM was the
      scorer, not the keys (IDEAS).
  - Triggers fired, not fixed: TD-036 (the answer shown twice, live) and
    TD-044 (the index grew again).
  - 1292 tests; 120 modules; no new env vars.

- [x] **S29 — S28's code reviewed by others, and the integration phase
  designed.** (2026-10-14/15) F3's PR #34 merged and Promote #35 at Step 0.
  - **The review** (docs/probes/2026-10-14-s29-s28-code-review.md): 21
    findings, every one reproduced by execution first. Fixed: two message-driven
    event-loop stalls (D-047's and D-050's regexes), a context-only lookup
    overwriting a stored verdict (against D-055), a cut KB snippet supplying a
    wrong indicator, D-046's bound (then twice more after the fixes' own
    review), and a dropped alert name. Logged: B-010…B-020, TD-056…TD-058.
  - **The spec and D-060…D-067, each Burhan's call**
    (docs/superpowers/specs/2026-10-15-integration-phase-design.md): the words
    (connector, integration, case, Edge Agent); MSSP tenancy with a provider
    workspace, provider-wide grants, `restricted` clients, three roles and a
    region guard over the engine and enrichment; outbound-only Edge Agents
    running hash-pinned packages; edge secrets as names; one canonical
    manifest from Python or YAML; our own SKIP LOCKED queue; TD-023/TD-025 out
    of Deferred; live QRadar on a synthetic-only lab domain.
  - QRadar holds real data (hence D-067); its address comes later.
  - S30–S41 and F4–F9 re-checked against the spec; the order unchanged.
  - 1412 tests; 121 modules; no new env vars; no engine calls.

- [x] **S30 — MSSP tenancy: organizations, provider workspaces, memberships,
  roles, one workspace per token, and the region guard.** (2026-10-15) A
  promote milestone: the slate carries S29 and S30.
  - **Design:** Burhan's five calls (docs/superpowers/specs/2026-10-15-s30-tenancy-design.md,
    D-068): only a CLI creates organizations; dev login auto-provisions;
    one organization per migrated workspace; admins read their audit; `global`
    serves global. Baseline: docs/probes/2026-10-15-s30-tenancy-baseline.md.
  - **Built** (plan docs/superpowers/plans/2026-10-15-s30-tenancy.md, nine
    tasks, subagent-driven, each task reviewed): `auspex/tenancy/` (region,
    access, audit, admin, entry, the CLI); identity left the workspace
    (migration, one person per email); `enterable_workspaces` re-checked on
    every request; `POST /api/auth/switch` and `GET /api/auth/me`; roles
    enforced on every write; the membership API and `GET /api/audit`; the
    region guard over the engine and enrichment (`ENGINE_REGION`); structural
    and cross-tenant suites; mutants 10/10.
  - **Final adversarial review** (no isolation or residency break found):
    concurrent admin removals left zero admins (fixed: the workspace lock and
    in-transaction re-check); a mis-homed person had no recovery (fixed:
    `rehome-person`; TD-059 gates Google); the ksa agent path was unpinned
    (pinned); a malformed token claim was a 500 (fixed). Their fixes reviewed
    in turn: B-021 open (Burhan: next backend session).
  - **D-069:** a ksa workspace will live only on a KSA-storage deployment
    (Burhan overturned D-061's bound; built later).
  - 1554 tests; 129 modules; `ENGINE_REGION` born; no engine calls.

- [x] **S31 — A jobs queue, and TD-025's first half.** (2026-10-16) Not a
  promote milestone; the slate carries S31 (Burhan's call at S32's Step 0).
  - **Step 0:** B-021 fixed (`b1fa61e`); D-069 built (`6cd68e9`:
    `STORAGE_REGION`; Burhan: an existing misplaced workspace is named at
    startup); each reviewed by a fresh agent.
  - **Design:** Burhan's five calls (docs/superpowers/specs/2026-10-16-s31-jobs-design.md):
    a 24 h TTL; expired cards listed a day; one key per operation; per-kind
    lease and attempts; the expiry sweep as a real job. Baseline:
    docs/probes/2026-10-16-s31-jobs-baseline.md.
  - **Built** (plan docs/superpowers/plans/2026-10-16-s31-jobs.md, eight tasks,
    subagent-driven, each reviewed): `auspex/jobs/` (a scoped SKIP LOCKED claim
    serving workspaces in turn, leases, backoff, dead, token-checked answers;
    the in-app worker, `JOBS_WORKER_ENABLED`); `expired` refused in `settle`'s
    own UPDATE and swept by the `proposals.expire` job; `operation_key` handed
    to every handler and used by the note action; the page's expired card.
  - **Live:** the container's worker expired an aged proposal through the real
    job; 409 in words; the page (docs/probes/2026-10-16-s31-jobs-live.md).
  - **Final adversarial review** (the core held every race and scope attack):
    a NUL in a job's error or result aborted the tick (fixed: total answer
    writes); a booting replica's migration could deadlock a claim (fixed:
    `MIGRATION_LOCK` shared). Fixes reviewed in turn.
  - B-025, B-026, TD-063…TD-065 logged.
  - 1687 tests; 133 modules; `STORAGE_REGION`, `JOBS_WORKER_ENABLED` born; no
    engine calls.

## Track: front end (D-051)

- [x] **F1 — Where a deep turn's reasoning loses its speed, measured first.**
  (2026-10-12) Promote #30 (it collided with B1's window: STATE.md). Burhan
  added all three candidates.
  - **Measured** (docs/probes/2026-10-12-f1-stream-layers.md): the server adds
    ~1 ms a delta, the page ~3 ms, and the endpoint is the rest (glm bursts
    with 1-13 s silences; qwen 139-171 chars/s).
  - **D-052:** a `status` frame before each wait, a working line, pacing
    within 200 ms, and the slow local endpoint labelled "Local (slow)".
  - **D-053:** safe markdown in answers; https links show their host.
  - **The approvals panel:** every door, two clicks for runs
    (docs/superpowers/specs/2026-10-12-approvals-panel-design.md).
  - **D-054:** every deep turn records its spend, shown per answer and per
    chat.
  - **B-003 fixed** (`no-cache` pages). B-002 and B-004 were logged.
  - 1315 tests; 120 modules; no new env vars.
- [x] **F2 — A chat survives a reload.** (2026-10-12) Promote #31 at Step 0
  after B-007 (GitHub's Node prints TAP; fixed). Burhan added all three
  candidates; promote #32 at the close.
  - **Reload** (docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md):
    two scoped routes (`/api/chat/sessions`, `…/{id}/turns`), the sign-in in
    sessionStorage (D-056), an always-on chat sidebar, the chat in the hash,
    reopened turns with spend and proposals' doors. TD-050, TD-052, B-008.
  - **S26's chat edges:** an empty answer says so; errors in the server's
    words; narration on its own line.
  - **Narrow screens:** a compact header, one backdrop for either overlay,
    a full-width panel on a phone, dark scrollbars.
  - **TD-045 closed:** markup, a stylesheet and two modules, served no-cache
    from an allow-list; **D-057:** a strict CSP on the chat page (TD-051
    narrowed). TD-053 logged.
  - 1360 tests; 121 modules; no new env vars.
- [x] **F3 — Burhan's hands-on list of F2's page, then the timeline page joins
  the chat page** (2026-10-14). Run by the collaborator Hunaiza (D-059). No
  promote: a PR from `f3-timeline-csp` into `staging` (her call).
  - **TD-051 closed** (docs/superpowers/specs/2026-10-14-timeline-page-csp-design.md):
    markup, `css/timeline.css`, a tested `js/timeline-logic.js` (14 Node
    tests) and `js/timeline.js` building feed text as text; `/timeline`
    carries D-057's policy, pinned for both pages. Live: zero CSP violations,
    markup in feed text rendered as text, a link with `'` and `"` in its id.
  - **F2's page by hand**, walked in headless Chromium without a turn; Review
    and Undo not reached (STATE.md follow-up #26).
  - 1392 tests; 121 modules; no new env vars.
- [x] **F4 — One shell for every page, role-aware, with a workspace
  switcher** (2026-10-16). No promote at Step 0 (the slate was empty); the
  slate at the close is all of F4. Burhan added all four candidates.
  - **The shell** (docs/superpowers/specs/2026-10-16-f4-shell-design.md,
    **D-070**): `css/base.css`, `js/dom.js`, `js/api.js`, `js/shell-logic.js`,
    `js/shell.js`; chat and the timeline on it (one sign-in per tab); a
    read-only **Members** page, the first admin entry; doors by role; the
    switcher reloads and leaves nothing of the last client, Back included.
  - **Candidates:** TD-047 closed (304s); "[connection lost]" a sentence;
    the reopened proposal line follows the panel (#20); F2's page with live
    turns (#26, all but the empty-answer note). F3's minors (#25) fixed.
  - **Proven:** 10/10 mutants; live with two clients and every role, zero CSP
    violations (docs/probes/2026-10-16-f4-shell-live.md); the final review's
    Critical (Back restored the last client's page) reproduced live and fixed.
  - B-022…B-024, TD-061, TD-062 logged.
  - 1603 tests; 129 modules; no new env vars.

## Track: bugs (D-051)

- [x] **B1 — B-001: the platform invented an IP's owner.** (2026-10-12)
  Promote #30 at Step 0 (it collided with F1's window: STATE.md).
  - **Reproduced** (docs/probes/2026-10-12-b1-b001-fix.md): glm-4.5-air took
    the agent path and looked the IP up, 0/3 invented; qwen3:14b took the
    conversational path with no tools (D-037), and answered Amazon 3/3.
  - **Root cause:** AbuseIPDB named Google LLC on turn 1 and a low score
    dropped it, so the IOC check said "unknown to them".
  - **D-055 (Burhan's call):** the network a source names is kept beside the
    verdict, never as one; shown in the IOC check, handed to the agent
    (`a90e18a`). Live: qwen names Google LLC 3/3.
  - The offending answer is pinned (tests/fixtures/enrich/); 3/3 mutants.
  - TD-049 (only AbuseIPDB names the network). B-005 and B-006 were logged.
  - 1323 tests; 120 modules; no new env vars.
- [x] **B2 — B-002, B-004, B-006 and B-008, in Burhan's order.** (2026-10-13)
  No promote at Step 0 (the slate held only F2's docs).
  - **B-002 → D-058** (`4b753d4`, narrowed `d8c597b` after review). A section
    list compiles to one run longer than the thinking floor, so the thinking
    index drops runs wholly inside it, and the re-ask. Both floors re-measured
    on today's index (answer 5 vs 8; thinking 20 vs 40; recitation 58).
  - **B-004** (`29209fa`): a note names its observable as written. Live 3/3.
  - **B-006** (`fce2f55`, `c80bf29`, `58b45e4`): a no-signal lookup reads
    "reputation unknown", and general carries the no-data rule. A benign
    verdict 3/3 → 0/3; the "legitimate" residual is B-009.
  - **B-008** (`4680bf6`): a turn refused at the ceiling leaves nothing behind.
  - Every fix: a test that failed first, its exact text pinned, mutants, live,
    and a fresh-agent review (2 of 4 found a real defect, both fixed).
  - TD-054, TD-055 logged; TD-044 updated; B-009 logged; D-044 addendum.
  - 1385 tests; 121 modules; no new env vars.
- [x] **B3 — B-010, then B-024** (2026-10-19). Burhan's scope, run by the
  collaborator Hunaiza (D-059). No promote; a PR from `b3-b010-b024` into
  `staging` (her call). Record: docs/probes/2026-10-19-b3-b010-b024.md.
  - **B-010 fixed** (`0207b4a`): four classify rules no longer backtrack (the
    fourth found by the review). The worst message at the cap went from 101 s
    to about 12 ms, with the same matches (0 differences on 200,501 inputs).
  - **B-024 fixed** (`2bc5eec`): choosing a workspace only selects it; a
    Switch button switches (her UX call). Live: arrows switch nothing.
  - B-027 and B-028 logged from the reviews.
  - **Burhan's review of PR #41**, answered on the branch: **B-029 fixed**
    (`8c51cb4`, the input guard's two backtracking rules; the guard took
    130.7 s, now 11–15 ms, with every verdict unchanged); the pinned inputs run
    through the route's whole text pass; the Back/Forward check works again; a
    pending choice is shown and a turn snaps it back; a failed switch is
    announced and keeps the keyboard's place.
  - Re-review: a pending choice blocks Send; the guard scan pinned to the live rules; B-030, B-031 logged.
  - 1707 tests; 133 modules; no new env vars.
- [ ] **B4 — Burhan's call first:** the open entries (B-005, B-009, B-011…
  B-020, B-022, B-023, B-025…B-028).

## Later / explicitly deferred
Herd Immunity federation (needs k≥3 workspaces + privacy review) · billing ·
i18n · admin console · Python SDK public packaging · KSA residency routing.
