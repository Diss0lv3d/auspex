---
description: Plain-language briefing of a session's work — built / fixed / blocked / your move
argument-hint: "[session number, commit range, or blank for this session]"
---

Give a plain-language briefing of the work in scope: $ARGUMENTS
(blank = this session — the commits since the last `promote:` on `main`, i.e.
`git log $(git describe --tags --match 'promote*' 2>/dev/null || git merge-base HEAD main)..HEAD`;
if that's empty, use the commits since the last `chore(state): S* session-end`).

First gather reality — don't summarize from memory:
- `git log --oneline` over the range, and `git diff --stat` over it.
- Read the top of `STATE.md` (Where we are / Blockers) and the current
  `NEXT-SESSION.md` Step 0.
- Note whether the work is on `staging` only or already promoted to `main`.

Then write the briefing for a smart person who doesn't read code — the human who
paid for the work and wants to know what they got. Under ~250 words, four
headers, complete sentences (no bullets-of-fragments, no file paths, no class
names, no acronyms without a plain gloss the first time):

- **What we built** — the new capability in terms of what it does for a user
  ("the platform can now read a pasted phishing email and decide how dangerous
  it is"), not the module names.
- **What we fixed** — the bugs patched, each as "the problem → why it mattered →
  now". Lead with the one that mattered most. If a fix closed a security gap,
  say what someone could have done before and can't now.
- **What's blocked** — anything red or stuck, in real-world terms. If nothing is
  blocked, say so plainly ("nothing is blocked").
- **Your move** — exactly what, if anything, is needed from the human: a
  decision, a paste, an approval, a credential. If nothing is needed, say the
  work is done and safe to leave, and name the single thing to paste next
  session (from NEXT-SESSION.md).

Rules: honesty over polish — if a fix is only partial or a risk remains, say so
(name it the way STATE.md / TECHNICAL_DEBT.md does, in plain words). Never invent
work that isn't in the git range. If the range is ambiguous, state what you
briefed on. Follow the SIRP brand voice for any customer-facing phrasing (the
product is "the platform" / "Auspex", never the underlying model name).
