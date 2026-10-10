# Auspex Roadmap — sessions & deliverables

One session = one focused working window. A session is DONE only when the
CLAUDE.md session-end ritual is complete. Order may flex; scope of a session
may not grow mid-session (IDEAS.md exists for that).

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

## Later / explicitly deferred
Herd Immunity federation (needs k≥3 workspaces + privacy review) · billing ·
i18n · admin console · Python SDK public packaging · KSA residency routing.
