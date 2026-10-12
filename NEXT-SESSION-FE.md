# NEXT-SESSION-FE — track: front end · session: F1

_Paste everything below the line into a fresh Claude Code window opened in
/home/burhan/auspex-new. **This is the current focus** (Burhan, 2026-10-10,
after S28: "before moving on with more backend development we need to improve
on the FE so lets shift our focus there and pause BE for a bit")._

---

SESSION F1 of Auspex, **front-end track** (D-051): the first front-end
session. The working dir must be /home/burhan/auspex-new. Run
`/session-start fe F1` first (the full ritual). It reads `SESSION-RULES.md`
(standing rules for every track) and STATE.md.

Step 0 (do BEFORE new scope):

1. **If STATE.md says the promote slate is not empty, `/promote` it** (at the
   time of writing: #30, everything after `31f7fc1`). Read the diff, not the
   list.
2. **Ask Burhan what else he saw on the page.** He used it by hand on
   2026-10-10 and raised the slow reasoning below; his list outranks the
   candidates at the bottom. Things he names go into this session's goal only
   if he says so; the rest go to IDEAS.md (or BUGS.md, if broken).

Goal: **a deep turn's reasoning streams very slowly** (Burhan: "we should
perhaps increase the stream bit rate so it renders faster"). Find where the
time goes before changing anything.

What is already known (read both records first):
- **The turn Burhan watched ran on the local Ollama model**, `qwen3:14b`,
  picked through the page's dev endpoint switcher. It took 30 s to response
  headers and 3 min 13 s to the stored answer. It was the conversational path,
  not the agent (docs/probes/2026-10-12-b001-ip-owner-claim.md).
- **One sample each on glm-4.5-air** (docs/probes/fe-stream/, run right after
  he raised it): straight from the endpoint 391 reasoning chars/s, max gap
  1.25 s; through `/api/chat` 266 chars/s, max gap 2.17 s. They are two
  different completions, and the routed one resolved to `mode=definition`.
  That is a hint that the server path costs something, not a finding.
- **The page paces nothing.** `auspex/static/index.html` has no timer or
  animation-frame code; each reasoning delta is appended as it arrives. The
  answer bubble uses `textContent +=`, which rewrites the whole answer on
  every delta.

Measure first:
- At least 3 deep turns per endpoint (glm-4.5-air, and qwen3:14b in the
  background with a ~1500-token budget), on both the agent and the
  conversational path.
- At three layers, on the same runs where possible:
  1. the endpoint direct;
  2. the frames `/api/chat` sends, timestamped on arrival;
  3. what the page paints, in a real browser against the rebuilt container
     (the Playwright tools are available).

  Extend `docs/probes/fe-stream/probe_reasoning_rate.py` rather than starting
  over.
- Report time to first reasoning byte, chars/s, the largest gap, and how much
  each layer adds, as distributions, not single runs.

Then:
- **Fix the layer that adds the delay**, with tests, and check it live in the
  browser.
- **If the model is the bottleneck**, nothing in the stream path makes it
  faster. Say so with the numbers, and bring Burhan the options for what the
  page does while the engine thinks. Do not pick one unasked.

Candidates. **Ask Burhan at the start ritual. Do NOT start any of these
unasked:**
- Safe minimal markdown in answers (code spans for IOC values in JetBrains
  Mono, D-002) (IDEAS). Because model text never reaches the page as HTML
  (SESSION-RULES.md), this is a decision, not a refactor.
- A page door for the approval decisions that have none: abandon, and D-048's
  run-now and withdraw (DECISIONS.md D-048: "There is no page UI for any
  approvals door yet").
- Investigation cost ledger UI: token spend per verdict (IDEAS).

Constraints: everything in `SESSION-RULES.md`, especially **The page** and
**The output rail**. Front-end only, this session:
- **Speed never skips the scan.** A change that buffers, batches or re-chunks
  the stream on the server keeps the rail's carry, D-031's ordering and the
  narration hold. A change in the page only alters how already-scanned text is
  painted.
- Live probes and pytest never run at the same time.
