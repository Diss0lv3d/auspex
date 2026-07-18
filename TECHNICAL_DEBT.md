# Technical debt — logged the moment it's taken

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
**Still open:** phishing_analysis has no normalizer yet — a pasted email body is
still free attacker prose the model reasons over directly. Same treatment when
phishing_analysis grows its own parser; add an instruction-bearing pasted-email
fixture then.

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
