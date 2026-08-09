# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(Standing follow-up: **PR #15 is OPEN and unmerged** —
https://github.com/bh3082336888-cell/auspex/pull/15, MERGEABLE/CLEAN. It carries
S14 (retro-hunt + the packaging fix) plus the S15 Step-0 fixes. Merge it by hand
first; `gh pr merge` is blocked by the permission classifier. The S15 feature
commits landed on staging AFTER the PR was raised, so promote #16 carries them.
S15 shipped: Step 0 found the verdict trail's head was decided by transaction
start rather than write order — a transaction that began earlier and committed
last wrote the newest belief with the oldest stamp, so `latest_verdict` and the
retro-hunt event both reported a superseded label — and that `deleted` (an
NVD-withdrawn CVE) was announced with the copy written for a KEV addition. Then
falsification watchers: verdicts register typed conditions that would prove them
wrong, at write time; ingest and enrichment check them; a satisfied watcher
upgrades the S14 re-open event and never touches a label. CI-green 676 tests.)_

---

SESSION S16 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S16` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
re-check before every `gh` call. It did NOT flip at S13/S14/S15 start; assume it
flips anyway. Also: local `main` goes stale every promote — `git fetch` and diff
against `origin/main`, and read `git diff origin/main..staging --stat` rather
than the commit list, which the squash workflow makes meaningless.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **Check the TD-005 re-battery trigger first — it is close.** The corpus was
  **25,938** docs in `auspex-knowledge` at S15 start and grows ~770/day while
  the container runs. Over 30k → re-run the labeled retrieval battery before
  trusting any RAG-backed answer this session. (`curl -s
  "localhost:9200/_cat/indices/auspex-knowledge?v"`.)
- **Fresh-eyes review of the S15 commits** — scope: `233c132` (watchers: types,
  derive, store, sink, route, 1 table, the circular-import fix), `e940efd`
  (probes/D-021), and the Step-0 fixes `4c00af9`/`1e8e5dc`/`fa7b70b` if #15 has
  not shipped them. This code is live-verified with 29 tests but has had no
  independent adversarial pass. Angles S15 did NOT test:
  - **(order dependency — strongest lead) `satisfy_documents` links the re-open
    event by natural key including `change_kind`,** so it only finds the match
    if `RetroHuntSink` already wrote it — and `FanoutSink` happens to emit
    retro-hunt first. Reorder the two sinks and `falsifies` silently stops
    appearing, with no error anywhere. This is the exact class of defect S15
    fixed TWICE (the trail ordering, the circular import): correct by order, not
    by construction. Decide deliberately — make the link order-free, or make the
    order an enforced invariant rather than a coincidence.
  - **(double swallow) `FanoutSink` catches per sink and both sinks already
    catch internally.** A watcher check failing every cycle logs and is
    otherwise invisible; nothing counts consecutive failures. Is a silently dead
    falsification checker distinguishable from one with nothing to do? (The
    circuit-breaker precedent in `auspex/enrich/breaker.py` is the shape to
    consider.)
  - **(concurrency) escalation satisfaction under concurrent enrichment.** S15
    pinned concurrent REGISTRATION but not concurrent `check_escalation` — two
    enrichments racing on one observable, one escalating and one not. Verify
    with `asyncio.gather` against the live DB, not by reading.
  - **(claim text) `claim` is built from `observable.value` plus provider names
    and stored unbounded.** The S4 classifier validates CVE shape so this is
    probably fine — verify by execution rather than assume, and check what an
    edge/non-CVE observable actually produces.
  Verify findings BY EXECUTION before fixing; fix with regressions.
- **Then `/promote` #16** (S15 will have been reviewed once by then). Expect
  `gh pr merge` to be blocked by the permission classifier — I merge by hand,
  then Claude back-merges.

Goal (scope-locked, from ROADMAP.md S16 — Verdict timeline UI, Phase 3):

1. **A verdict's life, readable end to end.** The substrate now exists and has
   never been rendered: the append-only `verdicts` trail (D-017 decay fields),
   `verdict_flips` (S14 — what changed and why), `retrohunt_matches` (S14 — what
   intel re-opened it), and `watchers` (S15 — what the verdict committed to
   being wrong about, and which of those claims were contradicted). Start by
   reading `auspex/retrohunt/store.py`, `auspex/watchers/store.py`, and
   `auspex/enrich/verdict.py::effective_confidence` — the decay curve is
   executable and pinned by a test but **nothing has ever rendered it**.
2. **Decay and staleness get a vocabulary.** `effective_confidence` has existed
   since S5 and no surface uses it. Decide what "stale" means in code (not
   prose), and answer TD-020's open question rather than inheriting it: an open
   falsification claim attached to a verdict that has fully decayed still reads
   as "open" with the same weight as one written yesterday.
3. **"Your past got re-scored."** The view an analyst opens after a week away:
   what changed, what contradicted a claim we made, what is now stale. Reuse the
   existing event surfaces — do not invent a third notification shape (D-020,
   D-021 both say this and it has held twice).

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic. Zero LLM on this
  path — it is rendering and arithmetic over rows we already have.
- The dark-first brand palette is locked (CLAUDE.md Brand, D-002) — Night
  `#0A0D12`, Aurora `#4FF2C0`, Signal `#FFB454`, Ember `#FF5D5D`, Slate
  `#8B93A7` for stale/DEFERRED. Space Grotesk / Inter / JetBrains Mono.
  Never leak the underlying model or provider name into user-visible strings.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth.
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly if you forget —
  do not work around it.
- Plan assertions must VACUUM first, and only assert plans at table sizes where
  a scan would actually cost something (both existing suites seed 25k) — small
  tables legitimately seq-scan.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 9× now); TD-012 (post-hoc
  validation); TD-014 (unbounded history); TD-015 (brand/confusable coverage);
  TD-016 (ACH surface bounds); TD-017 (chat-side NUL hardening); TD-018
  (per-workspace inference-call bound — S19 owns it); TD-019 (retro-hunt v1
  bounds); TD-020 (watcher v1 bounds: CVE-shaped vocabulary, `provider_escalation`
  is passive, open watchers never expire); model-PROPOSED hypotheses/evidence
  and model-PROPOSED falsifiers (D-019-later, D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move
  on. Tired human = short session; rituals anyway.
- End with `/session-end`; S16 done = a verdict's full history renders in one
  place with decay made visible, staleness defined in code, satisfied claims and
  re-open events shown as the events they already are, all pinned by hermetic
  tests and live-verified in-container.
