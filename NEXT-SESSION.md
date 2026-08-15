# NEXT-SESSION — paste everything below the line into a fresh Claude Code window opened in /home/burhan/auspex-new

_(**Four commits are waiting to promote** — `2bb20ad`, `e14a684`, `74adb7d`,
`928705a` — plus this session-end commit. **`gh` did NOT flip to the work account
at S19 start**, but it did at S18 and S16 — unpredictable is the pattern, so
re-check anyway. S19 shipped: Step 0 found the S18 hand-off was **stale about its
own promote** (PR #18 had already merged), then answered the **first-ever TD-005
re-battery** — both floors verified sound at 9.3× the calibration corpus and
nothing fabricates — while catching that the battery had been measuring the neural
leg when users read the **fused** top hit (**3/7 definitions render the wrong ATT&CK
page**, TD-026). The S18 review confirmed the fingerprint blind spot was real
(a new declared field fingerprinted **byte-identically**) and fixed it plus a
version-bump message that told the analyst a lie. Then Hardening: the guard asks
whether an instruction is **ISSUED or ANALYSED**, and TD-018 finally closed with
per-workspace inference ceilings claimed 8-way-race-proof. **A pasted phishing
email containing "ignore all previous instructions" is still analysed; the same
sentence issued bare is refused in code.** CI-green 883 tests, 116 modules.)_

---

SESSION S20 of Auspex. Working dir must be /home/burhan/auspex-new — run
`/session-start S20` first (full ritual). Primary dev LLM is **Llama-4-Scout via
Northflank (D-015)**; local Ollama `qwen3:14b` is the secondary/offline endpoint
(D-013) and is what the session-start local-Ollama gate validates. Any mismatch →
STOP and tell me. (D-011: `gh` flips to the work account between AND mid-session —
it did at S18 and S16, did not at S17, S13–S15 or S19, so assume it has and
re-check before every `gh` call. `gh pr edit` fails on this repo with a
Projects-classic GraphQL error — use `gh api -X PATCH repos/.../pulls/N`. Local
`main` goes stale every promote — `git fetch` and read
`git diff origin/main..staging --stat`, **never the commit list**. And: **the app
container runs the built image, not the working tree** — a new migration needs
`docker compose up -d --build app`, not `restart`.)

Step 0 (carried follow-ups, do BEFORE new scope):

- **`/promote` first.** `2bb20ad`, `e14a684`, `74adb7d`, `928705a` and the S19
  session-end commit are on staging and not on `main` (real diff: 26 files,
  +3565/-18). Confirm the gh ACTIVE account is `bh3082336888-cell` immediately
  before the call, then back-merge and assert the tree is unchanged.
  **Then update STATE.md to say the promote happened** — S18's session-end commit
  was written before its promote and shipped a hand-off that was wrong about it,
  which cost S19 Step 0 a correction. Do not repeat that.
- **Fresh-eyes review of the S19 commits** — scope: `74adb7d` (the fingerprint
  fixes) and `928705a` (`auspex/guard.py`, `auspex/limits.py`, the chat and
  investigations wiring, the migration). Angles S19 did NOT adversarially test:
  - **(strongest lead — the guard's regexes ARE the attack surface.)** The whole
    rail is five regexes and four carve-outs, and S19 tested the cases it thought
    of. Try to get an injection through: unicode homoglyphs and zero-width joiners
    inside "ignore" (note `auspex/untrusted.py` already strips those — but the
    guard inspects the RAW message, so does it?), base64/rot13 wrappers, a
    600-char pad to buy the artefact-length carve-out (that threshold is a
    *number*, and nothing stops an attacker padding to it), splitting the
    imperative across the `[^.!?\n]{0,40}` gaps, or a fake RFC-5322 header block
    to claim `_is_email_paste`. **The last one is the sharpest: two header-shaped
    lines is a low bar to forge.** Decide honestly which of these the guard should
    catch and which are out of scope — a rail that claims more than it does is
    worse than a narrow one (D-025 already says the guard bounds input, not output).
  - **(the plan fallback is a security control nobody has attacked)** `plan_for`
    resolves unknown → most restrictive. Verify there is no path where a NULL,
    an empty string, whitespace, or a case variant (`'Enterprise'`) reaches it and
    lands somewhere other than `free`. And: what happens to a workspace whose plan
    is set to a tier a FUTURE build removes?
  - **(metering honesty under failure)** A claim is made BEFORE the call. If the
    endpoint then 502s, the workspace was charged for inference it never received.
    Is that right (it protects against retry-storms) or wrong (it charges for our
    outage)? Force it and decide — and check whether a client that disconnects
    mid-stream is charged.
  - **(the window boundary)** `window_start` truncates to the hour, so a workspace
    can spend its full ceiling at 13:59 and again at 14:01. Measure it, then decide
    whether a fixed window is the right shape or whether it needs to be said out
    loud in the refusal copy.
  - **(the migration)** `ALTER TABLE workspaces ADD COLUMN ... DEFAULT 'free'` ran
    against a live table. Confirm it is genuinely idempotent on re-run and that a
    workspace created by every route (dev-login, OAuth stub) gets a plan.
  Verify findings BY EXECUTION before fixing; fix with regressions.

Goal (scope-locked, from ROADMAP.md S20 — Beta, **the last roadmap session**):

1. **Deploy pipeline.** How Auspex ships. Today `./ci.sh` locally IS the gate
   (this repo has NO GitHub Actions — `gh pr checks` reports 0 checks). Decide
   whether that changes for beta and build whatever is decided. Nothing may
   weaken the always-demoable invariant: `main` passes `docker compose up` +
   `pytest`.
2. **Docs pass.** The repo is the memory (CLAUDE.md), and a beta means someone
   other than Burhan reads it. README, `docs/ENV_VARS.md`, and an honest account
   of what Auspex does and does NOT do today — the deep path is still
   conversational-only, the guard bounds input not output, `EXECUTABLE_SYSTEMS`
   is `{"auspex"}`.
3. **Demo script.** The demo turns are scattered across nine STATE.md revisions.
   Consolidate into one runnable, ordered script that shows the differentiators:
   the 92/8 split, Living Verdicts + decay, the approval flow that really executes
   and really undoes, and S19's guard telling issued-from-analysed.

Constraints:
- Tests ship with each step (CLAUDE.md rule 8); CI hermetic.
- **Do not let the docs pass become a rewrite of history.** DECISIONS.md entries
  are immutable once ratified; if beta needs a decision overturned, that is a NEW
  numbered decision that says which one it supersedes.
- **The demo script must be honest about what is a bound.** TD-025 and TD-028 mean
  the approval flow has states with no way back; a demo that only ever walks the
  happy path is a demo that lies. Show at least one honest refusal.
- Brand is locked (CLAUDE.md Brand, D-002) — Night `#0A0D12`, Aurora `#4FF2C0`,
  Signal `#FFB454`, Ember `#FF5D5D`, Slate `#8B93A7`; Space Grotesk / Inter /
  JetBrains Mono. **Never leak the underlying model or provider name into
  user-visible strings** — a docs pass is exactly where that leaks.
- Every new env var → `.env.example` + `docs/ENV_VARS.md` at birth. S14–S19 each
  added **zero**; a deploy pipeline will probably break that streak — fine, just do
  it at birth.
- New package directory? → `pyproject.toml [tool.setuptools] packages` AND the
  Dockerfile skeleton. `tests/test_packaging.py` fails loudly if you forget — do
  not work around it. (116 modules now.)
- **Tests that touch `usage_counters` must clean up** — all dev-login users share
  the `default` workspace, and S19 lost real time to a live reading that disagreed
  with the code because the suite had leaked a row into it.
- Deferred and waiting (do NOT pick up unless explicitly re-scoped): KB-doc
  citability / ioc_check→KB-CVE-context (parked 13× now); TD-012 (post-hoc
  validation); TD-014; TD-015; TD-016; TD-017; TD-019; TD-020; TD-021; TD-022;
  TD-023 (remaining: grant-checked scope, array params); **TD-024 (the decay-read
  crossover — a costed, measured fix is written down and deliberately not taken)**;
  TD-025; **TD-026 (the wrong-definition defect — two of its seven battery labels
  are corpus-stale and must be re-examined FIRST)**; **TD-027 (HARD GATE: re-run
  the CVE battery before any free-text-over-CVEs surface ships)**; **TD-028 (the
  un-reaped `executing` row)**; model-PROPOSED hypotheses/evidence and
  model-PROPOSED falsifiers (D-019-later, D-021).
- Thrash brake: two failed approaches on one problem → STATE.md Blockers, move on.
  Tired human = short session; rituals anyway.
- End with `/session-end`; S20 done = someone who is not Burhan can clone the repo,
  read the docs, run the demo script end to end, and ship a change through the
  deploy pipeline without asking a question that the repo should have answered.
