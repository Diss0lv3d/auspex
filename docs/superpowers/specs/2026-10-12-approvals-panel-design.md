# Approvals panel — design (F1, 2026-10-12)

_Approved by Burhan in F1: "this looks right, build it". Placement, friction and
history were his picks from F1's options (all three the recommended ones)._

## Why

The approval API has seven doors (`auspex/routes/proposals.py`): approve,
reject, abandon, keep, execute (run now), withdraw and undo. The page has
none of them. A proposal the agent files (D-045) shows in the chat as
"Awaiting your approval: …", and from there the analyst can do nothing. D-048
recorded it: "There is no page UI for any approvals door yet".

## What

**A side panel on the chat page.**
- A header button, "Approvals · N", opens it on the right (380 px, overlaying
  the chat on narrow screens).
- While signed in, the page polls `GET /api/proposals` every 5 s. The card
  stream only announces new cards, never status changes (STATE.md follow-up
  5), so polling is the one source.
- Waiting cards come newest first. Below them, a "Decided this session" group
  keeps every card decided since the page loaded, with its outcome.

**A card shows the proposal's stored card (D-045), as text:**
- the action name (mono) and a risk badge: write = Signal, destructive = Ember;
- a status line in words;
- the dry-run summary, and the systems it writes;
- the undo line, "Undo: <description> · cannot restore: …", or "No undo — this
  cannot be taken back";
- "Asked N more times", from `identical_pending`;
- the short id.

**Doors by status**:

| status (as served) | doors |
|---|---|
| `pending_approval` | **Approve**², Reject |
| `approved` (in the queue only when no run claimed it; D-048) | **Run now**², Withdraw |
| `executing`/`undoing` (in the queue only when the claim is stale) | Abandon |
| `incomplete` | Keep, **Undo**² if the card declares one |
| `executed`, `kept`, `abandoned` (session history) | **Undo**² if the card declares one |
| `rejected`, `withdrawn`, `undone`, `failed` | none |

² **Two clicks.** The first arms the door and shows its consequence with a
**Confirm**. Five seconds without the second click disarms it. Doors that do
not run anything are a single click.

**Responses.**
- 200: the card updates in place from the response's `proposal`. Approve
  reports the run, so its card is re-read with `GET /{id}`.
- 409: the server's detail ("already approved — someone else decided this
  one"), then a refresh.
- 500 from a run or an undo: the server's sentence (it names the door that
  exists), then the card is re-read.
- Every server string is set with `textContent`.

**In the chat**, each "Awaiting your approval" line gains a **Review** button.
It opens the panel and highlights the card.

## How

- **Pure logic** goes in the page's `// <page-logic>` block (SESSION-RULES):
  `doorsFor(proposal)`, `statusText(proposal, now)`, `undoText(card)`,
  `mergeQueue(waiting, decided)` and a confirm state, `armDoor` /
  `confirmable`. It is tested under Node in `tests/js/page_logic.test.mjs`.
- **DOM wiring** is thin: the panel, the cards rebuilt from the pure output, the
  poll timer, and `fetch` for the doors.
- **No backend change.** The doors, their status rules and their copy are the
  server's.

## Not in scope

- Full decision history (it needs a new endpoint).
- Status changes over the stream (follow-up 5).
- Splitting the page into modules (worth its own change past ~1000 lines).

## Testing

- **Node:**
  - every status's doors;
  - a stale approval and a stale claim get their doors from queue membership,
    not a page clock;
  - the confirm disarms after 5 s;
  - the merge keeps the waiting order, puts decided cards after the waiting
    ones, and drops a decided card the queue still shows;
  - the undo line, for both the declared and the absent undo;
  - the status copy.
- **pytest** (`test_ui.py`): the header has the panel's button, and no
  `innerHTML` takes a variable.
- **Live, against the rebuilt container:**
  - file a real note proposal through an agent turn on an indicator the probe
    recorded;
  - in the panel, approve it (two clicks), then undo it;
  - file a second and reject it;
  - the probe deletes only the observable it created (SESSION-RULES).
