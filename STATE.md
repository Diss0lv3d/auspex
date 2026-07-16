# STATE — Auspex

_Last updated: 2026-07-16 (S4 complete — 92/8 fast classifier, all steps incl. stretch)_

## Where we are
- **S4 COMPLETE** (steps 1–3 + stretch step 4, all with tests) → **next is S5**
  (Enrichment fan-out + verdict store — see NEXT-SESSION.md).
- **Promoted:** promote #3 (S2+S3+D-014/015/016) is on `main`; S4 is on
  `staging` only — S4 is a demoable milestone, so a `/promote` is reasonable.
- **Primary dev LLM (D-015):** Llama-4-Scout-17B via Northflank (remote vLLM,
  `native_tools`). **Secondary/offline:** local Ollama `qwen3:14b` (D-013);
  `llama3.1:8b` = weak-endpoint case. `.env` is source of truth (gitignored).
- **CI-green: 177 tests** (was 101 at S3 end; +76 this session). `./ci.sh`
  passes end-to-end: ruff, pytest, container build + health.

## S4 shipped (all committed on staging, 2026-07-16)
- **Step 1 — `auspex/classify/observables.py`:** defang-aware extraction +
  normalization (IPv4/IPv6 via candidate-regex + stdlib `ipaddress`,
  TLD-allowlist domains with internal-suffix backtrack, URLs, SHA-256/1/MD5
  span-tiebroken, emails, CVEs). Refang covers hxxp/[.]/(.)/{.}/[dot]/[at]/[:]
  and tracks rewritten chars, so each Observable carries a **positional
  `defanged` flag** (verdict-floor input for S7) + a short deterministic
  `obs_id` (e.g. `ipv4-c3045edd` — tool-arg friendly, IDEAS.md). Pattern
  source snapshot: `docs/probes/2026-07-16-sara-fastpath-pattern.md`.
- **Step 2 — `classifier.py`:** code-owned categories greeting/identity/
  ioc_check/cve_lookup/definition/deep. Format beats keywords (CEF/LEEF/
  syslog/JSON pastes → deep even with IOCs; analytical-verb veto incl.
  definition-shaped asks); residual-word gates keep bulk IOC pastes fast;
  suffix-aware common-domain suppression (defanged common domains still
  count); greeting = true salutations ONLY (bare "ok"/"thanks" go deep — a
  mid-investigation ack must reach the model). Errors bias deep.
- **Step 3 — `shortcuts.py`:** static on-brand answers (engine never named,
  test-enforced via the now-canonical FORBIDDEN_ENGINE_NAMES in
  `tests/_fakes.py`); ioc_check echoes normalized observables + ids +
  defanged markers, defers enrichment honestly (no fabricated verdicts,
  D-014 spirit); cve_lookup/definition defer to KB (S6) with a deep-path
  pointer. Plain text (UI renders verbatim). Tests prove the path offline:
  socket-block fixture + structural import scan.
- **Step 4 (stretch) — 92/8 gate in `/api/chat`:** classify BEFORE the model;
  shortcut turns stream deterministic answers with zero LLM calls; `done`
  frame carries `path: "shortcut"|"model"`. `ChatEndpointResolver` resolves
  the endpoint lazily — unknown dev `endpoint_id` still 404s eagerly, but the
  scorecard DB read + httpx client construction happen only on deep turns
  (fixes a client-leak window + per-greeting waste). Unconfigured LLM now
  503s only deep turns; shortcuts work with no LLM at all (real-dependency
  test included). `ChatBody.message` capped at 32k (bounds in-loop regex).
- **Review pass (8-angle adversarial, all findings fixed):** Dockerfile
  deps-layer skeleton gained `auspex/classify` (image didn't build without
  it); IPv6-trailing-period, `-v`-flag-vs-version, defanged-substring-
  lookalike extraction bugs; UI `send()` now surfaces HTTP errors (deep-turn
  503 no longer an empty bubble). TD-003 logged (test-helper duplication).
- **Live-verified in-container:** greeting + defanged-IOC paste stream
  `path: "shortcut"` with normalized values/ids/defanged markers through the
  rebuilt container, LLM never touched.
- **Human sign-off (2026-07-16):** Burhan approved the customer-facing
  shortcut copy (shortcuts.py) as-is and eyeballed the UI in a browser
  (plain-text echo + error bubble render fine). Don't reword without asking.

## In-flight / standing follow-ups (carry forward until DONE)
- Nothing event-triggered outstanding.

## Blockers / open risks
1. **Embeddings approach unmeasured** — probe in S6 (decided).
2. **TD-001 (OAuth identity keyed on email)** — hard gate before any
   GOOGLE_CLIENT_ID is configured.
3. **Deep path is conversational-only (v1)** — AgentLoop (tools) still not
   wired into /api/chat; history replay unbounded; shortcut answers are
   persisted and replayed into deep-turn history (few-shot contamination
   risk). All parked in IDEAS.md; modes land S9.
4. **Live model-path smoke checks must assert `done.path == "model"`** —
   definition-shaped smoke messages now shortcut (caution appended to
   docs/probes/2026-07-16-server-to-ollama-networking.md).

## Host notes (reality snapshot)
- Postgres host port **55432**; app 8000; OpenSearch 9200. Host-run scripts
  and tests pin `DATABASE_URL`/`OPENSEARCH_URL` via `auspex.devhost` (no
  LLM_BASE_URL pin per D-015).
- Ollama 0.24.0 (snap) on :11434, binds `*:11434` (container reaches it via
  host.docker.internal); models qwen3:14b / llama3.1:8b / mistral:latest.
  GPU: RTX 5070 Ti Laptop 12 GB.
- Host reboots between sessions — `docker compose up -d` at start (ritual
  covers it); rebuild app image on source changes (`--build`, ci.sh does it).
- Mid-S4 note: the compose stack went down mid-session once — cause confirmed
  by Burhan as a manual machine restart (not daemon flakiness). If pytest
  suddenly can't reach :55432, `docker compose up -d --wait` first.

## Reference intelligence (from the SARA Open architecture study, 2026-07-14)
Base: `/home/burhan/sara-open/` (paths re-verified 2026-07-15):
- ReACT loop: /home/burhan/sara-open/sara/core/agent_loop.py:60
  (S3 loop pattern; Auspex loop is `auspex/agent/loop.py`)
- Plan→DAG→Judge loop: nearest surviving copy is
  /home/burhan/sara-open/.claude/worktrees/1359-chain-surface/sara/core/orchestrator_loop/runner.py:39
  (worktrees get cleaned; re-snapshot to docs/probes/ before S8)
- Permission hard-rails: /home/burhan/sara-open/sara/core/permissions.py:65-176
  (S3 gate pattern; Auspex gate is `auspex/agent/permissions.py`)
- Fast classifier / 92-8: snapshot now in
  docs/probes/2026-07-16-sara-fastpath-pattern.md (S4 pattern source)
- RRF retrieval + ID bypass: /home/burhan/sara-open/sara_retriever.py:538,599
- DEFERRED rail: /home/burhan/sara-open/sara/agents/alert_triage.py:1429
- Capability shape: /home/burhan/sara-open/sara/core/unified_registry.py:37

## Next session should
Run S5 exactly as written in NEXT-SESSION.md (Enrichment fan-out + verdict
store). Consider `/promote` of the S4 milestone first (staging → main).
