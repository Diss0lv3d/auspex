# Probe: candidate KB ingestion sources — formats, sizes, cadences, LICENSES (verified live)

- **Date:** 2026-07-18 (S8, post-session research; 6 category scouts + 10
  adversarial license verifications, all claims fetched from the actual
  license/terms pages — not memory).
- **Why licenses lead:** the KB renders ingested text VERBATIM to paying
  customers with a Source line. That is commercial redistribution — any
  non-commercial (NC), share-alike-viral, or hosted-service-restricted
  license is disqualifying regardless of content quality.

## Tier 0 — already on our disk (zero new fetch, license already verified)

| Source | What | License verdict |
|---|---|---|
| ATT&CK bundle: intrusion-set 174 live, malware 726, tool 95, campaign 56, course-of-action 44 live (of 268 — REST ARE DEPRECATED, filter mandatory) | ~1,095 new docs: "who is APT29 (G0016)", "what is Qakbot (S0650)", "what mitigates X (M-ids)" | Verified 2×: ATT&CK ToU grants commercial use; reproduce "© 2026 The MITRE Corporation…" notice |
| ATT&CK detection graph: data-component 109, detection-strategy 699, analytic 1,758 + 21k relationship edges | "what telemetry detects T1059"; DET objects carry NO own description — needs composed-doc design | Same ToU. Park until composed-doc design exists |
| ATT&CK Mobile + ICS domains (same repo/index, ~9.8 MB) | +221 techniques (T-ids never collide with Enterprise — measured); groups/software HEAVILY overlap (18/20, 12/14) — must merge by external_id | Same ToU |

## Tier 1 — external, license VERIFIED clean, ingest-ready

| Source | Size / cadence | License (verified) | Answers |
|---|---|---|---|
| CISA Vulnrichment (SSVC) | 163,977 CVE files, multiple pushes/day | **CC0** (zero obligations) | "is there a PoC / active exploitation" for 50× more CVEs than KEV |
| MISP Galaxy threat-actor cluster | 1,017 actors, 1.27 MB, updates weekly | **CC0 OR BSD-2 dual** (verified incl. no upstream infection) | fresh + long-tail actors ATT&CK's 174 groups lack; NO stable id → BM25/neural only |
| SigmaHQ/sigma | 3,752 active rules (2,797 ATT&CK-tagged, 197 CVE-tagged); quarterly tags | **DRL 1.1** (verified: sell/publish OK; MUST keep per-rule author + rule URL + DRL notice) | "how do I detect X" — joins T-id and CVE rails |
| Splunk security_content | 2,113 detections + 362 analytic stories, ~monthly | **Apache-2.0** (verified; ingest from GitHub, NOT Splunkbase — different EULA) | richest detection prose: how_to_implement, known_false_positives |
| MITRE CWE | 944 weaknesses, ~3 releases/yr, XML only | Verified: commercial OK, reproduce copyright+license | "what is CWE-79" — every NVD CVE cites CWE ids |
| MITRE D3FEND | ~267 defensive techniques, ~2/yr | Verified: site ToU commercial grant governs the published JSON (repo MIT covers tooling) | "what defends against X" — D3-ids, maps to ATT&CK |
| MITRE CAPEC | 559 patterns, near-static (v3.9) | Same MITRE ToU family | cve→cwe→capec→technique bridge; ingest AFTER CWE |
| NIST CSRC glossary | 10,113 terms, daily export | US public domain | "what is X" definitions → existing `concept` type, smallest possible feed |
| GHSA reviewed advisories | 33,376 reviewed (SKIP 314k unreviewed NVD mirrors) | **CC-BY 4.0** | GHSA-id rail; npm/PyPI/Go/Maven ecosystems NVD covers poorly |
| Metasploit module metadata | 7,110 modules (2,668 exploits), weekly | **BSD-3** (framework DEP-5; keep notice) | "is CVE-X weaponized" — stronger than PoC links |
| MITRE CAR | 102 analytics, DORMANT since 2022 (not archived) | Apache-2.0 + NOTICE | one-shot ingest; "why this detection works" essays; tag stale |
| CERT-EU advisories | ~8–20/yr | **CC BY 4.0** | cleanest-licensed advisory prose |
| NCSC-UK reports + guidance | several items/wk (all-feed) | **OGL v3** (verified: commercial OK, attribution + OGL link, NO share-alike) | incident reports + explainer guidance |
| CISA CSAF repo (ICSA/ICSMA/VA) | 3,889 JSON advisories; changes.csv = ready-made watermark | TLP:WHITE / USG public domain | ICS/OT advisories — only if customers touch OT |
| CISA AA-series advisories | ~1–4/mo, 3k–15k words each | USG public domain + TLP:CLEAR | BEST current campaign narrative. **Caveat: cisa.gov Akamai 403'd every fetch from this datacenter host** — probe from prod egress first; HTML/PDF extraction; drop IOC tables (enrichment path, not KB) |
| FIRST EPSS bulk CSV | 349,158 CVEs daily | free-to-public w/ citation | score-column backfill; bulk host moved to epss.empiricalsecurity.com |
| NVD CPE/match data | 1.77M names / 420k match strings | public domain + NVD-API notice | "what CVEs affect nginx" — LARGE effort, version-range matching is where naive impls lie; later |
| OSV.dev | 865,710 records | per-source (no blanket) | use as ALIAS RAIL (GHSA↔CVE↔DSA↔USN), not bulk text |

## Tier 2 — legal review required before any ingest (park)

- **VulnCheck KEV — REFUTED by adversarial verification:** the friendly
  "free with attribution" page is NOT the license; registration binds to
  Service Terms (rev 2026-04-20) that prohibit making Services Data
  available free/open and bar building competitive products — Auspex is
  arguably both. Path: email community@vulncheck.com for written
  confirmation, else skip.
- **LOLBAS (242 entries) + GTFOBins (478):** best content-per-effort found
  anywhere, but both **GPL-3.0** — verbatim display in a proprietary SaaS
  is a copyleft question. Decide both together with counsel.
- **OWASP Cheat Sheets (120) + Top 10:** CC BY-SA — verbatim-with-
  attribution is arguably fine, adaptations are viral. Legal sign-off.
- **MSRC Security Update Guide:** structured facts only (KB numbers,
  Exploited flags); site ToU's only explicit grant is non-commercial —
  never the prose.

## Tier 3 — DO NOT ingest (verified disqualifiers)

- **Elastic detection-rules + protections-artifacts:** ELv2 forbids
  providing the material as part of a hosted/managed service — exactly
  what Auspex is. Content quality is irrelevant.
- **Malpedia** (CC BY-NC-SA) and **ETDA group cards** (CC BY-NC-SA):
  non-commercial + viral. ETDA is anyway derivative of sources we can
  ingest directly. **CIS Benchmarks** (CC BY-NC-SA; paid SecureSuite is
  the only route).
- **Exploit-DB:** GPL-2.0 + murky third-party authorship on submitted
  exploits; at most CSV metadata after legal review (Metasploit covers
  the signal).
- **Vendor blogs (Unit 42/Talos/Mandiant/P0) + The DFIR Report:**
  all-rights-reserved; Unit 42 explicitly non-commercial. Legitimate
  route = link + ids + own-words abstract rail ("further reading"),
  never body text.
- **ProjectDiscovery cvemap/vulnx + Shadowserver:** ToS bar
  redistribution/competitive use; our NVD/KEV/EPSS ingestion already
  covers their main inputs first-hand.

## Standing constraint

Every wave adds doc_types ⇒ **trips the TD-005 re-battery trigger by
definition** (probe 2026-07-18-td005-calibration.md). Budget the labeled
battery + possible floor shifts into any ingestion session. DRL/CC-BY/OGL
sources need per-doc attribution machinery (author + URL in Source line,
plus a licenses/notices page) — build that ONCE before the Sigma wave.
