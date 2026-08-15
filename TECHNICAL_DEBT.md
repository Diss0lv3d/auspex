# Technical debt — logged the moment it's taken

## TD-028 (S19) — the proposal status machine has no way back from three states
**Where:** `auspex/actions/settlement.py` (`ActionExecutor.execute` / `.undo`),
`auspex/routes/proposals.py` (`list_proposals`, pending-only).
**All four items below were REPRODUCED BY EXECUTION** at S19 Step 0 —
docs/probes/2026-08-15-s19-step0-review.md, harness
`docs/probes/s19-step0/probe_s18_review.py`.

**(a) `executing` and `undoing` are claims with no timeout, and nothing reaps them.**
A process that dies between the claim and the handler wedges the row forever:
`execute` refuses `not_approved`, `undo` refuses `not_executed`, `reject` gets
`already_decided`. Measured. Worse than the S18 hand-off predicted — the row is
also **invisible**, because the approvals list filters `status = 'pending_approval'`,
so **a human watching the queue sees the action vanish** with nothing to click.
*Fix wants:* a claim timestamp plus a reaper on the existing SKIP LOCKED job seam,
and a decision about what a reaped row becomes (back to `approved` is wrong if the
handler had already half-run — see (b)).

**(b) A failed execute leaves effects it denies.** Forced a failure after the
handler's INSERT landed: the note is really in the table and the row says `failed`
with `{"error": "RuntimeError"}`. The surface reports that nothing happened while
something did. No idempotency key, no partial-effect reasoning (TD-025 named this
as unwritten; this is the measurement behind it).

**(c) The cleanup path exists and is gated shut.** `undo` requires
`status = 'executed'`, so a `failed` proposal cannot be undone through the API —
even though `put_back` is keyed on `proposal_id` (`builtin.py:136-141`) and would
delete exactly the orphaned row and nothing else. **Not the one-word change it
looks like:** allowing undo from `failed` needs terminal-state semantics — what the
row becomes, and whether a proposal whose write never landed should report `undone`.

**(d) Two identical proposals in one turn are indistinguishable to the approver.**
A model calling one action twice files two rows with identical fingerprints and
arguments. **Deduping is deliberately NOT the fix** — a proposal is a request for a
human decision, and collapsing two requests would have the platform decide that a
second intent was a mistake, which is the judgement D-014 reserves for the human.
The defect is that the card gives an approver no signal they are being asked the
same question twice.
**Why deferred:** (a) needs a durable job and a state decision; (b)/(c) need
terminal-state semantics that belong with TD-025's idempotency gap; (d) is card
rendering. None is Step-0-sized, and S19's scope is Hardening.
**Risk if left:** (a) is the sharpest — an action can silently disappear from the
queue after a restart, and the S18 demo's "something really executes" claim quietly
depends on nothing crashing mid-run.
## TD-027 (S19) — the `doc_types` filter no longer restores recall for `cve`
**Where:** `auspex/kb/service.py:518-524` (the `search()` docstring's recall
argument), `NEURAL_FLOORS["cve"]` in `auspex/kb/fuse.py`.
**Risk:** S7/S8 established that filtering kNN to a `doc_type` "makes lucene kNN
exact over the subset — this restores recall, it doesn't just trim". That
justification is load-bearing for the curated pool and is **no longer true for
`cve`**: cve is 30,553 of 31,819 chunks (96%), so filtering to it is not a subset.
Measured at S19 — the filtered and unfiltered CVE batteries returned **byte-identical**
results (docs/probes/2026-08-15-td005-rebattery.md §3). Nothing is broken today
because no shipped surface does free-text CVE search, but a future one would
inherit a recall argument that does not apply to it, on a floor (0.70) that has
never gated a real request and whose noise headroom is down to 0.0437.
**Why deferred:** purely latent — v1 has no such surface (verified by grepping
every `kb.search`/`kb.lookup_ids` caller). Fixing it speculatively means designing
for a surface that does not exist.
**HARD GATE:** re-run the CVE battery and re-derive the cve floor **before** any
free-text-over-CVEs retrieval surface ships. Do not assume the filter buys recall.

## TD-026 (S19) — the definition path renders a neighbouring ATT&CK page
**Where:** `auspex/kb/fuse.py::rrf_fuse` (accumulates per `chunk_id`, line 64),
`auspex/kb/echo.py::render_definition_answer` (renders `hits[0]` as THE definition),
`auspex/routes/chat.py:383`.
**Risk:** user-visible wrong answers on the shipped definition path. Labeled
through the real path for the first time at S19 (the S8 battery labeled the neural
*leg*, which is fine): **3 of 7** true positives render the wrong page —
"what is phishing" → **T1598: Phishing for Information** (T1566 not in the returned
5 at all), "what is credential dumping" → **TA0006: Credential Access** (the parent
tactic, T1003 absent), "how do adversaries abuse command line interpreters" →
**T1202: Indirect Command Execution** (T1059 at rank 1). A fourth, "what is lateral
movement" → TA0008, is a **stale label rather than a defect** — TA0008's page is
titled exactly "Lateral Movement".
**Not a safety issue:** every hit involved is above its floor, and all four
off-corpus queries still return an honest miss. Nothing fabricates. This is
relevance, not fabrication — but an analyst asking "what is phishing" and reading
about reconnaissance is bad output on a shipped surface.
**Measured mechanism** (docs/probes/2026-08-15-td005-rebattery.md §4):
1. **RRF fragments a doc's vote.** Scores accumulate on `chunk_id`, so T1566's
   three chunks (neural ranks 2/4/5) each score separately and never combine,
   while single-chunk T1598 sits at rank 0 in both legs and accumulates. RRF runs
   over chunks; the answer is a doc.
2. **BM25 omits the canonical page entirely** — T1566 and T1003 are absent from
   their BM25 legs; sub-technique neighbours fill all 10 slots.
3. **Tactic pages out-score their techniques** on technique questions (TA0006 is
   rank 0 in both legs for "credential dumping").
**Two fixes measured, neither clean (thrash brake, CLAUDE.md rule 7):** dedupe each
leg to best-chunk-per-doc before fusion — principled, fixes mechanism 1, moves the
battery **3/7 → 3/7** because mechanisms 2 and 3 dominate; plus a title-exactness
promotion → **4/7**, fixing only "what is phishing" via a stopword list that will
rot. Harness in `docs/probes/s19-step0/variant_fusion.py`, re-runnable.
**Path to fix:** treat retrieval-for-definitions as doc-level, not chunk-level —
fuse by `doc_id` with a best-chunk representative, and give the canonical page a
real signal (exact title match on the `ids`/title keyword field, or preferring the
technique over its tactic when both clear the floor) rather than hoping BM25
surfaces it. Needs the labeled battery re-run as the acceptance test, and the
labels re-examined first: two of the seven are corpus-stale.
## TD-025 (S18) — approval flow v1 bounds: one executable system, a polled stream, no expiry
**Where:** `auspex/actions/settlement.py`, `auspex/actions/builtin.py`,
`auspex/routes/proposals.py`.
**Risk:** each is a bound rather than a bug, and each becomes real at a different
moment:
- **A proposal never expires.** `pending_approval` is forever. An action proposed
  during an incident can be approved a week later; the spec fingerprint stops it
  running against a CHANGED declaration, and stops nothing if the declaration is
  the same but the world is not (the host was already reimaged). Wants a TTL and
  an explicit "stale, re-propose" state — the D-022 staleness posture applied to
  decisions rather than verdicts.
- **`scope` still is not a permission (carried from TD-023).** The executor
  allow-lists SYSTEMS in code, so today no third-party action can run at all. The
  moment one can, "this workspace granted us `edr`" has to be a checked grant and
  not a declaration the action makes about itself.
- **One executable system, and it is us.** `EXECUTABLE_SYSTEMS = {"auspex"}` is
  deliberate (D-024) and means the executor has never been exercised against a
  network, a credential, a timeout, or a partial failure. Everything about
  retries, idempotency keys and half-applied effects is unwritten because nothing
  yet can half-apply.
- **The card stream is polled, once a second, per connected client.** Fine at
  current scale (one indexed query on `idx_proposals_ws_status`), and it is a
  per-client cost that grows with connections rather than with proposals. A
  LISTEN/NOTIFY channel would fix it and needs its own probe of delivery
  guarantees before it is trusted with an approval queue.
- **The stream has a lifetime, so clients must reconnect.** `STREAM_MAX_TICKS`
  (600 ticks ≈ 10 minutes) exists because `is_disconnected()` does not reliably
  fire; SSE reconnect is native, but nothing in the repo yet CONSUMES this stream,
  so the reconnect path is untested against a real client.
- **`decided_by` is recorded and never enforced.** Any authenticated member of a
  workspace can approve anything in it. Roles, four-eyes on destructive actions,
  and "the proposer may not be the approver" are all absent — and all of them are
  approval-flow features that only mean something once more than one human uses
  one workspace.
**Path to fix:** TTL + `stale` state first (cheapest, and the one that silently
misleads); grant-checked scope before the first third-party action; roles when
multi-user workspaces are real.

## TD-024 (S18) — the digest's decay read is slower than the defect it replaced at the widest legal window
**Where:** `auspex/timeline/store.py` `_DECAYED_SQL`; `MAX_SINCE_DAYS = 365` in
`auspex/routes/timeline.py:46`.
**Measured (S18 Step 0, docs/probes/2026-08-15-s18-step0-review.md):** the S17
rewrite wins overwhelmingly on the windows analysts actually open and loses on
the tail. At **100k verdicts / 12 half-life families**: 7 d = 5.4 ms vs the old
query's 150.9 ms (0.04×), 90 d = 37 ms (0.26×), but **365 d = 161.4 ms vs 133.8 ms
(1.21×)**. The crossover is **~300 days** there and **~185 days** at 25k/50
families — it moves IN as a workspace accumulates half-life families.
**Risk:** low but real and reachable — `days` is a user-supplied query parameter
capped at 365, so any analyst can request the slow shape, and 161 ms is slower
than the 143 ms defect the S17 rewrite existed to fix. It scales with the table:
at 200k rows the 365-day case would be ~320 ms.
**Why not fixed in S18 Step 0:** a variant WAS built and measured — sort the
candidates by decay first (a key each row carries alone) and let the `LIMIT` stop
the "is this still current?" probe early. It is **2.2–2.9× faster at every
window** with byte-identical output at limits 50/200/1000 (probe count 59 instead
of ~30 000), and it beats the old query everywhere, removing the crossover. It is
not shipped because the early stop depends on the candidate ordering surviving
into the outer query, which Postgres does not guarantee — a non-recursive CTE
referenced once may be inlined and its `ORDER BY` dropped. That is a second
load-bearing invisible construct and a worse one than the `OFFSET 0` fence:
losing the fence makes the query slow, losing this ordering makes the digest
render **the wrong rows first** while returning the right set. Not a trade to
make mid-review, in a session whose goal is the approval flow.
**Path to fix:** ship the variant WITH a test that fails on mis-ordering at a size
where the planner has a real choice (not just the row set — assert
`half_lives_elapsed` is descending at 100k), or get the same early stop from a
shape Postgres guarantees. `MAX_SINCE_DAYS` should NOT move: narrowing the API to
protect a 161 ms tail would cost a real capability to save an explicit,
rarely-asked whole-year request.

## TD-023 (S17) — Actions SDK v1 bounds: scope is declared but not enforced, and an undo is never exercised
**Where:** `auspex/actions/types.py` (`ActionScope`, `UndoSpec`, `ParamType`),
`auspex/actions/registry.py` (in-process registry).
**Risk:** none today — nothing executes (D-023, and S17 ships no executor). Each
item becomes real the moment S18 wires the proposal round-trip:
- **`scope` is a declaration, not a permission.** An action says it touches
  `edr`, and nothing checks that this workspace granted anything at `edr`. The
  approval card will name the system, so a human is the only enforcement — which
  is the S18 design anyway, but it means scope is currently documentation with a
  type.
- **~~An undo is declared and never exercised.~~ RESOLVED (S18).** The first
  executable action ships with an undo a test actually RUNS, and the live probe
  runs it too (docs/probes/2026-08-15-s18-approval-flow-live.md). Still true for
  any action that cannot execute here — a third-party undo remains unexercised
  because its action is proposal-only by design (D-024).
- **Parameters are primitives only** (string/integer/number/boolean). Deliberate
  — the S2 harness measured every model mangling long/structured arguments — but
  an action needing a list of host ids has no way to say so today.
- **The registry is in-process and workspace-blind.** One `ActionRegistry` per
  app, populated by code. There is no per-workspace action surface and nothing
  persisted, so "which actions does this tenant have?" has no answer yet — and
  the future customer Python SDK is exactly that question.
- **~~No spec identity across time.~~ RESOLVED (S18, D-024).** A canonical
  fingerprint of the declared facts is stamped on the proposal and re-checked
  before execution, alongside a re-run of the D-014 gate on today's risk. What it
  still cannot see is a changed handler BODY behind identical declared facts —
  named in D-024 rather than left implied.
**Why accepted:** S17's scope was the contract, and every item above is either
S18's subject (approval, execution, re-check at execute time) or needs a real
customer action to design against. Logging them now so S18 does not rediscover
them as surprises.
**Path to fix:** ~~(a) spec fingerprint~~ and ~~(c) exercise the undo~~ DONE in
S18 (D-024). Remaining: (b) grant scopes per workspace and check them in the gate
rather than only rendering them — now tracked in TD-025, which owns the live
approval flow's bounds; (d) array params once a real action needs one, with a
measured bound per the S2 finding.

## TD-022 (S17) — a checker that dies AFTER succeeding once still reads as healthy
**Where:** `auspex/checks.py` (`FailureCounter`, `CheckerStatus`),
`auspex/ingest/scheduler.py` (`_cycles`), `auspex/timeline/types.py`
(`Digest.trustworthy`).
**Risk:** S17 Step 0 closed the two holes it could close without a schema change
(docs/probes/2026-08-11-s17-step0-review.md): a process that has run nothing no
longer vouches for the quiet, and a checker whose only evidence is failure no
longer hides behind `DEGRADED_AFTER` across restarts. **What remains is the
mirror image:** `ever_succeeded` never expires and `consecutive_failures` only
moves when something runs, so a scheduler task that dies silently after a week of
health leaves a roster that reads perfectly clean — no failures, a recorded
success, `trustworthy=True` — forever. Cycles simply stop, and nothing counts a
cycle that did not happen.
**Why accepted:** every honest fix needs a heartbeat with a TIMESTAMP behind it,
durable across restarts, plus a staleness bound derived from the cycle interval —
and a bound on the app side alone re-opens the restart false-alarm the S17 fix
was careful to avoid. That is a schema change (`ingest_state` is the natural
home — a checker heartbeat is the same shape as a feed watermark) and its own
piece of work, not a rider on a review.
**Path to fix:** record `last_success_at` per checker in Postgres on every
completed cycle; `trustworthy` requires the newest heartbeat to be within a few
cycle intervals of `now` (the DB clock — see `timeline.store.reader_now`). That
also subsumes the second replica noted in TD-021, since the heartbeat stops being
per-process.

## TD-021 (S16) — verdict timeline v1 bounds: unpaginated history, per-process checker health, and one uncosted digest query
**Where:** `auspex/timeline/store.py` (`MAX_TRAIL`, `_DECAYED_SQL`),
`auspex/checks.py`, `auspex/routes/timeline.py`.
**Risk:** low today, and each item is visible in the payload rather than hidden.
- ~~**The decay-crossing query is the one read S16 did not cost.**~~
  **RESOLVED at S17 Step 0** (docs/probes/2026-08-11-s17-step0-review.md). The
  worry was correct: seeded at 99k observables / 109k verdicts it read the whole
  history and spilled its sort to disk, 143 ms. Rewriting the crossing as a
  `created_at` range per (edge, half-life) pair — the same predicate with
  `created_at` moved to one side — put it on a new index
  (`idx_verdicts_ws_hl_created`) at **4.6 ms**, and it now has the plan
  assertion at 25k the other reads have. One residue, logged rather than
  buried: at the widest legal window (365 days) the new shape is ~9% slower
  than the old one.
- **Checker health is per-process and in-memory.** `FailureCounter` lives on the
  sink object, so it resets on restart and knows nothing about other replicas.
  With one app container that is exactly right; with two, a digest served by a
  healthy replica would call a degraded one's silence trustworthy.
- ~~**`ever_succeeded` is reported but not required for `trustworthy`.**~~
  **RESOLVED at S17 Step 0**, and the trade this entry described turned out to be
  a false choice. Requiring it WOULD have flagged health as failure — but only
  because nothing in the system meant "a cycle ran" (every `emit()` is guarded on
  a non-empty doc list, so a quiet cycle reached no counter at all). The
  scheduler now counts completed cycles, which is true in a quiet week and false
  in a crash loop, so `trustworthy` can require a success without punishing an
  idle platform. See TD-022 for what is still not caught.
- **No pagination**, and **a page that is cut is now SAID to be cut** (S17 Step 0
  — `limit`, `complete` and `truncated` in the digest payload; before that,
  a 365-day window found 32,930 decayed verdicts, returned 50, and the page
  announced "50 went stale"). `MAX_TRAIL` 200 on a verdict's history, `limit`
  <= 200 on the digest — same shape as TD-016/TD-019/TD-020. An observable
  re-enriched daily for a year still shows only its newest 200 verdicts, and the
  TRAIL does not yet carry the truncation flag the digest now does.
- **`/api/watchers` does not carry `standing`.** Only the timeline surface does
  (see TD-020), so the same claim reads with different detail depending on which
  surface you open.
**Why accepted:** S16's scope was rendering a history that already existed and
giving decay a vocabulary. The crossing query is the only genuinely new read
shape, and seeding a 100k-observable workspace to cost it properly is its own
piece of work.
**Path to fix:** (a) seed a large workspace and EXPLAIN `_DECAYED_SQL`; if it
scans, materialise "latest verdict per observable" (a partial index on
`verdicts (workspace_id, observable_id, created_at DESC)` already exists — the
crossing predicate is the part that resists) or precompute the next band-crossing
timestamp per verdict at write time and index THAT; (b) move checker health into
Postgres when a second replica is real; (c) keyset pagination on
`(created_at, id)`, shared with TD-016/019/020.

## TD-020 (S15) — falsification watcher v1 bounds: a thin vocabulary, one passive checker, no expiry
**Where:** `auspex/watchers/types.py` (`WatcherKind` — three kinds),
`auspex/watchers/derive.py` (the derivation rules), `auspex/routes/watchers.py`
(`limit` only, no cursor).
**Risk:** low, and the shape of it is stated in the payload (`kinds`,
`checked_by`) rather than hidden — but "this verdict has 3 open falsifiers"
reads as more self-scrutiny than it is, and that is the risk worth naming.
- **The vocabulary is CVE-shaped.** `kev_listing` and `record_withdrawn` are
  the only ingest-checked kinds, and both key off a CVE doc id, so a domain, IP
  or hash verdict registers exactly one condition (`provider_escalation`). The
  S15 prompt's own example — "this domain's registrar changes" — is not
  implementable today: no connected feed reports registrar or ASN changes.
  Deliberately NOT faked with a watcher that nothing evaluates; a kind with no
  checker fails `test_every_kind_is_owned_by_exactly_one_checker` by
  construction.
- **`provider_escalation` is PASSIVE.** It is satisfied inside
  `persist_enrichment`, so it fires only when something re-enriches the
  observable — which today means an analyst happening to ask again. Nothing
  schedules re-enrichment, so this watcher can sit open indefinitely while the
  world changes. The ingest-checked kinds are genuinely active; this one is
  "checked when someone looks", and the two are not distinguished on the
  surface beyond `checked_by`.
- ~~**Open watchers never expire.**~~ **ANSWERED in S16 (D-022).** A claim on a
  decayed verdict now carries a derived `standing` (`load_bearing` / `lapsed`)
  alongside its `status`, on `/api/timeline/{obs_id}`. It is deliberately NOT
  expiry: the claim stays open and still fires, because the platform committed
  to watching and quietly stopping is the failure this feature exists to
  prevent. `status` answers "was this contradicted?", `standing` answers "does
  the belief behind it still stand?" — expiring into `status` would have erased
  the difference between never-contradicted, contradicted, and superseded.
  Still open on the WATCHER surface: `/api/watchers` does not yet carry
  `standing` (it has no verdict-age context in its query), so the two surfaces
  describe the same claim with different detail.
- **No pagination.** Newest-first with `limit` ≤ 200, same shape as TD-016 and
  TD-019.
- **The cycle path is unobserved end-to-end,** inheriting TD-019's open half:
  `WatcherSink` is pinned as wired and live-verified by emitting the real
  `DocChange` directly, but no test drives `run_cycle` all the way through to a
  satisfied watcher.
**Why accepted:** S15's scope was the registration/derivation/check core and the
honesty rail. Widening the vocabulary is gated on feeds that do not exist yet,
and inventing conditions for them now would be exactly the unfalsifiable
self-scrutiny this feature exists to replace.
**Path to fix:** (a) add kinds as feeds land (abuse.ch quartet, passive DNS,
registrar/RDAP), each with a checker and a test, per D-021's extension rule;
(b) give `provider_escalation` a real trigger by scheduling re-enrichment of
observables with open escalation claims — bounded, off the ingest critical path
(the TD-008 precedent); (c) decide what an expired claim means alongside S16's
decay/staleness surfaces; (d) keyset pagination on `(created_at, id)`, shared
with the retro-hunt collections; (e) drive `run_cycle` against a fake KEV feed
whose catalogue contains an enriched CVE — hermetic, and it closes this bullet
for both sinks at once.

## TD-019 (S14) — retro-hunt v1 bounds: CVE-only sweep, no pagination, scheduler timing unobserved
**Where:** `auspex/retrohunt/types.py` (`SWEEPABLE_TYPE = "cve"`),
`auspex/routes/retrohunt.py` (`limit` only — no cursor/offset on
`/matches` or `/flips`), and the emit-on-a-real-cycle path in
`auspex/ingest/scheduler.py`.
**Risk:** low, and named in the payload rather than hidden.
- **CVE-only.** A CVE-keyed feed can only match CVE observables, so this is
  currently complete rather than partial — but the moment a feed lands that
  carries hashes, domains or IPs (abuse.ch quartet, ROADMAP S8 line), the sweep
  silently covers none of them. `/matches` reports `sweeps_on` so a client can
  see the trigger kinds, but nothing reports the swept observable TYPES.
- **No pagination.** Newest-first with `limit` ≤ 200. A workspace with a long
  trail cannot page to older events; they are reachable only by narrowing
  `status`. Same shape as the S12 top-20 cap (TD-016).
- **Cycle path not driven end-to-end** (narrowed at S15 Step 0). The sink is
  pinned as WIRED by `test_the_scheduler_is_wired_to_the_retrohunt_sink`, and
  the sweep is live-verified end-to-end
  (docs/probes/2026-08-09-s14-retrohunt-live.md), but the probe called `emit`
  directly rather than waiting for an ingest cycle to call it. Observing that
  needs CISA to publish a KEV entry for a CVE this workspace has already
  enriched — not schedulable within a session.
  The **cost** half of this bullet is now closed by measurement
  (docs/probes/2026-08-09-s15-step0-review.md): the worst case named in the S14
  review — a KEV first-run refresh of 1,600 ids where every id matches a held
  observable — costs **175 ms** inside `run_cycle` (16 ms for 32 swept chunks,
  159 ms for 1,600 match inserts), and 96 ms when the same batch is re-emitted
  and written off as already-known. Against a cycle that paces NVD single
  fetches at seconds apiece, that is not on the critical path, so the TD-008
  precedent (move it off the cycle) is NOT warranted.
**Why accepted:** S14's scope was the reasoning/event core (the sweep, the
honesty rail, the flip trail). Type coverage is one line plus a per-type test
once a non-CVE feed exists; pagination is surface work with no design question
in it.
**Path to fix:** (a) widen `SWEEPABLE_TYPE` to a set when the first non-CVE feed
lands, and report swept types alongside `sweeps_on`; (b) keyset pagination on
`(created_at, id)` for both collections, shared with the S12 collection view
when that arrives; (c) assert the cycle path by driving `run_cycle` against a
fake KEV feed whose catalogue contains an enriched CVE — hermetic, and it closes
the gap without waiting on CISA.

## ~~TD-018 (S13) — inference-spending routes have no per-workspace bound~~ RESOLVED S19
**Resolved 2026-08-15 (D-026):** `auspex/limits.py` + the `usage_counters`
table. A per-workspace inference-CALL ceiling is claimed by a conditional UPSERT
that enforces the limit in the same statement that reads the counter — raced with
eight concurrent claims over one unit of headroom, exactly one wins. **Both routes
this entry named are wired**, sharing one counter (the ceiling belongs to the
workspace's inference, not to a route): `/api/chat` DEEP turns claim 1 or **2**
(a two-pass endpoint really makes two requests — D-016/TD-002), and
`POST /api/investigations/{id}/summary` claims 1. Refusal is a 429 naming the
meter, the ceiling and the reset time, and the LLM-free paths keep working because
the claim happens after the 92/8 gate. Plans live on the workspace, limits in
code, unknown plan ⇒ most restrictive. Regressions in `tests/test_limits.py` and
`tests/test_hardening_surface.py`. Original entry kept below for the record.

## TD-018-original (S13) — inference-spending routes have no per-workspace bound
**Where:** `POST /api/investigations/{id}/summary` (new in S13) and
`/api/chat` DEEP turns both call the customer's LLM endpoint with no
per-workspace rate/spend ceiling — any authenticated client can loop them.
**Risk:** a runaway or hostile client burns the customer's inference quota
(D-005 means it's THEIR endpoint bill) and can degrade the endpoint for
real analysts. Low today (dev, single tenant); real at beta.
**Why deferred:** S13 scope was citations; rate limiting is an S19
(Hardening) roadmap line — this entry pins the specific routes so S19
doesn't miss the non-chat one.
**Path to fix:** per-workspace token/request budget checked before the LLM
call (Postgres counter, honest 429 with the budget named), shared by chat
and summary; S19 already owns "rate limits".
**Narrowed in S14 Step 0 (still open):** the per-CALL amplification is gone,
which was the part specific to the summary route. The directive grew with the
evidence count — 200 rows (reachable: `_MAX_SNAPSHOT_IOCS=200` observables can
each fold one enrichment answer) compiled a 54k-char / ~13.5k-token directive
against the ~1.2k-token norm, i.e. one request costing 10x, with the pin
instruction sitting on the LAST line where a context-capped endpoint drops it
first. `_MAX_DIRECTIVE_EVIDENCE=40` + `_MAX_BEARING_PER_HYPOTHESIS=12` now hold
it flat at ~3k tokens (measured: 50 rows and 200 rows both compile ~12.1k
chars), and the truncation is named to the model and to the analyst
(`evidence_shown`/`evidence_total`). What remains is the original entry: no
bound on the NUMBER of calls, on either route.

## TD-017 (S13) — NUL-byte hardening exists only at the investigations paste boundary
**Where:** `auspex/routes/investigations.py` strips U+0000 before parsing
(S13 Step-0 review finding 1, live-verified 500 — Postgres text/jsonb cannot
represent NUL). Any OTHER route that persists request text is still exposed:
`/api/chat` writes the message to `messages` (and an email/alert paste there
takes the same parse-and-persist shape).
**Risk:** a NUL-carrying paste to chat 500s mid-session instead of degrading
honestly; noise in logs, confusing UX, and a trivially scriptable error shape.
**Why deferred:** S13 Step-0 scope was the S12 diff; chat predates it. One
concern per commit.
**Path to fix:** strip NUL centrally where request text first crosses into
persistence (a shared sanitizer used by ChatBody/CreateInvestigationBody
handling, or a pydantic validator both bodies share), plus one live-shaped
regression per route. Verify the chat 500 by execution first — same drill.

## TD-016 (S12) — ACH v1 surface bounds: top-20 ranked cap, no list/close endpoints, no lookup-attempt backoff
**Where:** `auspex/ach/gain.py` (`_MAX_RANKED = 20`), `auspex/routes/investigations.py`
(no `GET /api/investigations` collection, no way to set `status='closed'` —
the column exists in the schema ahead of its surface, the proposals-table
precedent), the `/lookups` route (retry of a never-completed lookup re-fans-out;
bounded only by the S5 circuit breaker, no per-obs attempt ledger).
**Risk:** low. The caps are NAMED in the response (`total_candidates`,
`iocs_truncated`) so nothing is silently hidden, but `body.obs_id` can only
run a candidate inside the surfaced top-20, an investigation can never be
closed, and a determined client can re-trigger provider fan-outs during an
outage window (each bounded by the breaker's 3-failure/60 s cycle).
**Why accepted:** v1 scope was the reasoning core (D-019); pagination, a
collection view, lifecycle, and an attempt ledger are surface work with no
open design questions.
**Path to fix:** pagination params on the ranked plan; `GET` collection +
`PATCH status`; a per-(investigation, obs_id) attempt timestamp to back off
re-fan-outs. Trigger: the first UI work over investigations, or S14 retro-hunt
needing the collection view.

## TD-015 (S11) — phishing deterministic layer uses heuristic coverage (brand list, confusable set)
**Where:** `auspex/phishing/brands.py` (`BRAND_ALLOWLIST` ~44 brands),
`auspex/phishing/lookalike.py` (`_CONFUSABLES` a high-frequency Cyrillic/Greek
subset; `_MULTI_LABEL_SUFFIXES` a curated compound-suffix set).
**CORRECTED in the S12 review — the original entry was wrong on two counts, both
verified by execution:** item (c) (naive last-two-labels `registrable_domain`)
was NOT false-negative biased and is now FIXED, not accepted. It produced false
POSITIVES: `amazon.co.uk` read as registrable domain `co.uk`, so a genuine,
fully auth-passing Amazon UK mail scored 35 → SUSPICIOUS (brand-subdomain bait
+20, display-name brand +15), and every ccTLD brand in the list behaved the same.
It also *suppressed* indicators rather than only under-detecting: with a victim
on `acme.co.uk`, every `.co.uk` observable matched the victim's registrable
domain, so attacker infrastructure was withheld from the analyst. The blanket
claim "none can produce a FALSE MALICIOUS or leak a victim IOC — they only
under-detect" did not hold and has been removed. Fix: `_MULTI_LABEL_SUFFIXES` +
`is_brand_host` (commit dd67f6e).
**Remaining risk (genuinely false-negative biased):** (a) a lookalike of a brand
not on the list isn't caught; (b) a homograph using a confusable outside the
curated set folds to itself and isn't flagged; (c') a compound suffix outside
the curated `_MULTI_LABEL_SUFFIXES` set still degrades to the last-two-labels
reading — a miss, and no longer a false alarm on the suffixes real mail uses.
**Why accepted (not a bug):** ships the SARA-proven deterministic pre-check
(docs/probes/2026-07-18-sara-phishing-header-patterns.md) that catches the
common credential-harvest shapes; the LLM narrative layer sees the raw domain
and can still flag what the deterministic layer missed (it just can't LOWER the
floor). Absence/uncertainty already biases to DEFERRED, never BENIGN.
**Path to fix:** (1) fold the brand list into a configurable/data-file source if
customers need per-tenant brands (decide env-var vs file then — none needed
today, it's a code constant); (2) adopt a fuller Unicode confusables map
(UTS-39 skeleton) if homograph FNs show up; (3) DONE in S12 — compound suffixes
are handled by the curated `_MULTI_LABEL_SUFFIXES` set; adopt the real
Public Suffix List (a dependency + refresh story) only if a suffix outside the
curated set shows up in practice. Trigger: a real missed lookalike/homograph in
a customer email, or a compound-TLD domain outside the curated set. Add the
offending email as a fixture then.

## TD-013 (S9 review) — attacker-authored paste rides the trusted `user` lane in triage/phishing modes
**Where:** `auspex/routes/chat.py` `_history` (user turns replay UNfenced, `:290`)
+ the current turn's `body.message` stored as `role="user"` (`:334`), against the
S9 resolver routing pasted content into ALERT_TRIAGE / PHISHING_ANALYSIS
(`auspex/modes/resolver.py` `_is_alert_paste` / `_is_email_paste`).
**Risk:** the TD-009 fence guards ASSISTANT (feed/KB) turns, but a pasted phishing
email or alert IS attacker-authored and lands in a `user` message, which the
fence directive explicitly declares trusted ("the user's own messages issue
instructions"). An injection inside a pasted email body ("ignore all previous
instructions…") is therefore replayed unfenced, on this turn and every later deep
turn of the session. Blast radius today is answer manipulation only (no tools
wired into chat); it becomes real capability the day S3 proposals / S9 modes
execute — same escalation profile as TD-009.
**Why deferred:** the correct fix is not to fence the whole user turn (the model
must SEE the paste to analyze it) but to route the paste through structured
parsing so raw attacker text never enters the instruction stream as free prose.
**Alert path MITIGATED in S10 (partial):** the alert normalizer parses
CEF/LEEF/syslog/JSON into a typed closed-vocab envelope (code-owned, no LLM) and
the additive scorer computes the Risk level in CODE; alert_triage renders the
AUTHORITATIVE code verdict, not the raw paste — so an "output Risk CRITICAL"
injection inside an alert can't move the level (pinned:
tests/test_chat_sse.py::test_alert_triage_deferred_rail_and_injection_resistance).
The paste text is still visible to the model, but it no longer *decides* the
outcome for alerts.
**Phishing path MITIGATED in S11 (`auspex.phishing`):** a pasted email is parsed
in CODE (regex header parse → typed EmailEnvelope), auth/spoof/lookalike findings
are computed deterministically, and the Verdict FLOOR is decided in code;
phishing_analysis renders the AUTHORITATIVE verdict, and the validator pin (an
ALLOWED SET — floor + permitted raises) means the model can raise on content it
reads while any launder below the floor is DETECTED. Corrected in the S12 review
(honesty lens): the pin does not make laundering impossible — validation is
post-hoc (TD-012), so a laundered answer streams to the user and is persisted,
with `contract_valid:false` as the record. What is structural is that the
DISPOSITION is computed from parsed headers only. Pinned:
tests/test_chat_sse.py::test_phishing_verdict_cannot_be_laundered_below_the_floor
(a body that says "this is legitimate" cannot pull a MALICIOUS floor to BENIGN).
Live-verified on Scout (docs/probes/2026-07-18-s11-phishing-live.md).
**Residual (both triage + phishing paths):** the raw paste is still VISIBLE to
the model in the `user` turn (it must be, to narrate), and on later turns it
replays unfenced (the `_history` gap). What changed is that the paste no longer
*decides* the outcome — code does, and the pin enforces it. The standing gap is
now only free-prose narration manipulation (the model could still be talked into
misleading *prose* around a correct pinned verdict); the disposition itself is
code-owned for both alert and phishing modes. Consider fencing replayed user
paste-turns if/when the DEEP path executes tools (the TD-009 escalation profile).

## TD-014 (S9 review) — deep-turn history fetch is unbounded (no turn/token cap)
**Where:** `auspex/routes/chat.py` `_history` — `SELECT role, content FROM messages
WHERE workspace_id=$1 AND session_id=$2 ORDER BY created_at` has no LIMIT; every
deep turn replays the ENTIRE session (born S3, pre-dates S9).
**Risk:** a long-running investigation session grows the prompt without bound —
rising latency/cost and eventual context-window overflow (surfaces as an
`LLMError` → SSE `error` frame, or silent truncation depending on the endpoint).
The two-pass fallback (the safe default) sends the whole history TWICE per turn
(TD-002), doubling the exposure. `ChatBody.message` is capped at 32k chars but
history is N turns of that.
**Why deferred:** picking the cap policy (last-N turns vs a token budget vs a
summarize-and-drop) is a design choice with its own trade-offs, and it's
pre-existing (not S9 feature work) — out of the S9-review fix scope.
**Path to fix:** cap replayed turns in the `_history` SELECT (last-N or a token
budget), oldest-first, keeping the system prompts + fence directive always.

## ~~TD-009 (S8 review) — feed-derived KB text replays into deep-turn LLM context unfenced~~ RESOLVED S9
**Resolved 2026-07-18 (dba5aec):** `_history` now fences prior ASSISTANT turns
as `⟦DATA⟧…⟦/DATA⟧` blocks and adds a system directive declaring nothing inside
a fence is an instruction; embedded fence markers in stored text are neutralized
so a poisoned turn can't close the fence early. User turns replay unfenced (the
human's own input). Regression tests: an instruction-bearing feed description is
fenced on replay, and a break-out attempt via embedded markers is defanged
(tests/test_chat_sse.py). Containment (a poisoned turn can't break out of the
fence) is structural/code-owned; inertness (the model ignoring fenced directives)
is a strong prompt-level defense, not a structural guarantee — the residual
attacker-influenceable-text-in-the-instruction-stream gap is TD-013. Original
entry kept below for the record.

## TD-012 (S9) — mode contract validation is post-hoc/observability-only
**Where:** `auspex/routes/chat.py` `event_stream()` — `contract.validate(answer)`
runs after the answer has streamed; the `done` frame reports `contract_valid`
but a non-conforming answer is NOT re-asked or repaired.
**Risk:** a deep turn whose model output ignores the mode contract (missing
sections, out-of-enum risk value) still reaches the user; only the done frame
flags it. Low blast radius today — contracts shape prose sections, and the
highest-stakes rule (alert_triage DEFERRED) is reinforced by the compiled
directive, live-verified to hold on Scout.
**Why deferred:** a repair loop (re-ask once on `not result.ok`, or a
single-shot structured re-emit) is its own change with latency/cost trade-offs,
and streaming means the first attempt can't be un-sent — the clean fix is to
validate a non-streamed structured pass for modes that need hard guarantees
(uses the scorecard's `json_schema_mode`).
**Path to fix (S10+):** for structured-critical modes (alert_triage,
phishing_analysis), request a non-streamed structured output when the endpoint
advertises `json_schema_mode`, validate before emit, re-ask once on failure;
keep the streamed prose path for the narrative modes.

## TD-009 (S8 review) — feed-derived KB text replays into deep-turn LLM context unfenced
**Where:** `auspex/kb/echo.py` (rendered verbatim into `answer_text`) →
`auspex/routes/chat.py` (`_insert_message` … `_history` → `chat_stream`).
**Risk:** a poisoned NVD/KEV description carrying instructions lands in the KB,
renders into a stored assistant message (honest so far — analysts should see the
source text), and then rides EVERY later deep turn of that session as
assistant-role context — a persisted prompt-injection channel from feed to
model. Blast radius today is answer manipulation only (no tools wired into
chat); it becomes real capability the day S3 proposals/S9 modes execute.
**Mitigation shipped in S8:** descriptions cap at 20k chars at parse
(`kb/seed.py::MAX_DESCRIPTION_CHARS`).
**Why deferred:** the correct fix is data-vs-instruction fencing of replayed
history (SARA's instructions-in-system/data-in-user pattern) — that is S9
agent-loop architecture, not an ingest patch.
**Path to fix (S9, WITH the modes work):** mark feed/KB-derived spans in stored
messages; on deep turns, replay them fenced (system-side "quoted data, not
instructions" wrapper or user-role data blocks), and add a regression test with
an instruction-bearing description.

## TD-010 (S8 review; scope grew S9 review) — feed HTTP responses have no byte ceiling (decompression bomb)
**Where:** `auspex/ingest/kev.py` (1.5 MB gzip → httpx transparent inflate),
`auspex/ingest/nvd.py`, `auspex/ingest/epss.py`, **and `auspex/ingest/attack.py`
(S9 review, security lens: `latest_version` reads the 31 KB index EVERY cycle
and `fetch_objects` reads the 53 MB bundle — both `resp.json()` on an unbounded,
gzip-inflatable body)** — all read the full body before any size check.
**Risk:** a compromised origin/CDN (TLS is verified, URLs are constants — this
requires upstream compromise) serves a small gzip inflating to multi-GB;
httpx inflates fully into memory. **Severity note (S9 review, ops lens):** the
app container has NO `mem_limit`/`deploy.resources` in docker-compose.yml, so
there is no *compose-limit* OOM; a bomb is bounded only by host RAM (a real
61 MB STIX payload measured ~174 MB peak RSS). Still a host-exhaustion vector,
and the ATT&CK bundle is the largest designed fetch.
**Why deferred:** the real fix is streamed reads with an inflated-bytes cap on
all four clients — mechanical but cross-cutting, and the page-cap +
content-cap work (the assembled-content cap, S9 review, closed the `extras`
bypass) already bounds the *parsed* blast radius. Upstream compromise of
CISA/NVD/FIRST/GitHub is a low-likelihood, high-noise event.
**Path to fix:** shared `bounded_json(resp_stream, max_bytes)` helper
(`client.stream()` + `iter_bytes()` counting DECOMPRESSED bytes, abort past
cap: KEV 50 MB, NVD 200 MB/page-call, EPSS 5 MB, ATT&CK index 4 MB / bundle
128 MB), MockTransport bomb tests. Consider a compose `mem_limit` on the app
container as defense-in-depth.

## TD-011 (S8 review) — auspex-knowledge grows unbounded (no rollover/retention)
**Where:** the single `auspex-knowledge` index; growth ~770 docs/day (~5k/week)
while the container runs (STATE.md host notes).
**Risk:** months out, the HNSW graph + segment volume outgrow the 1 GiB
single-node heap: slower searches, then allocation failures. No tracked
trigger existed — only a "watch RSS/disk" note.
**Why deferred:** at ~2.5k chunks the index is far from pressure; rollover
design (ISM policy vs dated indices vs retention-by-doc_type) deserves its own
session with real growth data.
**Trigger to act:** >150k chunks OR OpenSearch RSS >70% of its 1 GiB heap OR
p95 search latency >500 ms (check via `_cat/indices` + `docker stats` at
session starts).
**Path to fix:** ISM rollover on the `auspex-*` prefix or per-doc_type
retention (CVEs decay by lastModified; curated docs never expire).

## TD-007 (S6 review) — BM25-only degrade can surface weak matches during neural outages
**Where:** `auspex/kb/service.py::search` (neural-leg *unavailability* branch).
**Risk:** when the neural leg is down (no model), free-text queries serve
BM25-only results. The `minimum_should_match: 2<75%` damping and the relative
floor gate most noise, but an off-corpus query CAN surface a weak lexical match
labeled as a KB answer with a source line — the fixed live bug (7446fbc) only
covers neural-ran-and-disagreed, not neural-couldn't-run.
**Why accepted:** deliberate degradation (docstring service.py; STATE.md S6):
during an outage a mostly-right lexical answer beats a blanket miss, and the
outage window is now bounded by the 60 s model-lookup retry (S6 review fix).
**Path to fix:** fold into the TD-005 calibration (S8) — a labeled query set can
decide whether BM25-only needs its own absolute floor.

## ~~TD-008 (S6 review) — KB bootstrap runs inline in app lifespan~~ RESOLVED in S7 (same day)
**Resolved 2026-07-17 (96e42df):** the S7 ingest scheduler runs as a background
startup task and owns the KB bootstrap — lifespan yields immediately, the port
binds before bootstrap, and KB turns during warm-up get the honest "didn't
answer this turn" copy. Worst-case bootstrap latency no longer intersects the
compose healthcheck window at all.

## TD-001 (S1) — OAuth identity keyed on email, not Google `sub`
**Where:** `auspex/auth.py` `get_or_create_user` (matches users by `(workspace_id, email)`).
**Risk:** For OAuth logins the immutable Google `sub` is stored but never compared to
the incoming one. Two takeover paths *once real OAuth is live*: (a) corporate email
recycling — a reissued address logs in and matches the prior holder's row; (b) first-bind —
a dev-login-created row (google_sub NULL) gets silently bound to whichever Google
account first presents that email.
**Why deferred:** OAuth is config-stubbed (503 until a client ID exists), so this is
not reachable today. The S1 `email_verified` check closes the unverified-email takeover.
The correct fix (look up by `sub` first; refuse to link when an email-matched row has a
different non-NULL `sub`) changes the provisioning contract and deserves its own focused
change with tests.
**HARD GATE:** must be fixed *before* any `GOOGLE_CLIENT_ID` is configured in any
environment. Raised by the S1 adversarial review (2/2 verifiers confirmed).

## TD-002 (S3/D-016) — two-pass reasoning doubles LLM calls for non-native endpoints
**Where:** `auspex/routes/chat.py` `event_stream()` two-pass branch.
**Risk:** endpoints without native reasoning (Scout, most instruct models) make
TWO endpoint calls per chat turn (reasoning pre-pass + answer) → ~2× latency and
token cost on those turns. This also affects the **prod default** endpoint until
it has a persisted scorecard row (unknown ⇒ `native_reasoning=False` ⇒ two-pass).
**Why accepted:** the visible reasoning trace is a deliberate product feature
(D-016); two-pass is the reliable way to produce it on any endpoint. Native
endpoints (qwen3) keep the single-call path, and once a default endpoint is
probed its scorecard flips it to single-call automatically.
**Path to fix:** (a) ensure the default endpoint is probed on connect so its
`native_reasoning` is known (avoids needless two-pass); (b) optionally cache/skip
the pre-pass for short/conversational turns (92/8, S4); (c) a single-pass
`<thinking>`-tag variant could halve cost for endpoints that reliably honor it.

## TD-006 (S6) — KB bootstrap has no multi-replica guard
**Where:** `auspex/kb/service.py::bootstrap` (model register/deploy, seed ingest).
**Risk:** two app replicas booting against one fresh OpenSearch volume could
double-register the embedding model (harmless but messy) or double-seed (benign —
chunk-id upserts). Zero risk in today's single-replica compose.
**Why deferred:** no multi-replica deploy shape exists yet; inventing a lock for it
now would be speculative.
**Path to fix:** advisory lock (Postgres `pg_advisory_lock`) or find-before-register
double-check with jittered retry, added when a second replica becomes real.

## ~~TD-005 (S6) — NEURAL_MIN_SCORE=0.6 calibrated on a 3-point sample~~ RESOLVED S8
**Resolved 2026-07-18:** per-doc_type floors calibrated against the live
3,417-chunk corpus with a 14-query labeled battery
(docs/probes/2026-07-18-td005-calibration.md): curated 0.65 (noise ceiling
0.618 vs weakest relevant 0.691), cve 0.70 (0.624 vs 0.766), default 0.6 for
future types. The battery re-caught the fabrication LIVE the same day
("quantum entanglement" → T1090.002 at 0.617 after ATT&CK grew the curated
pool) before it could ship. Operating point regression-pinned in
tests/test_kb_fuse.py — each boundary row names the live query that breaks
if a constant moves. **Standing trigger to re-run the battery:** corpus
> 30k chunks, any new doc_type, or an embedding-model change.
Original entry kept below for the record.

**S19 (2026-08-15) — the size trigger FIRED and the battery was re-run.**
Corpus 3,417 → **31,819** chunks (9.3×), same embedding model, same doc_types.
Record: docs/probes/2026-08-15-td005-rebattery.md. **Both floors verified sound
by measurement, and nothing fabricates** — all four off-corpus queries still
return an honest miss through the real `search()` path.
- **curated 0.65:** gap `[0.6184 .. 0.6905]` vs S8's `[0.618 .. 0.691]` — the
  pool is structurally bounded and barely moved. Recall 7/7 in the leg.
- **cve 0.70:** gap `[0.6563 .. 0.7660]`. Noise ceiling rose 0.624 → 0.6563 as
  that pool grew 15× (2k → 30.5k chunks); headroom fell 0.076 → **0.0437**.
  Still holds, and the floor is **dormant in v1** — no shipped surface reaches it
  (CVE questions take the exact-ID rail; definitions filter to the curated pool).
- S8's "growth is flattening logarithmically" claim **confirmed across a 9× jump**
  (~0.023/ln-unit early vs ~0.0145 for the 3.4k→30.5k leg).
- **Trigger refreshed** so it can fire again: cve pool > 300k chunks, curated pool
  > 5k chunks, any new doc_type, any embedding-model change, or **before any
  free-text-over-CVEs surface ships** (see TD-027).
- The re-battery also surfaced a defect TD-005 was never scoped to catch — the
  battery labeled the neural *leg*, never the fused top hit users actually read.
  Logged as **TD-026**.

## TD-005-original (S6) — NEURAL_MIN_SCORE=0.6 calibrated on a 3-point sample
**Where:** `auspex/kb/fuse.py::NEURAL_MIN_SCORE` (the pre-fusion absolute floor that
turns off-corpus queries into honest misses).
**Risk:** calibrated against one probed pair (relevant 0.695 / unrelated 0.498) plus
one live query (0.586) on a 14-chunk corpus. A bigger corpus or oddly-phrased but
legitimate queries could false-miss (annoying, self-healing via the deep path) or a
semantically-adjacent-but-wrong doc could clear 0.6 (worse). Errors currently bias
toward the honest miss, per the S4 rule.
**S7 spot-check (2026-07-17, ~2 500 chunks) CONFIRMED both failure modes for
UNFILTERED search** — plus an HNSW recall collapse at k=10 the original entry
didn't predict (docs/probes/2026-07-17-s7-ingest-live.md). The definition
shortcut is now structurally safe (doc_types filter ⇒ exact kNN over the
curated subset), so no user-facing path currently depends on the unfiltered
floor — but S8's free-text-over-CVEs search will.
**Why deferred:** a defensible threshold needs a labeled query set, which needs the
real S7/S8 corpora (now materializing).
**Path to fix (S8, before any unfiltered free-text surface ships):** labeled
relevant/irrelevant query fixtures from live probes; calibrate per-doc_type
floors AND neural-leg k/ef sizing together (recall and floor interact);
regression-pin the operating point.

## ~~TD-004 (S5) — URLhaus / ThreatFox / AbuseIPDB happy paths are docs-coded, not probe-verified~~ RESOLVED same day
**Resolved 2026-07-16 (evening):** Burhan registered both keys; all three happy paths
probed live (docs/probes/2026-07-16-keyed-providers-live.md). Docs-coded shapes were
correct except one trap the probe caught: URLhaus `/v1/payload/` returns
`query_status:"ok"` for ANY bytes ever served from a listed URL — including empty
failed downloads — so the parser gained a `file_size == 0 ⇒ no signal` guard and a
signature-null ⇒ SUSPICIOUS (not MALICIOUS) downgrade, with pinned live fixtures.
Also measured: heavy payload hashes 504 server-side (~60 s; the 6 s cap handles it),
`url_count` is int on /host/ but string on /payload/.

## TD-003 (S4) — SSE/test helpers duplicated across test files
**Where:** `_frames()` + `_token()` in `tests/test_chat_sse.py` and
`tests/test_models.py` (near-identical `_dev_token` in `tests/test_auth.py`).
**Risk:** an SSE protocol change (e.g. `event:` lines) fixed in one copy lets the
other file's parser silently drop frames and pass on a broken stream.
**Why deferred:** pre-existing before S4; moving them to `conftest.py`/`_fakes.py`
touches three test files and deserved its own change, not a rider on the 92/8 work.
**Path to fix:** hoist both into `tests/_fakes.py` (FORBIDDEN_ENGINE_NAMES already
moved there in S4) and import everywhere; delete the copies.
**Grew in S6:** `tests/test_chat_kb.py` added another copy of `_frames`/`_token`/
`_use` (now 3 SSE-parser copies + 2 token helpers). Same fix, more call sites.

## TD-029 (S20) — `workspaces.plan` has no CHECK constraint, so a typo silently downgrades
**Where:** `auspex/migrations.py:512` (`ADD COLUMN ... plan text NOT NULL DEFAULT
'free'`), read by `auspex/limits.py:91` `plan_for`.
**What was verified (S20 Step 0):** `plan_for` is sound — all ten hostile inputs
(`None`, `''`, `'   '`, `'Enterprise'`, `'ENTERPRISE'`, `'enterprise '`,
`' enterprise'`, `'enterprise\n'`, `'free; DROP TABLE'`, `'legacy_gold'`) resolve to
`free`, and no path reaches a more generous tier. The security direction holds.
**Risk:** the *availability* direction. Nothing constrains what may be written to
the column, so `UPDATE workspaces SET plan = 'enterprise '` (trailing space) leaves
a paying customer silently capped at 100 calls/hour with only a `logger.warning` to
say so. Fails safe, fails quiet — and the quiet is the problem once a plan is
something a human sets.
**Why deferred:** correctly restrictive today, and a CHECK constraint has to be
written against the tier list the commercial model settles on, which does not exist
yet (D-026: `PLANS` is explicitly a seam, nothing is sold).
**Path to fix:** either a `CHECK (plan IN (...))` migration generated from `PLANS`,
or — better, since the tier list is code and the constraint would drift from it — a
startup assertion that every distinct `workspaces.plan` value resolves to itself
under `plan_for`, logged loudly at ERROR. Cheap either way; do it when a plan
becomes settable by anything other than SQL.

## TD-030 (S20) — a failed or abandoned turn is charged in full, and there is no refund seam
**Where:** `auspex/routes/chat.py:504-517`, `auspex/routes/investigations.py:464`.
**Measured (S20 Step 0):** claim happens before the call; forcing an endpoint
failure after the claim gives `claimed=2 charged=2 for 0 inference received`.
`UsageLimiter` has no `release`/`refund`/`unclaim` method. A client that
disconnects mid-stream is charged identically.
**This is RATIFIED behaviour, not an accident** — D-027 decided to keep it, because
refund-on-failure means a failing endpoint costs a workspace nothing (the retry
storm the ceiling exists to bound), and an up-front claim of the full turn cost is
what lets a turn either run completely or be refused cleanly instead of being cut
off mid-answer at 99/100.
**Residual risk it is logged for:** during a sustained endpoint outage a workspace
can burn its entire hourly ceiling receiving nothing, and the 429 it then gets says
"you reached your limit" when the truthful sentence is "our endpoint is down and you
were charged for it." The refusal copy cannot currently tell those apart.
**Path to fix (costed, deliberately not taken):** a `settled` counter alongside
`used`, incremented when a turn actually produces content, plus refusal copy that
reads the gap between them and names an outage when `used - settled` is large. One
column, one UPDATE in the stream's `finally`, one branch in `refusal_text`. Do it
when the platform runs against an endpoint whose uptime we do not control — i.e. the
first real customer deployment.
