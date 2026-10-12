---
description: Log a bug in BUGS.md without breaking session scope-lock
argument-hint: <what is broken, and where it was seen>
---

Add this bug to `BUGS.md` as a new entry: $ARGUMENTS

- Give it the next free id (`B-<nnn>`, one higher than the last entry). Fill
  the entry's fields the way BUGS.md's header describes: found (today's date,
  who, where), what happened, evidence, status `open`.
- **Evidence is what was observed, not a diagnosis.** A quoted answer, a log
  line, a probe record, or "seen by Burhan, not yet reproduced". If the only
  copy of the evidence lives somewhere a test run or a container restart will
  erase (a chat in Postgres, a container log), save it to a dated probe record
  in `docs/probes/` first and point at that.
- Never paste secrets, keys or tenant data into an entry (org rule).

Commit it on its own (`chore(bugs): B-<nnn> — <one line>`). Then immediately
return to the current session's scope-locked work. Do NOT diagnose or fix the
bug here; that is the bugs track's job (D-051). If the bug blocks the CURRENT
session's goal or makes its results wrong, say so in one sentence and let
Burhan decide.
