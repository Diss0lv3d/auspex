# Auspex

**The flock sees first.**

A cloud-native security intelligence platform: an AI co-analyst with SOAR-grade
action capabilities, a living threat-knowledge base, and a **customer-supplied
LLM**. You bring an OpenAI-compatible endpoint; the platform adapts to whatever
it can actually do. We never pay for inference, and neither does a pilot.

> **Status: pre-beta.** Everything described below is built, tested and running
> — 2112 tests, `docker compose up` green. The [What Auspex does not do
> yet](#what-auspex-does-not-do-yet) section is not a roadmap wish-list; it is
> the honest boundary of what you get today, and it is worth reading before the
> feature list.

---

## Quick start

Requires Docker, Docker Compose, and Python 3.12+.

```bash
git clone git@github.com:bh3082336888-cell/auspex.git
cd auspex
cp .env.example .env          # works as-is for local dev; no secrets needed
docker compose up -d --wait
curl -s localhost:8000/api/health/ready
```

`{"status":"ready","checks":{"postgres":…,"opensearch":…}}` means you are up.
Open <http://localhost:8000> for the chat UI, or run the demo:

```bash
./scripts/demo.sh              # ~3 min, narrated, ends with an honest refusal
```

**No LLM endpoint?** Most of the platform still works — that is the point of the
92/8 split below. Set `LLM_BASE_URL` / `LLM_MODEL` in `.env` when you want the
deep path. Every variable is documented in [docs/ENV_VARS.md](docs/ENV_VARS.md).

---

## What it does

### The 92/8 split — code answers before the model does

Roughly 92% of real SOC questions have a deterministic answer, so a **code-owned
classifier** picks the path before an LLM is ever touched. IOC checks, CVE
lookups and definitions are answered by enrichment providers and the knowledge
base with **zero inference calls**. Only genuinely open-ended analysis takes the
deep path.

This is not a cost optimisation dressed as architecture. It means a workspace
whose endpoint is down, or which has hit its rate ceiling, keeps getting real
answers to most of its questions.

### Living Verdicts

A verdict is not a timestamped row that quietly rots. Verdicts carry **decay
curves** — confidence falls off on a half-life appropriate to the observable —
and every verdict registers **falsification watchers** that say in advance what
new evidence would flip it. New intel **retro-hunts** historical observables, so
an IP that was benign last Tuesday and appeared in a KEV entry this morning
surfaces on its own. `GET /api/timeline/{observable_id}` shows a verdict's whole
life, decay included.

### An approval flow that really executes — and really undoes

The agent **proposes**; a human decides. Proposals carry a **fingerprint** of the
action's full declared contract, so an approver is shown exactly what they are
approving and a spec that changed between proposal and approval fails the
re-check. Approval settles exactly once under concurrency (a conditional UPDATE,
raced and verified). A proposal nobody decides within 24 hours expires: approve and reject refuse it in the same statement, and it reads `expired`. Actions declare their own undo, and `POST
/api/proposals/{id}/undo` runs it.

`EXECUTABLE_SYSTEMS` is `{"auspex"}` — see the honesty section.

### Input guard — issued versus analysed

Auspex has a problem most products with a prompt-injection filter do not: **our
legitimate traffic IS attack text.** An analyst pastes a phishing body that says
"ignore all previous instructions" *because that sentence is the artefact under
analysis*. So the guard does not ask "does this contain an injection?" but **"is
this instruction being issued to the platform, or analysed by it?"** — a question
answerable in code.

A pasted phishing email containing that sentence is analysed normally. The same
sentence issued bare is refused with a 400 that names the rule and says how to
re-send. See [D-025](DECISIONS.md) and [D-027](DECISIONS.md) — the second of
which states, out loud, what the rail does **not** bound.

### Output rail — did our own configuration come back out?

The input guard bounds what arrives. It cannot promise that nothing got through,
so the deep path also watches what leaves. It does not ask whether an answer was
*influenced* — that is not decidable from the text, and asking a model to grade
itself is what code-owned decisions exist to avoid. It asks the question we hold
both halves of: **is the platform's own configuration being reproduced in the
answer?**

A turn that starts reproducing its own instructions is cut off mid-stream, told
to the analyst plainly, and **not persisted** — a stored assistant turn replays
into every later turn of that session, so a leak that was saved would become a
permanent one. The threshold is calibrated on live model output, not chosen: 34
real answers, a legitimate ceiling of 6 shared words, a floor of 8. A thinking
model's own thinking is held to a higher floor of 40: it reasons by quoting its
instructions (measured at 19–20 words on legitimate questions), while a
recitation runs 58 or more ([D-040](DECISIONS.md)). See
[D-030](DECISIONS.md) and the honesty section for what it does not cover.

### Capability-negotiated agent runtime

The platform probes the endpoint you bring and compiles its agent loop to what
that model can actually do — native tool-calling, prompted tools, or plan-only —
and reports a capability scorecard rather than assuming a feature set and
failing strangely. The deployment measures its configured endpoint itself, in
the background at startup and again whenever the measurement is a week old
([D-038](DECISIONS.md), [D-042](DECISIONS.md); `LLM_AUTOPROBE_ENABLED` turns it
off). Deep chat turns use the loop only when
that scorecard says native tool-calling; each tool step streams to the Thinking pane as it runs,
and every model call is counted against the workspace's ceiling as it is made.

### Per-workspace spend ceilings

A workspace's **plan is data; its limits are code.** Inference calls are counted
and capped per hour, claimed in the same statement that reads the counter (so two
concurrent turns cannot both slip under the wire). A ceiling is not an outage:
the 429 names the meter, the ceiling and the reset time, and the LLM-free paths
keep working. `GET /api/usage`.

---

## What Auspex does not do yet

Read this part. A demo that only walks the happy path is a demo that lies.

- **The agent may propose; it never acts.** A deep turn goes through the agent
  loop (enrichment, CVE lookup and knowledge-base search, each step shown as it
  runs) only on an endpoint measured to call them: the deployment's
  capability scorecard must say it calls tools natively and streams them, and an
  endpoint nobody has probed stays conversational. Alert triage and phishing analysis
  never take it, because their verdicts are computed in code (D-037). It sends
  third parties only indicators that you, or a knowledge-base record, supplied:
  an indicator the model composed is never looked up (D-039). What it looks up
  is recorded, observable and verdict, the same way the IOC check records it
  (D-049). It may call the
  platform's actions, and a call only files a pending proposal with its
  dry-run card, shown in the turn; nothing runs until a human approves it
  (D-014, D-045). A call whose dry run would change nothing is not filed. When
  an endpoint narrates before a tool call, the first 400 characters of each
  step are held back so the narration is not shown as answer (TD-036). Narration longer than that would still
  reach the analyst ahead of the result.
- **A code-decided verdict is held until it passes; nothing else is.** For alert
  triage and phishing analysis, whose Risk or Verdict the platform computes in
  code, the written answer is checked against its contract and the code's
  verdict before the analyst sees it. If it fails it is re-asked once, and then
  replaced by the code's own rendering (D-043); the analyst is never shown a
  verdict off the code's. Every other mode streams as it is written, and a
  non-conforming answer there is reported in the done frame, not repaired. On
  the dev engine 60 of 60 answers conformed
  (docs/probes/2026-10-10-s27-contract-drift.md); a customer's engine may not.
- **`EXECUTABLE_SYSTEMS` is `{"auspex"}`.** Actions execute against Auspex's own
  store — an observable annotation is real, durable and undoable. There is **no
  firewall, no EDR, no ticketing integration**. The contract, the approval gate,
  the fingerprint and the undo rail are all real; the blast radius is deliberately
  one system until a customer's first integration.
- **Two rails, two different failure modes — neither is a closure.** The input
  guard does not defeat a determined authenticated caller, because every
  carve-out is decided by text the sender controls (D-027, D-029). The output
  rail (S22, D-030) catches the platform's own configuration coming back out of
  a turn — calibrated on live output, cut off mid-stream, never persisted — but
  it does **not** catch a *paraphrase* of that configuration, and it does **not**
  judge whether an answer was influenced. An injection that produced a confident
  wrong answer looks exactly like an answer; only a verdict the platform computed
  in code can contradict one, which is what the 92/8 split is for.
- **A failed action says what it left behind only if it can look.** When a
  handler dies, the platform asks the action what of that proposal's effects
  exist. Nothing → `failed`, a checked fact. Something, or no way to look →
  `incomplete`, which joins the approvals queue. A human can put it back or keep
  it, and can also put back a claim they abandoned (D-041). An approval whose
  run never started (the process died between approve and run, or the run was
  refused because the action changed) rejoins the queue after five minutes. A
  human can run it now, re-checked exactly as approve would, or withdraw it
  (D-048). An action that
  declares no way to look is never `failed`, only `incomplete`. One bound
  remains: a handler that is merely *slow* on a run a human abandoned can land
  its write after the put-back. When it does, its answer is recorded on the
  row, never dropped. Every run and put-back carries an idempotency key, one per operation, so a
  handler can drop a repeat; the built-in note action does.
- **Definition ranking is measured on eleven queries, not a benchmark.** The
  definition path fuses over documents and picks the page a question is most
  *about*, by title/question overlap in code (`auspex/kb/canonical.py`) — 7 of 7
  correct on the labeled battery, with all four off-corpus queries still missing
  honestly. Eleven queries is the whole of that evidence. The corpus grows daily,
  and TD-005 says when the floors and labels must be measured again.
- **No billing, no multi-workspace federation, no admin console.** The plan tier
  list is a seam, not a commercial model. Herd Immunity — anonymised verdict
  propagation across workspaces at k≥3 — is designed and deliberately unbuilt.
- **Residency is a refusal, not routing.** A workspace carries a region
  (`global` or `ksa`) and the deployment one engine region (`ENGINE_REGION`).
  A workspace the engine may not serve gets no co-analyst turn, and one whose
  region no connected source may serve gets no third-party lookup — refused by
  code, with the reason. There are no per-workspace engines: a KSA client on a
  deployment whose engine is global has the LLM-free answers only. A workspace's
  own records (chats, indicators, investigations, its audit trail) are stored on
  this deployment's own database and search index, wherever the deployment runs.
  A `ksa` workspace can be created only on a deployment that declares it stores
  its data in `ksa` (`STORAGE_REGION`). One made before that rule is named in a
  startup warning, not moved. The declaration is the operator's: nothing
  verifies where the database actually runs.

---

## Architecture

```
                    ┌──────────────────────────────────────────┐
  analyst ──────────▶  input guard  (issued or analysed?)      │  code, no LLM
                    ├──────────────────────────────────────────┤
                    │  92/8 classifier — code picks the path    │  code, no LLM
                    └───────┬───────────────────────┬───────────┘
                            │ ~92%                  │ ~8%
                  ┌─────────▼─────────┐   ┌─────────▼──────────┐
                  │ shortcut answers  │   │ deep path          │
                  │ • IOC enrichment  │   │ • rate ceiling     │
                  │ • CVE lookup (KB) │   │ • typed contracts  │
                  │                   │   │ • read-tool agent  │
                  │ • definitions (KB)│   │ • SSE streaming    │
                  │   ZERO inference  │   │   customer LLM     │
                  └─────────┬─────────┘   └─────────┬──────────┘
                            └───────────┬───────────┘
                    ┌───────────────────▼──────────────────────┐
                    │ verdicts + decay · watchers · retro-hunt  │
                    │ proposals → approval → execute → undo     │
                    └───────────────────┬──────────────────────┘
                         ┌──────────────┴──────────────┐
                    ┌────▼─────┐                 ┌─────▼──────┐
                    │ Postgres │ ACID: users,    │ OpenSearch │ KB/RAG,
                    │          │ verdicts,       │  2.19.x    │ observables,
                    │          │ proposals, jobs │            │ telemetry
                    └──────────┘                 └────────────┘
```

**Stack:** FastAPI + asyncpg, async throughout. Postgres for transactional truth
(jobs via `SKIP LOCKED`). Our own OpenSearch container for KB/RAG and search
(`auspex-*` index prefix). Embeddings server-side via the OpenSearch ML plugin,
falling back to in-process sentence-transformers.

**Knowledge base:** ~41,500 documents — NVD CVEs enriched with CISA KEV and FIRST
EPSS, plus MITRE ATT&CK Enterprise techniques and tactics, ingested on
watermarked catch-up cycles. Hybrid retrieval (RRF-fused BM25 + kNN) with
**per-doc_type relevance floors calibrated against the live corpus**, so an
off-corpus question returns an honest miss instead of a confident wrong answer.

---

## Development

```bash
./ci.sh          # the gate: ruff + 2112 tests + container build + installed-dist check
make check       # same thing
make up / down   # stack lifecycle
```

`./ci.sh` is the **whole** gate, and [CI](.github/workflows/ci.yml) runs that
exact script — never a re-listed copy of its steps, so local and CI cannot drift.
It does more than run tests: it builds the container and then imports the
**installed distribution** from a directory that cannot shadow it, because
uvicorn runs with the working directory on `sys.path` and will happily serve on
top of a broken install (that hid two real defects until S14).

Work lands on `staging`; `main` moves only through a promote PR
([D-010](DECISIONS.md)). `main` must always pass `docker compose up` + `pytest` —
the always-demoable invariant.

### The repo is the memory

This project is built by one human and one LLM across many sessions, under a
protocol written down in [CLAUDE.md](CLAUDE.md). It is worth understanding
before contributing, because it explains why the repo looks the way it does:

| File | What it is |
|---|---|
| [STATE.md](STATE.md) | Single source of truth: where the project is right now |
| [DECISIONS.md](DECISIONS.md) | Numbered, dated, **immutable once ratified**. Overturning one is a new entry that says which it supersedes |
| [TECHNICAL_DEBT.md](TECHNICAL_DEBT.md) | Every shortcut, with its risk and its costed path to fix |
| [ROADMAP.md](ROADMAP.md) | Phases and per-session deliverables |
| [docs/probes/](docs/probes/) | Saved reality snapshots of external systems |
| [IDEAS.md](IDEAS.md) | Parking lot — never implemented directly from here |

Two rules carry most of the weight. **Reality over memory:** never code against a
remembered API — probe the live thing, save the snapshot to `docs/probes/`, code
against that. **Tests ship with the feature,** in the same change, no exceptions.

---

## License

Not yet licensed for redistribution. Ask.
