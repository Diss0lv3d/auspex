# NEXT-SESSION-FE — track: front end · session: F3

_Paste everything below the line into a fresh Claude Code window opened in
the Auspex repo (Burhan's clone: /home/burhan/auspex-new). **The front end is
the current focus** (Burhan, 2026-10-10: "before moving on with more backend
development we need to improve on the FE so lets shift our focus there and
pause BE for a bit")._

_**F3 is handed to a collaborator** (Burhan, 2026-10-13: "She owns F3 fully").
She runs it on her own machine under her own personal identity, and every F3
call is hers, new D-entries and `/promote` included (D-059). New here? Read
`HANDOFF.md` first._

---

SESSION F3 of Auspex, **front-end track** (D-051). The working dir must be the
Auspex repo: Burhan's /home/burhan/auspex-new, or a collaborator's own clone.
Run `/session-start fe F3` first (the full ritual). It reads `SESSION-RULES.md`
(standing rules for every track) and STATE.md.

**Who decides (D-059).** The human running F3 owns its calls. Where this
prompt, the rules or a command say "Burhan's call" or "ask Burhan", ask them.
Re-scoping the backend or bugs track stays Burhan's: flag it, don't do it.

**No local engine needed.** F3's default goal is page work and needs no LLM,
so the local-Ollama gate (`/session-start` 4b) is not a stop for F3. A chat
turn, if one is needed, uses the dev endpoint from `.env` and costs money.

Step 0 (do BEFORE new scope):

1. **One window at a time (D-051).** If anything moves that you did not move,
   check `ps` for a second `claude` in this directory and stop.
2. **If STATE.md says the promote slate is not empty, `/promote` it.** Read
   the diff, not the list. (At F2's close it held only F2's session-end docs.)
3. **Use F2's page by hand first, and say what you saw.** Burhan handed F3 on
   before using it, so nobody has used these for real:
   - a chat survives a reload: the always-on sidebar, + New chat, reopening a
     chat (the "Reopened" divider, spend lines, proposal lines with Review);
   - the sign-in kept for the tab (D-056), and Sign out;
   - Review on a reopened proposal bringing back its card, and Undo from there;
   - the empty-answer note, errors in the server's own words, narration on its
     own line;
   - the page on a phone (the Chats button, the backdrop, Esc).

   That list outranks the goal below. What the session's owner names joins
   F3 only if they say so; the rest goes to IDEAS.md, or BUGS.md (`/bug`) if
   it is broken.

Goal (default): **the timeline page joins the chat page under D-057's policy**
(closes TD-051). Today `auspex/static/timeline.html` (280 lines) carries its
own inline `<style>` and `<script>`, four `onclick=` attributes, and builds its
cards as HTML strings into `innerHTML`, escaped by an `esc()` that does not
escape `'`, with inline `style="width:…"` attributes. All of that would be
blocked by a strict CSP. So:
- its CSS and script move into files on `auspex/routes/ui.py`'s allow-list,
  served no-cache, the way F2 moved the chat page's;
- the cards are built with elements and text (the chat page's `el` pattern),
  not HTML strings, and widths are set through the CSSOM;
- the handlers are listeners;
- `/timeline` carries the same policy as `/` (D-057), pinned by a test, and
  the "no CSP yet" test is replaced.

Design first (brainstorming): whether timeline's pure logic (its staleness
labels, its counts "at least N") moves into a tested module like
`js/page-logic.js`, and whether the two pages share helpers, are design
questions; ask. `tests/test_ui.py`'s timeline tests read the page's source;
they must read it as served, as the chat page's do (`_page(client)`). Live in a
real browser with **zero CSP violations**, against the rebuilt container.

Candidates. **Ask the session's owner at the start ritual. Do NOT start any
of these unasked:**
- **Analyst notes shown** (IDEAS, F2): `annotate_observable` writes
  `observable_notes` and nothing reads them back. Showing them on the
  timeline needs a read route (scoped to the workspace) — a design question.
  Handing them to the agent or the IOC check is rail-sensitive (new text the
  model reads): ask first.
- **TD-047:** every load of the chat page is four full responses (no 304s).
- **The stale proposal line** in a reopened turn after a door is used in the
  panel (STATE.md follow-up #20).
- **"[connection lost]"**, the last bracketed error copy on the chat page.
- **D-057's pins** (STATE.md follow-up #21): no test catches `style=` in the
  markup or in `chat.js`'s `innerHTML` templates.

Constraints: everything in `SESSION-RULES.md`, especially **The page** (the
logic module, D-053's subset, D-052's pacing, D-057's CSP) and **The output
rail**.
- The timeline page shows feed-derived text (sources, claims, checker names):
  it is text, never HTML, once it is rebuilt.
- A new external origin, or loosening the policy (`'unsafe-inline'`), is a
  D-entry, not an edit.
- Console-driven probes cannot reach the chat page's module-scoped names;
  drive the DOM (STATE.md follow-up #16).
- Live probes and pytest never run at the same time. A probe that files
  proposals rejects or undoes them; one that records observables deletes only
  what it created.
