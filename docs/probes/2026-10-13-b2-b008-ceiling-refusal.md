# B-008 — a turn refused at the usage ceiling left its question behind (B2)

_2026-10-13, B2. F2 found it by reading the code, never live. Fixed in
`4680bf6`, on Burhan's call: discard on refusal, rather than reorder the
route._

## Reproduced at the route (before the fix)

The deep path stores the session and the question (`auspex/routes/chat.py`,
`_ensure_session` and `_insert_message`) BEFORE the usage claim. A refused
claim then raises 429, which carries no session frame.

Two tests drive `/api/chat` with a limiter that refuses the turn's first
claim (`tests/test_chat_sse.py`, `test_b008_…`). On the pre-fix code both
failed:
- **A new chat:** the chat list grew by one, a chat the page never learned
  the id of. The question was stored.
- **An open chat:** the refused question was stored under the chat's answered
  turn.

## The fix

On a refusal, `_discard_refused_turn` deletes exactly what this turn stored:
- the question, by its id;
- the chat, only if this turn created it and nothing else is in it.

Three mutants, 3 caught: no discard; the question but never the chat; the chat
always, without the emptiness guard. `./ci.sh` green at 1385 tests.

## Live, after the fix (`b2-b008/probe_live_ceiling.py`, `raw-live-after.log`)

Reaching the ceiling honestly would spend about 100 calls. Instead the probe
set this hour's `inference_calls` counter for `default` to the plan's limit
(100), made two refused turns through the running container, and put the
counter back exactly (5 → 5). No inference call was made.

| turn | HTTP | question stored | chat list grew |
|---|---|---|---|
| A: a new chat, deep question | 429 | 0 | 0 |
| B: an open chat (from an unmetered IOC check), deep follow-up | 429 | 0 | 0, and the chat still holds its `user, assistant` turn |

The 429's detail is the limiter's own sentence: "This workspace has reached
its limit of 100 inference calls per hour (100 used). It resets at 09:00 UTC.
Analysis that does not need the reasoning engine — IOC checks, CVE lookups
and definitions — keeps working." The page shows server errors in the
server's own words (F2).

**No live before-run.** `./ci.sh` rebuilds the running app container
(`ci.sh:26`), so by the time the probe ran the container already carried the
fix. The route tests are the reproduction.
