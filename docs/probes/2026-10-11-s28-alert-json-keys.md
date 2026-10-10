# S28 — JSON alert key spellings, probed from the published schemas

_2026-10-11, S28. IDEAS (S27) asked: "measure which JSON key spellings real
EDR/SIEM exports use before widening `normalize`". No real tenant export is
available to this project, so the measurement is against the two published
schemas that could be fetched. CrowdStrike and SentinelOne document theirs
behind a login and were not probed; nothing here claims their spellings._

## Sources, as fetched

- **Elastic Common Schema**:
  `https://raw.githubusercontent.com/elastic/ecs/main/generated/csv/fields.csv`,
  `ECS_Version` 9.6.0-dev, 2737 rows. The rows used:

  | Field | Type | Example |
  |---|---|---|
  | `@timestamp` | date | `2016-05-23T08:05:34.853Z` |
  | `source.ip` | ip | |
  | `destination.ip` | ip | |
  | `process.command_line` | wildcard | `/usr/bin/ssh -l user 10.0.0.16` |
  | `process.name` | keyword | `ssh` |
  | `host.name` | keyword | |
  | `user.name` | keyword | `a.einstein` |
  | `event.severity` | long | `7` |
  | `rule.name` | keyword | `BLOCK_DNS_over_TLS` |
  | `threat.technique.id` | keyword | `T1059` |
  | `threat.tactic.id` | keyword | `TA0002` |

- **Microsoft Graph security alert, v1.0**:
  `learn.microsoft.com/en-us/graph/api/resources/security-alert` (page dated
  2026-01-08), with `security-processevidence` and `security-ipevidence`.
  - Properties used: `title`, `severity` (`unknown`, `informational`, `low`,
    `medium`, `high`, `unknownFutureValue`: there is no `critical`),
    `createdDateTime` and `mitreTechniques` (a string collection).
  - `evidence` is a collection. `processEvidence.processCommandLine` holds the
    command line, and `ipEvidence.ipAddress` holds an address with no
    source/destination role.

## Step 1 — the S27 case: the hypothesis was wrong

The S27 alert (`{"rule": "Credential dumping", "severity": "critical",
"process": "procdump.exe -ma lsass.exe", "mitre": "T1003.001", "confidence":
95, …}`) scored MEDIUM.
- IDEAS guessed its keys sat outside what `normalize` reads. They do not:
  - `rule` became the name;
  - `severity` read as CRITICAL;
  - `confidence` read as 95;
  - the technique id came from the text.
- Only `process` was not taken as the command line, and the signal detectors
  scan the whole paste anyway.
- The score is 40 (severity) + 15 (confidence) + 5 (MITRE) = 60, under HIGH's
  70. The additive scorer has no signal for credential dumping. That is
  calibration, not coverage (IDEAS, below).

## Step 2 — the documented shapes against `normalize`, before

| Shape | name | src | dst | cmdline | timestamp | score |
|---|---|---|---|---|---|---|
| ECS alert | **`dc01`** (`host.name`) | missed | missed | read | read | LOW 35 |
| Graph alert | read (`title`) | — | — | **missed** | **missed** | LOW 35 |

- **The ECS name was the host's.** `_leaf` matched the first key ending in
  `.name`, and in an ECS document that is `host.name`. The deterministic
  triage block told the model the alert was called "dc01".
- `source.ip` / `destination.ip` end in `ip`, which neither address list
  held.
- Graph's `processCommandLine` and `createdDateTime` were in no list.

## Step 3 — fixed (tests pin the documented shapes)

- The alert's name is a top-level `name`, else `rule.name`, the rule, the
  signature or the title. A `.name` under an entity (host, user, process) no
  longer counts.
- Keys added: `source.ip`, `destination.ip`, `processcommandline`,
  `createddatetime`.
- The S10 flat shapes are unchanged, pinned by
  `test_a_flat_alert_with_a_top_level_name_keeps_it` and the existing suite.

**Effect on scores: none.** No scorer input reads `name`, `src`, `dst`,
`cmdline` or `timestamp`. Signals and MITRE ids come from the whole text. The
fix changes what the code tells the model ("Parsed alert: …") and what the
envelope carries, not any Risk level.

## Seen, and parked: the scorer under-rates credential theft

Both documented credential-theft alerts score **LOW 35**: severity HIGH (30)
plus a mapped technique (5). Microsoft's own description of `high` names
"credential theft tools activities". The additive scorer has no
credential-access signal (`procdump … lsass`, T1003). A fix is a scoring
decision and needs its own battery of alert shapes (IDEAS).
