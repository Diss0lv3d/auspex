# A chat survives a reload — design (F2, 2026-10-12)

_Approved by Burhan in F2, section by section. His calls: the sign-in survives
a reload in `sessionStorage` (recommended); the chat list is an **always-on
sidebar** (over the recommended toggled panel); a reopened turn brings back its
**proposals only, with no new storage** (recommended); the turns endpoint is
named `/turns`._

## Why

A reload loses everything: the conversation, the approvals panel's decided
cards (and with them the Undo door) and the chat's spend total. B-003's fix
makes reloading normal after every deploy. Two things cause it:

- The page keeps `sessionId` in memory only, and the API has no way to list or
  read a chat.
- The page keeps the sign-in token in memory only
  (`auspex/static/index.html:443`), so a reload signs the analyst out as well.

## What is stored today, and what is not

| Kept | Where |
|---|---|
| each question and each answer | `messages` (`auspex/migrations.py:66`); a question is stored before the turn runs (`auspex/routes/chat.py:575`) |
| what a deep turn spent, and how it ended | `turn_spend` (`auspex/migrations.py:627`); `message_id` names the answer, NULL when there is none |
| the proposals a turn filed | `proposals.session_id` (`auspex/migrations.py:105`) |

- **What is stored is what was shown.** A turn cut by the output check or
  refused at the usage ceiling returns before anything is stored
  (`auspex/routes/chat.py:1126-1144`, `:1154-1170`). A held answer is stored
  only after it passed, was re-asked, or was replaced (`:1171-1177`).
- **Not stored, by design:** reasoning (the Thinking pane) and tool lines.
- **No ledger row:** shortcut answers (`:634`, D-054 counts deep turns only)
  and turns from before D-054.
- `chat_sessions.title` and `updated_at` exist and are never written. This
  design leaves them alone.

## API

Both routes sit beside `GET /api/chat/sessions/{id}/spend`
(`auspex/routes/chat.py:503`) and are scoped the same way: the workspace AND the
user.

### `GET /api/chat/sessions`

Your 50 most recent chats, by their newest message.

```json
{
  "sessions": [
    {
      "id": "<uuid>",
      "title": "We saw 185.220.101.133 beaconing every 60s from the finance…",
      "created_at": "<iso>",
      "last_at": "<iso>",
      "spend": {"turns": 2, "engine_calls": 6, "prompt_tokens": 5100, "completion_tokens": 900}
    }
  ],
  "complete": true
}
```

- `title`: the first question with its whitespace collapsed, cut at 80
  characters with "…". (Collapsed rather than first-line, found while
  planning: a pasted JSON alert's first line is `{`.)
- A chat with no messages is left out.
- `spend` is the ledger's sum, the same arithmetic as `/spend`. A chat with no
  rows has `turns: 0` and null token counts.
- `complete` is false when there were more than 50.
- Another analyst's chats never appear, in this workspace or any other.

### `GET /api/chat/sessions/{id}/turns`

The chat's turns, oldest first.

```json
{
  "id": "<uuid>",
  "turns": [
    {
      "question": "…",
      "asked_at": "<iso>",
      "answer": "…",
      "spend": {"engine_calls": 4, "prompt_tokens": 2800, "completion_tokens": 300, "ending": "stop"},
      "proposals": [
        {"id": "<uuid>", "action": "annotate_observable", "summary": "…", "status": "executed",
         "decided_at": "<iso>", "claimed_at": null, "result": {"effects": null}}
      ]
    }
  ]
}
```

**Pairing, done on the server.** Each question opens a turn, and the turn runs
until the next question. Within it:
- `answer` is the assistant message in the window, or null;
- `spend` is the ledger row whose `message_id` is that answer. With no answer,
  it is the first row (with `message_id` NULL) created in the window. Otherwise
  null;
- `proposals` are the chat's proposals created in the window, oldest first,
  each with its CURRENT status, the summary from its stored card, and the
  fields the panel's `statusText` reads (`decided_at`, `claimed_at`,
  `result.effects`), so a reopened chat words a status exactly as the panel
  does.

**Ownership.** The chat is checked like `_ensure_session`
(`auspex/routes/chat.py:369`). Another analyst's chat, or one in another
workspace, is a 404 with the same body as a missing chat. Proposals are reached
only through an owned chat, and their query is pinned to the workspace too.

**Bound (TD-050).** Pairing is by time. Two tabs sending into the SAME chat at
the same moment can interleave, and a proposal or a ledger row can land under
the other question. One tab cannot: Send is disabled while a turn runs. Exact
pairing would need a key on `turn_spend` and `proposals` (a migration that only
fixes new turns).

## The page

### Sign-in survives a reload (D-056)

- On sign-in, the token goes into `sessionStorage`: it survives a reload in the
  same tab and is gone when the tab closes. The token's lifetime is unchanged
  (12 h, `jwt_ttl_minutes`).
- On load, a stored token is checked with `GET /api/auth/whoami`. A 401 clears
  it and shows sign-in. A 200 shows "signed in", as a fresh sign-in does.
- A **Sign out** button clears it and reloads the page (a persistent token
  needs a way out, for example to switch test users).
- Every `sessionStorage` call is in a try/catch. When storage is unavailable,
  the page behaves as it does today.
- **The risk D-056 accepts:** any script running on the page can read the
  token. The page sends no Content-Security-Policy (`auspex/routes/ui.py:23`
  sets only `no-cache`), so the guard is D-053's rule that model and tool text
  never become HTML. A real CSP needs nonces or hashes for the inline script,
  which belongs with TD-045's module split (TD-051).

### The current chat lives in the URL hash

`#chat=<uuid>`. Why the hash and not `localStorage`: a reload keeps that tab's
chat, two tabs can hold two different chats without overwriting each other,
and a fresh visit starts a new chat. It is the analyst's own id, and anyone else
who opens it gets a 404.

- The hash is set when a turn's first `session` frame arrives, or when a chat
  is opened. **New chat** clears it.
- On load: sign in (or wait for it), then open the hash's chat.
- A hash that is not a UUID is ignored.
- A 404 clears the hash, says "That chat is not available to you" in one line,
  and starts a new chat.

### The sidebar

- Always on at 900 px and wider, on the left:
  - the Auspex mark;
  - **+ New chat**;
  - the chats, newest first. Each shows its title, a relative time ("2 min",
    "1 h", "yesterday", then a date) and its spend in engine calls. The open
    chat is highlighted.
  - When `complete` is false, a closing line says only the 50 most recent are
    listed.
- Below 900 px it hides behind a **Chats** button and overlays the chat, as the
  approvals panel does. F2's narrow-screen pass refines both.
- The list loads after sign-in and refreshes when a turn ends and on New chat.
  It does not poll.
- Switching chats is disabled while a turn runs (otherwise we would have to
  decide what becomes of a half-streamed answer).
- Titles are set with `textContent`.

### A reopened chat

- **A divider** at the top: "Reopened · answers and spend only; reasoning and
  tool steps aren't kept." One line for the chat, not an empty pane per turn.
- **Each turn:**
  - the question, as text;
  - the answer, through D-053's builder (`markdownNodes`), then its spend
    line from the ledger row: "4 engine calls · 3.1k tokens (2.8k in · 0.3k
    out)". No row, no line;
  - with no answer, a slate line in place of it, naming the ending in words:
    - `endpoint_error`: "No answer: the engine returned an error";
    - `output_guard`: "No answer: stopped by the platform's output check";
    - `usage_refused`: "No answer: the workspace's usage limit was reached";
    - `empty_answer`: "No answer: the engine returned none";
    - no row at all: "No answer was stored";
  - each proposal: "Proposal: <summary> · <status> [Review]", the status
    written by the panel's own `statusText`.
    **Review** opens the approvals panel at that card. If the card is not in
    the waiting queue, the page fetches `GET /api/proposals/{id}` and adds it
    to the decided list, so its doors come back: an executed note can be
    undone after a reload.
- **Continuing** the chat sends its `session_id`. New turns stream live below
  the divider, exactly as today.
- **The chat's total** comes from the existing `/spend` endpoint.

### Page logic

New pure functions in the `// <page-logic>` block (SESSION-RULES), tested under
Node in `tests/js/page_logic.test.mjs`:
- `chatIdFromHash(hash)`: the UUID, or null;
- `relativeTime(then, now)`;
- `chatListLabel(chat, now)`: the entry's title, time and spend;
- `ledgerSpendText(spend)`: a ledger row's spend line, reusing `calls` and
  `kTokens`;
- `endingText(ending)`: a turn with no answer, in words;
- `reopenedTurnPlan(turn)`: the ordered parts a reopened turn renders.

The DOM wiring stays thin: the sidebar, the hash, `sessionStorage`, the fetches.

## Not in scope

- Renaming, deleting or searching chats.
- Paging past 50.
- Storing tool lines or reasoning (Burhan: proposals only).
- Exact turn keys (TD-050).
- A Content-Security-Policy (TD-051).
- Splitting the page into modules (TD-045). This change takes the page past
  ~1000 lines, which makes the split more pressing; it stays its own change.

## Testing

**pytest.** Rows are inserted straight into Postgres: no inference, hermetic.
- List:
  - newest first by the latest message;
  - the title rule: whitespace collapsed, 80 characters;
  - an empty chat is left out;
  - the spend totals match the ledger;
  - `complete` flips past 50.
- Turns:
  - an answered turn gets its row by `message_id`;
  - a failed turn's row (`message_id` NULL) lands under its own question, not
    a neighbour's;
  - a shortcut answer has `spend: null`;
  - each proposal lands under the turn that filed it, with its current status;
  - a turn cut by the output check has `answer: null` and its ending.
- Isolation:
  - another analyst's chat in the same workspace, and a chat in another
    workspace: 404, with the same body as a missing chat;
  - neither appears in the other user's list;
  - another workspace's proposal never attaches.
- Mutants, each expected to fail the suite:
  - drop the `user_id` predicate;
  - widen the pairing window by one turn;
  - accept a non-UUID hash (Node).
- The README's test count travels with each test-adding commit.

**Node:** every function above. A stored answer holding
`<img src=x onerror=…>` and `<script>` is built as text by the frozen element
factory. The floor in `tests/test_page_logic.py` rises from 32.

**Live, in a real browser against the rebuilt container:**
1. A reload mid-chat keeps the chat and the sign-in.
2. Reopen an older chat and continue it; the new turn streams live below the
   divider.
3. Review an executed note proposal from a reopened chat; Undo is there.
4. A foreign chat id in the hash shows the one-line note and a new chat.
5. Sign out returns to sign-in.

A handful of Z.ai calls, never while pytest runs. A probe that files proposals
rejects or undoes them; one that records observables deletes only what it
created.

## Decisions and debt this adds

- **D-056:** the sign-in token survives a reload in `sessionStorage`, and the
  risk that accepts.
- **TD-050:** a reopened chat's turns are paired by time.
- **TD-051:** the page sends no Content-Security-Policy.
