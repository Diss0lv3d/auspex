# STATE — Auspex

_Last updated: 2026-08-16 (**S22 COMPLETE — the output side finally exists.**
Scoped by decision again, and the decision was the one the repo had already
written down four times: **TD-012(a) shipped as `auspex/outguard.py` (D-030)**,
calibrated on 34 live answers rather than a chosen number. Step 0 found that
**S21's sentence fix closed only one of three spellings** (6/6 open on each of the
other two) and that **a late handler was overwriting the human who abandoned it**.
**1014 tests.**)_

## Where we are

**Phase 4 is contract (S17) + decision loop (S18) + hardened input and spend (S19)
+ a pipeline, docs and a demo anyone can run (S20) + the beta debt paid down (S21)
+ an output rail (S22). The ROADMAP through S20 is complete; S21 and S22 were both
scoped by a decision rather than a plan. S23 has a clear candidate for the first
time in three sessions — see "Next session should".**

- **S22 Step 0 — `/promote` done first, and the slate behaved exactly as S21
  predicted.** The docs-only slate reached `main` as squash `4056070` via **PR #22**
  (merged 2026-08-15 19:22 UTC), back-merged `7700d07`, tree verified unchanged.
  Real diff **4 files, +376/-376**. PR #22's commit LIST still showed every commit
  back to S2 — **read the diff, never the list.**
- **S22 Step 0 — fresh-eyes review of the S21 commits (DONE, 2 fixed, 1 ratified,
  5 sound).** Record: docs/probes/2026-08-16-s22-step0-review.md; harnesses in
  docs/probes/s22-step0/ (`probe_designs_against_corpus.sh` mutates `guard.py` and
  restores it on an EXIT trap; `probe_abandon_race.py` deletes its two workspaces
  and asserts 0 residue). **36 new assertions, 20 proven to fail pre-fix**; the
  other 16 pin already-sound areas, so they pass both ways by design.
  - **(FIXED — S21's own fix was one third of a fix) a sentence ends at a newline
    and at the end of the input, not only at `[.!?]\s`.** The exact six pairs S21
    closed came straight back as CONTENT written across two lines (**6/6**), and
    **deleting the single space** after the full stop put all six back (**6/6**) —
    `[.!?]\s` needs a character that is no longer there. Four designs measured
    against the **real 129-test corpus** rather than one written alongside them:
    the shipped design looked expensive on my own 10-message corpus and **costs
    nothing** on the repo's. Treating every newline as a boundary is safe because
    **Enter sends** in the chat input (`static/index.html:228`), so a newline
    arrives by paste or API — deliberate structure, never a soft wrap.
  - **(FIXED — a defect TD-028a opened) a late handler overwrote the human who
    abandoned it.** `abandon` guards on claim AGE, and an old claim is not the same
    fact as a dead process: a merely *slow* handler passes `STALE_CLAIM_SECONDS`,
    gets abandoned, and then returns. All four completion statements were
    `WHERE id = $1` with **no status guard**. Raced with a real handler held open on
    an event: `abandoned` → `executed` with `decided_at`/`decided_by` still naming
    the abandoning human, so the row asserted a human had decided `executed`. On the
    failure path it is worse — `failed` is precisely the "nothing happened" claim
    the no-reaper design refuses to let a *timer* make. Now each completion is
    guarded on the status it claimed, and a late answer is recorded on the abandoned
    row **without moving it**.
  - **(RATIFIED — TD-033) an abbreviation ends the sentence early**, discarding the
    attribution and refusing legitimate prose (`e.g.`, `i.e.`, `Dr.` — 3/3 against
    controls that are CONTENT *for the reported-speech reason*). It fails **closed**,
    and closing it needs a rot-prone abbreviation list. Structural periods are
    unaffected (`T1566.001`, `192.168.1.1`, `3.5` do not split).
  - **(SOUND) the folded ∪ raw union** — the brief's strongest lead, attacked and
    not broken: quoted and fenced artefacts containing a ZWSP stay CONTENT, the five
    pinned legitimate shapes are still allowed, the index map is monotonic, and no
    boundary computed on one copy is applied to the other.
  - **(SOUND) `title_score` / `promote_canonical`** — degenerate titles and queries
    return 0.0 and promote nothing; the 0.3 floor stops a lone coincidental word.
    **Measured bound, not a defect:** prefix equivalence at 4 chars treats
    `port`/`portal` and `host`/`hostile` as one word. No wrong promotion observed.
  - **(SOUND) `abandon` as a state transition** — raced 8-way, exactly one wins;
    never-claimed → refused; cross-tenant → NOT_FOUND (not a 409 that would confirm
    existence); the `pending()` **stale arm** is tenant-scoped like the pending arm;
    a stale claim cannot be approved or rejected through the ordinary buttons.
  - **The measurement discipline caught a live error in this probe's own first
    draft.** The abbreviation cases were first measured with a payload carve-out
    **(3)** matched — an introducer, not reported speech — so the probe was reading
    the wrong arm and would have called the abbreviation harmless. Asserting the
    **reason**, not just the verdict, is what turned that into a finding. *A verdict
    is not evidence about which rule produced it.*
- **S22 — TD-012(a) SHIPPED: `auspex/outguard.py`, ratified as D-030.** Record:
  docs/probes/2026-08-16-s22-outguard.md.
  - **The question it answers is narrow on purpose.** Not "was this answer
    influenced?" — not decidable from text, and a model grading itself is what D-006
    refuses. It asks **"is the platform's own configuration coming back out?"**,
    which is decidable because we hold both halves: we know exactly what we sent.
  - **What is indexed is a decision.** Only configuration we issued
    (`CHAT_SYSTEM_PROMPT`, `HISTORY_FENCE_DIRECTIVE`, `contract.system_directive()`,
    `PASS1_DIRECTIVE`). **Never** the analyst's paste (their own email quoted back is
    a *correct* answer), **never** the deterministic verdict blocks (the answer is
    *pinned* to echo their values), **never** `_pass2_directive` (it embeds the
    model's analysis the answer is built from).
  - **`SHINGLE_WORDS = 8` is calibrated on live Scout output, like NEURAL_FLOORS.**
    34 real answers across both streaming shapes: **legitimate ceiling 6** (including
    12 questions whose *correct* answer is written in the instruction set's own
    vocabulary — prompt injection, DATA blocks, fencing), and the one extraction
    attempt that complied reproduced **60** words. **The model refused 3 of 5
    attempts** — which is exactly why the rail exists rather than being unnecessary:
    refusal is a property of the model, and we run on whatever endpoint the customer
    brings (D-005). The 7-word partial sits in the gap and is **not** caught, named
    rather than tuned away.
  - **A leak is cut off mid-stream and NOT persisted.** Bounded, not prevented — a
    streamed answer cannot be un-sent, exactly as TD-012 said. The guarantee that
    *lasts* is non-persistence: a stored assistant turn replays into every later deep
    turn of the session (TD-009), so a saved leak becomes a permanent one.
  - **Live-verified through the rebuilt container against real Scout.** The attack
    returned `finish_reason: output_guard`, `output_valid: false`, and left **no
    assistant row** in Postgres; the hardest legitimate turn returned
    `output_valid: true` and persisted normally. Probe rows deleted, residue 0.
  - **TD-012 is HALF resolved and the entry now says so.** The number covered two
    different pieces of work: (a) output-side injection detection shipped; **(b)
    contract-conformance repair — the original S9 text — is untouched.**
- **CI-green: 1014 tests** (964 at S21 end → **+36** Step-0, **+14** outguard).
  `./ci.sh` green including the installed-dist gate (**118 modules**, was 117 —
  `auspex/outguard.py`); `/api/health/ready` 200. **Zero new env vars — nine
  sessions running.**

- **S20/S21 (kept for context).** S20 made CI a check anyone can see (D-028, runs
  `./ci.sh` and nothing else) and gave the repo its README and `scripts/demo.sh`.
  S21 closed TD-026 (definition path 3/7 → 7/7) and TD-028a (a dead claim is
  visible; deliberately no reaper). Earlier sessions are in git history and
  DECISIONS.md — this file no longer restates them.

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: this session's four commits + this session-end commit.**
   `e8a5607` (guard sentence boundary), `4957b5e` (the late-handler overwrite),
   `711e85f` (Step-0 record + TD-033), `6ae733a` (the output rail). **This is a
   real slate, not the docs-only steady state — `/promote` first next session.**
   - **Read the diff at promote time. Never trust a quoted number or the commit
     LIST** — after a squash the list is meaningless (PR #22's still showed every
     commit back to S2; the real change was 4 files).
2. **Branch protection on `main` is STILL the one manual step left** — the CI check
   exists and is green, but nothing yet REQUIRES it before a promote merge.
   Repository settings, Burhan's call, not a commit's (D-028). One command:
   `gh api -X PUT repos/bh3082336888-cell/auspex/branches/main/protection -f 'required_status_checks[strict]=true' -f 'required_status_checks[contexts][]=ci.sh (lint + tests + container build + installed-dist)' -F 'enforce_admins=false' -F 'required_pull_request_reviews=null' -F 'restrictions=null'`
3. **TD-028b is the sharpest open half of TD-028** — a failed execute leaves effects
   it denies (the handler's INSERT is really in the table while the row says
   `failed`). (c) is sharper after S21: `abandoned` joins `failed` as a state whose
   effects are unknown and whose `undo` is gated shut. **S22 fixed the adjacent
   defect in the same four statements**, so the code is freshly mapped. (d) is card
   rendering.
4. **The card stream still emits only new cards, never status changes** — opened by
   the TD-028a fix. A client watching `/stream` is not told when a claim goes stale;
   the polled list is where it surfaces today.
5. **TD-031 / TD-032 / TD-033 are ratified bounds, not a backlog.** Do **not**
   re-open the guard regex — S19, S20 and S21 each spent a session there, and S22
   touched only the sentence *boundary* because it was a defect in S21's own fix.
   All three name **TD-012** as the real answer, and **TD-012(a) now exists**.
6. **TD-005 trigger, still armed:** cve pool > 300k chunks, curated pool > 5k, any
   new doc_type, any embedding-model change, **or before any free-text-over-CVEs
   surface ships** (TD-027 is a HARD GATE). Corpus at S21: **31,828** — cve 30,562,
   technique 1,248, tactic 15, concept 3. Not tripped. TD-026's battery labels
   belong on this trigger list too.
7. **`SHINGLE_WORDS` is a calibrated number, not a constant to edit.** It was
   measured against a **specific model** (Scout). A customer endpoint that is more
   verbose, or a materially longer instruction set, changes the legitimate ceiling —
   re-run `docs/probes/s22-outguard/probe_calibrate2.py` before moving it. Same rule
   NEURAL_FLOORS has.

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
2. **Deep path is conversational-only (v1)** — AgentLoop still not wired into
   `/api/chat`. **Its stated prerequisite (TD-012) is now half-shipped**, which is
   what makes it the S23 candidate. Open: TD-012**(b)**, TD-014, TD-015, TD-016,
   TD-017, TD-019, TD-020, TD-021, TD-022, TD-023, TD-024, TD-025, TD-027,
   **TD-028b/c/d**, TD-029, TD-030, TD-031/032/033. **TD-018, TD-026, TD-028a and
   TD-012(a) are CLOSED.**
3. **KB bootstrap needs outbound HTTPS once per fresh volume**; ingest needs
   NVD/CISA/FIRST/GitHub reachability — failures degrade honestly.
4. **Corpus 31,828 docs and growing while the container runs.** TD-011 tracks the
   index rollover trigger.
5. **Two rails now, and neither is a closure.** The INPUT guard bounds accidents and
   naive attempts and does not defeat a determined authenticated caller (D-027,
   D-029 — quotation marks, an introducer, an abbreviation). The OUTPUT rail (D-030)
   catches our configuration coming back out, **but not a paraphrase of it, and not
   an injection that merely made the answer wrong** — that prose looks like an
   answer, and only a code-computed verdict can contradict it. Both bounds are
   written down rather than implied.
6. **An intermittent, unattributed test failure was observed once.** One `./ci.sh`
   run reported `1 failed` with pytest's "multiple unraisable exception warnings"
   ExceptionGroup and **did not name a test**. It has not reproduced in **five**
   subsequent full-suite runs (1000 then 1014 tests). Recorded rather than
   dismissed: if it returns it is an async-teardown flake, not the settlement change,
   which was green in every run.

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`.
- Ollama 0.32.5 on :11434; models qwen3:14b / llama3.1:8b / mistral:latest.
  **Primary dev LLM is Northflank Scout (D-015)** — reachable, HTTP 200, and it is
  what S22's calibration was measured against.
- **S22 session-end (2026-08-16):** staging, tree clean, identity
  `bh3082336888-cell`. All three containers healthy; `./ci.sh` **green, 1014 tests,
  118 modules**; `/api/health/ready` **200**.
- **`gh` did NOT flip to the work account at S22** (checked three times: ritual,
  before `gh pr create`, before `gh pr merge`). It DID at S18 and S16; did not at
  S17, S13–S15, S19–S22. **Unpredictable is the pattern** — re-check before EVERY
  `gh` call.
- **`gh pr merge` works.** `gh pr edit` still fails with a Projects-classic GraphQL
  deprecation — use `gh api -X PATCH repos/.../pulls/N`.
- **Run the suite the way `ci.sh` does.** `./ci.sh` uses `.venv`, where the package
  is installed editable. A bare `python3 -m pytest` uses the **system** interpreter,
  where `auspex` is NOT installed, and
  `test_the_package_imports_before_enrichment_does` fails for that reason alone —
  it cost time this session before being spotted.
- **This repo HAS GitHub Actions** (S20, D-028) — `.github/workflows/ci.yml` runs
  `./ci.sh` on push and PR to `main`/`staging`. Cold run ~5m30s. **A clean runner is
  a different environment from this laptop and finds things it cannot.**
- **Local `main` ref goes stale every promote.** `git fetch origin` and read
  `git diff origin/main..staging --stat`, never the commit list.
- **The app container runs the BUILT IMAGE, not the working tree.** S22's live
  verification needed `docker compose up -d --build app`, not `restart`.
- **All dev-login users share the `default` workspace.** Tests touching
  `usage_counters` must clean up. S22's live verification spent real inference and
  deleted its two chat sessions afterwards, asserting 0 residue.
- **Probe residue is expensive** (S18: a 100k-row seeded workspace made plan tests
  take 150 s instead of 21 s). Plan assertions must VACUUM first.
- **THE DEMO IS ONE COMMAND: `./scripts/demo.sh`** (~3 min, end to end). S22 added
  the output rail to its honest section — a real `grep` of the calibrated constant,
  no LLM dependency, because the rail's firing against a live model is not
  deterministic (the model refused 3 of 5 extraction attempts).

## Reference intelligence (from the SARA Open architecture study)
Base: `/home/burhan/sara-open/` — key snapshots in docs/probes/:
- ACH analogues (S12): 2026-08-08-sara-ach-analogues.md
- Phishing/header/typosquat (S11): 2026-07-18-sara-phishing-header-patterns.md
- Alert additive scorer (S10): 2026-07-18-sara-alert-triage-scorer.md
- DEFERRED rail (S9): 2026-07-18-sara-orchestrator-deferred.md
- Fast classifier / 92-8: 2026-07-16-sara-fastpath-pattern.md
- RRF retrieval + ID bypass: 2026-07-17-sara-rrf-retriever-pattern.md

## Next session should
**Start with `/promote`** — the slate is a REAL one this time (four commits plus
this session-end commit), not the docs-only steady state.

Then, for the first time in three sessions, **there is a clear candidate rather
than an open question: wire AgentLoop into `/api/chat`.** It is the largest
remaining gap between what the platform is and what its own README says, and the
reason it kept losing to other work was that TD-012 read as its prerequisite —
**that prerequisite now half-exists.** Ask before implementing anyway; the
alternatives, in order:

1. **Wire AgentLoop into `/api/chat`.** The loop is built, capability-negotiated and
   tested, and the deep path does not use it. Now unblocked. Note what it changes:
   the output rail currently indexes four fixed strings, and a tool-calling loop
   makes the instruction set dynamic — the rail's index must follow it, or it
   silently protects less than it looks like it does.
2. **Finish TD-028 (b/c/d) with TD-025's terminal-state semantics.** (b) is the
   sharpest measured defect left, and S22 just fixed the adjacent defect in the same
   four statements — smaller than (1) and fully specified.
3. **TD-012(b) — contract-conformance repair**, the original S9 entry: re-ask once
   on a non-conforming answer. Smallest of the three.
4. **Phase 5 / Herd Immunity groundwork** — needs multi-workspace and a privacy
   review; a design session, not an implementation one.

NEXT-SESSION.md has the full prompt.
