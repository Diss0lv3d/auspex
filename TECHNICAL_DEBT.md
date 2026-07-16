# Technical debt — logged the moment it's taken

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

## TD-004 (S5) — URLhaus / ThreatFox / AbuseIPDB happy paths are docs-coded, not probe-verified
**Where:** `auspex/enrich/providers/{urlhaus,threatfox,abuseipdb}.py` + their fixtures in
`tests/test_enrich_providers.py` (marked `docs-coded`).
**Risk:** these providers are key-gated and no keys exist in `.env` yet, so only their
*error* shapes (401) were live-probed (docs/probes/2026-07-16-enrichment-providers.md).
The 200-shapes come from official docs fetched the same day. If the real shape drifts
from the docs, the parsers raise ProviderError / return no signal (fail-SOFT by
construction — `query_status` guards, defensive `.get()`s), so the failure mode is a
missing verdict + "source unavailable", never a fabricated verdict.
**Why accepted:** registering API keys is a human step (auth.abuse.ch account,
abuseipdb.com account); coding against fetched docs + soft-fail guards was the honest
maximum for an autonomous session.
**Path to fix:** Burhan registers the two free keys → `/probe` each provider's happy
path live → replace the docs-coded fixtures with real trimmed bodies → drop this entry.

## TD-003 (S4) — SSE/test helpers duplicated across test files
**Where:** `_frames()` + `_token()` in `tests/test_chat_sse.py` and
`tests/test_models.py` (near-identical `_dev_token` in `tests/test_auth.py`).
**Risk:** an SSE protocol change (e.g. `event:` lines) fixed in one copy lets the
other file's parser silently drop frames and pass on a broken stream.
**Why deferred:** pre-existing before S4; moving them to `conftest.py`/`_fakes.py`
touches three test files and deserved its own change, not a rider on the 92/8 work.
**Path to fix:** hoist both into `tests/_fakes.py` (FORBIDDEN_ENGINE_NAMES already
moved there in S4) and import everywhere; delete the copies.
