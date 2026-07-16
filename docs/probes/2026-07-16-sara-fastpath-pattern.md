# Probe: SARA Open fast-classifier / 92-8 pattern (S4 design source)

- **Date:** 2026-07-16 (S4)
- **Target:** `/home/burhan/sara-open` source tree (read-only study; no live system touched)
- **Method:** two parallel read-only subagents; all claims carry file:line cites into sara-open
- **Why:** S4 re-implements the *pattern* (never the code) in `auspex/classify/`

## The flow (where code decides "no LLM")

- Single dispatch chokepoint: `orchestrate()` — `sara/core/orchestrator/coordinator.py:158-749`.
  Every non-None return is the ~92% shortcut path; `None` falls through to the deep
  pipeline (query-analyzer LLM + RAG + agents, coordinator.py:744-749).
- `fast_classify(query)` is pure regex, <1ms, no LLM — `sara/core/orchestrator/classify.py:280-386`.
- Identity is **Phase 0, before classification** — anchored `^…$` patterns + ≤80-char gate so
  identity answers never depend on classifier drift or LLM probability
  (coordinator.py:206-217; identity_response.py:54-67). Canned, zero LLM calls.
- Handlers are **fallible by design**: `handle_ioc_check` returns `None` when nothing
  enriches; falling through to the deep path beats forcing a wrong fast answer
  (shortcuts.py:222-299,298-299).

## The regex table (single-source module)

`sara/patterns.py:1-43` — "All IOC detection regexes live here. Import from this module
instead of defining local copies."

- IPv4 octet-range-validated: `\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}…\b` (patterns.py:19-21)
- Private-IP filter `RE_IPV4_PRIVATE` + `is_public_ip()` (patterns.py:22-24,41-43)
- URL: `https?://[^\s<>"']+` (patterns.py:25); trailing junk `rstrip('.,;)')` (intel_enricher.py:177)
- Domain: **TLD-allowlist strategy** — the allowlist is what stops `report.pdf` and version
  strings matching as domains (patterns.py:26-32)
- Hashes 64/40/32 hex with `\b`; longest-first + containment guard (patterns.py:35-38;
  intel_enricher.py:189-213)
- CVE: `\bCVE-\d{4}-\d{4,}\b` IGNORECASE (patterns.py:11)
- Email: no canonical copy — two local variants (phishing.py:39, entity_agent.py:119)

## Refang (defang normalization)

Canonical: `intel_enricher.py:50-73` — `hxxp`→`http` (case-insens), `[.]`→`.`, `[@]`→`@`.
Wider artefact set in host parsing: `(.)`, `[dot]` (verdict_floor.py:194).
**Defanging is evidence**: a defanged-in-incident IOC floors the verdict at SUSPICIOUS —
the analyst defanged it deliberately (verdict_floor.py:229,321-325).

## Tiebreaks (format beats keywords)

Tail of `fast_classify` (classify.py:336-386), in order:
1. **Alert-format detection first**: `CEF:` / `LEEF:` / syslog `^<\d+>` prefixes → COMPLEX
   (deep), even if IOCs are present (classify.py:336-342).
2. **Analytical-verb veto**: sentence-initial `analyze|is this malicious|why is this|explain…`
   forces the deep path even with IOCs (classify.py:344-352).
3. IOC_CHECK: hash/public-IP always; bare domain only if not in `_COMMON_DOMAINS` AND
   (≤10 words OR check/enrich/lookup verb); whole query ≤15 words (classify.py:353-363).
4. CVE_LOOKUP: CVE present, ≤25 words, non-analytical (classify.py:365-367).
5. DEFINITION: `^what is…`, ≤10 words, no hash, not tenant-shaped (classify.py:369-380).
6. OFF_TOPIC gated to ≤20 words so long analytical text can't trip a stray keyword
   (classify.py:382-384). Fallthrough → COMPLEX.

## Pitfalls the code guards against (and one it doesn't)

- Benign/common domains as false IOCs: `_COMMON_DOMAINS` allowlist (classify.py:69-74).
- Domain-in-URL double-extraction: domains skipped when contained in an extracted URL
  (intel_enricher.py:207-213).
- Hash-length collisions: SHA-1/MD5 skipped inside matched SHA-256 (intel_enricher.py:189-206).
- Doc-id context: hex preceded by `_id:`/`doc_id:` is not a hash (intel_enricher.py:189-192).
- Trailing punctuation glued to URLs: `rstrip('.,;)')` (intel_enricher.py:177).
- Follow-ups ("tell me more") must NOT fast-path — context resolution needs the analyzer
  (query_analyzer.py:137-145).
- Short prompts + image attachments misclassify as GREETING — orchestrator bypassed entirely
  when attachments present (chat.py:2248-2263).
- **Version numbers vs IPs: NO explicit guard in SARA** — only softened by the ≤15-word gate;
  the study flags this as a gap. Auspex adds an explicit version-context guard
  (`auspex/classify/observables.py`, `_VERSION_CTX_RE`) + dotted-version lookarounds.

## What Auspex deliberately does differently (S4)

- IP validation via stdlib `ipaddress` after a loose candidate regex (code over regex);
  IPv6 supported (SARA has none) with identifier-boundary + `::`-needs-a-digit guards.
- Residual-word gate (words left after blanking observable spans) instead of SARA's raw
  ≤15-word gate — a bulk 30-hash paste stays on the fast path.
- Reference identifiers (hashes, CVEs) still extracted inside URLs (VirusTotal-link case);
  host-ish observables (domain/IP/email) are not double-extracted.
- Per-observable `defanged` flag + short deterministic `obs_id` (IDEAS.md tool-arg input).
