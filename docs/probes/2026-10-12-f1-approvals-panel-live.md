# F1 — the approvals panel, live against the rebuilt container

_2026-10-12, headless Chromium (Playwright) against the container on :8000,
Standard (glm-4.5-air, agent path), user `fe-probe@auspex.dev`, workspace
`default`. Design: docs/superpowers/specs/2026-10-12-approvals-panel-design.md._

## Run

1. "We saw 185.220.101.52 beaconing … Check it, and add a note to it …" →
   `enrich_observable · executed`, `annotate_observable · proposed` (proposal
   `bc4b468d`). The header read **Approvals · 1**, and the chat's proposal line
   had a **Review** button.
2. Review opened the panel with the card highlighted:
   `annotate_observable · WRITE · Waiting for your approval`, its dry-run
   summary, `Writes: auspex`, `Undo: Remove the note this approval added`.
   Doors: **Approve**, Reject.
3. Approve armed it, showing "This runs it now: …" and **Confirm approve** in
   Signal. Left alone, it disarmed back to **Approve** (also hit by accident:
   more than 5 s passed between two steps).
4. Approve then Confirm gave **Done**, with the server's note "Attached an
   analyst note to ipv4 185.220.101.52.". The card moved under "Decided this
   session" with an **Undo** door, and the header went back to "Approvals".
5. Undo armed as **Confirm undo** and disarmed after 5.3 s. Undo then Confirm
   gave **Undone**, "Removed 1 note(s) this approval added.", with no doors.
6. A second proposal (`75068957`) was rejected with one click: **Rejected**, no
   doors.

## Found and fixed during the run

- **The open panel covered the Send button.** It is fixed over the right
  380 px, where the composer's button sits, and Playwright's click was
  intercepted by the panel. Now, on screens at least 900 px wide, an open panel
  pushes the page aside (`body.panel-open`). Re-checked: `elementFromPoint` at
  Send's centre is Send.
- **A rejected card still showed its undo line.** `undoLineFor` hides it on
  rejected, withdrawn, undone and failed cards (Node test).

## Found and logged, not fixed

- B-004: a note request in a new chat on the now-recorded indicator was refused
  as "doesn't exist" (docs/probes/2026-10-12-b004-note-on-recorded-indicator.md).

## Cleanup

Both proposals ended as `undone` and `rejected`; no open proposal rows were
left in `default`. The observable `185.220.101.52` did not exist before the
probe and was deleted (`DELETE 1`).
