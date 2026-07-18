# KB Strategy — sourcing, tenancy, and flock knowledge

_Living strategy doc. Started 2026-07-18 (S8 research follow-up). Records the
"where does the KB's knowledge come from, and who owns it" direction so future
sessions inherit the reasoning, not just a wishlist. **Not yet ratified** —
items marked → D-CANDIDATE are ripe to graduate into DECISIONS.md when Burhan
signs off._

## 0. The load-bearing distinction: two systems, never merged

- **Knowledge Base** — durable, *verified* facts, rendered verbatim to the
  tenant with a Source line. "What is Qakbot", "how does Kerberoasting work",
  "what does CWE-79 mean". Slow-changing, authoritative. Hourly refresh is
  ample. This is what this doc is about.
- **Enrichment / intel pipeline** — fast-decaying *observables* ("is this
  ip/hash/domain bad right now"), looked up per-query, never rendered as
  settled knowledge. abuse.ch (URLhaus/ThreatFox), OTX, GreyNoise,
  InternetDB, AbuseIPDB already live here — NOT in the KB, by design (an IOC
  is stale in days; a verbatim knowledge doc built on it ships lies with a
  fuse).

Consequence — "real-time ETL" is the wrong ambition for the KB: the value is
*freshness of facts*, which the S7 hourly scheduler already delivers. Sub-minute
pipelines belong (if anywhere) to the enrichment side. Don't chase latency the
KB doesn't need.

## 1. Public-source sourcing (the 2026-07-18 survey)

Full verified survey with live-checked licenses:
`docs/probes/2026-07-18-kb-sources-research.md`. Headlines:

- **Ingest-ready, licenses verified clean:** the rest of the ATT&CK bundle we
  already download (groups/malware/tools/campaigns/mitigations — zero new
  fetch), MISP Galaxy actors (CC0), Sigma (DRL 1.1), Splunk security_content
  (Apache-2), CWE/CAPEC/D3FEND, NIST glossary + SP 800 (public domain), GHSA
  reviewed (CC-BY), Metasploit metadata (BSD-3), CISA/NCSC/CERT-EU advisories.
- **Exploitation-signal chain ("is this a live/emerging threat"):** we hold
  KEV + EPSS; CISA Vulnrichment (CC0) and Metasploit complete it. There is no
  "zero-day feed" to ingest — a true 0-day isn't publicly documented, and
  pre-disclosure intel (Mandiant/ZDI) is premium and non-redistributable.
  Honest capability = the exploitation-signal chain, not a crystal ball.

### 1a. Dark web → NOT in the KB → D-CANDIDATE (decided direction)

Ingesting dark-web content into the shared KB is rejected, and not merely on
caution:

- Its content is largely stolen credentials, breach dumps, and PII. Rendering
  it verbatim = redistributing stolen personal data — a head-on collision with
  the org data-handling rule (never echo PII/credentials/IOCs) and KSA data
  residency.
- It is unverified by nature (rumor, disinfo, scams) — the opposite of what a
  verbatim authoritative KB is for.
- The legitimate version is a *different product*: **per-tenant exposure
  monitoring** ("is MY org's data leaked"), sourced through vetted commercial
  feeds with legal machinery and counsel — an alerting/enrichment capability,
  never a shared KB rendered to everyone.

### 1b. OWASP / CIS → do NOT paraphrase-launder → D-CANDIDATE (decided direction)

- OWASP (CC BY-SA) and CIS Benchmarks (CC BY-NC-SA) can't be ingested verbatim
  by a commercial product (ShareAlike is viral; CIS's NC bars it outright).
- **"Reword it and it's ours" is rejected as a workaround.** Paraphrase
  produces a *derivative work*, which the holder controls; and CC BY-SA's
  ShareAlike + CC BY-NC-SA's NC both attach to *adaptations*, so rewording can
  leave our notes *encumbered*, not freed. An LLM-rewrite is the worst version
  (closest paraphrase, most infringement-prone). It also breaks the KB's own
  provenance-honesty ethic.
- **Decision:** if we want OWASP/CIS content, we acquire the rights properly —
  a paid **CIS SecureSuite** vendor license and a counsel-cleared OWASP use —
  as a business-development step, not an engineering trick. **FLAG:** revisit
  this the moment "best-practices content" becomes an upsell.

## 2. OEM posture changes who authors content

Auspex is an **OEM / platform**, not an MSSP. We do not staff security writers
to author a central best-practices corpus. Consequence: the "write our own
original best-practices content" moat is **not ours to build centrally** — it
belongs to the tenants who operate on the platform. This reframes the whole
"best practices / doctrine" question below.

## 3. Tenant-scoped KB (with multi-tenancy) → the clean answer

When multi-tenancy + tenant isolation land (D-008 reserved the `workspace_id`
column; the KB index already carries `workspace_id`, "" = global today), extend
isolation **into the KB**:

- Each tenant gets a **private KB layer** — their own doctrines, playbooks,
  runbooks, best practices, internal standards, and any third-party content
  **they are licensed for** (including their *own* CIS SecureSuite / OWASP
  usage rights). The KB becomes tailored per tenant, not one-size-fits-all.
- This **cleanly sidesteps the OWASP/CIS problem** for tenant-owned content:
  the licensing burden sits with the tenant who holds the rights — exactly
  right for an OEM model.
- Retrieval reads `global ∪ this-tenant`; writes are tenant-scoped; the
  isolation invariant (below) is never violated by a private-layer read.

## 4. Flock knowledge exchange — "the flock sees it first"

The differentiator. Extends CLAUDE.md's Phase-3 **Herd Immunity** (anonymized
confirmed verdicts propagate across workspaces at k≥3) from *verdicts* to
*expertise*:

- **The vision (Burhan):** reciprocal, consented sharing of **reasoning /
  doctrine / logic** — never credentials, PII, or raw tenant data — across the
  flock. "Contribute-to-receive" as a license term: owning Auspex means you
  willingly share your expertise, and in return you receive the flock's. A
  network-effects moat: every tenant makes every other tenant's Co-Analyst
  smarter.
- The shareable unit is *abstracted logic* ("this class of behavior tends to
  precede that"), not artifacts. k≥3 anonymity is the propagation gate,
  inherited from the Herd Immunity design.

## 5. Open questions / hard constraints — solve BEFORE the flock ships

These are engineering/legal flags on §4, recorded so they're inherited, not
rediscovered. None of them kills the vision; all of them shape it.

1. **Tenant-isolation invariant (org rule, non-negotiable).** The shared layer
   must be a *separate, explicitly-consented, abstracted* corpus reached
   through an anonymization gateway — **never a cross-tenant read**. No path
   may let one tenant's query touch another tenant's private layer directly.
   The flock corpus is a third scope (global ∪ tenant ∪ *flock-abstracted*),
   populated only by the gateway.
2. **"Logic can still leak posture" — the subtle one.** A tenant's doctrine
   reveals their gaps, tooling, and architecture ("we don't watch X because
   Y" is itself attacker-grade intel). The shareable/sensitive boundary is
   *harder* than credential-stripping — it needs a classification + review
   model, not a regex. Abstraction must destroy tenant-identifying and
   tenant-endangering signal, not just secrets.
3. **Consent model + tiered licensing.** Opt-in per tenant, possibly per
   data-class. Some enterprise tenants will pay *more* to NOT share (data
   sensitivity) — so "contribute-to-receive" is a *tier*, not a universal
   mandate. Non-contributors get global + own-tenant only; contributors get
   the flock layer.
4. **KSA / data residency (hard org requirement).** A KSA-region tenant's
   contributions may not flow into a pool on non-KSA infra, or be readable by
   non-KSA tenants, if the contribution counts as tenant data — even
   abstracted. Likely implication: **region-scoped flocks**, not one global
   pool. Must be designed in, not bolted on.
5. **Poisoning from inside the trust boundary.** A compromised or malicious
   tenant can poison shared reasoning — the same feed-poisoning threat the S7
   review hardened against, now *inside* the tenant boundary where input is
   more trusted. k≥3 is an anonymity gate, **not** a poisoning defense; the
   flock layer needs its own provenance-weighting / anomaly checks.

## 6. Sequencing

Phase 3 territory (matches CLAUDE.md's Herd Immunity placement). Prereqs, in
order:

1. **TD-001** resolved (OAuth identity keyed on Google `sub`, not email) — the
   hard gate before any real multi-tenant identity.
2. **Multi-tenancy + tenant isolation** proper (row-level scoping enforced,
   super-admin the only cross-tenant role).
3. **Tenant-scoped KB** (§3) — private layer, `global ∪ tenant` retrieval.
4. **Abstracted flock layer** (§4) — only after §5's gateway, consent, region,
   and anti-poisoning designs exist.

Public-source ingestion waves (§1) are independent of all this and can proceed
on the global layer meanwhile — each wave trips the TD-005 re-battery trigger
by definition (new doc_types), and DRL/CC-BY/OGL sources need the per-doc
attribution machinery built once before the Sigma wave.
