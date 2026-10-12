# NEXT-SESSION-BUGS — track: bugs · session: B1

_Paste everything below the line into a fresh Claude Code window opened in
/home/burhan/auspex-new. The bugs track works from BUGS.md (D-051)._

---

SESSION B1 of Auspex, **bugs track** (D-051): the first bugs session. The
working dir must be /home/burhan/auspex-new. Run `/session-start bugs B1` first
(the full ritual). It reads `SESSION-RULES.md` (standing rules for every track)
and STATE.md.

Step 0 (do BEFORE new scope):

1. **If STATE.md says the promote slate is not empty, `/promote` it.** Read the
   diff, not the list.
2. **Read BUGS.md and ask Burhan which open bug comes first.** Default: the
   top open entry. Mark it `fixing (B1)` when work starts.

Goal: **B-001, the platform named the wrong owner for an IP.** Read
docs/probes/2026-10-12-b001-ip-owner-claim.md first. In short: after the IOC
check found nothing on 34.187.179.218, "dig deeper" answered that it is
Amazon's "based on WHOIS and geolocation data", with an invented AWS hostname.
It is Google's (ARIN RDAP). That turn made no lookup and ran on the local
endpoint, on the conversational path.

Reproduce before fixing:
- **Run the same two turns on both endpoints** (glm-4.5-air, and qwen3:14b in
  the background), at least 3 times each. Record the path, the mode, the tools
  offered and called, and whether an owner, a hostname or a source is
  asserted.
- **Find why a follow-up about an indicator takes a path with no tools.**
  Does the classifier see "dig deeper" as deep, and does the previous turn's
  observable reach the next turn? Cite `file:line`.
- **Check what the model is told.** Is the IOC check's "unknown to 5 sources"
  in its context, and is anything telling it it has no WHOIS or reverse-DNS
  source?

Then:
- **Fix the cause, with a test that fails before the fix**, and pin the exact
  offending answer as a regression fixture (org rule: customer-reported bad
  output becomes a pinned fixture). Live-check through the rebuilt container
  on the dev endpoint.
- **If the only fix is a check on what the model writes**, that is the deferred
  item "the model fabricating incident specifics the contract validator
  passes" (SESSION-RULES.md, Deferred). Stop and put it to Burhan: re-scope it,
  or ship the routing/context fix alone.
- A routing change is a classifier or resolver change, so it is judged by
  SESSION-RULES.md's two-battery rule.

If B-001 closes early, ask Burhan before taking the next open entry.

Constraints: everything in `SESSION-RULES.md`. Bugs-only, this session:
- **One bug per fix commit.** Each one names its B-id, and BUGS.md gets the
  status `fixed <commit> (B1)` in the same session.
- A new bug found while fixing this one → `/bug`, not this session's scope,
  unless it blocks B-001's fix. In that case say so and let Burhan decide.
- The B-001 chat is evidence only in its probe record now. The next pytest run
  deletes it from Postgres.
