# F2 — the narrow-screen pass, measured before and after

_2026-10-12, headless Chromium (Playwright) against the container on :8000.
Viewports: 390×844 (a phone), 768×1024 (a tablet), 1280×800 (wide). User
`fe-probe-narrow@auspex.dev` with one shortcut chat (`check 8.8.8.8`, no
engine call); one pending `annotate_observable` proposal was inserted into
that chat to show a card, and deleted afterwards with the user. No inference.
After: `./ci.sh` exit 0, 1348 passed, at `a812238`._

Screenshots: `docs/probes/f2-narrow/` (`before-*` at `225af8c`, `after-*` at
`a812238`).

## Before

| # | Seen | Width | Screenshot |
|---|---|---|---|
| 1 | Header in two rows, 132 px. "Sign in", "Sign out" and "Approvals · 1" broke over two lines; the status over two or three. | 390 | before-1, before-2 |
| 2 | Header + footer took 250 of 844 px (132 + 118). | 390 | before-2 |
| 3 | The 380 px approvals panel left a 10 px sliver of the chat. | 390 | before-3 |
| 4 | The chat list and the approvals panel sat over a live, undimmed chat; a tap outside did nothing. At 768 the panel covered Send. | 390, 768 | before-4, before-6 |
| 5 | Both overlays could be open at once (the chat list on top). | < 900 | — |
| 6 | The light default scrollbar on Night. | all | before-2, before-4 |

Already fine: no horizontal scroll (`scrollWidth` 390 at 390), the reopened
chat and its proposal line, the card layout.

## After (one commit each)

- `78ba00f` — `color-scheme: dark`: the scrollbars are dark (after-2).
- `8175edb` — labels never wrap; below 600 px the tagline goes and both bars
  tighten. Measured at 390: **header 101 px, footer 106 px** (was 132 + 118);
  no header button or the status taller than one line.
- `54a9a89` — below 900 px one backdrop (`#scrim`) dims the chat behind the
  open overlay. Checked by script at 390:
  - the point (350, 400) beside the open chat list hits `scrim`, and the tap
    closes it (`chats: false, scrim: false`);
  - Esc closes it;
  - opening Approvals with the chat list open leaves only Approvals open;
  - the panel is 390 px wide (full width at ≤ 420 px).

  At 768 the chat is dimmed behind the panel (after-5). At 1280 nothing
  changed: the backdrop computes `display: none`, the panel still makes room
  (`padding-right: 380px`), the chat list is always on, and the point at the
  centre of Send hits `send`.
- `a812238` — the sign-in row takes the full width on a phone: the email box is
  203 px (it clipped its placeholder at 9 em) (after-1).

## Not done

- The footer's "Actions that change state…" line stays on a phone (Burhan: keep
  the honesty line).
- At ≤ 420 px the approvals panel covers the header too; Close is in the panel.
