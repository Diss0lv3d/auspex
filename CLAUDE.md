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
- **LLM**: dev endpoint = Z.ai general API, `glm-4.5-air` (D-034; Scout on
  Northflank is decommissioned). `LLM_BASE_URL` is the provider's documented API
  root (D-033). Prod = whatever the customer configures.
- Embeddings: probe server-side (OpenSearch ML) first; fallback = in-process
  sentence-transformers all-MiniLM-L6-v2.

## Working protocol (the work-proof strategy — non-negotiable)

One human (Burhan) + one LLM (Claude), across many sessions. These rules exist
because LLMs hallucinate and humans paste prompts into wrong windows and get tired.
**The repo is the only memory either of us trusts.**

> Shortcut: `/session-start`, `/session-end`, `/probe`, `/idea`, `/bug`,
> `/review-issue`, `/explain-issue`, `/promote` (in `.claude/commands/`)
> encode these rituals — prefer them over doing the steps by hand.

> Collaborators (D-059): Burhan may hand a session to a collaborator, who works
> under their own personal identity (SESSION-RULES.md, "Identity and `gh`") and
> owns the calls the handoff names. New to the repo? Read `HANDOFF.md` first.

### Tracks (D-051)
Sessions run in three tracks, one session at a time:

| Track | Prompt | Session ids | Start with |
|---|---|---|---|
| backend | `NEXT-SESSION-BE.md` | S29, S30, … | `/session-start be S<n>` |
| front end | `NEXT-SESSION-FE.md` | F1, F2, … | `/session-start fe F<n>` |
| bugs (from `BUGS.md`) | `NEXT-SESSION-BUGS.md` | B1, B2, … | `/session-start bugs B<n>` |

- Rules every track obeys live once, in `SESSION-RULES.md`. A prompt holds
  only its own session.
- Moving numbers (tests, modules, the promote slate) live only in `STATE.md`,
  and so do the Tracks table and which track is the focus.
- `/session-start` with no track asks which one; it never picks.

### Session start ritual (every session, before any work)
1. `pwd` must be this repo. Read `STATE.md`, `SESSION-RULES.md`, then the
   track's prompt (`NEXT-SESSION-<BE|FE|BUGS>.md`).
   Work happens on `staging` (D-010) — `main` only moves via `/promote`.
2. Verify the pasted prompt's track and session id match that file's header.
   **Mismatch or missing → STOP and tell the human "wrong window / wrong session,
   expected <id> on the <track> track" — do not improvise.**
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
6. **Scope lock.** The session goal is whatever the track's prompt says. New
   ideas go to `IDEAS.md`, bugs found to `BUGS.md` (`/bug`) — one entry, move
   on. Do not implement them.
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
11. Update `STATE.md` (done / in-flight / blockers / next, and this track's
    row of the Tracks table).
12. Rewrite this track's `NEXT-SESSION-<BE|FE|BUGS>.md` with the complete prompt
    for its next session — the human should never have to remember or compose
    anything. Then fix anything this session made untrue in the other two.
13. Tick ROADMAP.md checkboxes. Log any shortcut in `TECHNICAL_DEBT.md`.
14. Commit everything. End with a ≤10-line summary for the human:
    what shipped, what's blocked, what to paste next.
15. A change of scope or focus said after the ritual is written into STATE.md
    and the prompt files before the window closes (D-051).

### Human-side rules (Claude: remind Burhan if violated)
- Only ever paste from a `NEXT-SESSION-<BE|FE|BUGS>.md` file, the one for the
  track you mean to work on. If unsure which window this is, ask Claude to run
  the start ritual — that's what it's for.
- Decisions get made once, in `DECISIONS.md`. If we're re-debating a D-entry,
  Claude must point at it and ask "overturn or drop?"
- Tired human = short session. Ending early with rituals done beats pushing on.

## File map

| File | Purpose |
|---|---|
| `STATE.md` | Single source of truth: where we are right now |
| `ROADMAP.md` | Phases + per-session deliverables, one section per track |
| `NEXT-SESSION-BE.md` | The exact prompt for the next backend session (S<n>) |
| `NEXT-SESSION-FE.md` | The exact prompt for the next front-end session (F<n>) |
| `NEXT-SESSION-BUGS.md` | The exact prompt for the next bugs session (B<n>) |
| `SESSION-RULES.md` | Standing rules every session reads, whatever its track |
| `BUGS.md` | What is broken, found by using the platform; the bugs track's list |
| `DECISIONS.md` | Numbered, dated, immutable-once-ratified decisions |
| `IDEAS.md` | Parking lot — never implemented directly from here |
| `TECHNICAL_DEBT.md` | Shortcuts taken, with risk + path to fix |
| `docs/probes/` | Saved reality snapshots of external systems |
| `docs/ENV_VARS.md` | Every env var, documented |
| `HANDOFF.md` | Handbook for a collaborator taking over a session: setup, workflow, commands |

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
