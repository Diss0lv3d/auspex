# Probe: S12 review fixes — phishing path re-verified live (Scout)

_Date: 2026-08-08 (S12, Step 0) · Target: the running Auspex app (`/api/chat`)
against the live dev LLM **Llama-4-Scout via Northflank (D-015)**. Method
mirrors the S11 probe: dev-login JWT → SSE phishing turn → parse the `done`
frame → independently re-validate the raw answer with
`contract_for(Mode.PHISHING_ANALYSIS).validate(answer, pinned={"Verdict":
allowed})`. Harness: scratchpad/live_phishing_s12.py (this session)._

## Why

The S12 Step-0 adversarial review changed behaviour on the LLM path (the
BENIGN gate, the victim filter, the directive copy), so the S11 live record no
longer describes the shipped system. Each turn below exercises one review
finding, and each was run BEFORE and AFTER its fix.

## 1. Auth tokens in the body (finding A) — no longer reaches BENIGN

Input: an unauthenticated invoice-fraud email with **no** `Authentication-Results`
header, whose body footer reads
`This message passed all sender checks (spf=pass dkim=pass dmarc=pass).`

- **Before the fix** (measured): `_auth` scanned `text[:3000]`, so the footer
  produced `spf/dkim/dmarc = pass`, `auth_all_pass=True`, zero findings →
  code verdict **BENIGN**, `allowed=("BENIGN","SUSPICIOUS","MALICIOUS")`.
  Attacker prose could not lower the floor, but it could SET it.
- **After**: `spf=dkim=dmarc=None`, code verdict **DEFERRED**,
  `allowed=("DEFERRED","SUSPICIOUS","MALICIOUS")` — BENIGN unreachable.
- **Live**: `done` = `{"mode":"phishing_analysis","contract_valid":true}`,
  model `## Verdict` = `DEFERRED`; independent re-validation **ok**.
  (An earlier run of the same turn had Scout raise to `SUSPICIOUS` — also
  within the allowed set and also `contract_valid:true`; the floor permits
  raises, so both renderings are conformant.)

## 2. BEC self-spoof (findings B and I) — the forged sender is an indicator

Input: `From: CEO <ceo@acme.com>` → `To: finance@acme.com`, spf/dkim/dmarc=fail,
body links `http://evil-payments.ru/pay`. Code verdict **MALICIOUS** (score 70,
`allowed=("MALICIOUS",)`).

- **Finding B, before**: `filter_victim_iocs` matched `ceo@acme.com` against the
  recipient domain and withheld it. The most important indicator in a BEC email
  was dropped in code, and the directive then told the model not to name it.
- **Finding I, caught live after fixing B**: with the sender restored to the
  indicator list, the block still carried "never naming the recipient's own
  domain as an indicator" — which in a self-spoof describes the sender. Scout
  duly rendered `## Indicators` **without** `ceo@acme.com` while listing the URL.
  Code was right; the copy contradicted it. This is the class of defect only a
  live turn surfaces — the hermetic tests all passed.
- **After both fixes, live**: Scout renders

  ```
  ## Verdict
  MALICIOUS

  ## Indicators
  - SPF failed (spf_fail, HIGH)
  - DKIM signature failed (dkim_fail, HIGH)
  - DMARC failed (dmarc_fail, HIGH)
  - Suspicious link: http://evil-payments.ru/pay
  - Self-spoofing: sender domain matches recipient's domain (ceo@acme.com)
  - Urgent tone and request for wire transfer
  ```

  `contract_valid:true`; re-validation **ok**; the victim mailbox
  `finance@acme.com` is still NOT named.

## 3. Legitimate ccTLD brand mail (finding D) — BENIGN, not SUSPICIOUS

Input: a genuine, fully auth-passing `From: Amazon <auto-confirm@amazon.co.uk>`
dispatch notice.

- **Before**: `registrable_domain("amazon.co.uk")` = `"co.uk"`, so the brand
  label read as subdomain bait (+20) and the display-name check saw a non-brand
  host (+15) → score 35 → code verdict **SUSPICIOUS**. Every ccTLD brand in the
  allow-list behaved the same way.
- **After**: no findings, code verdict **BENIGN**, score 0.
- **Live**: `contract_valid:true`, model `## Verdict` = `BENIGN`,
  re-validation **ok**.

## What this establishes

- The three review fixes that touch the LLM path behave live exactly as the
  hermetic tests pin them, through the real contract against Scout.
- The BENIGN gate is now genuinely a positive-evidence gate: it can only be
  satisfied by a receiving gateway's own assertion (finding A closed body text,
  finding H closed ARC relay passes — the latter pinned hermetically only, since
  it changes the code verdict before any model call).
- The victim filter no longer suppresses the suspect. Sender-side artifacts are
  exempt in code (B) and the directive tells the model why (I).
- **Honesty note, unchanged by this session:** `contract_valid` is a post-hoc
  signal (TD-012). Every turn above conformed, but a non-conforming answer would
  still have streamed to the user — the pin detects a launder, it does not
  prevent one. See render.py's docstring for the precise split.
