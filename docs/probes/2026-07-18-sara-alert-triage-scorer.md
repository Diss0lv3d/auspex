# Probe: SARA alert_triage additive scorer (reference for S10 scorer)

_Date: 2026-07-18 · Source: `/home/burhan/sara-open/sara/agents/alert_triage.py`
(live source still present, 122 KB; read lines 1276–1590 in full 2026-07-18).
Re-snapshotted because the prompt warns the live source may be cleaned and S10's
additive scorer ports this pattern. Auspex reuses the PATTERN, not the code._

## The additive accumulator

```python
score = 0
contributions: list[dict] = []
def _add(signal, points, detail=""):
    score += points
    contributions.append({"signal": signal, "points": points, "detail": detail or signal})
```

Each signal names itself, its points, and a human detail — never an opaque
number (the QA #415 lesson: a flat factor list hid which branches fired vs were
silently skipped).

## Signal weights (verbatim)

- **Severity** (always adds; default 10): `CRITICAL 40 / HIGH 30 / MEDIUM 20 /
  LOW 10 / INFORMATIONAL 5`.
- **Confidence**: `>=80 → +15` (`confidence_high`), `>=50 → +10`
  (`confidence_medium`). Non-numeric confidence → 0.
- **Process**: `suspicious_process +10` — BUT #1587 gate: a bare dual-use shell
  (powershell/cmd/wsl/bash) with no exec co-signal on the cmdline scores 0
  (recorded as `shell_process_no_cosignal`, points 0). Higher-signal LOLBins
  score unconditionally.
- **Encoded command** (`-enc`/`-encodedcommand`/`base64` in cmdline):
  `encoded_command +20`; auto-decodes base64 → `encoded_command_decoded +10`
  (decode failure → 0-point breadcrumb).
- **LOLBin patterns** in cmdline: `lolbin_pattern +15`.
- **MITRE**: high-risk tactic (TA0002/3/4/5/6/8/10/0040) → `high_risk_mitre_tactic
  +10` (ONCE, breaks); else any technique id → `mitre_technique_mapped +5`.
- **Low local prevalence**: `low_local_prevalence +10`.
- **Artifact COUNT is deliberately NOT scored** (P415-14): a phishing email
  naming sender+recipient+1 link sat at 15 points purely because the parser
  found 3 entities. "The signal is what the IOCs ARE, not how many were
  extracted." Reputation/KEV/EPSS/classification verdicts drive score — those
  come from enrichment, which the fast-path scorer does NOT have.
- `score = min(score, 100)`.

## Risk-level mapping (after DEFERRED rail)

- `>= 70` → HIGH · `>= 40` → MEDIUM · else → LOW.
- `true_positive_estimate`: HIGH → HIGH, MEDIUM → (MEDIUM if score>=35 else LOW),
  LOW → LOW.

## DEFERRED rail — both conditions ("no data ≠ low risk")

`_sev_known = sev not in (None,"","UNKNOWN") and upper()!="UNKNOWN" and not
lower().startswith("unable to determine")` — the descriptive sentinel MUST count
as not-known (BUG-1168 reopen: sentinel drift silently regressed the rail to LOW).

- **(a) signal-poor** (`_signal_poor_envelope`): `not _sev_known AND not
  has_enrichment AND zero non-severity contributions` → DEFERRED. Copy: "no
  severity, no IOCs, no MITRE tagging, no process-level indicators."
- **(b) severity-only pending enrichment** (`_severity_only_pending_enrichment`):
  `_sev_known AND not has_enrichment AND has_ioc_artifact AND zero non-severity
  contributions` → DEFERRED. Copy NAMES the un-enriched IOC counts (so the brief
  doesn't read "no IOCs" when there ARE IOCs — the SEV1-WannaCry hash shape).

DEFERRED shape (both): `score → 0` (nulled — the old 10 was a fallback constant,
not a measurement), `true_positive_estimate = UNKNOWN`, `needs_deep_triage =
True` (machine-readable — escalation is data, not prose), recommendation names
what's missing + what to run next.

**Pending-enrichment tail**: `score>=40 and not has_enrichment and risk!=DEFERRED`
→ append "⏳ pending enrichment — score may shift" (DEFERRED already says it;
don't double up).

## What Auspex S10 takes

- The additive `_add(signal, points, detail)` shape → itemized `contributions`
  in the score result (never an opaque number).
- Signal weights as a starting calibration (Auspex has no enrichment on the
  fast-path score, so `has_enrichment=False` always for now — the pending tail
  and DEFERRED (b) are load-bearing).
- Both DEFERRED conditions, with the sentinel-drift guard baked in as CODE.
- Auspex differences: severity/signals/MITRE/IOCs come from the S10 code-owned
  **normalizer** (CEF/LEEF/syslog/JSON → typed closed-vocab envelope), not SARA's
  upstream parser. IOC extraction reuses `auspex.classify.observables.extract`.
  No enrichment is wired into the score path yet (that's the ioc_check→KB stretch,
  parked) → `has_enrichment` is always False in S10, so DEFERRED (b) fires on any
  severity-only alert carrying un-enriched IOCs.
