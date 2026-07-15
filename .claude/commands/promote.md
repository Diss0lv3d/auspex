---
description: Promote staging → main (PR when remote exists, guarded merge locally) after all checks pass
---

Promote the current state of `staging` to `main` (branch model: D-010 — work
lands on `staging`; `main` is only ever updated through this command).

Preconditions — verify ALL, abort with a clear message on any failure:
0. Identity (D-011): `git config user.email` is the personal noreply address
   AND `gh auth status` shows active account `bh3082336888-cell` (switch with
   `gh auth switch` if not). Remote URLs must use the `github-personal` SSH
   alias, never plain `github.com`. Work identity detected → stop.
1. On `staging` with a clean tree (`git status`). Uncommitted work → stop.
2. `staging` is ahead of `main` (`git log main..staging --oneline`); show the
   commit list that would promote.
3. Full check suite green, run fresh: `./ci.sh` (lint + tests) AND
   `docker compose up -d --build` then hit `/api/health/ready` until 200 (or
   30s timeout). Any red → stop, report, do not promote.

Then promote:
- **Remote exists** (`git remote -v` non-empty): push staging, open a PR
  staging → main via `gh pr create` titled `promote: <one-line summary of the
  commit range>`, body = the commit list + check results, ending with the
  standard PR footer. Wait for CI (`gh pr checks --watch`); merge with
  `gh pr merge --squash` only when green.
- **No remote yet**: `git checkout main && git merge --no-ff staging
  -m "promote: <summary>"`, then `git checkout staging`.

After promoting:
- **Back-merge (squash workflow):** the squash gives `main` a commit staging
  doesn't have, which makes the NEXT promote PR conflict. Immediately run, on
  `staging`: `git merge -X ours origin/main -m "merge: back-merge main after
  promote"`, verify the tree is unchanged (`git diff <pre-merge-sha> HEAD
  --stat` is empty), and push. If the PR itself reports "not mergeable" before
  merging, do this same reconciliation first, push, then merge.
- Confirm `main` still passes `docker compose up` + `/api/health/ready`
  (always-demoable invariant), then report what was promoted in one short
  list. Never force-push, never promote with skipped checks, never promote
  from any branch other than staging.
