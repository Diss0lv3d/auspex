# NEXT-SESSION-FE — track: front end · session: F2

_Paste everything below the line into a fresh Claude Code window opened in
/home/burhan/auspex-new. **The front end is the current focus** (Burhan,
2026-10-10: "before moving on with more backend development we need to improve
on the FE so lets shift our focus there and pause BE for a bit")._

---

SESSION F2 of Auspex, **front-end track** (D-051). The working dir must be
/home/burhan/auspex-new. Run `/session-start fe F2` first (the full ritual). It
reads `SESSION-RULES.md` (standing rules for every track) and STATE.md.

Step 0 (do BEFORE new scope):

1. **One session at a time.** STATE.md's Tracks table says whether B1 is
   still mid-session in another window. If it is and that window is open,
   STOP and ask Burhan to finish or close it first. Two windows promoted at
   once on 2026-10-12.
2. **If STATE.md says the promote slate is not empty, `/promote` it.** Read
   the diff, not the list.
3. **Ask Burhan what he saw using F1's page by hand.** F1 shipped four
   things he has not yet used for real:
   - the working line and paced stream (D-052);
   - markdown answers with host-labelled links (D-053);
   - the approvals panel;
   - the spend lines (D-054).

   His list outranks the goal below. What he names joins F2 only if he says
   so; the rest goes to IDEAS.md, or BUGS.md if it is broken.

Goal: **a chat survives a reload.** Today a reload (and B-003's fix makes
reloading normal after every deploy) loses the conversation, the approvals
panel's decided cards and the chat's total. The page keeps `sessionId` in
memory only, and the API has no way to list or read a chat.
- **Backend:**
  - `GET /api/chat/sessions`: your chats, newest first, each with its first
    question as a title, its time and its spend total.
  - `GET /api/chat/sessions/{id}/messages`: its stored turns.
  - Both are scoped like `_ensure_session` (workspace AND user), so another
    analyst's chat is a 404.
  - Tests ship with them, including the foreign-chat 404.
- **Page:**
  - a chat list (where it lives is a design question for Burhan);
  - opening a chat renders its turns: answers through D-053's builder, and
    spend lines from `turn_spend` where a turn has a row;
  - continuing a chat keeps its `session_id`;
  - the current chat's id survives a reload (it is the analyst's own id, so
    the URL hash or localStorage is fine; say which and why).
- **What a chat can and cannot replay:** the Thinking pane and tool lines are
  not stored (reasoning is ephemeral by design). Say so on a reopened turn
  rather than showing an empty pane. Whether to store tool lines is a
  decision, not a refactor; ask first.
- Design first (brainstorming), Node tests for the new page logic, live in the
  browser against the rebuilt container.

Candidates. **Ask Burhan at the start ritual. Do NOT start any of these
unasked:**
- The S26 chat UX edges (IDEAS):
  - an `empty_answer` turn shows a Thinking pane and nothing else;
  - the usage-ceiling and leak copy are prefixed "[endpoint error]";
  - narration joins the Thinking pane with no separator.
- Split the page into modules (TD-045). The page is 808 lines; the split
  should be its own change, with B-003's no-cache on the scripts too.
- A narrow-screen pass over the chat and the panel (the panel overlays below
  900 px; nobody has looked at it on a phone).

Constraints: everything in `SESSION-RULES.md`, especially **The page** (the
page-logic block, D-053's subset, D-052's pacing) and **The output rail**.
- A stored answer reaches the page through D-053's builder, never as HTML.
- Live probes and pytest never run at the same time.
- A probe that files proposals rejects them, and a probe that creates
  observables deletes only what it created.
