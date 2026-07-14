# CLAUDE.md — Auspex

## What this is

**Auspex** — a cloud-native security intelligence platform. An AI co-analyst with
SOAR-grade action capabilities built in (proposals + approvals + custom actions via
a future Python SDK), a living threat-knowledge base, and a **customer-supplied LLM**
(the platform adapts to whatever OpenAI-compatible endpoint the customer brings —
we never pay for inference).

Flagship differentiators (see ROADMAP.md Phase 3):
1. **Capability-negotiated agent runtime** — probe the customer's LLM endpoint,
   compile the agent loop to what the model can actually do (native tools →
   prompted tools → plan-only), show a capability scorecard.
2. **Living Verdicts** — verdicts carry decay curves; new intel retro-hunts
   historical observables; every verdict registers falsification watchers.
3. **Herd Immunity** (later, multi-workspace) — anonymized confirmed verdicts
   propagate across workspaces (k≥3 anonymity threshold).

Origin: architecture study of SARA Open (sara-open). We reuse its *patterns*
(92/8 regex split, code-picks-the-mode, instructions-in-system/data-in-user,
destructive-always-gates, DEFERRED rail), not its code.

## Stack (locked — see DECISIONS.md before changing)

- **FastAPI + asyncpg**, async throughout. Docker-compose for everything.
- **Postgres** — transactional data (users, workspaces, sessions, messages,
  verdicts, approvals, jobs via SKIP LOCKED). ACID matters here.
- **OpenSearch 2.19.x — our own container in docker-compose** (D-009). KB/RAG,
  observables search, telemetry; `auspex-*` index prefix. SARA's DO cluster was
  probed read-only for schema conventions and is **never** used by Auspex at
  runtime — its creds stay out of Auspex config.
- **LLM**: dev endpoint = Northflank vLLM (Llama-4-Scout-17B, OpenAI-compatible
  `/v1/chat/completions` with `tools`). Prod = whatever the customer configures.
- Embeddings: probe server-side (OpenSearch ML) first; fallback = in-process
  sentence-transformers all-MiniLM-L6-v2.

## Working protocol (the work-proof strategy — non-negotiable)

One human (Burhan) + one LLM (Claude), across many sessions. These rules exist
because LLMs hallucinate and humans paste prompts into wrong windows and get tired.
**The repo is the only memory either of us trusts.**

### Session start ritual (every session, before any work)
1. `pwd` must be this repo. Read `STATE.md`, then `NEXT-SESSION.md`.
2. Verify the pasted prompt's session number matches `NEXT-SESSION.md`.
   **Mismatch or missing → STOP and tell the human "wrong window / wrong session,
   expected S<N>" — do not improvise.**
3. Run `git log --oneline -5` and `docker compose up -d && docker compose ps`
   (once compose exists) to confirm reality matches STATE.md. Divergence → fix
   STATE.md first, then work.

### While working
4. **Reality over memory.** Never code against a remembered/guessed API, schema,
   or model behavior. Probe the live thing first, save the response to
   `docs/probes/YYYY-MM-DD-<thing>.md`, code against the snapshot. If it wasn't
   executed, it isn't true.
5. **Cite or probe.** Claims about our code → `file:line`. Claims about external
   services → a probe file. No invented env vars: every var exists in
   `.env.example` + `docs/ENV_VARS.md` the moment it's born.
6. **Scope lock.** The session goal is whatever NEXT-SESSION.md says. New ideas
   go to `IDEAS.md` — one line, move on. Do not implement them.
7. **Thrash brake.** Two consecutive failed approaches on the same problem →
   stop, write what was tried + why it failed into STATE.md "Blockers", and
   either move to the next task or end the session. No third attempt in the
   same session.
8. **Tests ship with the feature.** Same session, no exceptions. `main` always
   passes `docker compose up` + `pytest` — always-demoable invariant.
9. **Secrets:** `.env` is gitignored; no literal defaults for secrets in code;
   placeholders only in examples.
10. One concern per commit. Commit messages: `feat|fix|chore(scope): summary`.

### Session end ritual (never skip, even on a bad session)
11. Update `STATE.md` (done / in-flight / blockers / next).
12. Rewrite `NEXT-SESSION.md` with the complete prompt for the next session —
    the human should never have to remember or compose anything.
13. Tick ROADMAP.md checkboxes. Log any shortcut in `TECHNICAL_DEBT.md`.
14. Commit everything. End with a ≤10-line summary for the human:
    what shipped, what's blocked, what to paste next.

### Human-side rules (Claude: remind Burhan if violated)
- Only ever paste from `NEXT-SESSION.md`. If unsure which window this is, ask
  Claude to run the start ritual — that's what it's for.
- Decisions get made once, in `DECISIONS.md`. If we're re-debating a D-entry,
  Claude must point at it and ask "overturn or drop?"
- Tired human = short session. Ending early with rituals done beats pushing on.

## File map

| File | Purpose |
|---|---|
| `STATE.md` | Single source of truth: where we are right now |
| `ROADMAP.md` | Phases + per-session deliverables (S1–S20) |
| `NEXT-SESSION.md` | The exact prompt to paste to start the next session |
| `DECISIONS.md` | Numbered, dated, immutable-once-ratified decisions |
| `IDEAS.md` | Parking lot — never implemented directly from here |
| `TECHNICAL_DEBT.md` | Shortcuts taken, with risk + path to fix |
| `docs/probes/` | Saved reality snapshots of external systems |
| `docs/ENV_VARS.md` | Every env var, documented |

## Brand (locked 2026-07-14, D-002)

- **Name:** Auspex (Latin: one who reads the future from the flight of birds —
  watching signals, prediction, the flock).
- **Tagline:** "The flock sees first."
- **Voice:** calm, precise, analyst-to-analyst. Never "AI magic" copy.
- **Palette (dark-first):** Night `#0A0D12` bg · Surface `#11161F` ·
  Text `#E7ECF3` · Aurora `#4FF2C0` (primary accent / benign) ·
  Signal `#FFB454` (warning / suspicious) · Ember `#FF5D5D` (critical / malicious) ·
  Steel `#7AA2F7` (info / links) · Slate `#8B93A7` (muted / DEFERRED / stale).
- **Fonts:** Space Grotesk (display), Inter (body), JetBrains Mono (data/IOC/code).
- The customer-facing model name is **the platform's engine** — never leak the
  underlying model/provider name into user-visible strings.
