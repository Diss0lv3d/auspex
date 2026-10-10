# S27 — actions on the chat agent path (D-045), live

_2026-10-11, S27, added to scope by Burhan at the start ritual. IDEAS asked
for "its own probe (does the model file sensible proposals?)" before the chat
agent could propose. Script: `docs/probes/s27-actions/probe_app_chat_actions.py`;
raw: `docs/probes/s27-actions/raw-app-chat-actions.log`. Rebuilt container,
glm-4.5-air, one session, the shared `default` workspace._

## Four turns, one session

| turn | path / mode | what the agent did | proposals filed |
|---|---|---|---|
| 1 `185.220.101.5` | shortcut | IOC check; the observable is persisted, and the answer names its short id `ipv4-7179fc4a` | 0 |
| 2 "Add a note to 185.220.101.5 saying it is a Tor exit node…" | agent / ioc_enrichment | **`annotate_observable(ipv4-7179fc4a, <the analyst's words>)` → proposed**; answer: "I've proposed adding the note… it requires human approval before it will be performed" | **1** |
| 3 same indicator, "just tell me, don't change anything" | agent / ioc_enrichment | answered from the earlier enrichment; no action called | 0 |
| 4 "How does kerberoasting lead to domain admin?" | agent / threat_intel | 3 × `search_knowledge`; no action called | 0 |

The filed card read "Attach an analyst note to ipv4 185.220.101.5 (108
characters)." Its arguments were the observable's id and the analyst's own
sentence. The probe rejected it afterwards, so nothing was left pending.

## What this establishes

- **The proposals were sensible and appeared only when asked for.** One
  explicit ask filed one correct proposal. Two turns that did not ask filed
  none.
- **The agent said "proposed", not "done".** The loop's directive ("never
  report an action as completed") held on this endpoint.
- **The short id came from the session.** The IOC check earlier in the
  session had printed it, so the model took it from history.

## Seen, not pursued

- **An action request does not fit its mode's contract.** Turn 2 resolved to
  `ioc_enrichment` (an indicator is present), and a reply of the form "I've
  proposed the note" has no Indicators/Assessment/Recommended action
  sections, so it read `contract_valid: false`. It is reported, not repaired
  (D-043 item 5: a narrative mode), and it is honest. It is a new source of
  drift-log lines, so the drift log is no longer a clean trigger for the
  narrative modes once actions are proposed from chat. Logged in IDEAS.
- **Not measured live:** the path where the observable was never checked.
  The model then has no short id, and the dry run resolves nothing, so the
  call is declined with the action's own sentence (`NothingToPropose`). That
  path is pinned by tests, not by a live turn.
- **The rail scans what the turn shows.** The approvals surface still serves
  the stored card unscanned, as it always has, because a card is
  code-rendered from the action's dry run. An action whose dry run echoes its
  arguments would put model text on that surface. No builtin action does.
