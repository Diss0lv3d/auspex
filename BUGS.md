# BUGS — what is broken, found by using the platform (D-051)

The bugs track works from this list, top open entry first unless Burhan says
otherwise. Add entries with `/bug` mid-session; the session that finds a bug
does not fix it. Not ideas (IDEAS.md), not deliberate shortcuts
(TECHNICAL_DEBT.md).

Each entry: id · found (date, by whom, where) · what happened · evidence ·
status. Status is `open`, `fixing (B<n>)` or `fixed <commit> (B<n>)`. Entries
are never deleted.

## B-001 — the platform named the wrong owner for an IP, and said where it got it

- **Found:** 2026-10-10, Burhan, by hand in the chat page.
- **What happened:** "what do you know about this IP: 34.187.179.218" got the
  IOC check: no signal from 5 sources. A follow-up, "dig deeper", answered
  that the IP belongs to **Amazon.com, Inc.** "based on WHOIS and geolocation
  data", with an AWS hostname. The registry says **Google LLC**. The turn made
  no lookup, and the platform has no WHOIS or reverse-DNS source. It ran on
  the local endpoint (qwen3:14b), on the conversational path.
- **Evidence:** docs/probes/2026-10-12-b001-ip-owner-claim.md (the stored
  turns, the server log, the RDAP result).
- **Status:** open.
