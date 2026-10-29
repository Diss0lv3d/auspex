# STATE — Auspex

_Last updated: 2026-10-29 — **PR #51's review answered on `s33-edge-agent`**
(Burhan: changes requested; findings in docs/probes/2026-10-28-pr51-review.md,
each row marked with its fix). Fixed, one commit each, test first: heartbeats
renew only running jobs and a failed result post is retried (#1); a result is
accepted on the agent's own claim (#2); a secret echoed in a RESULT is redacted
(#3; live re-run with an echoing connector); **D-074** (Hunaiza's call): an undo is
refused only when the code it would run changed (#4); the agent survives a bad
package, a full disk (#5) and a refused credential (#6); s1–s4 (press never hangs a
pool; NUL/surrogate and malformed URLs refused in words; a config edit cancels a
queued test). A **fresh-agent review** of the fixes and S33's sensitive changes ran
(Hunaiza agreed), recorded in the S33 record. Pushed to the same PR #51; `staging`
untouched. **S34 is Burhan's** (his window); **the promote stays Hunaiza's** once
#51 is merged (S32, B4, S33).

2026-10-28 — **S33 CLOSED** by Hunaiza (D-059, handed fully):
**integrations, Edge Agents and "Test connection" end to end** through a real
agent container (docs/probes/2026-10-28-s33-live.md). Step 0 fixed all ten of
PR #43's review findings (#32), with D-072 (the SDK version is not identity).
D-073 (S33's audit actions); TD-068 closed; TD-071…TD-074 logged. `./ci.sh`
green: **2183 tests, 153 modules**, the app image and the new **edge image**
checked; `/api/health/ready` 200. The S33 build's own review is a
**self-review** (Hunaiza asked for no helper agents mid-session): stated in the
record and the PR. **S33 goes to `staging` as one PR from `s33-edge-agent`**;
Burhan reviews and merges. **Promote slate: S32, B4 and S33** (S33 is a promote
milestone; the promote is Hunaiza's once the PR is merged). Record:
docs/superpowers/records/2026-10-28-s33-record.md._

2026-10-28 — **PR #50 (B4) merged into `staging`** (Burhan's
window, after the re-review: B-018's third fix holds on the review's
host-swap links, which keep their real host, and on the credential shapes,
defanged and malformed ones included; the stream-index fix read): a
fast-forward to `d62e9b7`, so every commit B4's records cite is on
`staging`. **S33 is next, Hunaiza's** (`NEXT-SESSION-BE.md`). **Promote slate:
S32 and B4** (S33's promote carries them, after #32's fixes).

2026-10-28 — **PR #50's review answered on `b4-bugs`**
(Burhan approved five of six; B-018 needed one more round). **B-018's third
fix** (`2837720`) follows the URL standard: the authority ends at the first
`/ ? # \`, the userinfo at its last `@`, and no host is taken from after it,
so `http://evil.com:x/p?r=@google.com` keeps `evil.com`; TD-070 reworded (a
password with an unencoded delimiter is a host and a path); a fresh
adversarial review approved it. **B-017**: a numeric-string stream index is
its number (`45314f8`). The dead `rsplit("@")` is gone. Logged: **B-036**
(credentials outside http(s)), **B-037** (a membership removed mid sign-in),
and from the re-fix's review **B-038** (`\` read with another host
downstream) and **B-039** (a tab, newline or quote cuts a URL short). `./ci.sh`
green: **2095 tests**. Pushed to the same PR #50 (no history rewritten);
`staging` untouched, so it merges as a fast-forward. Burhan re-reviews and
merges; S33 starts after.

2026-10-28 — **B4 CLOSED** by Hunaiza (D-059, handed fully):
all six bugs fixed, each with a fresh review (B-025 and B-030 adversarial):
**B-018** (a URL's credentials dropped), **B-025** (a sign-in and a rehome
cannot interleave), **B-017** (a malformed tool call is an unknown tool),
**B-027** (extract's overlap checks bisect), **B-030** (the guard's quote-line
scan is linear), **B-032** (the run-led rules pinned). The reviews logged
**B-033, B-034, B-035** and TD-070. `./ci.sh` green: **2091 tests, 139
modules**; `/api/health/ready` 200. **B4 goes to `staging` as one PR from the
branch `b4-bugs`**; Burhan merges it, then S33 starts. No promote. Records:
docs/probes/2026-10-28-b4-*.md.

2026-10-28 — **PR #43 (S32) merged into `staging`** (Burhan,
after a fresh review in his window): a fast-forward to `4cd5132`, so every
commit S32's record cites is on `staging`. The review's ten findings
(docs/probes/2026-10-28-pr43-review.md) are follow-up #32: **S33 fixes them
first**, before any dispatch code and before its promote. **B4 and S33 are
handed to Hunaiza, fully (D-059): B4 first**, scoped by Burhan to six bugs,
every one required (B-018, B-025, B-017, B-027, B-030, B-032; GitHub #44–#49),
**then S33**. **Promote slate: S32** (S33's promote carries it; B4 does not
promote).

2026-10-27 — **S32 CLOSED** by Hunaiza (D-059, handed fully):
the connector contract, the SDK (`sdk/`, `auspex-sdk`), the reference
connector, actions compiled to `ActionSpec` (fingerprint v2), the catalogue
and `/api/connectors`; **B-026 fixed**; **D-071** written. `./ci.sh` green:
**2058 tests, 139 modules**; `/api/health/ready` 200. **S32 goes to `staging`
as one PR from the branch `s32-connectors`** (Hunaiza's call: local commits,
nothing pushed mid-session); Burhan reviews and merges it. Promote #42
(`69a8800`) shipped B3 at S32's Step 0. Record of every call:
docs/superpowers/records/2026-10-27-s32-record.md._

2026-10-22 — **PR #41 merged into `staging`** (Burhan, after
Claude's review of the A–C answers in his window): a fast-forward to
`45ac519`, so every commit B3's records cite is on `staging`. That review
logged **B-032** (a test gap in the guard's live-rule test, no bypass today).
**Promote slate: B3's fixes** (S32's Step 0 promotes them).

2026-10-20 — **B3 CLOSED, and its PR's review answered**: by
the collaborator Hunaiza (D-059), on her machine: **B-010, B-024 and B-029
fixed** (B-029 from Burhan's review of PR #41, with the review's other six
items). `./ci.sh` green after the re-review fixes: **1707 tests, 133 modules**;
`/api/health/ready` 200. **B3 goes to `staging` as a PR from the branch
`b3-b010-b024`** (Hunaiza's call; the prompt said push `staging`).
Promote #40 (`09af821`) is the last one._

## Tracks (D-051) — read this first

| Track | Prompt | Last closed | Next | Status |
|---|---|---|---|---|
| backend | `NEXT-SESSION-BE.md` | S33 (2026-10-28, Hunaiza; PR #51's review answered 2026-10-29, awaits Burhan's merge) | S34 | **focus** · **Burhan's** (2026-10-28), in his window · Step 0: #51 merged and Hunaiza's promote (S32, B4, S33) landed (checked, not run); then connector actions through approvals |
| front end | `NEXT-SESSION-FE.md` | F4 (2026-10-16) | F5 | waits for S34 (the order table); F4 built the shell F5's admin pages stand on |
| bugs | `NEXT-SESSION-BUGS.md` | B4 (2026-10-28, Hunaiza; PR #50 merged 2026-10-28) | B5 | unscoped: Burhan picks from the open entries (B-033…B-039 new from B4) |

- **B4 closed (2026-10-28) as a PR from `b4-bugs`.** The focus moves to
  S33, which starts only after Burhan merges B4's PR. GitHub #44–#49 are
  commented and closed with the PR.
- **Focus was: bugs, B4, then backend, S33. Both are Hunaiza's** (Burhan,
  2026-10-28: "assign B4 to Hunaiza as well, tell her to first start on the
  bugs and then continue with S33"; D-059). Order table row 5b.
  - She owns both fully: every call, new D-entries and `/promote` included,
    on her machine under her own identity. **Re-scoping stays Burhan's**: B4
    takes the six bugs and no others.
  - **B4 does not promote**: S32 is on `staging` with PR #43's review unfixed,
    and Burhan's call is that S33 fixes it before any promote. S33's promote
    carries S32, B4 and S33.
  - B4 closes as a PR into `staging`, which Burhan merges; S33's Step 0 starts
    only after that.
  - Claude told her on PR #43 and through the six issues, which are assigned
    to her. #38 and #39 (B3's) are still open on GitHub, although promote #42
    shipped their fixes.
- **S32 closed (2026-10-27) as a PR, merged 2026-10-28.** Hunaiza kept every
  commit local on `s32-connectors` and opened PR #43 at the end. S32 did not
  promote (the plan's next promote milestone is S33). It was handed to her
  fully on 2026-10-22.
- **B3 ran on Burhan's calls from the planning window** (history; B3's
  section below has the record):
  - **S31 promoted now** (promote #40); the slate is empty.
  - **B3 runs before S32**, scoped to **B-010** (three old classify rules a
    crafted message can stall for seconds) **then B-024** (the switcher's
    keyboard behaviour, unverified). Order table row 4b in
    `NEXT-SESSION-BE.md`.
  - **B3 is handed to Hunaiza (D-059)**, on her machine under her own
    identity; GitHub #38 (B-010) and #39 (B-024) are assigned to her, and
    Burhan tells her himself. **B-024's UX call goes with the handoff**
    (Claude's default under D-059; Burhan left the question unanswered, so
    he may take it back). Re-scoping stays his.
  - **B3 does not promote**; S32's Step 0 promotes B3's fixes from Burhan's
    window (Claude's default; his to change).
- **The 2026-10-12 two-window collision is over.** F1 and B1 ran at once that
  morning, and both ran Step 0's `/promote`. B1 opened PR #30 while F1's
  `ci.sh` ran, and merged it 4 s before F1's merge; the promote is correct
  (F1 verified it). Burhan paused B1, F1 closed, then B1 resumed in its own
  window and closed. **One session at a time (D-051).** Running two at once is
  parked in IDEAS ("Parallel tracks"); adopting it needs a new D-entry that
  overturns D-051's rule.
- **That pivot was nearly lost** (2026-10-10). Recovered from the session
  transcript; evidence in docs/probes/2026-10-12-b001-ip-owner-claim.md.
- **F3 was handed to a collaborator, and closed** (Burhan, 2026-10-13: "She
  owns F3 fully"; Hunaiza closed it 2026-10-14, section below).
  - She is a junior developer, working in Claude Code on her own machine, in
    her own clone, under her own personal GitHub account.
  - **D-059:** a collaborator authors under their own personal identity, on
    SESSION-RULES.md's "Who works here" table, and adds her own row in her
    first session. `/session-start` 3b and `/promote` 0 now check that table
    instead of writing Burhan's email into the config.
  - Every F3 call is hers, new D-entries and `/promote` included. Re-scoping
    the other tracks stays Burhan's.
  - Her handbook is `HANDOFF.md`: setup, workflow, the starter prompt, and
    the commands in full.
  - **One session at a time spans two machines.** Burhan's planning commits
    landed on `origin/staging` while F3 ran; F3 merged them (`7c64126`, no
    conflict, docs only) and its PR carries the merge.
  - Her row is on SESSION-RULES.md's "Who works here" table (`f54c9ce`).
- **The integration phase is planned (2026-10-14) and designed (S29).** The
  goal is a SIEM on the platform and case management, built on integrations
  (a connector configured in a workspace); customers and MSSPs can write
  their own connectors. **S29's spec,
  docs/superpowers/specs/2026-10-15-integration-phase-design.md, and D-060…
  D-067, every one ratified by Burhan, are the contract from S30 on.** The
  bullets below are the plan as it stood before S29; D-060 renamed its words
  (application → integration, integration → connector, runner → Edge Agent,
  incident → case).
  - **The plan lives in the two prompt files.** Backend: S29–S41 in
    `NEXT-SESSION-BE.md`. Front end: F4–F9 in `NEXT-SESSION-FE.md`, after F3,
    whose prompt is unchanged. Each entry has a goal and exit criteria.
  - **The order across both tracks** is the table in `NEXT-SESSION-BE.md`.
    Each session-end keeps the plan section, writes the next prompt from it,
    and sets the focus to the next session's track.
  - **Burhan's calls.**
    - F3 stays the collaborator's, and the front-end plan starts at F4.
    - S29 opens the phase, and keeps the review of S28's code as Step 0.
      S29's old goals stay here: TD-036 is follow-up #3, TD-044 is #4.
    - QRadar is the first SIEM, and Burhan already runs one on another
      machine. Its credentials come later, once applications exist (S33).
      They never go into the chat or the repo. S29 probes only its
      reachability and TLS, and asks what data it holds; the full API probe
      runs once the token is saved (by S36's Step 0 at the latest).
    - **MSSP tenancy** (Burhan: "My other concern is MSSP clients and
      their multi tenancy problem"). The proposal is S29's decision 1d:
      provider and client organizations owning workspaces, roles on
      memberships, one workspace per token, cross-client views built from
      memberships, and shared SIEMs routed to client workspaces with unmapped
      items quarantined. S30 builds it, before anything else stands on
      roles.
    - He asked how on-prem-only controls work for a cloud app. The proposed
      answer is an outbound-only edge runner plus a later cloud runner, with
      customer code running only on the customer's edge in v1. It is S29's
      goal 1a, a D-entry he ratifies.
  - **S29 ran after F3 closed**, merged F3's PR, and closed 2026-10-15
    (section below). One session at a time spans both machines (D-051,
    D-059).
  - **S30 built MSSP tenancy** and closed 2026-10-15 (section below): D-068
    holds its five calls, D-069 overturns D-061's storage bound.
  - **S31 built the jobs queue and TD-025's first half**, fixed B-021 and
    built D-069, and closed 2026-10-16 (section below).
- Standing rules every track obeys: `SESSION-RULES.md`. Bugs: `BUGS.md`.

## S32 — what happened (backend track; the connector contract, the SDK, the catalogue)

Hunaiza's session (D-059), 2026-10-22 → 2026-10-27, on the branch
`s32-connectors`, to `staging` by one PR. The full record of calls, rulings and
deferred minors: docs/superpowers/records/2026-10-27-s32-record.md.

- **Step 0:** PR #41 merged; promote #42 (`69a8800`, back-merge `da7986a`)
  shipped B3. Baseline probe: docs/probes/2026-10-22-s32-connector-baseline.md.
- **Design and plan:** docs/superpowers/specs/2026-10-22-s32-connectors-design.md
  (decisions 1–11, Hunaiza's; builder-checked), the 13-task plan
  docs/superpowers/plans/2026-10-22-s32-connectors.md.
- **Built:**
  - the SDK, a separate distribution under `sdk/` (`auspex-sdk`, import
    `auspex_sdk`): vocab pinned equal to the core's; manifest v1 with
    `validate_manifest`; packages and their tree hash; the runtime (decorators,
    typed context, a host-bound HTTP client with TLS pinning, redacting logs,
    result encoding); `auspex-sdk build` (Python or YAML → one manifest); the
    harness over recorded exchanges;
  - the reference connector `examples/connectors/mock_siem/` (both forms);
  - `auspex/connectors/`: `compile_action` (four dispatchers, wire names
    `<prefix>__<action>` ≤ 64), connector job kinds, the catalogue
    (`connector_packages`, `register`, `available`, the first-party CLI
    `python -m auspex.connectors register --first-party`), and
    `POST`/`GET /api/connectors`;
  - `FINGERPRINT_VERSION = 2` (connector origin in the canonical spec; v1
    approvals refused with a scheme-change reason);
  - **B-026 fixed** (`c0b30de`, `19282ae`): undeclared arguments refused at
    propose, file, execute and undo;
  - structural tests (the core never imports connector code or YAML) and the
    worker's failing-`fail` test.
- **Decided:** D-071 (a provider and its clients are one customer for D-062;
  a certificate pin replaces the chain check).
- **Live:** docs/probes/2026-10-22-s32-connectors-live.md: built, registered by
  a provider admin, offered and listed by its clients only, then first-party
  and listed everywhere; all deleted afterwards.
- **Reviews:** per task for Tasks 1–10 (opus for 8 and 9, the approvals core);
  Tasks 11–13 inline at Hunaiza's request; one fresh final review of the whole
  branch: no Critical or Important; three minors fixed (`5eb852b`, `e4a653f`,
  `02cda97`), one logged (TD-069).
- **Debt:** TD-066…TD-069. **New dependency:** `python-multipart`.
- **No new env vars.**

## S33 — what happened (backend track; integrations, the Edge Agent, Test connection)

Hunaiza's session (D-059), 2026-10-28, on the branch `s33-edge-agent`, to
`staging` by one PR. Full record of calls: docs/superpowers/records/2026-10-28-s33-record.md.

- **Step 0:** PR #43's ten findings fixed, one commit each (rows marked in
  docs/probes/2026-10-28-pr43-review.md); 6, 7, 8 and 10 reproduced first
  (docs/probes/2026-10-28-s33-pr43-6-7-8.md, …-10.md). **D-072** (Hunaiza's):
  the SDK version is recorded in the zip's comment, not hashed. A fresh
  adversarial review of the fixes found two gaps (a post-claim refusal read
  "effects unknown"; race paths skipped the offer check): fixed, re-reviewed,
  approved. Baseline: docs/probes/2026-10-28-s33-baseline.md.
- **Design and plan** (Hunaiza's three calls: an integration names one agent;
  actions wait for S34; disable, never delete, prefix never reused):
  docs/superpowers/specs/2026-10-28-s33-edge-agent-design.md, builder-checked;
  docs/superpowers/plans/2026-10-28-s33-edge-agent.md (nine tasks, inline).
- **Built:** `auspex/integrations/` (store, routes, Test connection),
  `auspex/edge_api/` (agents, credential auth, the edge API: long-poll claim,
  validated results, heartbeats extending leases, packages by hash),
  `auspex/edge/` (the agent), `auspex_sdk.run` and `auspex_sdk.validate`,
  `connector.test` (`auspex/connectors/kinds.py`), `extend_leases` (TD-064's
  heartbeat half), `Dockerfile.edge`, compose `edge` and `mock-siem` (dev
  profile), **D-073** and the audit actions.
- **Live:** Test connection answered `ok: reachable` through the real `edge`
  container against `mock-siem` with its certificate pinned; offline refused in
  words; the secret in no log or row.
- **Review of the build:** a self-review (no helper agents, Hunaiza's
  instruction); one gap fixed (`2d18930`).
- 2183 tests; 153 modules; env vars `AUSPEX_URL`, `AUSPEX_AGENT_TOKEN(_FILE)`,
  `AUSPEX_SECRETS_FILE`, `AUSPEX_AGENT_CACHE`, `AGENT_UID/GID` (agent and dev
  only), `AUSPEX_SDK_RUN_FIXTURE` (tests only).

## B4 — what happened (bugs track's fourth session)

Hunaiza's session (D-059), 2026-10-28, on the branch `b4-bugs`, to `staging`
by one PR. Scope fixed by Burhan: six bugs, every one required. Each was
reproduced first (a "before" saved), fixed with a test that failed first and
the exact input pinned, checked live in the rebuilt container, and reviewed by
a fresh agent; each review found something, all fixed or logged.

- **B-018** (`d78bc43`, `42ffd65`; #44): the userinfo is dropped by text
  before the URL is parsed. The review found the parse-failure fallback and a
  `/ ? #` in a password still leaking (fixed); TD-070 is the ambiguous limit.
- **B-025** (`6310550`, `e145583`; #45): `enter()` is one transaction with the
  person's row locked `FOR SHARE` first; login and switch races pinned (both
  failed on the old code). Adversarial review: approved, no deadlock cycle.
- **B-017** (`59d9a7c`, `0d6f980`; #46): a tool call's fields and the
  stream's call list/index read as text or empty, never raised on; the loop
  answers "unknown tool".
- **B-027** (`be208f4`, `3ca52d7`; #47): a sorted `_Spans` index; at the cap
  about 1,089 ms → 23 ms CPU for 4,571 emails. The review made the tests
  firm: growth in CPU time, boundary mutants caught.
- **B-030** (`aedb018`, `98cffb7`; #48): `_quote_line_spans`, the regex's
  spans in one pass; 2,875 ms → 20 ms; the rule-hit stall input added.
  Adversarial review: 0 differences on 300,000 texts.
- **B-032** (`f837432`, `7e11b36`; #49): the run-led rules' text, flags and
  start sets pinned; the `{{system}}` mutant (and a flag mutant) now fail it.
- **PR #50's review round** (Burhan): B-018 re-fixed by the URL standard
  (`2837720`), B-017's numeric-string index (`45314f8`), B-036…B-039 logged.
- **Logged from the reviews:** B-033 (a pasted credential in the stored
  message and pre-fix rows), B-034 (the membership API stamps a home read at
  the request's start), B-035 (a malformed reply envelope still crashes the
  parsers), TD-070.
- 2091 tests; 139 modules; no env vars; no new dependencies.

## B3 — what happened (bugs track's third session)

B3 ran 2026-10-19, by Hunaiza (D-059), on her own machine as `HunaizaK`.
Record: docs/probes/2026-10-19-b3-b010-b024.md. Her calls:
- B-024's UX: **a Switch button** (over "Enter to switch");
- the fourth backtracking rule the review found: **fixed inside B-010**;
- **a PR into `staging`** at the close, not a push (Burhan merges);
- no commit until the full gate and the live checks had passed.

1. **Setup.** Her app container would not rebuild at first: pip timed out on
   `pydantic-core` over a slow network and reported it as a version conflict.
   It built on retry. Ollama is not installed on her machine (no B3 bug needed
   an engine).
2. **B-010 fixed (`0207b4a`).** Reproduced first, worse than logged: at the
   32,000 cap `classify("hi" + spaces + "x")` took 101.5 s on her host and
   41.8 s in the container.
   - The refang rules take whitespace only from where its run begins.
   - `_GREETING_RE` and `_ANALYTICAL_INITIAL_RE` (the fourth, found by the
     review: 64.3 s on `"." + spaces + "x"`) are possessive.
   - `_DOMAIN_CAND_RE`/`_EMAIL_RE` are unchanged, searched by linear scans
     that skip only positions proven to fail. The note's "start only at the
     beginning of a dotted run" would have lost `my_host.evil.com` →
     `evil.com`.
   - Worst message at the cap: about 12 ms. Same matches: 0 differences on
     200,501 inputs over six rules. Mutants 7/7. The exact inputs are pinned
     and run at full size under a 10 s timeout.
3. **B-024 fixed (`2bc5eec`).** Reproduced live: three arrow presses, three
   switches and reloads.
   - The fix: choosing only selects; the Switch button (`switchReady` in
     `js/shell-logic.js`) switches.
   - Live: arrows made 0 switches; Tab and Enter, or a click, made exactly
     one; zero CSP violations; phone width fits. Mutants 6/6.
   - **The first build broke every page** (a TDZ error: `showSignedOut` has
     its own `const go`). The live check caught it; the source-reading tests
     could not.
4. **Reviews (fresh agents).** No Critical in either. Fixed: the fourth rule,
   weak timing inputs, a wrong comment, the button's gap, its state on render,
   its screen-reader name, a failure-path test. **Logged for Burhan: B-027**
   (`extract()` is O(matches × spans), 0.2–0.8 s) **and B-028** (a failed
   switch after a re-check with one workspace throws; predates B3).

+11 tests (1687 → 1698). No engine calls, no new env vars. GitHub #38 and
#39 have the commits in a comment; they close when the PR is merged.

**Burhan's review of PR #41 (2026-10-20), answered on the same branch.**
Items 1–7 became B3's scope by his call.
1. **B-029 fixed (`8c51cb4`).** The input guard runs before classify, and two
   of its rules had the same shape: `inspect("\n" * 31999 + "x")` took
   130.7 s. They are now searched by a run-aware scan, and persona_override's
   prefix is possessive. Result: 11–15 ms at the cap. Every verdict and span
   is unchanged: 0 differences on 200,501 inputs against the old guard.
   SESSION-RULES.md records his speed-only exception to "do not re-open the
   guard regex" (`e3665d9`).
2. **The pinned inputs run through the route's whole text pass** (guard,
   extract, classify), with B-029's newline inputs, each under 1 s
   (`f63d6ed`).
3. **The Back/Forward live check** switches with the Switch button. Re-run with
   the cache ON, it gives F4's after-fix result (`b325432`).
4. **A choice not yet switched to is pending.** The select turns Signal and the
   status reads "still in <active> — Switch to move". A turn snaps it back
   (`a045881`). Live: the header names the active client while a turn runs.
5. **`switchTo` asks `switchReady`** (`e069bd9`). It went in with an F4 pin
   failing; `af26499` fixed that pin. Commits now wait for green tests.
6. **A failed switch is announced and gives focus back.** `#status` is
   `role=status` (`1720719`). The live check showed focus still falling to
   `<body>` after the re-check rebuilt the header. A rebuilt picker now keeps
   the old one's choice and focus (`1db360a`), which also covers the review's
   optional "pending choice lost on re-check".
7. These records. The review's idea is parked in IDEAS.md (`d1137d8`). Two
   optional items were not taken: one C call for `_domain_candidates`' label
   chain, and moving the timing helpers to `conftest.py`.

**GitHub's run, then the re-review (2026-10-20).** GitHub's CI failed one
timing bound on runner noise: a single 84 ms sample of a call that takes 4 ms
locally. `tests/_timing.py` now times each input three times and keeps the
fastest, from one shared helper (`65c101f`). The re-review then asked for
three things:
- **A.** A pending choice blocks Send (`464503e`). This replaces the
  snap-back. Live: 0 `POST /api/chat`.
- **B.** The pending note is organization-first.
- **C.** A test pins the guard's scan to the live rules (`bb80411`).

It also logged B-030 and B-031 (`a2f7d47`). Commits use `feat|fix|chore`
only (CLAUDE.md rule 10).

## S31 — what happened (backend track; the jobs queue and TD-025's first half)

S31 ran 2026-10-16, alone, on Burhan's machine. Burhan's calls, one at a time:
- **D-069 built here** (Step 0); a `ksa` workspace already on a deployment
  whose storage may not hold it is **named in a startup WARNING**, not refused;
- the design's five: **a 24 h TTL**; an expired card **listed 24 h, then
  gone**; **one idempotency key per operation**, used by the note action;
  **per-kind lease and attempts** (60 s, 5; backoff 30 s doubling to 15 min,
  then `dead`); **the expiry sweep as a real job**;
- the spec, the plan, **subagent-driven execution**.

1. **Step 0.**
   - **B-021 fixed** (`b1fa61e`): a rehome's event keeps only `to`, the CLI
     prints the old home, and the rehome locks `users` alone (a second
     concurrent rehome no longer answers NotFound). Its fresh review found no
     leak to the new home's admins; its test gap was pinned (`3d5007b`); an
     older race it found is **B-025**.
   - **D-069 built** (`6cd68e9`, addendum in DECISIONS.md): `STORAGE_REGION`
     (born with its docs); `create-org`/`create-client` refuse a workspace the
     storage may not hold; startup names any already there. Its fresh review
     found no bypass; two pins hardened (`34d5650`).
   - Reality probed: docs/probes/2026-10-16-s31-jobs-baseline.md.
2. **Design** (docs/superpowers/specs/2026-10-16-s31-jobs-design.md, with an
   "after execution" note); plan docs/superpowers/plans/2026-10-16-s31-jobs.md,
   eight tasks.
3. **Built** (`f5c3479`…`d2dedd0`, each task by a fresh agent, each reviewed by
   another; Task 2 needed one fix round):
   - `auspex/jobs/`: `queue.py` (`jobs`, `job_turns`; an idempotent `enqueue`;
     a scoped `FOR UPDATE SKIP LOCKED` claim serving workspaces in turn;
     leases, backoff, `dead`/`failed`; token-checked `complete`/`fail`; the
     claimer cleared on every exit from `claimed`) and `worker.py` (kinds and
     schedules in code, bucketed keys, `tick`/`run`); the worker in the
     lifespan behind `JOBS_WORKER_ENABLED` (pinned off for host and test runs);
   - pending proposals expire after 24 h: `settle`'s own UPDATE refuses an
     overdue one and moves it to `expired` (the new status, in the one CHECK
     block); the `proposals.expire` job (`auspex/actions/expiry.py`) is the
     sweep; listed for 24 h; approve and reject answer 409 "expired: nobody
     decided within 24 h; propose it again";
   - `operation_key` (`proposal:<id>:execute|undo`) handed to execute, undo
     and observe; `validate_spec` refuses a handler that cannot take it, and a
     parameter named `workspace_id`, `proposal_id` or `idempotency_key`; the
     note action writes once per key;
   - the page: "Expired: nobody decided in time; propose it again", no doors;
     the approvals badge counts only cards a human can act on.
   - Rulings on the per-task reviews: the claimer cleared on every exit (spec
     §1 over the plan's SQL); a `SKIP LOCKED` pin the brief lacked; two expiry
     tests made able to fail; the badge count (a consequence of call 2).
4. **Proof.** Gate green (1603 → 1687). Mutants on every guard. **Live**
   (docs/probes/2026-10-16-s31-jobs-live.md): the rebuilt container's worker
   expired an aged proposal through the real job (`done` in 11 ms,
   `{"expired": 1}`); approve and reject answered 409 in words; in Chromium the
   expired card reads as designed, the badge counts 1 of 2, and "Nothing is
   waiting on you." once only the expired card is left; zero CSP violations.
5. **The final adversarial review** (fresh agent, the most capable model, every
   finding reproduced): the core held every attack (300 settle-versus-sweep
   races at the boundary, 0 inconsistent; 16 claimers with leases expiring
   mid-handler, no double completion; every scope attack). **Important:** a NUL
   or a lone surrogate in a job's error or result aborted the tick and lost the
   error. **Minor:** a booting replica's migration could deadlock with a live
   claim (1 boot in 30). One fix wave (`0cd32df`…`75af29b`): the answer writes
   are total; `claim` and `enqueue` take `MIGRATION_LOCK` shared; the `enabled`
   wiring and the dead step's scope pinned; `Schedule` validates its interval;
   the SDK's example fixed. **Its own fresh review:** all addressed (60/60
   migrations under load, 0 errors); minors parked (#30).
6. **B-026** found by the key's review and reproduced live: an undeclared
   argument named like a platform keyword is approved, then the run fails into
   `incomplete`.

No engine calls. Two new env vars (`STORAGE_REGION`, `JOBS_WORKER_ENABLED`).
+84 tests (1603 → 1687), +4 modules (129 → 133). Logged: B-025, B-026,
TD-063…TD-065.

## F4 — what happened (front-end track; one shell for every page)

F4 ran 2026-10-16, alone, on Burhan's machine. Burhan's calls, one at a time:
- **all four candidates in** ("[connection lost]", TD-047, the stale proposal
  line #20, F2's page with live turns); analyst notes out;
- **a switch reloads the page**; **a read-only Members page** is the first admin
  entry; **a native select**; the spec, the plan, **subagent-driven execution**.

1. **Step 0.** Reality probed before any code
   (docs/probes/2026-10-16-f4-s30-routes.md): `/me` and the switch as six
   people across a provider, a ksa client and a restricted client. Every
   prompt claim held. New: the switch answer names no organization, a 422's
   `detail` is an array, a viewer cannot send even a shortcut question, an
   explicit membership reaches a restricted client.
2. **Design** (docs/superpowers/specs/2026-10-16-f4-shell-design.md, plan
   docs/superpowers/plans/2026-10-16-f4-shell.md, nine tasks). **D-070:** a
   switch reloads without the hash; `/me` is the page's only judge of access;
   the page never computes the switchable set.
3. **Built** (`4ac7891`…`e73b22a`, each task by a fresh agent, each reviewed by
   another; Task 4 needed one fix round):
   - shared modules: `css/base.css`, `js/dom.js` (one `el`), `js/api.js` (the
     one client; the bearer header lives only here), `js/shell-logic.js`
     (pure: nav, switcher labels, one error copy), `js/shell.js`
     (`startShell`: header, sign-in, the switch, the `/me` re-check);
   - chat and the timeline on the shell (the timeline lost its own sign-in and
     pre-filled address); a viewer gets no composer, no New chat, no doors;
     the switcher and Sign out hold still while a turn streams;
   - `/members` (read-only, admin; the server's 403 for anyone else);
   - **TD-047 closed** (304s on every page and file); "[connection lost]" →
     a sentence; **#20 fixed** (a reopened proposal line follows the panel);
     **F3's deferred minors (#25) fixed**; D-070 written.
   - Plan defects found by implementers and ruled on: a plan comment that named
     `request.headers` (the tenancy walk forbids the text); a viewer test that
     could never pass; sign-in unguarded in flight (could run `ready` twice).
4. **Proof.** Gate green (1554 → 1603). **Mutants 10/10** caught. Live, two
   clients and every role (docs/probes/2026-10-16-f4-shell-live.md): after a
   switch nothing of the first client on screen, in storage or in any request
   (5/5 requests on the new token); the residency sentence; viewer/analyst/
   admin as designed with the server refusing anyway; a removed membership
   signs the tab out in the server's words; zero CSP violations at 1280 and
   390 px on all three pages.
5. **F2's page with live turns (#26), 8 engine calls:** Review → Approve → Undo
   on a reopened proposal, the line following each step; the rail's and the
   usage ceiling's sentences; narration on its own line. Not reached: the
   empty-answer note. **B-022** found (the rail cut a note-only request).
6. **The final adversarial review** (fresh agent, most capable model):
   **Critical C1** — Back/Forward undid the switch and sign-out guarantees (the
   back/forward cache restored the previous client's live page; a fresh Back
   load sent the old chat id under the new token). **Reproduced live before the
   fix** with the cache on (headless Playwright disables it). Also: the bidi
   fix could be escaped, four D-070 guarantees were unpinned. One fix wave
   (`bd5e6af`…`7057ca4`): a `pageshow` reload, `history.state` owning the
   chat hash, `isolateName`, the pins, TD-061/TD-062, D-070's history bullet.
   Its own fresh review: all addressed; five minors parked (#29). Live after:
   Back loads fresh, sends no old chat id; the hostile label reads in order.

+49 tests (1554 → 1603); no new modules; no new env vars. Logged: B-022,
B-023, B-024, TD-061, TD-062.

## S30 — what happened (backend track; MSSP tenancy)

S30 ran 2026-10-15, alone, on Burhan's machine. Burhan's calls, one at a time:
- **the five design questions** D-061 left (D-068): only a CLI creates
  organizations and workspaces; a dev login auto-provisions as before; one
  organization per migrated workspace; workspace admins read their audit;
  `global` and `ksa`, a `global` processor serves only `global`;
- **the design**, section by section, and the spec and plan;
- **subagent-driven execution**;
- at the close: **promote now, fix B-021 next session**, and **overturn
  D-061's storage bound** (D-069).

1. **Step 0.** Reality probed (docs/probes/2026-10-15-s30-tenancy-baseline.md):
   3 workspaces, 13 users all in `default`, no email in two workspaces, no API
   keys; every route on `resolve_user`, none reading a workspace id from input.
2. **Design and plan.** Spec docs/superpowers/specs/2026-10-15-s30-tenancy-design.md
   (with an "after execution" note); plan
   docs/superpowers/plans/2026-10-15-s30-tenancy.md, nine tasks. IDEAS: RLS as a
   second wall, changing a live workspace's region.
3. **Built** (`b93791c`…`29c6ae8`, each task implemented by a fresh agent and
   reviewed by another; Tasks 3 and 5 needed one fix round each):
   - `auspex/tenancy/`: `region.py` (`ENGINE_REGION`, born with
     `.env.example`/`docs/ENV_VARS.md`), `access.py` (`enterable_workspaces`),
     `audit.py`, `admin.py`, `entry.py`, the CLI `__main__.py`;
   - the migration: identity left the workspace (persons with a home
     organization, memberships, `audit_events`); it ran on the dev database;
   - `resolve_user` re-checks access every request (JWT and API key); roles
     enforced on every write; `POST /api/auth/switch`, `GET /api/auth/me`;
   - `auspex/routes/workspace.py`: the membership API and `GET /api/audit`;
   - the region guard over chat, the investigation summary and lookups, and
     every enrichment provider;
   - structural suites that walk the app (every write role-guarded; no tenant
     id from input, every spelling; region pins) and a cross-tenant suite
     through HTTP; **mutants 10/10** (one needed an added pin).
   - Task-review fixes: `__deployment__` refused explicitly, the create paths
     pinned, `set-member` no longer silently withdraws a grant (Task 3); the
     tenant-id walk normalised and unwrapping nested bodies (Task 5).
4. **The final adversarial review** (fresh agent, the most capable model,
   every finding reproduced by execution): **no tenant-isolation or residency
   break.** Three Important, fixed in one wave (`137eedd`…`e951ce6`):
   - two admins removing each other at once left zero admins (19/20 over
     HTTP) → membership writes hold the workspace row and re-check the acting
     admin inside the transaction;
   - a mis-homed person had no recovery → `rehome-person` (audited
     `person.rehome`); creation over the API stays open, **TD-059, a hard gate
     beside TD-001**;
   - the ksa agent path was unpinned (a forcing mutant survived 183 tests) →
     pinned; also a malformed token claim was a 500 → 401, the auth docstring,
     an offset-less audit `before` → 422, the README says where a workspace's
     records are stored.
5. **The fixes' own fresh review** (stress: 1,800 concurrent operations, no
   deadlock, no admin-less workspace): all addressed; **B-021** open (the
   re-home event names the old organization to the new one's admins), two
   minors with it. **Burhan: promote now, fix next session.**
6. **D-069** (Burhan: overturn): a `ksa` workspace will live only on a
   deployment that stores data in KSA; placement of the build is his call.
7. **Live** (docs/probes/2026-10-15-s30-tenancy-live.md): the CLI built a
   provider and a ksa client; `/me` listed both; a provider-wide switch into
   the client; a deep turn there refused 403 before anything was stored; the
   CVE shortcut answered; the entry audited; rows cleaned up.

No engine calls. One new env var (`ENGINE_REGION`). +142 tests (1412 → 1554),
+8 modules (121 → 129). Logged: B-021, TD-059, TD-060; IDEAS: API keys a
workspace admin can see, offboarding across clients.

## S29 — what happened (backend track; opens the integration phase)

S29 ran 2026-10-14 into 2026-10-15, alone, on Burhan's machine. Burhan's calls,
one at a time: every decision of the phase (below), the QRadar's data ("some
real data") and its address ("later").

1. **Step 0.**
   - The working tree on `f3-timeline-csp` held uncommitted edits reverting
     STATE.md and both prompt files to `staging`'s pre-F3 versions
     (byte-identical to `ff19016`); restored to HEAD, nothing lost.
   - **F3's PR #34** reviewed (feed text built as text, the CSP on both pages,
     GitHub CI green) and merged by fast-forward, keeping Hunaiza's
     one-concern commits and the SHAs STATE.md cites.
   - **Promote #35** (`1a7708f`, back-merge `a8503f6`): D-059 and the handoff
     docs, the integration plan, all of F3. Gate green at 1392; GitHub CI
     green twice.
2. **The adversarial review of S28's code** (record:
   docs/probes/2026-10-14-s29-s28-code-review.md; scripts in
   docs/probes/s29-review/). Four fresh read-only reviewers, one per area;
   every finding reproduced by execution here before anything was fixed.
   **21 findings: 7 fixed, 13 logged, 1 already Deferred.**
   - **Two HIGH, fixed (`8187925`):** D-047's identity lead-in backtracked
     exponentially (1.3 s for 55 characters, ~13 min within its 80-character
     cap) and D-050's note-request prefix quadratically (~1 min at 32,000
     characters, twice a turn), both on the route's event loop. Possessive
     whitespace; 0 of 58,707 differential inputs changed; the D-047 and D-050
     pins hold.
   - **`14bafba`:** a context-only lookup (InternetDB's ports, or reputation
     sources down) overwrote a stored `malicious` verdict with `unknown`, a
     flip, and retired watchers, against D-055's own text. Reproduced live.
   - **`b069b84`:** a KB snippet cut inside an indicator supplied a different,
     real one (`185.220.101.45` → `.4`), sent to providers and recorded.
   - **`6750028`, `39908b5`:** D-046's "up to 5 calls" did not hold (a model
     calling the withdrawn tool ran to 9), and a failed call spent the budget
     without the notice.
   - **`d16afaa`:** `e2af082` dropped `alert.name` / `detection.name`.
   - **Logged:** B-010…B-019, TD-056…TD-058.
   - **The fixes had their own fresh review**, which found two defects in the
     budget stop, both fixed (`47c3f35`, `34fe9a1`), plus B-020 and a third
     old stalling rule (added to B-010). +20 tests (1392 → 1412), each failing
     first; mutants caught on every guard (one surviving mutant got a pin).
3. **Goal 1: the phase's spec and D-060…D-067**
   (docs/superpowers/specs/2026-10-15-integration-phase-design.md), Burhan's
   call on each:
   - **D-060 words:** connector, integration, case, Edge Agent / Cloud Agent.
   - **D-061 tenancy:** a provider's own workspace; explicit memberships plus
     an opt-in provider-wide grant, with `restricted` clients; roles admin,
     analyst, viewer; one workspace per token; a region guard over the engine
     AND third-party enrichment.
   - **D-062:** outbound-only Edge Agents, one workspace each, running
     hash-pinned packages (pulled, or installed locally when air-gapped).
   - **D-063:** edge secrets are names in Auspex; only Cloud Agent secrets are
     sealed.
   - **D-064:** one canonical `manifest.json`, written in Python or YAML,
     compiled to today's `ActionSpec`; the fingerprint gains the package hash.
   - **D-065:** our own SKIP LOCKED jobs table. **D-066:** TD-023/TD-025 out
     of Deferred, in TD-025's order. **D-067:** live QRadar checks on a
     synthetic-only lab domain.
   - Supersedes nothing. SESSION-RULES.md's Deferred list updated (`f0ad2ef`).
4. **Goal 2: QRadar** (docs/probes/2026-10-14-qradar-reachability.md). It
   holds some real data, hence D-067. **The address is not given yet**, so
   reachability, TLS and the unauthenticated API answer are unprobed; S33's
   Step 0 runs them once Burhan gives it.
5. **Goal 3:** S30–S41 and F4–F9 re-checked against the spec (`3d017b3`,
   `c38fbde`): the words, S30's provider workspace and region guard, S32's
   two authoring paths, S33's pull-by-hash and Step 0 probe, S36 on the lab
   domain, F5's memberships admin. The order is unchanged.

No engine calls. No new env vars (`ENGINE_REGION` is born in S30). +20 tests.

## F3 — what happened (front-end track's third session)

F3 ran 2026-10-14, by Hunaiza, the collaborator Burhan handed it to (D-059),
on her own machine as `HunaizaK`. Her calls:
- Step 0's `/promote` skipped: nothing goes to GitHub until she has checked
  the work on her own container, then **a PR into `staging`** at the close
  (Burhan reviews and merges it);
- Step 0 item 3 (F2's page by hand) walked in headless Chromium;
- the timeline's logic in its own tested module; **no helpers shared with the
  chat page** (spec decision 2); behaviour and copy unchanged;
- native execution of the plan; "just follow exactly what's told in F3".

1. **Setup on her machine.** Her user was not in the `docker` group (added;
   a `setfacl` on the socket until her next login). `/usr/bin/node` is v18,
   which cannot load the page modules, so the chat page's own Node tests
   failed too; every gate ran with nvm's v22 first on `PATH`.
2. **Mid-session, Burhan's planning commits** (`34598e9`…`ff19016`) were
   merged into her `staging` (`7c64126`). F3's prompt was unchanged.
3. **Goal: TD-051 closed.** Spec
   docs/superpowers/specs/2026-10-14-timeline-page-csp-design.md, plan
   docs/superpowers/plans/2026-10-14-timeline-page-csp.md.
   - `timeline.html` is 27 lines of markup; `css/timeline.css`;
     `js/timeline-logic.js` (count, pct, conf, the claim colours, the digest
     banner; 14 Node tests, `tests/test_timeline_logic.py`); `js/timeline.js`
     builds every card from elements and text, no `innerHTML`, no `esc()`,
     widths through the CSSOM, listeners instead of `onclick=`.
   - A verdict with a missing confidence now shows "—" and an empty bar
     instead of failing the whole timeline (`conf`/`pct`).
   - `/timeline` carries the chat page's exact policy, pinned for both pages
     (`test_each_page_is_served_with_the_same_strict_policy`).
   - The old `onclick="open_(&quot;…&quot;)"` could be broken by a `"` in an
     observable id; the link now carries the id in a closure.
4. **Proof.** Every test failed first; mutants 3 + 3 + 1, all caught. Live in
   Chromium against the rebuilt container, with seeded probe rows deleted the
   same command: zero CSP violations, an `<img onerror>` value, source and
   trigger rendered as text, a link whose id holds `'` and `"` opened the
   right timeline (docs/probes/2026-10-14-f3-timeline-csp.md).
5. **The final review (opus)**: no Critical; two Important, both fixed (a test
   for "there are more"; the link path checked live); five Minor deferred
   (follow-up #25).
6. **F2's page by hand (Step 0 item 3), as `hunaiza@analyst.dev`:** sign-in,
   the sidebar, reopen (divider, spend lines, chat total), reload keeps the
   sign-in and the chat, + New chat, phone width (Chats, backdrop, Esc), Sign
   out, a new tab signed out: all as designed, zero CSP violations. **Not
   reached:** Review/Undo (no saved proposal; it needs a paid turn), the
   empty-answer note, server errors, narration — all need live turns.

No engine calls. No new env vars. +7 tests.

## B2 — what happened (bugs track's second session)

B2 ran 2026-10-13, alone. Burhan picked the bugs one at a time: **B-002, then
B-004, B-006 and B-008**, all fixed. He made seven calls along the way:
- B-002: option A, then narrowing it after review;
- B-004: code, not prompt;
- B-006: code and prompt, then closing the context-only gap;
- B-009: closed B-006 and logged B-009;
- B-008: discard on refusal.

**Each fix had a read-only adversarial review by a fresh agent. Two of the
four found a real defect, both fixed the same session.**

No promote at Step 0: the slate held only F2's session-end docs.

1. **B-002 → D-058 (`4b753d4`, narrowed `d8c597b`).** Record:
   docs/probes/2026-10-13-b2-b002-reproduce-and-calibrate.md.
   - **Not reproduced live: 0/6 today.** The endpoint restated the definition
     contract's sections as its plan in every run, but with "each term" and
     "meets them", so the longest run was 11. At F1 it was 40. The
     composition was byte-identical to F1's; the KB results differed.
   - **Reproduced at the route** with F1's exact logged run.
   - **Root cause.** The tokeniser makes a section list ONE run: definition
     43 words, threat_intel 42, D-043's re-ask 42–44. All are longer than the
     thinking floor of 40.
   - **Both floors re-measured on today's index (TD-044).**
     - The answer floor: legit max 5 against 8.
     - The agent path, 36 legitimate turns (S26's battery plus a blind one):
       thinking 28, answer 5, narration 3, tool lines 3. A recitation ran 58.
     - Neither floor moved.
   - **D-058.** The thinking index drops the re-ask and the runs lying WHOLLY
     inside a section list; every other channel keeps all of it at 8.
     Re-scored against that, the thinking ceiling is 20.
   - **The review found the first cut too wide.** It exempted the whole
     directive, which on the conversational path (a 22-word chat prompt) left
     a recitation of alert/phishing directives in thinking uncut. Narrowed
     (D-058 addendum).
2. **B-004 fixed (`29209fa`).** Record:
   docs/probes/2026-10-13-b2-b004-reproduce.md.
   - **Live 3/3:** in a fresh chat the model passes the indicator itself, and
     the note action resolved only the short id.
   - **The fix.** It now also resolves exactly one indicator, parsed with the
     route's extractor, inside the workspace. Live 3/3 proposed.
   - **The review** found that the route test could delete real dev rows on
     the shared workspace. Fixed (`943d285`). The latent execute-time
     retargeting is TD-054.
3. **B-006 fixed (`fce2f55` code, `c80bf29` prompt, `58b45e4` after review).**
   Record: docs/probes/2026-10-13-b2-b006-reproduce.md.
   - **Live 3/3:** "dig deeper" ran in `general` and read a bare
     `"signals": []`, then called the IP clean.
   - **The fix.** The agent's lookup says `"reputation": "unknown"` with a
     code-written line, also for context-only signals (the review's gap).
     general carries ioc_enrichment's no-data rule (D-044 addendum).
   - **Live:** a benign verdict 3/3 → 0/3; "unknown" 0/3 → 3/3.
   - **Residual: B-009.** The model still calls the address "legitimate",
     inferred from its operator.
4. **B-008 fixed (`4680bf6`).** Record:
   docs/probes/2026-10-13-b2-b008-ceiling-refusal.md.
   - **Reproduced at the route.**
   - **The fix.** A turn refused at the ceiling deletes the question it
     stored, and the chat if it made it.
   - **Live at a set ceiling** (the counter was restored): 429, nothing
     stored, no chat added.
   - **The review found no defect.** Its bounds are TD-055.
5. **Logged, not fixed:** B-009; TD-054 and TD-055. TD-044 was updated: two
   later index additions, and general's rules are now one 43-word run, over the
   thinking floor and unmeasured.

**How the work was proven.**
- Every fix shipped with a test that failed first; the exact offending text
  is pinned in `tests/fixtures/{rail,actions,agent}/`.
- Mutants were run on every guard: 4+4+3+3+3+1+3+3, all caught.
- The full gate ran after every fix, and each fix was checked live.
- About 250 inference calls on Z.ai: the calibration ~150; reproductions and
  live checks ~100.

## F2 — what happened (front-end track's second session)

F2 ran 2026-10-12, alone. Burhan's calls: fix B-007 inside Step 0's promote;
the sign-in kept in the tab's sessionStorage (D-056); an always-on chat
sidebar; a reopened turn brings back its proposals only, with no new storage;
the route named `/turns`; all three candidates into F2; the page split as a
logic module plus one DOM module; the CSP in the same session (D-057);
subagent-driven execution for the reload plan, native for the split.

1. **Promote #31 at Step 0, after B-007.** GitHub's runner Node printed TAP, so
   F1's page-logic floor found no `ℹ pass` line: the PR went red while
   `./ci.sh` was green locally. Fixed by naming the reporter (`b8ee7fd`).
2. **Burhan's hands-on test of F1's page** matched what was predicted; nothing
   new was logged. He asked where analyst notes go (nothing reads them back:
   IDEAS) and proposed incident management with bring-your-own integrations
   (IDEAS; a phase of its own, with prerequisites on record).
3. **Goal: a chat survives a reload.** Spec
   docs/superpowers/specs/2026-10-12-chat-survives-reload-design.md, plan
   docs/superpowers/plans/2026-10-12-chat-survives-reload.md; 8 tasks, each
   reviewed by a fresh agent.
   - `GET /api/chat/sessions` and `GET /api/chat/sessions/{id}/turns`, paired
     by the pure `auspex/chat_history.py`, scoped to the workspace AND the
     user (a foreign chat is a 404 like a missing one).
   - The page: sign-in in sessionStorage with Sign out (D-056); the sidebar;
     the open chat in the URL hash; a reopened chat with its spend lines and
     its proposals, whose Review brings back the card's doors (Undo).
   - The whole-branch review (opus) found an `openChat` race that could switch
     chats under a streaming turn; it and ten small guards were fixed in one
     wave. Live: docs/probes/2026-10-12-f2-chat-reload-live.md.
   - TD-050 and TD-052 logged; B-008 logged.
4. **S26's chat edges** (`627e370`, `6445546`, `86b9c72`): an empty answer
   says so; errors in the server's own words; narration on its own line.
   docs/probes/2026-10-12-f2-s26-edges-live.md.
5. **Narrow screens** (docs/probes/2026-10-12-f2-narrow-screen.md, with
   before/after screenshots): the header 132 → 101 px with no wrapped label;
   one backdrop that closes either overlay (tap or Esc), one open at a time; a
   full-width approvals panel on a phone; dark scrollbars.
6. **TD-045 closed, then D-057.** Spec
   docs/superpowers/specs/2026-10-12-page-split-csp-design.md. `index.html` is
   62 lines of markup; `css/chat.css`, `js/page-logic.js` (the Node tests
   import it) and `js/chat.js`, served no-cache from an allow-list. The chat
   page carries a strict CSP; TD-051 narrows to /timeline. The review (opus)
   found R7's guard incomplete and D-057 overstating `connect-src`; both fixed.
   docs/probes/2026-10-12-f2-page-split-csp.md.
7. **Promote #32** at the close.

**Data note.** Deleting the probe user `fe-probe@auspex.dev` in the reload
probe also deleted F1's probe chats (F1's evidence lives in docs/probes).

**How the work was proven.** Every change shipped with a test that failed
first, and mutants were run on every guard. Each page change was checked in
headless Chromium against the rebuilt container. Two whole-branch reviews ran
on the most capable model. About 15 engine calls on Z.ai, plus Burhan's own
hands-on turns.

## B1 — what happened (bugs track's first session)

B1 ran 2026-10-12, in two halves around F1 (above). Burhan made two calls:
where the owner lives (D-055), and ending after B-001 rather than taking
another bug.

1. **Promote #30** (Step 0): see the collision note above.
2. **Goal: B-001, the invented IP owner — fixed (`a90e18a`).** Record:
   docs/probes/2026-10-12-b1-b001-fix.md; scripts and logs in
   docs/probes/b1-b001/.
   - **Reproduced through `/api/chat`, both endpoints, 3 runs each.**
     - glm-4.5-air took the agent path and looked the IP up: 0/3 invented an
       owner.
     - qwen3:14b took the conversational path with no tools: **Amazon 3/3**,
       claiming WHOIS and Shodan.
   - **Why no tools.** "dig deeper" resolves to `general`, because the
     resolver reads only the current message (`auspex/modes/resolver.py:129`).
     Dev-switcher endpoints carry no agent mode, so they stay conversational
     (D-037), as does a customer endpoint that is not `native_tools`.
   - **Replayed one variable at a time.** The mode did not decide it:
     `ioc_enrichment` said Amazon 2/3 on glm. The owner in context did: 9/9
     Google.
   - **Root cause: the platform had the owner and threw it away.** On turn 1,
     AbuseIPDB named Google LLC (isp, domain, hostname) and OTX named
     AS15169. A low AbuseIPDB score returned None, so the echo said "unknown
     to them".
   - **Fix (Burhan's call, D-055).** A lookup may return a `NetworkContext`
     beside its signal, or alone. It is never a verdict, so it is never
     recorded and cannot flip one. The IOC check shows it and the agent's
     tool result carries it.
   - **Proven.** 8 new tests (six failed before; two pin unchanged
     behaviour), with the exact offending answer pinned in
     tests/fixtures/enrich/b001_ip_owner_claim.json. 3/3 mutants caught.
     Full gate green.
   - **Live, rebuilt container:** qwen names **Google LLC 3/3** (was Amazon
     3/3). glm 3/3, and its agent turn now makes one lookup instead of two
     (~3.1k tokens, was ~4.1k).
3. **Found and logged, not fixed:**
   - **B-005:** on the conversational path glm forges the `⟦DATA⟧` fence
     and writes invented "platform data" inside it;
   - **B-006:** a follow-up on a no-signal IP calls it "clean", because the
     follow-up resolves to `general`.
4. **Bounds.**
   - Only AbuseIPDB supplies the owner (TD-049).
   - The model still adds what nobody supplied ("likely us-central1"). That
     is the deferred fabricated-specifics item, not re-scoped.

About 25 inference calls on Z.ai, plus local qwen runs.

## F1 — what happened (front-end track's first session)

F1 ran 2026-10-12. At the start ritual Burhan named nothing else he had seen on
the page, and added **all three candidates** to the goal. Mid-session he
picked from options four times (the stream, links, the panel's shape, the
ledger's unit) and asked for B-003 to be fixed in F1.

1. **Promote #30**, with the collision above.
2. **Goal: where a deep turn's reasoning loses its speed — measured first**
   (docs/probes/2026-10-12-f1-stream-layers.md). Three layers on the same
   runs, plus the page in a real browser, both endpoints:
   - the server adds ~1 ms a delta (p50; 4.6 ms max);
   - the page ~3 ms to paint (p50; 41 ms max), with no long tasks;
   - **the endpoint is the whole of it**. glm-4.5-air bursts at ~1000
     chars/s with 1-13 s silences between an agent turn's calls. qwen3:14b
     runs 139-171 chars/s.

   B-001's 3 min 13 s qwen turn was not reproduced (a cold start is 4.7 s).
3. **D-052 (Burhan picked all four options):**
   - a `status` frame before every model call, tool and held answer;
   - a working line ("Thinking · 3 s");
   - pacing bounded at 200 ms (live max 200.4 ms);
   - the switcher's local endpoint relabelled "Local (slow)".
4. **D-053, safe markdown in answers.**
   - A pure parser plus a DOM builder, with no `innerHTML` anywhere.
   - Links are clickable, https only, and show their real host. That was
     Burhan's call, over the recommendation to leave them literal; the risk
     is stated in D-053.
   - Code spans are neutral.
   - Live: an `<img onerror>`/`<script>` in an answer is text and never runs.
5. **The approvals panel** (docs/superpowers/specs/2026-10-12-approvals-panel-design.md).
   - Every door the API has, by status. Two clicks for the doors that run
     something, disarming after 5 s. Decided cards stay for the session.
   - Live on real proposals: approve → done → undo → undone, and a reject
     (docs/probes/2026-10-12-f1-approvals-panel-live.md).
   - Fixed during the run: the open panel covered Send, and a rejected card
     still showed its undo line.
6. **D-054, the cost ledger.** One `turn_spend` row per deep turn, failed
   turns included. Each answer gets a line, and the chat its total
   (`GET /api/chat/sessions/{id}/spend`). Live, a 4-call turn's row matched
   its line exactly.
7. **B-003 fixed** (`4693084`): the pages are served `no-cache`, so a deploy
   reaches an open browser. A page cached before the fix needs one reload.

**Found and logged, not fixed:** B-002 (the rail stops a definition question on
the agent path 3 of 4 times: TD-044's trigger, live) and B-004 (a note on a
recorded indicator is refused as "doesn't exist").

**How the work was proven.**
- The page's logic lives in a `// <page-logic>` block, run under Node by
  `tests/js/page_logic.test.mjs` (32 tests) inside the pytest gate
  (`tests/test_page_logic.py`).
- The test element factory is frozen, so a builder that edits an element
  after creating it fails as it would on a real DOM. That caught a real bug.
- Mutants were run on every guard: the loop 2/2, the route 4/4, the page
  3/3 + 3/3.
- Every page change was checked in headless Chromium against the rebuilt
  container.
- About 60 inference calls on Z.ai, plus local qwen runs.

## S28 — what happened (backend track's last session)

S28 ran 2026-10-11. At the start ritual Burhan answered the candidates question
with **"all"**, so all three candidates joined the goal. Mid-session he made
three more calls:
- fix the identity leak;
- keep D-002 (put back to him as overturn or drop: dropped);
- both doors for TD-042.

Everything is recorded where it lives:

1. **Promote #29** (`31f7fc1`) shipped the S27 slate (D-042…D-045), with the
   back-merge `08bebdf`.
2. **An adversarial second-pass review of S27's own code** (record:
   docs/probes/2026-10-11-s28-s27-code-review.md). Three findings:
   - `831dedc`: an undo that lost its row and got it back said "moved from
     incomplete to incomplete". It now refuses as `contended`.
   - `3a09fcd`: a real action call was logged as `<unregistered>`.
     `AgentLoop.knows()` fixes it.
   - **Live, 4/4 identity questions that missed the shortcut were answered
     "I'm Claude, by Anthropic".** That is false and breaks D-002. It became
     D-047 (item 5).

   Cleared: D-043's hold, D-042's re-probe, D-044's contract, D-045's
   proposal path, and `922f30c`/`9458518`. Two bounds were stated (tool-result
   text is unindexed by D-031's design; a leaking held draft ends the turn).
3. **Goal: TD-043 → D-046, measured first.**
   - **0 of 31 re-searches were misses.** Every search returns a full page,
     because the KB has no entity documents.
   - `search_knowledge` now has a per-turn budget of 3. It is withdrawn from
     the wire once spent, and a call from history is refused (glm-4.5-air
     made one every thin turn). The last allowed result says it was the last.
   - S27's prompts went **37 calls → 23**, with no step-cap hits and 6/6
     conformant.
   - Price: the LockBit turns no longer reach T1566. TA0001, found first,
     names the same vectors.
   - De-dup and a budget of 5 were measured and not shipped (thrash brake).
     Record: docs/probes/2026-10-11-s28-td043-search-budget.md.
4. **Goal: TD-042 → D-048 (Burhan: both doors).**
   - An `approved` row with no claim, older than STALE_CLAIM_SECONDS, rejoins
     the queue.
   - `POST /{id}/execute` re-runs `check_executable` and records the human in
     `resolved_by`.
   - `POST /{id}/withdraw` moves it to the new status `withdrawn`, added to the
     one status-CHECK block in place.
   - Both doors are stale-only and claim-first, with a race test. 6/6 mutants
     were caught. Live through the container (docs/probes/s28-td042/).
5. **D-047, identity.** The widened shortcut was judged on a held-out battery
   written blind: **0/45 → 18/45 caught, 0/45 false positives.** The copy says
   it runs on "the platform's engine", never the model (D-002 kept).
6. **Candidate → D-049.** What the agent looks up is recorded like the IOC check
   (`record` → `persist_enrichment`), and the model is told
   `recorded: true/false`. Live: one turn checked a never-seen IP, recorded it,
   and filed its note proposal.
7. **Candidate → D-050.** A note request never takes the IOC shortcut. One that
   leads the message resolves to an eighth mode, `action_request`, with no
   sections. Held out:
   - note-only → `action_request`: 0/30 → **19/30**;
   - note-only → shortcut: 9 → 3;
   - mixed → shortcut: 6 → 0;
   - **0 false positives.**

   Live: `contract_valid: true`.
8. **Candidate: alert JSON keys, measured against the published ECS and
   Microsoft Graph schemas** (docs/probes/2026-10-11-s28-alert-json-keys.md).
   - **An ECS alert was named after its host** (`host.name` before
     `rule.name`). Fixed (`e2af082`), and `source.ip`/`destination.ip`/
     `processCommandLine`/`createdDateTime` are now read.
   - The S27 MEDIUM was the scorer, not the keys. Documented credential-theft
     alerts score **LOW 35** (IDEAS).

**How the work was proven.**
- Every fix and feature shipped with tests, and each one was shown to fail
  before the change.
- Mutants were run: TD-043 3/3, TD-042 6/6, D-049's route wiring.
- Classifier/resolver changes were judged on batteries written by agents that
  never read the repo, with the held-out one opened once after freezing.
- Live checks went through the rebuilt container.
- About 70 inference calls on Z.ai, well under a dollar.
- **One gate went red in between and was fixed before commit:** a comment in
  `classifier.py` said "requests", and the structural test that forbids that
  library's name in the classify package caught it. Targeted test runs had
  skipped that file; the full gate did not.

## Where we are

Phase 4:
- contract (S17);
- decision loop (S18);
- hardened input and spend (S19);
- pipeline/docs/demo (S20);
- beta debt (S21);
- output rail (S22–S24);
- tools as prompts and a streaming loop (S25);
- the agent path live in chat (S26);
- verdicts the code decides held on screen, and the agent proposing (S27);
- **S28: the agent's spend bounded per tool, an approval that never ran given
  doors, the agent's lookups recorded, note requests routed to a mode they can
  meet, and the engine no longer naming another vendor on 18/45 held-out
  identity questions;**
- **F1 (front end): the endpoint measured as the whole of the slowness; the
  page saying what a turn waits on and pacing what arrives (D-052); answers in
  safe markdown (D-053); every approvals door on the page; and every deep
  turn's spend recorded and shown (D-054);**
- **B1 (bugs): the network a source names reaches the analyst and the model,
  beside the verdict, never as one (D-055, B-001);**
- **F2 (front end): a chat survives a reload (list, reopen, sign-in kept for
  the tab, D-056); S26's chat edges; narrow screens; the page split into
  modules (TD-045) under a strict CSP (D-057).**
- **B2 (bugs): a thinking model may restate the sections it was told to write
  (D-058, B-002); a note names its indicator as written (B-004); a no-signal
  lookup reads as unknown, not clean (B-006); a turn refused at the ceiling
  leaves nothing behind (B-008).**
- **F3 (front end, the collaborator): the timeline page runs under the chat
  page's policy, builds feed text as text, and its logic is tested (TD-051).**
- **S29 (backend): S28's code reviewed by others (two message-driven stalls,
  a verdict overwrite, a laundered indicator and D-046's bound fixed), and the
  integration phase designed: D-060…D-067.**
- **S30 (backend): MSSP tenancy — organizations, memberships and roles, one
  workspace per token with an audited switch, access re-checked on every
  request, and residency refused by code (D-068); D-069 decided.**
- **F4 (front end): one shell for every page — one sign-in, one header, shared
  tested modules; a workspace switcher that reloads and leaves nothing of the
  last client, Back included (D-070); doors by role; a read-only Members page;
  304s (TD-047).**
- **S31 (backend): a fair, leased, workspace-scoped jobs queue with an in-app
  worker (D-065); pending proposals expire after 24 h, refused in the settling
  UPDATE; one idempotency key per operation handed to every handler (TD-025's
  first half, D-066); a `ksa` workspace only on KSA storage (D-069); B-021
  fixed.**
- **S32 (backend, Hunaiza): connectors as typed, versioned, content-hashed
  packages written in Python or YAML (the SDK), compiled into approvable
  actions (fingerprint v2), and a per-workspace catalogue a provider can offer
  to its clients (D-071); B-026 fixed.**
- **S33 (backend, Hunaiza): integrations, Edge Agents that enroll once and
  run connectors from hash-verified packages in a subprocess, and "Test
  connection" end to end; PR #43's review fixed; D-072, D-073.**

The ROADMAP through S20 is complete; S21–S30, F1–F4 and B1–B3 were each
scoped by a decision or a bug. **The integration phase (S30–S41, F4–F9) builds
the spec; S30, F4, S31, S32 and S33 are done.**

## In-flight / standing follow-ups (carry forward until DONE)
1. **Promote slate: S32, B4 and S33** (S33 is the plan's promote milestone;
   **the promote is Hunaiza's once Burhan merges #51**; S34 only checks it). Before that, it read:
   **all of S32 and, once its PR is merged, all of B4**
   (the six fixes, their tests and records, B-033…B-035, TD-070, the
   session-end docs). S33's promote carries both. S32's, once Burhan merges its PR
   (`s32-connectors` → `staging`): the baseline probe, spec, plan, 13 tasks,
   the review fixes, B-026's fix, D-071, TD-066…TD-069, the live record, the
   S32 record and the session-end docs. The plan's next promote milestone is
   S33 ("Test connection" end to end), so S32 waits on the slate for S33's
   promote unless Burhan calls one sooner. Promote #42 (`69a8800`, back-merge
   `da7986a`; S32's Step 0, Hunaiza's) shipped all of B3 (B-010, B-024,
   B-029, the PR review's fixes, B-027…B-031, the session-end docs).
   Promote #40 (`09af821`, back-merge `6007efb`; `./ci.sh`
   green fresh, 1687 tests; GitHub CI green on push and PR; Burhan's call,
   2026-10-19) shipped all of S31 (B-021's fix and its review's pin; D-069's
   build, its pins and addendum; the S31 baseline, spec, plan, the eight
   tasks, the final review's fix wave, the live record; B-025, B-026,
   TD-063…TD-065; the session-end docs).
   Promote #37 (`6c12f18`, back-merge `992b9f4`;
   GitHub CI green on push and PR) shipped all of F4 (the Step 0 probe, the
   spec and plan, nine tasks, the final review's fix wave, the live records,
   B-022…B-024, the session-end docs). Promote #36 (`605f95a`, back-merge `4c83f76`; GitHub CI green on push and
   PR) shipped all of S29 and all of S30 (S29's
   review fixes, spec and D-060…D-067; S30's tenancy build, its reviews'
   fixes, D-068, D-069, the records). **The S30 migration cannot be rolled back** (it drops
   `users.workspace_id` and `users.role`; a pre-S30 image cannot boot on a
   migrated database): no production database exists yet, so take a `pg_dump`
   before the first real deploy. Promote #35 (`1a7708f`, back-merge `a8503f6`)
   shipped D-059, the plan and all of F3.
   - **The first session of any track runs `/promote` as its Step 0 — but
     only ONE window at a time** (the 2026-10-12 collision).
   - Read `git diff origin/main..staging --stat`, never the commit list.
   - **The two untracked overview files stay untracked — Burhan's call,
     2026-10-10.** `Auspex-Product-Architecture-Overview.pdf` and
     `docs/auspex-overview.html` are his; never commit, move, publish or delete
     them, and do not ask again.
2. **S29's review of S28's code left 13 entries open** (it is otherwise
   DONE; docs/probes/2026-10-14-s29-s28-code-review.md):
   - **B-010: fixed at B3 (`0207b4a`)**, with a fourth rule of the same class
     its review found.
   - B-011, B-012 (the D-050 and D-047 rules route some analysis, drafting
     and bot/AI questions wrongly; a change needs blind batteries, and B-012
     is partly Burhan's call), B-013 (a fully flattened ECS export is not
     detected as an alert), B-014 (the `action_request` contract passes any
     answer), B-015 and B-020 (what the agent says it recorded), B-016
     (approvals wording), B-017 and B-018 (**fixed at B4**), B-019 (a
     refused call reads as a search).
   - TD-056 (latent stream hold), TD-057 (`tool_names` not enforced at
     dispatch, before S34 passes it), TD-058 (an overlong URL).
3. **TD-036's trigger FIRED at S28 — the analyst reads the answer twice.** In
   2 of 3 D-049 probe turns, glm-4.5-air wrote a full answer before its
   annotate call. It passed the 400-char hold, streamed as answer, and then the
   real answer followed. The route logged the TD-036 line both times. Not
   fixed: re-measure the longest pre-tool narration on action-calling turns
   first.
4. **The rail's index keeps growing (TD-044; its trigger fired again at S28).**
   - `SHINGLE_WORDS = 8`: re-run `docs/probes/s22-outguard/probe_calibrate2.py`.
   - **`THINKING_SHINGLE_WORDS = 40`** (D-040): re-run
     `docs/probes/s26-step0/probe_calibrate_agent.py`. **Its margin is only
     1.4×** over the live legitimate ceiling of 28, so re-measure it **first**
     on any model change. D-042 logs a WARNING when the endpoint changes under
     the same name; that line is the trigger.
   - S27 added D-043's repair directive and D-045's action surface. S28 added
     D-050's `action_request` directive.
   - Every live S28 turn read `output_valid: true` (about 8 turns). The
     legitimate ceiling has not been re-calibrated.
   - **F1: the trigger fired as a live false positive (B-002).** A definition
     question on the agent path was cut 3 of 4 times. The match was 40 words
     of the definition contract's section spec on the THINKING channel, at
     exactly `THINKING_SHINGLE_WORDS`.
   - **B2 re-measured both floors on today's index and fixed B-002 (D-058).**
     - Answer floor: legit max 5 against 8. Agent path, 36 turns: thinking 28,
       every run above 20 a restated section list; a recitation 58.
     - D-058 drops the re-ask and the runs wholly inside a section list from
       the thinking index. Re-scored, the thinking ceiling is 20 (a 2× margin).
       Neither floor moved.
     - **Still unmeasured:** action-request turns; the conversational path's
       thinking; and general's two rules, now ONE 43-word run over the
       thinking floor (B-006, `c80bf29`). Re-measure general-mode thinking
       first (TD-044).
   - **S34 adds customer-written connector text to the index (D-064)**, and
     re-runs the calibration with it before anything ships.
5. **The card stream still emits only new cards, never status changes.** A
   client watching `/stream` is not told when a claim goes stale, or when a row
   becomes `incomplete`/`kept`/`withdrawn`, or rejoins the queue as a stale
   approval (D-048). The polled list is where those surface, and **F1's
   approvals panel polls it every 5 s** (TD-046).
6. **TD-031 / TD-032 / TD-033 are ratified bounds, not a backlog.** Do **not**
   re-open the guard regex.
7. **TD-005 trigger, still armed:** cve pool > 300k chunks, curated pool > 5k,
   any new doc_type, any embedding-model change, **or before any
   free-text-over-CVEs surface ships** (TD-027 is a HARD GATE). The IDEAS line
   "ingest ATT&CK groups and software" would be a new doc_type.
8. **Test usage isolation is designed for test_chat_sse.py (autouse refund) and
   incidental elsewhere.** Any other file whose tests spend inference calls has
   the 29-unit problem waiting; the `default` workspace has an hourly ceiling of
   100. All S28 chat tests live in test_chat_sse.py.
9. **The agent proposes; the bounds that remain.**
   - **D-049 retired the first** (an action could only target an observable
     the shortcut had recorded).
   - The approvals surface serves the stored, code-rendered card unscanned.
   - A turn the rail cuts at a tool frame can still leave a filed proposal.
   - `prompted_tools` is still unwired, and the narration hold is
     native-only.
   - **New, live (D-050):** a note-only request on an indicator the workspace
     has never seen is refused (`NothingToPropose`) and answered honestly. The
     agent does not look the indicator up first, which would record it and let
     the proposal file (IDEAS).
   - **B-004 fixed (B2).** A note may name its observable as written, not
     only by its short id. The bound is TD-054: the stored string is
     re-resolved at execute time and not pinned to the card's target.
   - **B-026 (S31):** an undeclared argument named like a platform keyword
     (`idempotency_key`, `proposal_id`, `workspace_id`) is filed and approved,
     then the run raises and the row reads `incomplete`, though nothing ran.
10. **D-041's bound, and TD-025** (S30 did TD-025's roles step).
    - A merely slow handler on an abandoned run can land after its put-back.
      It is recorded on the row, not prevented.
    - **S31 added the idempotency key** (`operation_key`, one per operation,
      handed to execute, undo and observe; the note action writes once per
      key) **and the proposal TTL** (24 h, `expired`). S34 adds grant-checked
      scope and runs actions as jobs carrying the key (TD-025's second half).
    - TD-042 is closed (D-048). Its own bound: `resolved_by` is the LATEST
      human resolver.
11. **Brand, partly owned now (D-047).** The identity shortcut catches 18/45
    held-out identity questions. **The other 27 reach the model, which named
    another vendor 4/4 times live.** Nothing guards the model's
    self-description in the answer or the Thinking pane. D-030/D-040 check for
    OUR configuration, not the model's claims about itself.
12. **D-043's drift log is cleaner but not clean.** D-050 sends note-only turns
    to `action_request` (no sections). A **mixed** request ("check X and add a
    note") stays in its analysis mode, and 11/30 held-out note-only phrasings
    still miss. Either can still log drift honestly.
13. **Three classifier/resolver operating points are pinned:**
    - D-044: `test_the_measured_operating_point_on_the_independent_battery_holds`;
    - D-047: `test_the_identity_operating_point_on_the_held_out_battery_holds`;
    - D-050: `test_the_action_request_operating_point_on_the_held_out_battery_holds`.

    Every battery behind them is training data now. **Any improvement claim
    needs a fresh, independently written battery.**
14. **D-046's price.**
    - Thin-topic turns reach fewer documents. The LockBit turns lost T1566;
      TA0001 still grounds the vectors.
    - A refused over-budget call shows in the turn as `· error` (and as a
      search on the status line: B-019).
    - The cause is KB coverage (IDEAS: ATT&CK groups and software).
    - **Since S29 the bound holds:** a step with a budget refusal in which
      nothing ran or was proposed goes to the synthesis pass (`6750028`,
      `34fe9a1`).

15. **Model-written links are clickable now (D-053, Burhan's call).** They are
    https only, show their real host, and open with `noopener noreferrer`. A
    poisoned answer can still put a clickable link in front of an analyst; the
    host beside it is the mitigation, not a prevention.
16. **Every page is markup, `css/base.css` plus its own stylesheet, and its
    own module on the shared shell (F4: `js/shell.js`, `js/api.js`,
    `js/dom.js`, `js/shell-logic.js`), under a strict CSP (D-057).** Module
    functions are module-scoped: a probe drives a page through its DOM. A new
    page file goes on `auspex/routes/ui.py`'s allow-list and into
    package-data (the globs already cover `static/*.html`, `css/*.css`,
    `js/*.js`).
17. **The spend ledger (D-054) counts what a turn's own ending records.** A turn
    cut by a dropped connection may record nothing (TD-048).
18. **An address's network now comes from one source (D-055, TD-049).** Only
    AbuseIPDB supplies it, and it is key-gated. A deployment without its key
    is back on B-001's path. OTX's keyless `asn` is still dropped.
19. **The model invents what nobody supplied (B1, B2).** On the
    conversational path, with no tools, glm forged a `⟦DATA⟧` block with
    invented platform lines (B-005). Every customer endpoint that is not
    `native_tools` takes that path (D-037). On the agent path, after B-006's
    fix, it still calls a no-signal IP "legitimate", inferred from its operator
    (B-009). **Both wait on Burhan's call on the deferred fabricated-specifics
    item.**

20. **F2's reload work, the bounds.**
    - A reopened chat's turns are paired by time (TD-050); nothing indexes
      `proposals.session_id` (TD-052).
    - **Fixed at F4 (`987c81c`):** a reopened turn's proposal line now follows
      the status the panel learns (live: Waiting → Done → Undone).
    - A proposal summary the rail may have cut can come back in a reopened
      turn (the approvals panel already serves the same stored card).
    - B-008 is fixed (B2): a turn refused at the ceiling leaves nothing
      behind. Other failures between storing the question and the claim still
      leave one (TD-055).
21. **The sign-in token sits in the tab's sessionStorage (D-056); D-057's CSP
    is its guard.** Since F4 only `js/shell.js` touches it (three guarded
    helpers, pinned), and D-070 governs a switch, lost access and Back. A
    script that did run could still navigate the token out (D-057, as
    corrected). Every page carries the same policy (chat, the timeline since
    F3, Members since F4), and the timeline's and Members' markup are pinned
    free of `style=`. No test pins `style=` in the chat page's markup or in
    `chat.js`'s two `innerHTML` templates, which the CSP relies on.
22. **F2's deferred minors** (kept so they are not lost): the 50-chat cut has
    no exact-boundary test; pairing edge cases no write path produces are
    untested; a malformed stored card would 500 the turns route; the busy
    gating and the foreign-hash path are proven live, not by tests; a hash
    pasted mid-turn is refused silently; `ci.sh`'s installed-dist check covers
    `*.py` only (TD-053). ("[connection lost]" became a sentence at F4.)

23. **D-058's bounds (B2).**
    - A recitation of ONLY a section list (or the re-ask) in the Thinking pane
      is not cut. It is still cut in the answer, at 8.
    - A plan that restates the 16-word preamble verbatim together with the
      section list trips the rail. Not seen live.
    - Whether a turn is cut depended on one or two words of the model's
      paraphrase, and on the KB results it read. **Live runs can pass a
      question that F1 saw cut**; the route tests with the logged run are the
      proof.
24. **A fresh-agent adversarial review after each fix (B2: 2 of 4 found a real
    defect).** SESSION-RULES.md asks for it on rail, action, tenancy and
    approvals changes, **and since S29 on the agent loop and on a review's own
    fixes** (S29: the review of six fixes found two more defects).
25. **Closed at F4** (`252aa6f`, `91e5e7a`): F3's deferred minors — the
    null-safe `conf`/`pct` pinned, `obsLink`'s own listener pinned, every
    served-page helper checks status 200, the arithmetic scan reads only JS,
    pill classes come from `labelClass`.
26. **Closed at F4** (docs/probes/2026-10-16-f4-shell-live.md): F2's page with
    live turns — Review/Undo on a reopened proposal, server errors in the
    server's words, narration on its own line. **Still not reached: the
    empty-answer note** (no live turn ended with neither an answer nor an
    error; Node pins `noAnswerNote`).
27. **The QRadar's address is not known yet** (Burhan, S29: "later").
    Reachability, its TLS certificate and its unauthenticated API answer are
    unprobed (docs/probes/2026-10-14-qradar-reachability.md). S33's Step 0
    runs them once he gives it; S33's agent work depends on the TLS answer.
    It holds real data, so D-067's synthetic-only lab domain is the only part
    of it the phase may fetch.

28. **S30's open ends** (they die by being done):
    - **TD-059 is a hard gate beside TD-001**: limit person creation over the
      API before any Google client id is configured.
    - **The deferred minors of S30's reviews** (kept so they are not lost; the
      final review triaged each "can wait"): a blank `ENGINE_REGION=` stops
      startup; `workspaces_org_required` would let `__deployment__` take an
      organization by SQL; a client's parent kind is checked in code only;
      no test drives the concurrent-loser branch of dev provisioning; the
      migration's fix-it advice is a `HINT`, not in the boot log; Google
      sign-in no longer records `google_sub` (it must, with TD-001); `ROLES`
      is not pinned to the DDL; refusal tests don't assert "nothing audited";
      `/me` would 500 rather than 403 in a vanishing-workspace race; the
      stream's access check sits outside its poll's `try`; the raw-input
      source pin misses cookies/body/form/url; `require_role` has no direct
      test; the member API's refusal edges (DELETE-self, PATCH non-member,
      empty PATCH) are thin over HTTP; the region guard's pin is per file;
      the isolation suite probes data by id, not through a list; the docs pin
      covers the README heading, not its body; the suite's residue in the dev
      database (TD-060).

29. **F4's open ends** (they die by being done):
    - **B-022** (the rail cut a note-only request: the model's thinking quoted
      the note tool's description; TD-044's action-request case), **B-023**
      (a `lapsed` pill has no colour), **B-024** (arrow keys on the closed
      switcher may switch at each step; unverified; a fix changes the UX —
      Burhan's call). BUGS.md.
    - **TD-061** (shell.js's state machine is pinned by source text and live
      checks, not run by a test) and **TD-062** (a turn or door started while
      a switch is in flight is cut by the reload).
    - **Parked by the final review's re-review** (kept so they are not lost):
      `switching` stays set (holding Sign out) if the switch answers a 2xx with
      no JSON body; three parts of the switch-in-flight code are unpinned; the
      hash pins accept an inverted condition; a typed hash whose open failed
      with a non-404 stays ownerless, so Back after a switch would send it
      (the server refuses it); a refused switch after the set shrank to one
      workspace throws at `picker.value`.
    - **The per-task reviews' deferred minors** (the final review triaged each
      "can wait"): `If-None-Match: *` untested; a deleted shipped file 500s;
      `el` would accept `innerHTML` as a prop; the select shows another client
      if `/me`'s list lacked the active one (the server 500s instead today);
      a 2xx with no JSON body still throws in `openChat`, `useDoor`, the
      shell's sign-in paths and the timeline; a member with no display name
      shows the email twice; a viewer still gets the dev endpoint select; the
      header is 143 px on a phone (F2 had 101; the nav adds a row).
    - **Live checks of anything about history must run with the back/forward
      cache ON** (headless Playwright turns it off):
      `docs/probes/f4-live/back-forward.cjs` (SESSION-RULES.md, The page).

30. **S31's open ends** (they die by being done):
    - (**B-025: fixed at B4**, `6310550`; **B-026: fixed at S32**,
      `c0b30de`, `19282ae`.)
    - **TD-063** (finished job rows never pruned), **TD-064** (no lease
      extension; S33's heartbeats), **TD-065** (a polled queue; the claim
      sorts every ready job).
    - **Parked by the fix wave's review** (S32 builds on these):
      `_clean_json` does not descend into tuples, and NaN or Infinity in a
      result fails `complete` (the job is recorded as a failure and re-run): a
      connector's output validation (S32's types, S33's core check) is the
      place (S32 typed the outputs; S33's core check remains); the worker's
      `except` around a failing `fail` **has its test since S32**;
      `_error_text(exc)` sits outside that `try` (an exception whose
      `__str__` raises still aborts a tick); `claim` and `enqueue` assume READ
      COMMITTED.
    - **Deferred by the final review:** a handler raising a non-`Exception`
      `BaseException` ends the worker silently, and the lifespan's `await`
      re-raises it past the pool's close (the ingest task has the same shape).
    - **Before S33:** one turn per workspace is shared across kinds and
      scopes (a busy agent could starve that workspace's in-app jobs);
      `job_turns.last_served_at` can move backwards under contention (use
      `GREATEST`); the lifespan test hangs instead of failing if its cancel
      block regresses (wrap it in a timeout).
    - **Before S34:** `operation_key` formats a string id as given (normalise
      it before a job stores it as its key); a key colliding with another
      kind's job comes back without a kind check.
    - **The per-task reviews' deferred minors** (the final review triaged each
      "can wait"): `enqueue`'s fallback read can find nothing after a cascade;
      keys are not stripped; `jobs.integration_id` has no FK until S33's table;
      the schedule's bucket memo is unpinned (the key de-dupes anyway);
      `failed` is counted on a `JobLost` from `fail`; the stream heartbeat's
      `waiting` and the list docstring count expired rows; a page holding only
      expired cards with more beyond it reads "Nothing is waiting on you.";
      `_takes_keyword`'s explicit-name branch untested; a stale comment on
      `EffectsProbe`; two long README lines.

31. **S32's open ends** (they die by being done; the full list is in
    docs/superpowers/records/2026-10-27-s32-record.md §5–6). **S33 did:** the
    runner builds `ctx.config` as the harness does and redacts stdout/stderr;
    the core imports the SDK's validators (`auspex_sdk.validate`); TD-068.
    **Left for S34 (actions, Hunaiza's call):**
    - dispatch runs `actions[].execute` and `commands.test`/`fetch.handler`;
    - `check_executable` admits only `auspex` (`EXECUTABLE_SYSTEMS`): admit
      connector systems, and bind an approval to its `integration_id` (it is
      not in the fingerprint) or never reuse a prefix;
    - the Edge Agent's runner builds `ctx.config` as the harness does, redacts
      stdout/stderr, and is the real egress sandbox (the SDK's HTTP client is
      not one);
    - the agent decodes zip member names as CPython does (cp437 unless flag
      0x800) and sorts by UTF-8 bytes when it re-hashes;
    - the core's result check imports the SDK's validators (now in
      `auspex_sdk.harness`) and calls `check_fetch_item`;
    - keep the zero-bytes pin test tied to the locked httpx version;
    - TD-068 (a `connector.registered` audit event, under a D-entry),
      TD-066, TD-067, TD-069;
    - the deferred minors in the S32 record §5.

32. **DONE at S33** (each row marked with its commit). PR #43's review, for S33's Step 0 (Burhan, 2026-10-28; it dies by
    being done): ten findings on S32's code, in
    docs/probes/2026-10-28-pr43-review.md, each fixed or closed as not real
    with the reason **before any dispatch code and before S33's promote**.
    The two that matter most: the SDK lets `dry_run` or `observe` share the
    undo's function, which the core refuses but cannot see once compiled
    (#1), and compiled handlers drop the `workspace_id` they are called with
    (#2). #2, #5 and #9 overlap #31's dispatch, approval and runner bullets.

33. **S33's open ends, for S34** (record §5–6): `check_executable` admits
    connector systems and an approval is bound to its integration (prefixes
    are never reused); dispatch runs `actions[].execute` on the edge API; the
    core checks envelopes with `auspex_sdk.validate`; TD-071 before any action
    runs; TD-072…TD-074; the S33 build's review was a self-review, and a fresh-agent review ran at PR #51's review (S33 record).

**Closed at S33, so they leave this list:** #32 (all ten findings). S33 added #33.

**Closed at S32, so they leave this list:** #30's B-026 and its worker-test
bullet. S32 added #31.

**Closed at S31, so they leave this list:** #28's B-021 and D-069 bullets;
#10's TD-025 line now records the key and the TTL as built. S31 added #30.

**Closed at F4, so they leave this list:** #25 and #26 (kept as one-line
stubs so the numbers stay put); #20's stale-line bullet; #22's "[connection
lost]". F4 added #29.

**Closed at S30, so they leave this list:** none outright; #1 now carries S30
and #10's roles step is done. S30 added #28.

**Closed at S29, so they leave this list:** the old #2, "S28's own code has
had no second-pass review" (done; 21 findings, now #2's open remainder).
#10's TD-025 and #14's bound moved (D-066; `6750028`). S29 added #27.

**Closed at F3, so they leave this list:** none of the numbered items closed
outright; #21's TD-051 clause is done (TD-051 closed). F3 added #25–#26.

**Closed at B2, so they leave this list:** none of the numbered items closed
outright. #4 was re-measured (D-058) and narrowed to what is still unmeasured;
#9's B-004 and #20's B-008 bullets are fixed. B2 added #23–#24.

**Closed at F2, so they leave this list:** #16's split (TD-045, done; #16 now
records what the split left). F2 added #20–#22.

**Closed at B1, so they leave this list:** none of the above closed. B1 added
#18–#19.

**Closed at F1, so they leave this list:** none of the above closed. F1 added
#15–#17.

**Closed at S28, so they leave this list:**
- the old #2, "S27's own code has had no second-pass review" (done; three
  findings);
- TD-042 (D-048) and TD-043 (D-046);
- the IDEAS lines for agent-path persistence (D-049), the action-request mode
  fit (D-050), and alert-normaliser key coverage (measured; the remaining
  issue is the scorer, now in IDEAS).

## Blockers / open risks
1. **TD-001 (OAuth identity keyed on email) and TD-059 (person creation over
   the API is unlimited)** are hard gates before any GOOGLE_CLIENT_ID is
   configured.
2. **Open debt.**
   - Still open: TD-014 … TD-025, TD-027, TD-029, TD-030, TD-031/032/033,
     TD-035 (the two-pass path only), **TD-036 (trigger fired, S28)**,
     **TD-044 (re-measured at B2, B-002 fixed by D-058; still open for
     action-request turns, conversational thinking and general's 43-word rules
     run)**,
     F1's TD-046 and TD-048 (the panel polling, and spend unrecorded on a
     dropped connection), B1's TD-049 (only AbuseIPDB names an address's network), and
     F2's TD-050 (turns paired by time), TD-052 (no index on `proposals.session_id`) and TD-053 (the gate's
     dist check covers `*.py` only), and B2's TD-054 (a note named by value is
     re-resolved at execute time) and TD-055 (only the ceiling refusal discards
     a stored question).
   - **S29:** TD-056 … TD-058 logged; **TD-023 and TD-025 left Deferred**
     (D-066) and are worked from S30 on.
   - **S30:** TD-059 (a hard gate beside TD-001) and TD-060 (test residue in
     the dev database) logged.
   - **F4:** TD-061 (the shell's state machine is not run by a test) and
     TD-062 (a turn or door started mid-switch is cut by the reload) logged.
   - **S31:** TD-063 (job rows never pruned), TD-064 (no lease extension) and
     TD-065 (a polled queue; the claim sorts every ready job) logged.
   - **Closed at F4:** TD-047 (304s on every page and file).
   - **Closed at F3:** TD-051.
   - **Closed at F2:** TD-045.
   - **Closed at S28:** TD-042, TD-043.
   - Closed earlier: TD-012, TD-018, TD-026, TD-028, TD-034, TD-037…TD-041.
3. **The KB bootstrap needs outbound HTTPS once per fresh volume**, and ingest
   needs NVD/CISA/FIRST/GitHub reachability. Failures degrade honestly.
4. **The corpus keeps growing while the container runs.** TD-011 tracks the
   index rollover trigger.
5. **Two rails, and neither is a closure.**
   - The INPUT guard bounds accidents and naive attempts (D-027, D-029).
   - The OUTPUT rail (D-030) catches our configuration coming back out, but not
     a paraphrase, and not an injection that merely made the answer wrong.
   - D-043 prevents a wrong code-decided verdict from being shown. It cannot
     prevent a wrong narrative answer.
   - Three defects in three sessions (S23, S24, S26). **Assume a fourth
     exists.** B2's first cut of D-058 widened the thinking exemption too far on
     the conversational path, and the review caught it before the close.
6. **An intermittent, unattributed test failure was observed once in S22.** Not
   reproduced in any later full run, including about ten at S28. Still recorded
   rather than dismissed.
7. **The chat route's event loop and crafted messages.** B3 closed B-010
   (the classify pass's four backtracking rules) and B-029 (the input guard's
   two). The route's whole text pass (guard, extract, classify) runs in
   milliseconds on every pinned input at the cap, each under a 1 s test
   budget. B-027 (`extract()`'s overlap checks) and B-030 (the guard's
   quote-line carve-out) were fixed at B4. The
   resolver has not been swept (IDEAS: one stall test for the whole pass).

## Host notes (reality snapshot)
- Postgres 55432; app 8000; OpenSearch 9200. Host runs pin via `auspex.devhost`.
- Ollama 0.34.0 on :11434 (root `http://localhost:11434/v1`, D-033); models
  qwen3:14b / llama3.1:8b / mistral:latest. The S28 start gate passed.
- **Primary dev LLM is glm-4.5-air on Z.ai (D-034)** — `https://api.z.ai/api/paas/v4`,
  pay-as-you-go key in `.env` as both `GLM_API_KEY` and `LLM_API_KEY`. **Never the
  Coding Plan endpoint.**
  - Thinking is on by default and billed inside `completion_tokens`.
  - **Prose precedes tool calls** (TD-036, triggered again at S28).
  - **It calls a tool withdrawn from the wire if it is in its history** (S28,
    D-046).
  - **It calls itself "Claude by Anthropic" when asked** (S28, D-047).
  - `json_schema` is silently ignored; `json_object` works.
  - glm-4.7-flash (free) answered 429 "overloaded"; glm-4.7-flashx hung once
    past 180 s. Rate limits are console-only.
- **Scout on Northflank is GONE** — `p01--new-llm--…code.run` is NXDOMAIN (2026-10-10).
- **S28 session-end (2026-10-11):** staging, identity `bh3082336888-cell`. The
  `gh` switch was re-run before every call. All three containers are healthy,
  `./ci.sh` is **green, 1292 tests, 120 modules**, `/api/health/ready` returns
  **200**, and `./scripts/demo.sh` **exits 0**.
- **F2 session-end (2026-10-12):** staging, identity `bh3082336888-cell`. All
  three containers are healthy, `./ci.sh` is **green, 1360 tests, 121
  modules**, `/api/health/ready` returns **200**, `./scripts/demo.sh` **exits
  0**. Promote #32 merged.
- **GitHub's runner Node prints TAP when its output is captured** (B-007);
  local Node v24 prints spec either way. The page-logic gate names its
  reporter. Anything else that parses Node's output must too.
- **The Playwright MCP writes only under the repo** (`.playwright-mcp/`,
  git-ignored); it refuses the scratchpad. Copy kept evidence into
  `docs/probes/`.
- **`gh` flips to the work account unpredictably** (S16, S18, #27). Re-check
  before EVERY call: `gh auth switch --hostname github.com --user bh3082336888-cell`.
- **`gh pr merge` works.** `gh pr edit` still fails with a Projects-classic
  GraphQL deprecation — use `gh api -X PATCH repos/.../pulls/N`.
- **`gh pr merge --squash` printed NOTHING on success at S24, S25, #27, #28
  AND #29** — do not read silence as failure; verify with
  `gh pr view <n> --json state,mergeCommit`.
- **`./ci.sh | tail` HIDES THE EXIT CODE.** Redirect to a file and read `$?`.
- **Run the suite the way `ci.sh` does** — `.venv`, where the package is installed
  editable.
- **Run the FULL gate before calling a change done.** S27's `e96e27c` and S28's
  D-050 comment both passed every file they touched and broke one they did not.
- **This repo HAS GitHub Actions** (S20, D-028) — `.github/workflows/ci.yml` runs
  `./ci.sh` on push and PR. PR #29 ran it; SUCCESS.
- **Local `main` ref goes stale every promote.** `git fetch origin` and read
  `git diff origin/main..staging --stat`, never the commit list.
- **The app container runs the BUILT IMAGE, not the working tree** —
  `docker compose up -d --build app`. In-container probes: `docker compose cp`
  the script in, then `docker compose exec -T app python /tmp/<script>.py`.
- **Editing code while `./ci.sh` runs puts the edit in its container build.**
  Pytest imports at collection, so the test phase is not affected, but the
  build is. Wait, or re-run.
- **qwen3:14b is SLOW to first token** — budget 1500 tokens and run it in the
  background.
- **Live probes run from `.venv`** against the app's own constructors (S27/S28
  probe dirs) or through `/api/chat` from the host (`probe_app_*.py`).
- **Enrichment skips reserved address space** (TEST-NET etc.): a probe that
  needs an indicator recorded must use a routable one (S28, D-049 run 1).
- **Independent batteries:** to judge a classifier/resolver change honestly,
  have a subagent write TWO batteries WITHOUT reading the repo. Build on one,
  and open the other once after the rule is frozen (S28: D-047, D-050).
- **Startup autoprobe (D-038/D-042):** the dev scorecard (row `a8113b41…`,
  probed 2026-10-10 09:33 UTC) expires **2026-10-17**. After that the running
  container re-probes it (~15 calls). If it logs the "endpoint changed"
  WARNING, re-measure D-040's thinking floor first.
- **Do NOT run pytest during live `/api/chat` probes.** The suite purges the
  shared `analyst@auspex.dev` user.
- **All dev-login users share the `default` workspace**, hourly ceiling 100
  inference calls. See standing follow-up 8.
- **Probe residue is expensive.** Probes that file proposals must reject them,
  and probes that create observables delete only what they created (S28
  probes do both).
- **THE DEMO IS ONE COMMAND: `./scripts/demo.sh`** (~3 min, end to end).
- **F1 session-end (2026-10-12):** staging, identity `bh3082336888-cell`.
  `./ci.sh` **green, 1315 tests, 120 modules**, `/api/health/ready` **200**,
  `./scripts/demo.sh` **exits 0**.
- **Node is part of the gate now.** `tests/test_page_logic.py` runs
  `node --test tests/js/page_logic.test.mjs`. Node missing is a failure, not
  a skip. Local Node is v24, and GitHub's ubuntu runner ships it.
- **The Playwright MCP writes to `.playwright-mcp/`** (gitignored since F1).
  It can only save screenshots under the repo. Use
  `browser_run_code_unsafe` when an action and its screenshot must be one step:
  the working line and armed doors live for seconds.
- **A page cached before B-003's fix needs one reload**; after it, every load
  asks. `FileResponse` sends a full 200 even to a matching ETag (TD-047).
- **Measuring the stream:** `docs/probes/fe-stream/probe_layers.py` runs the
  app in-process (:8011) with the endpoint stamped, so the endpoint and route
  layers are timed on one completion. `page_paint.js` is the page layer.
- **Two windows on one repo collide** (2026-10-12). Check `ps` for a second
  `claude` in this directory when something moves that you did not move.
- **B1 session-end (2026-10-12):** staging, identity `bh3082336888-cell`.
  `./ci.sh` **green, 1323 tests, 120 modules**, `/api/health/ready` **200**,
  `./scripts/demo.sh` **exits 0**.
- **A dev-switcher endpoint always takes the conversational path** (D-037: it
  carries no agent mode). To test what a customer's non-`native_tools`
  endpoint does on the dev endpoint, replay at it with the route's own
  composition: docs/probes/b1-b001/probe_replay_conversational.py.
- **The B-001 route test purges the observable 34.187.179.218** in every
  workspace, as the S5 IOC test does for its IP. B2's B-006 route test purges
  it too. B2's B-004 route test touches 185.220.101.52 in `default` only if it
  is absent, and deletes only the row and proposals it created.
- **B2 session-end (2026-10-13):** staging, identity `bh3082336888-cell`.
  `./ci.sh` **green, 1385 tests, 121 modules**, `/api/health/ready` **200**,
  all three containers healthy, `./scripts/demo.sh` **exits 0**.
- **`./ci.sh` rebuilds AND restarts the running app container** (`ci.sh:26`,
  `docker compose up -d --build --wait app`). A live "before" run has to
  happen before the gate; after a green gate the container already carries
  the change (B2 lost B-008's live "before" this way).
- **In-process probes run with enrichment OFF unless told otherwise**
  (`pin_host_defaults`). Set `ENRICHMENT_ENABLED=true` beside
  `KB_ENABLED=true`. B2's first B-006 run read `enrichment_inactive`, an
  invalid run.
- **Probing at the usage ceiling costs nothing:** set this hour's
  `inference_calls` counter for `default` to the plan's limit, make the turns,
  restore it exactly in a `finally`
  (docs/probes/b2-b008/probe_live_ceiling.py).
- **A model's word choice can hide a rail bug** (B-002): live runs passed 0/8
  where F1 saw 3/4 cut, on byte-identical configuration. Reproduce rail bugs
  at the route with the logged run, not only live.
- **F3 session-end (2026-10-14), Hunaiza's machine:** staging, identity
  `HunaizaK`. `./ci.sh` **green, 1392 tests, 121 modules**,
  `/api/health/ready` **200**, all three containers healthy.
- **Hunaiza's machine:** `/usr/bin/node` is v18 and cannot load the page
  modules (no ESM detection); nvm's v22 is her shell's default, but a
  non-interactive shell (Claude Code's) needs
  `export PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH` before
  `./ci.sh`. Her user joined the `docker` group on 2026-10-14; until her next
  login the socket carries a user ACL.
- **The dev database holds no verdicts after a full gate** (the suite clears
  its own). A timeline probe seeds an observable, verdicts and a flip, and
  deletes them in the same command (`trap`); F3's scripts are in
  `docs/probes/f3-timeline/`. Headless Chromium for them was installed with
  Playwright 1.48.2 in the session scratchpad, not the repo.

- **Promote #36 (2026-10-15):** `605f95a` on main, back-merge `4c83f76`;
  `./ci.sh` green fresh before it, GitHub CI green on push and PR, main's tree
  equals staging's.
- **S30 session-end (2026-10-15):** staging, identity `bh3082336888-cell`.
  `./ci.sh` **green, 1554 tests, 129 modules**, `/api/health/ready` **200**,
  all three containers healthy, `./scripts/demo.sh` **exits 0**.
- **The dev database is on S30's shape**: a user is a person
  (`home_org_id`), access is `memberships`; `default` and `dev` are each a
  `direct` organization; `__deployment__` has none. Manage it with
  `docker compose exec app python -m auspex.tenancy …` (SESSION-RULES.md,
  Tenancy). It holds S30 test residue (TD-060).
- **S30 ran subagent-driven**: implementers and reviewers were fresh agents.
  Commit `4c1714c`'s Co-Authored-By names the model that wrote it (Sonnet), not
  this session's line; amending is banned, so it stays.
- **Promote #37 (2026-10-16):** `6c12f18` on main, back-merge `992b9f4`;
  `./ci.sh` green fresh before it, GitHub CI green on push and PR, main's tree
  equals staging's.
- **F4 session-end (2026-10-16):** staging, identity `bh3082336888-cell`.
  `./ci.sh` **green, 1603 tests, 129 modules** (at `7057ca4`; docs only
  since), `/api/health/ready` **200**, all three containers healthy.
- **Headless Playwright disables the back/forward cache**, so a page restored
  by Back is never seen by the MCP browser. To check anything about history,
  run `docs/probes/f4-live/back-forward.cjs`:
  `NODE_PATH=<an npx playwright-core>/node_modules node back-forward.cjs`
  (F4 used `~/.npm/_npx/9833c18b2d85bc59/node_modules`), with
  `executablePath` at an installed Chromium (`~/.cache/ms-playwright/chromium-1208/
  chrome-linux64/chrome`) and `ignoreDefaultArgs: ['--disable-back-forward-cache']`.
  A cache restore fires no `load`: wait for `commit`.
- **A tool call batch runs in order, not in parallel**: a browser step that
  waits for a CLI change made in the same batch waits forever (F4 lost one
  60 s run this way).
- **S29 session-end (2026-10-15):** staging, identity `bh3082336888-cell`.
  `./ci.sh` **green, 1412 tests, 121 modules**, `/api/health/ready` **200**,
  all three containers healthy, `./scripts/demo.sh` **exits 0**. Promote #35
  merged.
- **The gate lints `auspex tests scripts server.py` only** (`ci.sh:14`).
  `ruff check .` also lints `docs/probes/` scripts and reports old issues
  there; lint a test edit with the gate's own scope before committing (S29's
  first post-fix gate went red on two long test lines).
- **Python is 3.12 everywhere** (venv, `python:3.12-slim`, CI), so possessive
  quantifiers (`\s*+`) and atomic groups are available; S29's two classify
  fixes rely on them.
- **Timing tests:** S29 pinned the two fixed classify rules at < 50 ms on
  inputs sized so a regressed rule fails in seconds (~1000× margin today).
- **S31 session-end (2026-10-16):** staging, identity `bh3082336888-cell`.
  `./ci.sh` **green, 1687 tests, 133 modules**, `/api/health/ready` **200**,
  all three containers healthy.
- **The app container runs the jobs worker** (`JOBS_WORKER_ENABLED` unset
  there means `true`): a tick every 5 s; the `proposals.expire` schedule once
  per 300 s bucket of the wall clock. Host and test runs pin it off
  (`auspex.devhost`). **Tests use `t.*` job kinds and never enqueue
  `proposals.expire`** (the container would claim it); they call its handler
  directly. A live check that ages a proposal waits for the next 300 s bucket.
- **`STORAGE_REGION` is unset on this deployment, so `global`**: the CLI
  refuses a `ksa` workspace here (D-069).
- **S31 ran subagent-driven**: a subagent's commit carries its own model's
  Co-Authored-By line (Sonnet, Haiku), a ruling recorded in the session; S30's
  `4c1714c` set the precedent; amending is banned.
- **A host probe script calls `auspex.devhost.pin_host_defaults()` before
  importing `auspex.config`**, or it reaches for the compose-internal
  `postgres` host and fails (S31's live scripts, `docs/probes/s31-live/`).

- **B3 session-end (2026-10-19), Hunaiza's machine:** branch `b3-b010-b024`,
  identity `HunaizaK`. `./ci.sh` **green, 1698 tests, 133 modules**,
  `/api/health/ready` **200**, all three containers healthy.
- **Hunaiza's machine, B3:** her user is in the `docker` group now (plain
  `docker` works). Ollama is not installed: the D-013 start gate fails there,
  so a session that needs no engine says so at the start. A slow network made
  pip report a `pydantic-core` "conflict" on a rebuild; a retry built it.
  Playwright 1.48.2 lives in the session scratchpad, so it is reinstalled per
  session; Chromium stays in `~/.cache/ms-playwright`.
- **A live browser check catches what the source-reading page tests cannot.**
  B3's first B-024 build raised a TDZ error that blanked every page while
  `tests/test_ui.py` stayed green. Load the page in Chromium after any shell
  change.

## Reference intelligence (from the SARA Open architecture study)
Base: `/home/burhan/sara-open/` — key snapshots in docs/probes/:
- ACH analogues (S12): 2026-08-08-sara-ach-analogues.md
- Phishing/header/typosquat (S11): 2026-07-18-sara-phishing-header-patterns.md
- Alert additive scorer (S10): 2026-07-18-sara-alert-triage-scorer.md
- DEFERRED rail (S9): 2026-07-18-sara-orchestrator-deferred.md
- Fast classifier / 92-8: 2026-07-16-sara-fastpath-pattern.md
- RRF retrieval + ID bypass: 2026-07-17-sara-rrf-retriever-pattern.md

## Next session should
**Pick a track (D-051); the Tracks table at the top has the ids.** Paste the
prompt file of the track you mean. `/session-start` with no track asks.
One window at a time (D-051).
- **S34, backend, the focus** (`NEXT-SESSION-BE.md`). **First Burhan reviews
  and merges S33's PR (`s33-edge-agent` → `staging`), then pull**; Step 0 runs
  the promote S33 is a milestone for (S32, B4, S33) and reads #33; then
  connector actions through approvals and per-client policy.
- **B5, bugs** (`NEXT-SESSION-BUGS.md`) waits for Burhan to scope it from the
  open entries, B4's new B-033…B-039 among them.
- **F5, front end** (`NEXT-SESSION-FE.md`) starts only after S34
  close (the order table): connectors, integrations, Edge Agents, memberships
  and approval-policy admin, on F4's shell and Members page.
