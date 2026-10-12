# F2 live probe: a chat survives a reload (2026-10-12)

Build: app container rebuilt from `staging` @ 5330f5b (`docker compose up -d --build app`, ready 200).
Gate: `./ci.sh` exit 0, `All checks passed!`, `1341 passed, 1 warning` (a Starlette httpx deprecation warning in fastapi/testclient; not ours).
Browser: Playwright headless Chromium at http://localhost:8000, endpoint picker on "Standard" for every turn. Users: fe-probe@auspex.dev, fe-probe-2@auspex.dev.

## Steps

1. **Shortcut turn, reload: PASS.** `check 8.8.8.8` answered "Answered without the engine"; hash `#chat=aca3987e-6188-405a-bfa2-b34c60971663`. After reload: signed in (token in sessionStorage), hash unchanged, main began with the divider "Reopened · answers and spend only; reasoning and tool steps aren't kept." followed by the user turn and the 8.8.8.8 verdict text; sidebar listed "check 8.8.8.8 / just now". Live-only lines ("Answered without the engine", "Reasoning") are not kept, as designed.
2. **Deep turn, reload: PASS (prompt changed).** The brief's prompt (`What is the difference between T1059.001 and T1059.003? Answer briefly.`) was routed to the no-engine glossary miss ("I don't have a curated definition for that term yet ..."), 0 engine calls. A second prompt was used on the same chat: `Explain how T1059.001 and T1059.003 differ and how each shows up in an investigation. Answer briefly.` Live: `2 engine calls · 3.6k tokens (3.0k in · 590 out)`. After reload the answer renders as markdown (H4, STRONG, UL/LI present) and the spend line is identical: `2 engine calls · 3.6k tokens (3.0k in · 590 out)`; sidebar row: "just now · 2 engine calls" (chat total matches).
3. **Proposal, approve, reopen, Review, Undo: PASS.** Prompt: the F1 note prompt on 185.220.101.141 (3 engine calls · 5.7k tokens). Live line: "Awaiting your approval: Attach an analyst note to ipv4 185.220.101.141 (53 characters). (proposal 4065e597)Review". Review opened the panel; Approve -> "Confirm approve" -> DB status `executed`. After reload: `Proposal: Attach an analyst note to ipv4 185.220.101.141 (53 characters). · DoneReview`. Review: panel card under "DECIDED": `annotate_observable / WRITE / 4065e597 / Done`, "Undo: Remove the note this approval added", **Undo** button. Undo -> "Confirm undo" -> card "Undone ... Removed 1 note(s) this approval added."; DB status `undone`. Observation: the in-chat line still said "Done" until the next reload; on reopening the chat it read `... · UndoneReview`.
4. **Foreign hash: PASS.** Sign out (clears token, hash, sidebar "Sign in to see your chats."), signed in as fe-probe-2, set hash to probe-1's chat id: main showed exactly `That chat is not available to you.`, hash cleared, chat otherwise empty.
5. **Bad token: PASS.** `sessionStorage.setItem("auspex.token","x")` + reload: header "Sign in / not signed in", sidebar "Sign in to see your chats.", `sessionStorage.getItem("auspex.token")` is null.
6. **Controls locked during a turn: PASS.** Mid-turn: "+ New chat" disabled, 33 of 34 sidebar buttons disabled (the one enabled is, I infer, the open chat's own row; not individually checked), a click on another chat and on + New chat left the hash and the running chat unchanged. After the answer finished all were enabled again.
7. **390 px: PASS.** Sidebar `display:none` (width 0); "Chats" button present; clicking it showed the sidebar as a 260 px overlay; picking "check 8.8.8.8" closed it (display none) and opened that chat (hash `#chat=aca3987e-...`, divider shown). Screenshot: `.superpowers/sdd/2026-10-12-chat-survives-reload/step7-mobile.png` (step 3 panel: `step3-approved.png`).
8. **Hygiene: done.** Before: observable 185.220.101.141 count 0 (so probe-created). Proposals of the probe users: one, `undone`. Deleted that proposal, the observable, and both probe users (cascade). After: observable 0, users 0.

## Inference calls

8 engine calls on Standard (glossary miss 0, step 2 deep = 2, step 3 = 3, step 6 = 3).

## Fixes made

None. Only console noise: favicon.ico 404.
