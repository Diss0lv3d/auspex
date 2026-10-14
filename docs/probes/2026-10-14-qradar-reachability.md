# QRadar — where it lives and what it holds (S29 goal 2, 2026-10-14)

_The first SIEM of the integration phase is Burhan's own QRadar, on another
machine. S29 probes it **without credentials**: reachability, TLS, and what
the API tells an unauthenticated caller. No credential appears in this file,
in the chat or in any commit, ever (org rule, NEXT-SESSION-BE.md)._

## Burhan's answers (asked at S29, 2026-10-14)

| Question | Answer |
|---|---|
| What data does it hold? | **"Some real data."** Not lab/synthetic only. |
| Where is it reachable from this machine (host:port)? | **"Later."** Not given yet. |

## What the data answer means (binding on every later session)

- **Nothing fetched from this QRadar may reach the dev engine.** The dev
  engine (Z.ai) processes in Singapore, and only lab or synthetic data may go
  there (org policy; KSA-tenant data never, to any non-KSA engine).
- So **S36's live checks need one of these first** (a decision for S29's spec,
  and Burhan's call):
  1. a **lab domain or tenant on the same QRadar**, holding only the synthetic
     offenses S36's recipe creates, with the edge runner's credentials scoped
     to that domain alone, so a fetch can only ever return synthetic items; or
  2. a **separate lab QRadar** (Community Edition) with synthetic data only; or
  3. live checks that **never send fetched content to an engine**: fetch,
     route and store only, with the co-analyst steps (S39) run against the
     hermetic QRadar fake instead.
- **Recorded responses for CI** (the fake) must be synthetic. Nothing recorded
  from this QRadar enters the repo unless it is a synthetic offense the recipe
  made, scrubbed of hostnames, users and addresses.
- The full API probe (S36's Step 0 list) still runs once the token is saved on
  the edge runner (S33). It records **shapes and field names, not values**.

## Not yet probed (waits for the address)

- TCP reachability of the console's API port from this machine, and the route
  the dev edge runner would take (LAN, VPN, tunnel).
- The TLS certificate: issuer, subject, SANs, validity, self-signed or not.
  A self-signed console is the common case; the runner then needs a pinned CA
  or certificate from the application's config, **never a silent "don't
  verify"** (input to the manifest contract, decision 1b).
- What the API answers without a token (for example, its version endpoint).

**Status:** open. The next session that has the address runs the three probes
above and adds them here, before S33's runner work depends on them.
