# Probe — branch protection on `main` is gated by the GitHub plan, not by a setting

**Date:** 2026-08-16 (S24, Step 0, immediately after promote #24 merged)
**Why:** STATE.md in-flight item 2 has carried, since S20 (D-028), the claim that
branch protection is *"the one manual step left … Repository settings, Burhan's
call, not a commit's"*, with a ready-to-run command. Burhan authorised running it
this session (after the promote). It does not work, and the reason is not the
command.

## What was executed

Identity confirmed first (`gh auth status` → active account `bh3082336888-cell`),
then the exact command recorded in STATE.md:

```
gh api -X PUT repos/bh3082336888-cell/auspex/branches/main/protection \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[contexts][]=ci.sh (lint + tests + container build + installed-dist)' \
  -F 'enforce_admins=false' \
  -F 'required_pull_request_reviews=null' \
  -F 'restrictions=null'
```

**Response:**

```json
{"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.",
 "documentation_url":"https://docs.github.com/rest/branches/branch-protection#update-branch-protection",
 "status":"403"}
```

The obvious alternative — repository **rulesets**, which on some plans cover
private repos where classic protection does not — was probed rather than
assumed:

```
gh api repos/bh3082336888-cell/auspex/rulesets
→ 403 {"message":"Upgrade to GitHub Pro or make this repository public to enable this feature."}
```

Repository state at probe time:

```
gh repo view bh3082336888-cell/auspex --json visibility,isPrivate
→ {"isPrivate":true,"visibility":"PRIVATE"}
```

## What this means

Both enforcement surfaces are gated the same way. The blocker is **the account
plan crossed with the repository's visibility**, not a checkbox and not the
command's syntax. The command in STATE.md is, as far as this probe can tell,
well-formed — it never got as far as being parsed.

So the carried claim was wrong in one specific way, and it matters: this was
never "one manual step" that could be closed in a quiet minute of a session. It
is a decision with consequences outside the repo. The three ways out:

1. **Make the repository public.** Protection and rulesets both become
   available at no cost. Auspex is a personal greenfield project with no
   customer data and no secrets in-tree (`.env` gitignored since S1), so this is
   not obviously wrong — but it publishes STATE.md, DECISIONS.md and every probe,
   which are candid working documents. Burhan's call, and not a small one.
2. **Upgrade to GitHub Pro.** Costs money, changes nothing else.
3. **Leave `main` unprotected and keep the discipline in the ritual.** Which is
   what has actually been happening for four sessions: `/promote` refuses to
   merge on anything but a CLEAN check, and every promote so far has waited for
   green. The gate is real; it is enforced by the process rather than by the
   forge.

Option 3 is the honest status quo and should be *named* as such rather than
carried as an unfinished task. The risk it leaves is precise and worth stating:
nothing stops a **future** promote — or a stray push — from landing on `main`
without the check. The protection would defend against a tired human, which is
exactly the failure mode CLAUDE.md's working protocol exists to bound.

## Follow-up

STATE.md in-flight item 2 must stop describing this as a pending settings change.
It is a **plan/visibility decision**, and until it is made, `main`'s protection is
procedural.
