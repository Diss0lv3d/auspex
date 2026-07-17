# Technical debt — logged the moment it's taken

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

## TD-005 (S6) — NEURAL_MIN_SCORE=0.6 calibrated on a 3-point sample
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
