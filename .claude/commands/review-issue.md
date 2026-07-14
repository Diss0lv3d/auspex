---
description: Deep-review a GitHub issue — reproduce, root-cause with file:line, propose a fix plan
argument-hint: <issue number or URL> [--comment]
---

Review issue $ARGUMENTS with engineering rigor. Follow CLAUDE.md rules (reality
over memory — run things, don't guess).

1. Fetch it: `gh issue view <n> --comments`. If there's no git remote yet, say so
   and ask for the issue text instead.
2. Reproduce before theorizing: find the code paths involved, run the relevant
   tests or a minimal repro (docker compose service if needed). If you cannot
   reproduce, say "NOT REPRODUCED" prominently and list what you tried.
3. Root-cause with evidence: cite exact `file:line`, show the failing
   input → wrong output chain. Distinguish *defect* from *symptom*.
4. Classify: severity (critical/high/medium/low), blast radius (which
   workspaces/features), regression or day-one bug, security-relevant? (If
   security-relevant: does it break workspace isolation? Flag loudly.)
5. Propose: the minimal fix, the test that pins it, and any adjacent debt worth
   logging in TECHNICAL_DEBT.md. Estimate size (S/M/L).
6. Output a structured review: **Verdict · Repro · Root cause · Fix plan ·
   Tests · Risks**. Do NOT start implementing — this command reviews only.
7. Only if `--comment` was passed: post the review as an issue comment via
   `gh issue comment`. Otherwise never write to GitHub.
