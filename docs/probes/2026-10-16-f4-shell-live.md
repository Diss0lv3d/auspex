# F4 live — one shell, two clients, every role (2026-10-16)

Reality snapshot of F4's shell (spec docs/superpowers/specs/2026-10-16-f4-shell-design.md,
D-070) in headless Chromium against the container `./ci.sh` built at `e73b22a`.
Synthetic people only (`@f4-live.auspex.dev`, `@auspex.dev` test users); tokens
were read in the browser to compare them and are not recorded here.
Scripts: `docs/probes/f4-live/seed.sh`, `cleanup.sh`, `ceiling.sh`.
Screenshots: `docs/probes/f4-live/shots/`.

## Gate

`./ci.sh > ci.log 2>&1; echo $?` → `0`: ruff `All checks passed!`, `1596 passed,
1 warning`, `installed dist == source tree (129 modules)`, `CI green.`

## Mutants (Task 10), each reverted after its run

| # | File | Mutant | Result | Caught by |
|---|---|---|---|---|
| 1 | shell-logic.js | `navEntries` keeps every page (Members for all) | caught | shell_logic: admin/analyst/viewer nav; signed-out nav |
| 2 | shell-logic.js | `afterSwitchUrl` keeps the hash | caught | shell_logic: "reloads without its hash" |
| 3 | shell.js | `switchTo` sets a status instead of `location.replace` | caught | test_ui `test_a_switch_reloads_the_page_without_its_hash` |
| 4 | page-logic.js | `doorsFor` without the `mayChange` guard | caught | page_logic: "a viewer gets no door…" |
| 5 | ui.py | `_matches` returns `True` | caught | test_ui `test_a_stale_or_absent_etag_gets_the_whole_file` |
| 6 | api.js | no `onForbidden` on a 403 | caught | api: the 403 hook; the refused stream |
| 7 | shell-logic.js | `errorText` returns `JSON.stringify(detail)` | caught | shell_logic: "a 422's detail list is never echoed" |
| 8 | shell-logic.js | `switchOptions` filters to `via: membership` | caught | shell_logic: "lists exactly what the server returned" |
| 9 | shell.js | `recheck` without `if (!checking)` | caught | test_ui `test_any_refusal_re_checks_access_through_me_once` |
| 10 | chat.js | `recordDecided` without `refreshProposalLines(p)` | caught | test_ui `test_a_reopened_proposal_line_follows_what_the_panel_learns` |

10 of 10 caught; the tree was clean after.

## The cast (seed.sh; cleanup.sh left 0 users and 0 organizations)

A provider `f4-live-mssp`; clients `f4-live-bank` (global), `f4-live-telco`
(**ksa**) and one named `<img src=x onerror=alert(1)> U+202E a very long client
name that goes on and on`. An MSSP analyst with a provider-wide grant; in bank,
a client admin, a client analyst and a client viewer.

## MSSP analyst, two clients

- Signed in, the switcher listed exactly `/me`'s four workspaces, home first;
  the nav had Chat and Timeline (no Members: an analyst).
- **In bank:** a shortcut question answered ("Answered without the engine"), the
  chat listed with its hash; the approvals panel ("Nothing is waiting on you.");
  `/timeline` in the same tab showed bank in the header and the digest.
- **Switch to telco** (every request recorded after the reload):
  - URL hash `""`; `sessionStorage` keys `["auspex.token"]`; the token differs
    from bank's;
  - chat list empty ("No chats yet."), no bank text in the transcript;
  - 5 API requests (`/api/auth/me`, `/api/models`, `/api/proposals`,
    `/api/chat/sessions`): **all on the telco token; none on bank's; none
    naming bank's chat id.**
- **A deep turn in telco** showed the server's sentence: "This workspace's data
  must stay in region ksa, and the platform's engine here processes in region
  global, so it cannot run this request. Answers that need no engine still
  work."
- **The hostile client:** its name rendered as text in the select and its
  `title` — 0 `<img>` elements, no dialog — and at 390 px no sideways scroll.
  **Finding:** the U+202E in the name reverses the rest of the label, so the
  role and kind read "tsylana · tneilc" (shots/f4-live-hostile-390.png).
  Inert, but a client's name can disguise the role the header shows. Fixed in
  the final review's wave (below).

## Roles

- **Client viewer:** label "f4-live-bank · client · viewer"; no composer, no New
  chat; the note "You are a viewer in f4-live-bank: you can read here; asking
  the co-analyst and deciding proposals need the analyst or admin role."; the
  approvals panel "Deciding needs the analyst or admin role." with 0 doors.
  `POST /api/chat` from the console with the tab's own token → **403** "This
  needs the analyst or admin role in this workspace."
- **Client analyst:** nav Chat, Timeline. `GET /api/workspace/members` → **403**
  "This needs the admin role in this workspace."; `/members` opened directly
  showed "Members of f4-live-bank" and that sentence, still signed in.
- **Client admin:** nav Chat, Timeline, **Members** (current); 3 members listed.
- **A membership removed while the chat page was open** (`remove-member`): at the
  next poll the page signed itself out with "You no longer have access to this
  workspace." (status `err`), `sessionStorage` empty.

Zero CSP violations throughout, at 1280 and 390 px, on all three pages; the only
console errors were the browser's lines for the expected 403/429 refusals.

## F2's page with live turns (#26), on `default`, 8 engine calls

- "Look up 45.155.205.233 and add a note…" (2 calls): looked up and recorded,
  no proposal filed.
- "Add a note to 45.155.205.233: reviewed in the F4 live walk." (1 call): **the
  output rail stopped it.** The model's thinking quoted `annotate_observable`'s
  description ("Calling one of these FILES A PROPOSAL for a human to approve.
  It does not perform the action, …"). The page showed the server's sentence
  ("This answer was stopped mid-stream: …"). Logged as a bug (TD-044's
  unmeasured action-request case).
- "check 45.155.205.233 again, and add a note…" (3 calls): `enrich_observable ·
  executed`, `annotate_observable · proposed`; "Awaiting your approval: Attach
  an analyst note to ipv4 45.155.205.233 (28 characters)." Approvals · 1.
- **Reopened** (reload): the banner, three turns with their spend lines, and the
  proposal line "… · Waiting for your approval". **Review** opened the panel on
  the card; **Approve** armed with "This runs it now: …", then confirmed → "Done",
  "Attached an analyst note…"; **Undo** armed, confirmed → "Undone", "Removed 1
  note(s) this approval added." **The reopened line followed each step:
  Waiting → Done → Undone (#20, live).**
- **The usage ceiling** (`ceiling.sh set`, after the hour turned): "This
  workspace has reached its limit of 100 inference calls per hour (1000000
  used). It resets at 09:00 UTC. …" in the server's words; no chat stored.
  `ceiling.sh restore` removed the row it had added (none existed before).
- **Narration on its own line** (2 calls, a deep question about the address):
  the thinking's "…enriching the IP address 45.155.205.233." then a newline,
  then the narration "I'll help you assess the risk…"; after the tool step the
  text started on a new line too.
- **Not reached:** the empty-answer note (no turn ended with no answer and no
  error; Node pins `noAnswerNote`).
- Cleanup: the observable the walk created (twice) deleted; the one proposal
  ended `undone`.
