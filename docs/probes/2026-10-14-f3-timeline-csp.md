# F3 — the timeline page under D-057's policy, checked live (2026-10-14)

_Session F3 (front end), Hunaiza. Spec:
docs/superpowers/specs/2026-10-14-timeline-page-csp-design.md; plan:
docs/superpowers/plans/2026-10-14-timeline-page-csp.md. Raw runs and
screenshots: `docs/probes/f3-timeline/`._

## How it was run

- `./ci.sh` green after Tasks 1–3 and the merge of Burhan's 2026-10-14
  planning commits: **1392 passed**, ruff clean, installed dist == source
  (121 modules). The gate rebuilt and restarted `auspex-app-1`, so everything
  below ran against the built image.
- Node: this machine's `/usr/bin/node` is v18, which cannot load the page
  modules (no ESM detection), so the chat page's own Node tests fail on it
  too. Every run used nvm's v22.23.3 first on `PATH` (HANDOFF: Node 20+).
- Browser: headless Chromium 130 (Playwright 1.48.2, installed in the session
  scratchpad, not the repo), driving `http://localhost:8000`. Scripts:
  `probe_timeline.mjs`, `probe_chat.mjs` (copied beside the runs).
- No engine calls were made.

## The served page

`GET /timeline` → 200, `cache-control: no-cache`, and

```
content-security-policy: default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
```

`/css/timeline.css`, `/js/timeline-logic.js`, `/js/timeline.js` → 200.

## The digest (timeline-run.txt, timeline-digest.png)

- Status `digest · quiet`; banner "Nothing re-scored your past this week — and
  everything that would have noticed was running."; all four sections render.
- `securitypolicyviolation` events: `[]`; console errors: `[]`.
- Digest and Sign in buttons re-render; phone width (390 px) does not
  overflow.
- The week was quiet, so the digest held no observable links to click.

## One observable's timeline (timeline-open-run.txt, timeline-open.png)

The dev database held no verdicts (the suite clears its own), so one probe
observable was inserted into `default` and deleted in the same command (a
shell `trap`): `ipv4-f3probe01` = `192.0.2.77` (TEST-NET, never enriched),
with two verdicts — `suspicious 0.8, 7 d half-life, 10 days old` and
`malicious 0.9, 14 d half-life, 3 days old`, the latter with the source
`<img src=x onerror="document.title='pwned'">`.

- Opened from the input + Open timeline: status `timeline · 2 verdicts`.
- Bars set through the CSSOM: `written=90%`, `now fresh-f=78%` (current),
  `written=80%`, `now aging-f=30%` (superseded).
- `main img, main script, main iframe`: **0**. The screenshot shows the
  `<img …>` source as literal text.
- `securitypolicyviolation` events: `[]`; console errors: `[]`.
- Cleanup: `0 observables, 0 verdicts left`.

## F3 Step 0 item 3 — F2's chat page by hand (chat-walk-run.txt)

Driven in the same browser as `hunaiza@analyst.dev` (2 saved chats, no
proposals), without sending a turn:

| Check | Result |
|---|---|
| Sign in, sidebar lists the chats with their spend | 2 chats, "4 engine calls" / "1 engine call" |
| Reopen a chat | URL hash `#chat=…`; the "Reopened · answers and spend only…" divider; spend line "4 engine calls · 10.8k tokens (9.9k in · 879 out)"; chat total "This chat: 1 turn · 4 engine calls · 10.8k tokens" |
| Reload | still signed in, same chat, divider back |
| + New chat | hash cleared, transcript empty |
| Phone (390 px) | header 99 px, no horizontal overflow; Chats opens the backdrop; a tap on it closes; Esc closes |
| Sign out | "not signed in", the stored token removed; a reload stays signed out |
| A new tab | signed out (the token is the tab's, D-056) |
| CSP violations / console errors | `[]` / `[]` |

**Not reached:** Review and Undo on a reopened proposal. Neither saved chat
holds a proposal, and making one needs a paid agent turn; left for a hands-on
run. The empty-answer note, server errors in their own words and narration on
its own line need live turns too, and were not exercised.

## A digest link clicked live (final review I1; timeline-link-run.txt)

The final review found the link path above unproven (the week was quiet). A
second probe observable was seeded and deleted the same way: obs_id
`ipv4-f3'probe"03` (a `'` and a `"`, the characters that could break out of
the old `onclick="open_(&quot;…&quot;)"`), value
`<img src=x onerror="document.title='pwned'">`, two verdicts and one
`suspicious → malicious` flip whose trigger is `<b>f3-probe</b> trigger`.

- Digest: `digest · activity`; banner "Your past got re-scored. 0 re-opened ·
  1 changed label · 0 claims contradicted · 0 went stale."; four checker pills
  (retrohunt, watchers, fanout, ingest-cycle).
- The link and the trigger render as literal text
  (timeline-link-digest.png); `main img, main script, main iframe`: **0**.
- Clicking the link opened that observable: `timeline · 2 verdicts`, bars
  `90%/86%` and `60%/37%` (timeline-link-open.png).
- `securitypolicyviolation` events: `[]`; console errors: `[]`.
- Cleanup: `0 observables, 0 verdicts, 0 flips left`.
