# Review: the agent path wired into /api/chat (S26)

- **Date:** 2026-10-10
- **Scope:** `39f1afc` (TD-036 hold), `1803253` (aclosing), `1b86070` (route),
  `44a040e` (UI).
- **Method:** two independent adversarial reviewers, one on the loop and one on
  the route and UI. Both were read-only and could run hermetic scripts against
  the fakes, but not pytest, the app or any live endpoint. Every finding below
  was reproduced by the reviewer's own script output before it was reported.
  Every fix shipped with a regression test that failed first.
- **Core verdict (route reviewer):** every frame goes through the rail before it
  is emitted, a leak is never persisted, usage claims equal the calls made, and
  tenant scoping holds. The defects were all at the edges.

## Fixed

| finding | severity | commit |
|---|---|---|
| A tool call AFTER the hold released did not mark the step, so prose after the call streamed as answer | Low | `771cc49` |
| The hold is native-only; prompted tool tags arrive in content (unreachable from the route) | Low, latent | `6a9b67d` (documented) |
| A whitespace-only agent answer (`empty_answer`) was persisted and contract-validated | Low | `4bd65a9` |
| Tool frame: NaN or an object argument made the step vanish in the page; the page ordered keys differently from the scan (a split run of our configuration was shown whole); keys were sent unscanned | Low–Med | `df761a1` (the server renders the line, scans exactly it, and the page shows it verbatim) |
| The per-call enrichment cap let one turn drive hundreds of third-party lookups (up to 9 calls × 8) on provider keys and breakers every tenant shares | **Medium** | `76be482` (turn budget = the shortcut path's per-turn bound) |
| The current message was stripped from history by content, so a concurrent turn in one session made it go out twice | Low | `4693329` (by row id; the session is still read once, before `resolve()`) |
| Arguments nested ~10k deep raised RecursionError, which nothing caught, so the turn died with no frame | Low | `ef66c7a` (`parse_arguments` keeps its ValueError contract) |
| The agent-turn log listed model-invented tool names | Low | `96ce09e` |

## Recorded, not fixed

- **TD-038:** the rail does not index the tool descriptions or the synthesis
  nudge. Indexing them needs the SHINGLE_WORDS calibration re-run first.
- **TD-039:** D-037 clause 1 covers only the modes the resolver recognises. A
  BRIEF of an attacker paste can steer tool arguments. This is a design call for
  Burhan.
- **TD-040:** the provider's error body reaches the analyst verbatim, which is a
  brand-rule risk. It predates S26.
- **TD-037 consequence:** nothing in a non-dev deployment writes the scorecard,
  so the agent path is unreachable outside dev.
- **Won't fix (loop F2):** whitespace-only narration deltas after a call are
  forwarded. Filtering them per delta would glue words together ("I'll" + " " +
  "check").
- **UX, noted:**
  - an `empty_answer` turn gets no explanation on either path;
  - the page prefixes the usage refusal and LEAK_COPY with "[endpoint error]";
  - narration is appended to the Thinking pane with no separator (glm's own
    narration begins with a newline);
  - `done.usage` sums every usage event, which would over-count on an endpoint
    that streams cumulative usage per chunk. Z.ai sends usage once.
- **Doc drift:** D-031 decision 4 says a mid-loop refusal "synthesises from what
  was gathered". The loop and the route instead end the turn with an error frame
  and keep the tool steps on screen. That is correct, because synthesising would
  need the call that was just refused.

## Checked and cleared (highlights)

- **Channels:** reasoning and narration are scanned as "reasoning", content as
  "content", and tool lines on the single literal "tool". The scan always
  precedes the yield.
- **Leaks:** a trip leaves `agent_done` as None and takes the leak branch before
  anything is persisted. A trip and a refusal cannot both happen.
- **Usage claims:**
  - the pre-claim is consumed exactly once;
  - the synthesis call is claimed (8 + 1 calls, 9 claims);
  - a refused claim consumes nothing (the UPSERT is conditional).
- **Endpoint failure:** an `LLMError` after a tool step keeps the tool frames,
  sends the error frame, persists nothing and closes the client.
- **The latent `aclosing` item:** stays latent. httpx 0.28.1's close does not map
  to `LLMError`, and a trip on a tool frame happens with no stream open.
- **Tenants:**
  - history is workspace- and session-scoped;
  - claims and the proposal store use `auth.workspace_id`;
  - the deployment scorecard cannot be spoofed: names are UNIQUE and auth
    refuses the reserved name.
- **Dev switcher:** never reaches the agent path, because no `agent_mode` is set.
- **XSS:** none. The status class comes from code; everything the model wrote is
  rendered as text.
- **Early close:** tested at narration, at reasoning, at a tool event and inside
  synthesis. The open stream closes immediately in every case.
