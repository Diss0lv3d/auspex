# HANDOFF — your handbook for Auspex

_Written 2026-10-13, when Burhan handed session **F3** (front-end track) to you.
It covers what Auspex is, how the work is run, how to set up your machine,
exactly what to type first, what F3 is, and the custom commands (full text in
Appendix A). When this file and the repo disagree, the repo wins: `STATE.md` for
where things stand, `SESSION-RULES.md` for the rules, `.claude/commands/` for
the commands._

---

## 0. Before you start: Burhan does these

- [ ] Adds your **personal** GitHub account to `bh3082336888-cell/auspex` as a
      collaborator with write access. You accept the invite.
- [ ] Sends you the `.env` values you need (the dev engine key, the enrichment
      keys) **through a password manager or another secure channel**. Never in
      chat, email, a commit, or a Claude prompt.
- [ ] Tells you how to reach him if you get stuck.

You own F3 fully. Burhan's words: "She owns F3 fully" (D-059). Every call the
docs call "Burhan's call" is yours for F3. That includes the design questions,
which candidates to take, new decisions (D-entries) and `/promote`. The one
exception is re-scoping the other two tracks (backend, bugs). Those stay
Burhan's.

---

## 1. Auspex in two minutes

Auspex is a security intelligence platform for SOC analysts. It is a chat-based
**co-analyst**: an analyst pastes an alert, an IP address or a phishing email,
and the platform answers. Most questions (about 92%) are answered by plain code
with no AI model at all. IP reputation checks, CVE lookups and definitions are
deterministic. The other ~8% (open-ended analysis) go to an AI model that the
**customer** supplies. Any OpenAI-compatible endpoint works, and Auspex never
pays for inference.

The pieces you will meet:
- **Backend:** FastAPI (Python 3.12, async), Postgres for transactional data,
  OpenSearch for the knowledge base. Everything runs in `docker compose`.
- **Front end:** two plain HTML/CSS/JS pages served by the backend, with no
  framework and no build step.
  - **`/`** is the chat page.
  - **`/timeline`** shows how each verdict on an observable has aged.
  - Your work is here.
- **The agent:** for deep questions the model can call tools (look up an IP,
  search the knowledge base) and **propose** actions. A human must approve
  them in the approvals panel, and approved actions can be undone.
- **Brand:** the product is "Auspex" or "the platform". The underlying model
  is "the platform's engine". **Never put a model or vendor name in anything a
  user sees** (D-002; tests enforce it). Colours, fonts and voice are in
  `CLAUDE.md` → Brand.

---

## 2. How the work is run (read this twice)

Auspex is built by one human plus Claude across many short sessions. Claude
forgets everything between sessions, and humans get tired and paste prompts
into the wrong window. So **the repo is the only memory anyone trusts.** Every
fact that matters is written down in a file. The rituals exist to keep those
files true.

### The files that run the project

| File | What it is | When you touch it |
|---|---|---|
| `CLAUDE.md` | The project's constitution. Claude Code loads it automatically. | Rarely |
| `STATE.md` | **Where things stand right now.** Test count, what each session did, open follow-ups, blockers, host notes. | Read at start, updated at end (Claude does it) |
| `SESSION-RULES.md` | Standing rules every session obeys. | Read at start; edit only when a rule changes |
| `NEXT-SESSION-FE.md` | **The exact prompt for the next front-end session.** Yours is F3. | Rewritten at session end for F4 |
| `NEXT-SESSION-BE.md`, `NEXT-SESSION-BUGS.md` | The other two tracks' next prompts. | Only if your session made something in them untrue |
| `ROADMAP.md` | Phases and per-session deliverables, one section per track. | Ticked at session end |
| `DECISIONS.md` | Numbered decisions (D-001 … D-059). **Immutable once ratified**: to change one you write a NEW D-entry that says what it supersedes. | When a real decision is made |
| `TECHNICAL_DEBT.md` | Shortcuts taken (TD-001 …), each with risk, path to fix and trigger. | When you take a shortcut, or close one |
| `BUGS.md` | Bugs found by using the platform (B-001 …). | `/bug` |
| `IDEAS.md` | Parking lot. **Never implemented directly from here.** | `/idea` |
| `docs/probes/` | Saved "reality snapshots": what a live system actually did, dated. | Whenever you verify something live |
| `docs/superpowers/specs/`, `docs/superpowers/plans/` | Design specs and implementation plans from the brainstorming workflow. | Your F3 design goes here |
| `docs/ENV_VARS.md` | Every environment variable, documented. | When a var is born |

### Tracks and session ids (D-051)

Work runs in three tracks, **one session at a time**:

| Track | Prompt | Ids | Status today |
|---|---|---|---|
| front end | `NEXT-SESSION-FE.md` | F1, F2, **F3** ← you | **the focus** |
| backend | `NEXT-SESSION-BE.md` | S28 … S29 | paused |
| bugs | `NEXT-SESSION-BUGS.md` | B1, B2, B3 | waiting on Burhan |

**Never run two sessions at once on the same repo.** All three tracks share the
`staging` branch, the docker stack and the test user.

### The rules that bite (the full list is in `SESSION-RULES.md`)

1. **Reality over memory.** Don't code against a remembered or guessed API,
   schema or browser behaviour. Run the live thing, save what it did to
   `docs/probes/YYYY-MM-DD-<thing>.md`, and code against that. "If it wasn't
   executed, it isn't true."
2. **Cite or probe.** A claim about the code gets a `file:line`. A claim about
   an outside system gets a probe file.
3. **Scope lock.** The session's goal is what its prompt says. A new idea goes
   to `/idea` and a bug you notice goes to `/bug`: one line each, then back to
   work. Neither is worked on in the session that found it.
4. **Thrash brake.** Two failed approaches to the same problem means stop.
   Write down what you tried and why it failed (STATE.md → Blockers), then
   move on or end the session. No third attempt in the same session.
5. **Tests ship with the feature, in the same session.** Burhan's standard is
   stricter still:
   - **the test fails first**: write it, watch it fail, then make it pass;
   - **mutants**: deliberately break the code the test guards, check that the
     test now fails, then restore the code. A test that never fails is
     checking nothing.
6. **One concern per commit.** Messages look like `feat(ui): …`,
   `fix(timeline): …`, `chore(state): …`, `docs(decisions): …`. **Never amend**
   a commit; make a new one.
7. **Branches (D-010).** All work lands on `staging`. `main` only moves
   through `/promote`, which runs the full gate, opens a PR, waits for CI and
   squash-merges.
8. **Secrets.** `.env` is gitignored. Never paste a key into code, tests,
   commits, docs or a Claude prompt. Use placeholders.
9. **Run the full gate before calling anything done:** `./ci.sh`. A change has
   twice passed every file it touched and broken a test in a file it didn't.
10. **A page change is verified in a real browser** against the rebuilt
    container, not only by reading the diff (Claude does this with the
    Playwright browser tool).

### A session, start to finish

```
/session-start fe F3      ← Claude checks you're in the right window and that reality matches STATE.md
   Step 0 of the prompt   ← promote if needed, then your own hands-on look at the page
   brainstorm → spec      ← design questions; you answer them
   plan → build → test    ← tests fail first; mutants; full gate
   live check             ← real browser, rebuilt container
   fresh-agent review     ← a separate agent reads the change adversarially
/session-end              ← STATE.md, the next prompt (F4), ROADMAP, commit, summary
```

**Tired? End early, but always run `/session-end`.** A short session with the
ritual done beats a long one without it.

---

## 3. Setting up your machine (once)

You need Linux or macOS (on Windows, use WSL2 and run everything inside it),
and about 10 GB of free disk.

### 3.1 Tools

| Tool | Version | Check with |
|---|---|---|
| git | any recent | `git --version` |
| Docker + Compose v2 | recent | `docker compose version` |
| Python | **3.12+** | `python3 --version` |
| Node.js | **20+** (Burhan runs 24). The page's logic tests run under Node inside the test gate, and **Node missing is a failure, not a skip.** | `node --version` |
| GitHub CLI `gh` | recent | `gh --version` |
| Claude Code | latest | `claude --version` |
| Ollama + `qwen3:14b` | **optional for F3** (see 3.6) | `curl -s localhost:11434/api/tags` |

Docker needs about 3 GB of RAM for the stack: OpenSearch alone takes a 1 GB
heap. Ports **8000** (app), **55432** (Postgres) and **9200** (OpenSearch) must
be free.

### 3.2 GitHub identity (D-011, D-059)

Auspex is Burhan's personal project. Only **personal** identities author
commits here, never an employer account or an employer email (such as
`@sirp.io`). You work under **your own personal GitHub account.**

1. Make an SSH key for your personal account, if you don't have one, and add
   it to GitHub (Settings → SSH and GPG keys):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/personal_git -C "<your personal GitHub username>"
   ```
2. Add the `github-personal` alias to `~/.ssh/config`. The repo's remote and
   the `/promote` check both use this alias, so everyone's URL is identical:
   ```
   Host github-personal
     HostName github.com
     User git
     IdentityFile ~/.ssh/personal_git
     IdentitiesOnly yes
   ```
   Test it: `ssh -T git@github-personal` should greet your personal username.
3. Find your **noreply email**: GitHub → Settings → Emails, the
   `…@users.noreply.github.com` address. That is your commit email.
4. Log the GitHub CLI in as your personal account: `gh auth login` (GitHub.com,
   SSH, pick `~/.ssh/personal_git`). If you also have a work account logged in,
   always check `gh auth status` shows the personal one as **active**.

### 3.3 Clone and configure

```bash
git clone git@github-personal:bh3082336888-cell/auspex.git auspex
cd auspex
git checkout staging                     # all work happens here, never on main
git config user.name  "<your name>"      # repo-local, not --global
git config user.email "<your noreply email from 3.2>"
cp .env.example .env
cp dev-endpoints.example.json dev-endpoints.json   # gitignored; only needed for the endpoint switcher
```

**Fill `.env`** with the values Burhan sends you. The ones that matter:

| Variable | What to put |
|---|---|
| `LLM_BASE_URL` | `https://api.z.ai/api/paas/v4` (the dev engine, D-034). **Only this general endpoint, never `api/coding/paas/v4`.** |
| `LLM_MODEL` | `glm-4.5-air` |
| `LLM_API_KEY`, `GLM_API_KEY` | the dev engine key from Burhan (the same key in both) |
| `ABUSEIPDB_API_KEY`, `OTX_API_KEY`, `ABUSECH_AUTH_KEY`, `GREYNOISE_API_KEY`, `NVD_API_KEY` | from Burhan if he shares them; each is optional and the platform degrades honestly without it |
| everything else | leave as in `.env.example` |

Without an engine key the platform still runs. Code-answered questions (IP
checks, CVEs, definitions) and the timeline page all work, and only deep chat
turns fail. **F3's default goal needs no engine at all.**

**The engine key is Burhan's money** (pay-as-you-go: $0.20 in / $1.10 out per
1M tokens, and a deep turn makes up to ~5 calls). Budget your chat turns. The
provider processes in Singapore, so **never put real customer data, and never
any KSA-tenant data, into a chat** (org policy). Dev data only.

### 3.4 First run

```bash
docker compose up -d --wait              # first time: pulls images, builds the app, bootstraps the knowledge base
docker compose ps                        # three services, all "healthy"
curl -s localhost:8000/api/health/ready  # {"status":"ready",...} = Postgres AND OpenSearch are up
./ci.sh > /tmp/ci.log 2>&1; echo "exit=$?"   # builds .venv, lint, full test suite, container build. exit=0 = green
```

The first `./ci.sh` takes a while. The test count it reports should match the
README and STATE.md (1385 at handoff). **Never pipe `./ci.sh` into `tail`:** the
pipe reports `tail`'s exit code, so a red run looks green. Redirect to a file,
as above.

On a fresh volume the first boot downloads an embedding model and pulls CVE,
KEV, EPSS and ATT&CK feeds. That needs outbound HTTPS. A blocked feed degrades
honestly and is not an error you need to fix.

Then open <http://localhost:8000>, sign in with any email (dev sign-in, for
example `you@analyst.dev`), and ask `check 8.8.8.8`. That is a code-answered IP
check: no engine call, and it records the observable. Now
<http://localhost:8000/timeline> has something to show.

### 3.5 Claude Code plugins

Burhan works with these plugins. Install them in Claude Code:

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install superpowers@claude-plugins-official
/plugin install frontend-design@claude-plugins-official
/plugin install playwright@claude-plugins-official
/plugin install code-review@claude-plugins-official
```

- **superpowers** is the design → plan → build workflow (section 5).
- **playwright** gives Claude a real browser to verify pages.
- **frontend-design** is guidance for UI work.
- **code-review** is for reviews.

Then `/reload-plugins` or restart Claude Code. The project's own commands
(`/session-start`, `/session-end`, `/bug`, …) come with the repo in
`.claude/commands/`, so you already have them.

Burhan's two personal UI mods (a progress pane and a token meter) are not
needed.

### 3.6 Ollama (optional for F3)

`/session-start` checks that a local Ollama answers on `:11434` with
`qwen3:14b`, the slow offline engine (D-013). **F3's prompt says the session
needs no local engine, so a missing Ollama is not a stop for F3.** If you want
it: install Ollama, then run `ollama pull qwen3:14b` (~9 GB; slow without a
good GPU).

### 3.7 Your first commit: add yourself to the table

In your first session, the identity guard will find that your email isn't in
`SESSION-RULES.md` → "Identity and `gh`" → **Who works here**. Claude will ask
who you are. Tell it, and it adds your row (name, personal GitHub account,
noreply email, `D-059`) as its own commit. After that the guard passes on its
own.

---

## 4. Your first session

### 4.1 Open Claude Code in the repo

```bash
cd auspex                    # your clone
git checkout staging
git pull origin staging      # start from what is on GitHub
claude
```

One session at a time also holds across machines (D-051). If a `git push` is
ever rejected because `staging` moved under you, someone else ran a session:
stop, `git fetch`, look at what changed, and tell Burhan. Never force-push.

### 4.2 Paste this as your first message

Replace the two `<…>` placeholders first.

```text
I'm <your name>, a developer Burhan has handed session F3 (front-end track) to.
I work on my own machine, in my own clone, under my own personal GitHub
account <your GitHub username> (D-059). Burhan handed me every F3 call, new
D-entries and /promote included, so wherever the rules or commands say
"Burhan's call" or "ask Burhan", ask me. Re-scoping the backend or bugs track
stays Burhan's; flag those to me and I'll pass them on.

I'm new to this repo. Read HANDOFF.md first. When you ask me a design question,
explain the options in plain terms with your recommendation first. Don't start
F3's work yet: tell me in five lines what you understood, then I'll run
/session-start fe F3.
```

### 4.3 Then run the start ritual

```
/session-start fe F3
```

Claude will:
- check the directory, the branch (`staging`), your identity (and add your
  row: 3.7) and the docker stack;
- read `STATE.md`, `SESSION-RULES.md` and `NEXT-SESSION-FE.md`;
- then restate the session. Its first line is **"Track: front end · Session:
  F3"**.

If Claude says **"wrong window / wrong session"**, stop. You typed the wrong
id, or the files moved. Don't let it improvise.

You don't paste `NEXT-SESSION-FE.md` yourself: `/session-start` reads it. (That
file's "paste everything below the line" is for opening a fresh window from
scratch.)

### 4.4 Step 0: use the page yourself first

F2 (the session before yours) shipped chat-page features nobody has used for
real yet. The prompt asks you to try them with fresh eyes before building
anything:
- a chat survives a reload;
- the chats sidebar and **+ New chat**;
- reopening a chat (the "Reopened" divider, spend lines, proposal lines with
  Review);
- Sign out;
- Review then **Undo** on a reopened proposal (this needs a deep chat turn
  that proposes something, which spends engine calls);
- the page on a phone-width window (the Chats button, the backdrop, Esc).

Tell Claude what you saw.
- Something broken → `/bug`.
- A wish → `/idea`.
- Something you decide F3 must fix → say it joins F3. Your list outranks the
  default goal.

---

## 5. How to work with Claude here (the superpowers workflow)

Burhan's sessions follow a fixed shape. Claude knows it, and these are the
names you will see:

1. **Brainstorming** (`superpowers:brainstorming`). Before any code, Claude
   asks design questions **one at a time**, usually with options and a
   recommendation. You answer, and it writes a spec to
   `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`. **This is where your
   calls get made.** Push back when an option is unclear; asking "why?" is
   fine.
2. **Writing the plan** (`superpowers:writing-plans`). The spec becomes a
   step-by-step plan in `docs/superpowers/plans/`, each task with its test.
3. **Executing.** Claude does it either inline or **subagent-driven** (a fresh
   agent per task, each reviewed). Claude will offer both, and for a page
   change of F3's size either is fine.
4. **Test-driven:** the test fails first, then the code makes it pass, then
   mutants.
5. **Verification.** `./ci.sh` green, the container rebuilt, and the page
   checked in a real browser.
6. **Fresh-agent review** (`superpowers:requesting-code-review`). A separate
   agent that didn't write the code reads it adversarially. At B2, two of four
   such reviews found a real defect after the code had passed its own tests.
7. **`/session-end`.**

Tips:
- **Ask Claude to explain.** "Explain this file like I'm new", "why does this
  test exist?", "what would break if I removed this?" all work. It's how you
  learn the codebase fast.
- **Insist on evidence.** If Claude says something works, ask how it checked.
  "I read the code" is weaker than "I ran it".
- **Stop it when it drifts.** If it starts fixing something that isn't F3's
  goal, say "scope lock: `/bug` it and come back".
- **Watch permission prompts.** Read what a command does before approving it,
  especially `git push`, `gh pr …` and anything that deletes.

---

## 6. F3: what you're building

Full text: `NEXT-SESSION-FE.md`. Here it is in plain terms.

### Why

The chat page keeps the user's sign-in token in the browser tab's
`sessionStorage` (D-056). Any script running on the page could read it. A
**Content-Security-Policy (CSP)** is a response header that tells the browser
"only run scripts from my own files". An attacker who manages to inject a
`<script>` or an `onclick=` into the page then gets nothing executed. F2 put
a strict CSP on the chat page (D-057).

**The timeline page has none** (TD-051). Its markup still carries everything
a strict CSP would block:
- an inline `<style>` and `<script>`;
- four `onclick=` attributes;
- cards built as HTML strings pushed into `innerHTML`;
- an escaper that doesn't escape `'`;
- inline `style="width:…"`.

### The goal: the timeline page joins the chat page under D-057's policy

- Its CSS and JS move into their own files (for example `css/timeline.css`,
  `js/timeline.js`). They go on the allow-list in `auspex/routes/ui.py` and
  are served `no-cache`, exactly as F2 did for the chat page.
- Cards are built with real elements and text (the chat page's `el(...)`
  pattern), never HTML strings. Widths are set with `element.style.width = …`.
  The CSSOM is not blocked by CSP; a `style=` attribute is.
- The `onclick=` attributes become `addEventListener` calls.
- `/timeline` sends the same CSP header as `/`, pinned by a test, and
  `test_the_timeline_page_has_no_csp_yet` (`tests/test_ui.py`) is replaced.
- **Done means:**
  - tests green (the full gate);
  - the page working in a real browser against the rebuilt container, with
    **zero CSP violations in the console**;
  - TD-051 closed in `TECHNICAL_DEBT.md`.

### Design questions that are yours (answer them in brainstorming)

- Does the timeline's pure logic (its staleness labels, its counts that say
  "at least N") move into a tested module like `js/page-logic.js`, with Node
  tests?
- Do the two pages share helpers (`el`, `$`, the fetch wrapper), or does each
  keep its own?

### Candidates: extra work, only if you pick it

Listed in the prompt:
- analyst notes shown on the timeline;
- TD-047 (no 304 responses);
- the stale proposal line after Undo;
- the "[connection lost]" message;
- tests pinning that no `style=` creeps into the chat page.

Take none, one or several. The last one sits naturally beside the timeline
work. "Analyst notes shown" needs a new read route (a backend change, scoped to
the workspace). **Handing notes to the model is rail-sensitive** (new text the
model reads), so leave that part alone unless you have a reason and a test.

### Where things are

| Path | What |
|---|---|
| `auspex/static/timeline.html` | **The page you're rebuilding** (280 lines today) |
| `auspex/static/index.html`, `css/chat.css`, `js/chat.js`, `js/page-logic.js` | The chat page: **the pattern to copy** |
| `auspex/routes/ui.py` | Serves the pages; the CSP string (`_CHAT_CSP`); the file allow-list (`_ASSETS`) |
| `auspex/routes/timeline.py`, `auspex/timeline/` | The `/api/timeline` API the page reads; the staleness vocabulary lives server-side in `auspex/timeline/staleness.py` |
| `tests/test_ui.py` | Page tests. They must read the page **as served**, through `_page(client)` the way the chat page's tests do. |
| `tests/js/page_logic.test.mjs` + `tests/test_page_logic.py` | Node tests for page logic, run inside pytest |
| `pyproject.toml` → `package-data` | Static files ship in the image via these globs (`static/css/*.css`, `static/js/*.js` already match new files) |
| `docs/superpowers/specs/2026-10-12-page-split-csp-design.md` | **F2's spec for the same job on the chat page.** Read it first. |
| `docs/superpowers/plans/2026-10-12-page-split-csp.md` | F2's plan |
| `docs/probes/2026-10-12-f2-page-split-csp.md` | F2's live verification record: the shape yours should take |
| `DECISIONS.md` → D-053, D-056, D-057 | Safe markdown, the sign-in in sessionStorage, the CSP |

### F3's constraints (the important ones)

- **Feed-derived text is text, never HTML.** The timeline shows sources,
  claims and checker names from outside feeds. Write it with `textContent` or
  text nodes, never `innerHTML`.
- **No loosening.** Adding `'unsafe-inline'`, or any new external origin (a
  CDN, a font host), needs a new D-entry. It is not a quiet edit.
- **A page change is invisible until you rebuild.** The app container runs the
  built image with the static files baked in. Rebuild with
  `docker compose up -d --build app`, or note that `./ci.sh` rebuilds it too.
- **CI's install check covers `*.py` only** (TD-053). A static file missing
  from the image passes CI and 404s in the browser, so check it live.

---

## 7. Gotchas Burhan learned the hard way

- **`./ci.sh` rebuilds AND restarts the app container.** A live "before"
  observation has to happen *before* you run the gate.
- **Don't edit code while `./ci.sh` runs.** The edit lands in its container
  build.
- **Don't run pytest during live chat probes**, and don't run it while a chat
  you still need as evidence lives only in Postgres. The suite deletes the
  shared test user `analyst@auspex.dev` and its chats. Save the evidence into
  `docs/probes/` first.
- **The chat page's functions are module-scoped** (because of the CSP). A
  browser probe drives the page through its DOM (click, type), not by calling
  functions from the console.
- **Playwright can only save screenshots under the repo**, in
  `.playwright-mcp/` (gitignored). Copy what you keep into `docs/probes/`.
- **`gh pr merge --squash` prints nothing on success.** Verify with
  `gh pr view <n> --json state,mergeCommit`.
- **`gh pr edit` fails on this repo** (a GitHub API deprecation). Use
  `gh api -X PATCH repos/bh3082336888-cell/auspex/pulls/<n> …`.
- **Your local `main` goes stale after every promote.** To see what a promote
  would ship: `git fetch origin && git diff origin/main..staging --stat`. Read
  the diff, never the commit list.
- **A probe that files proposals must reject or undo them afterwards. A probe
  that creates observables deletes only what it created.** The platform
  skips reserved address ranges (TEST-NET and the like), so use a routable IP
  when you need one recorded.
- **Two overview files** (`Auspex-Product-Architecture-Overview.pdf`,
  `docs/auspex-overview.html`) are mentioned in STATE.md. They exist only on
  Burhan's machine, untracked, and are his. Ignore them.
- **STATE.md's host notes describe Burhan's machine** (ports, the
  `gh`-flipping work account). Ports are the same on yours. The rest you
  inherit only if your setup matches.
- **The prompt files mention `/home/burhan/auspex-new`.** That's Burhan's path;
  your clone is the Auspex repo wherever you put it.
- **If the containers die suddenly**, run `docker compose up -d --wait`
  and carry on. It's almost always the machine, not the code.

---

## 8. Ending your session

Run `/session-end`. Claude will:
1. run the full gate and check health (a red end is written down, never
   silent);
2. update `STATE.md`: what F3 did, what's in flight, blockers, and the Tracks
   table (front end: last closed F3, next F4);
3. rewrite `NEXT-SESSION-FE.md` as the complete prompt for **F4**, and fix
   anything F3 made untrue in the other two prompts;
4. tick `ROADMAP.md`, record closed TDs (TD-051) and bugs, log new shortcuts in
   `TECHNICAL_DEBT.md`;
5. commit everything on `staging`;
6. end with a ≤10-line summary.

Then push `staging` (`git push origin staging`). If F3 reached a demoable
milestone, run `/promote` to ship it to `main` (you own that call). Send Burhan
the summary, or run `/briefing` for a plain-language version.

**If you change scope after the ritual** (you decide something new before
closing the window), tell Claude to write it into STATE.md and the prompt file
and commit it. Decisions said after the ritual have been lost before (D-051).

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **D-0nn** | A numbered decision in `DECISIONS.md`. Immutable; superseded only by a new one. |
| **TD-0nn** | A technical-debt entry: a known shortcut with its risk and fix path. |
| **B-0nn** | A bug in `BUGS.md`. |
| **S / F / B + number** | A session id: S = backend, F = front end, B = bugs. |
| **staging / main** | Work branch / always-demoable branch. Only `/promote` moves main. |
| **Promote, promote slate** | Shipping staging to main via a PR; the slate is what's on staging and not yet on main. |
| **The gate** | `./ci.sh`: lint, the full test suite, the container build, the install check. CI runs exactly this. |
| **Probe** | Hitting a live system and saving what it did to `docs/probes/`. |
| **Mutant** | Deliberately breaking guarded code to prove a test catches it. |
| **CSP** | Content-Security-Policy, the response header that limits what a page may load and run. |
| **CSSOM** | Setting styles from JS (`el.style.width = "40%"`), which CSP allows; a `style=` attribute it blocks. |
| **The rail** | The output rail: code that cuts an answer if the platform's own instructions start coming back out (D-030, D-040, D-058). Any new text the model reads goes into its index, so treat prompt text as sensitive. |
| **92/8** | ~92% of questions are answered by code, ~8% by the engine. |
| **Deep turn / agent path** | A chat turn that goes to the engine; on the agent path it can call tools. |
| **Proposal / approval** | The agent proposes an action; a human approves or rejects it in the approvals panel; it can be undone. |
| **Observable** | An indicator (IP, domain, hash, URL) the platform has recorded, with verdicts that decay over time ("Living Verdicts"). |
| **Workspace** | A tenant. Every row is scoped to one, and cross-workspace access is a security bug. |
| **The platform's engine** | How users see the AI model. Never name the model or vendor. |
| **Scorecard** | What the platform measured the configured engine can do (native tools or not). It is re-probed weekly at startup (~15 calls). |

---

## 10. The custom commands

They live in `.claude/commands/` (committed, so your clone has them). Type them
in Claude Code like any slash command. Full text: Appendix A.

| Command | What it does | When |
|---|---|---|
| `/session-start <track> <id>` | The start ritual: right window, right branch, right identity, stack healthy, reality matches STATE.md, then restates the session. | First thing, every session. Yours: `/session-start fe F3` |
| `/session-end` | The end ritual: gate, STATE.md, the next prompt, ROADMAP/TD/BUGS, commit, summary. | Last thing, every session, even a bad one |
| `/idea <idea>` | Appends one line to IDEAS.md and goes straight back to work. | You think of something out of scope |
| `/bug <what, where>` | Adds a bug to BUGS.md with evidence and commits it; never diagnoses or fixes it. | You notice something broken that isn't your goal |
| `/probe <thing>` | Hits a live system, saves the snapshot to `docs/probes/`, says where reality differed from assumptions. | Before coding against anything external |
| `/promote` | Ships staging to main: identity check, full gate, PR, wait for CI, squash merge, back-merge. | At a demoable milestone (your call for F3) |
| `/briefing [range]` | A plain-language summary of the work for a non-coder: built / fixed / blocked / your move. | To report to Burhan |
| `/review-issue <n>` | Reproduces and root-causes a GitHub issue; proposes a fix; doesn't implement. | If someone files an issue |
| `/explain-issue <n>` | Explains a GitHub issue in non-technical language. | Same |

The commands sometimes say "Burhan". Read that as **you**, for F3's calls
(D-059).

---

## Appendix A: full text of the custom commands

_Snapshot of `.claude/commands/` at handoff (2026-10-13, after D-059's guard
update). The files in the repo are what actually runs; if they differ from this
copy, they win. `$ARGUMENTS` is whatever you type after the command._

### `/session-start` (`.claude/commands/session-start.md`)

````markdown
---
description: Run the CLAUDE.md session-start ritual for one track (wrong-window guard + reality check)
argument-hint: "[be|fe|bugs] [session id, e.g. F1] — no track: asks which"
---

Run the session-start ritual from CLAUDE.md, strictly. Arguments: `$ARGUMENTS`

0. **Pick the track (D-051).** Sessions run in three tracks, each with its own
   prompt file and its own session numbers:

   | Track | Words accepted | Prompt file | Session ids |
   |---|---|---|---|
   | backend | `be`, `backend` | `NEXT-SESSION-BE.md` | `S<n>` |
   | front end | `fe`, `frontend`, `front-end` | `NEXT-SESSION-FE.md` | `F<n>` |
   | bugs | `bugs`, `bug` | `NEXT-SESSION-BUGS.md` | `B<n>` |

   - The first argument names the track. A bare session id names it by its
     prefix (`S29` → backend, `F1` → front end, `B1` → bugs).
   - **No track and no id → do NOT pick one.** Read the header line of each
     prompt file and the Tracks table in STATE.md, show the three next sessions
     (marking the one STATE.md calls the focus and any that are paused), and
     ask the human which to start. Wait for the answer.
   - An unknown word, or a track word that disagrees with the id's prefix
     (`fe S29`) → STOP and ask. Never guess a track.

1. Verify `pwd` is the Auspex repo (this repo). Wrong dir → STOP: "wrong window".
2. Read `STATE.md`, `SESSION-RULES.md` and the track's prompt file. If the human
   supplied a session id, it must match the id in that file's header line,
   `# NEXT-SESSION-<TRACK> — track: <track> · session: <id>`. Mismatch → STOP
   and say "wrong window / wrong session, expected <id> on the <track> track".
   Do not improvise a session.
2b. STATE.md's Tracks table must name the same next id for this track.
   Divergence → fix STATE.md first and say so. If the table marks the track
   paused, or another track as the focus, say that in one line and carry on;
   the human picked it.
3. Verify we're on `staging` (D-010). On main or detached → switch to staging
   and say so.
3b. Identity guard (D-011, D-059 — personal identities only): the repo-local
   `git config user.email` must be an email on SESSION-RULES.md's "Who works
   here" table, and if `gh` will be used this session, `gh auth status` must
   show as ACTIVE the GitHub account on the same row — otherwise run
   `gh auth switch --hostname github.com --user <that account>` (if it isn't
   logged in yet, tell the human to run `gh auth login` once, choosing SSH and
   their personal key; Burhan's is `~/.ssh/personal_git`).
   - Email not on the table → ask the human who they are. A collaborator Burhan
     added to the repo adds their own row (personal account + its noreply
     email) in its own commit, then carry on. Anyone else → STOP.
   - Never set one person's identity for another, and never let a work
     identity (an employer email such as `@sirp.io`, an account such as
     SIRP-Burhan) author commits or API calls in this repo.
4. Reality check: `git log --oneline -5`, `git status`, and (once compose
   exists) `docker compose up -d && docker compose ps` + `/api/health/ready`
   (readiness — checks Postgres AND OpenSearch, stricter than liveness).
   Divergence from STATE.md → fix STATE.md first, report the divergence.
4b. Dev-LLM gate (D-013 — the endpoint is load-bearing from S3 on):
   `curl -s localhost:11434/api/version` must answer, and
   `curl -s localhost:11434/api/tags` must list the dev model that STATE.md
   declares (currently `qwen3:14b`; read it from STATE.md, don't trust this
   file). Down or model missing → STOP and tell the human (Ollama service /
   `ollama pull`) unless the track's prompt says the session needs no LLM.
5. First line of the restatement: **"Track: <track> · Session: <id>"**. Then
   the session goal from the track's prompt in 2–3 lines, and the scope-lock
   rule (new ideas → `/idea`, bugs found → `/bug`), then begin the session's
   work.
````

### `/session-end` (`.claude/commands/session-end.md`)

````markdown
---
description: Run the CLAUDE.md session-end ritual for the track this session ran on (state, next prompt, roadmap, commit, summary)
---

Run the session-end ritual from CLAUDE.md. Never skip steps, even on a bad or
cut-short session. The track is the one `/session-start` named ("Track: … ·
Session: …"). If no start ritual ran in this window, ask which track before
writing anything.

1. Verify always-demoable: `./ci.sh` green + `docker compose up -d` +
   `/api/health/ready` 200. Red → either fix now or explicitly log the breakage
   in STATE.md Blockers before ending (a red end-state must never be silent).
2. Update `STATE.md`: done / in-flight / blockers / "next session should".
   - Update **this track's row** of the Tracks table (last closed, next id),
     and the shared facts every track reads: test count, module count, the
     promote slate. Those numbers live in STATE.md only.
   - Standing follow-ups in the outgoing "In-flight" section (event-triggered,
     cross-session — e.g. the D-013 Northflank validation run) MUST be carried
     into the new version unless actually completed; they die by being done,
     not by being forgotten in a rewrite.
3. Rewrite **this track's** prompt file completely for its next session (D-051):
   - `NEXT-SESSION-BE.md`, `NEXT-SESSION-FE.md` or `NEXT-SESSION-BUGS.md`, with
     its header line `# NEXT-SESSION-<TRACK> — track: <track> · session: <id>`
     and the id incremented (`S29` → `S30`, `F1` → `F2`, `B1` → `B2`).
   - A full paste-ready prompt: `/session-start <track> <id>`, Step 0,
     scope-locked goals, candidates, and only the constraints that are about
     this track's next session. The human must not need to remember or compose
     anything.
   - **Standing rules belong in `SESSION-RULES.md`, once.** A rule this session
     changed or learned → edit it there, not into a prompt. Never copy a
     moving number (tests, modules, promote #) into a prompt; point at STATE.md.
3b. **Read the other two prompt files.** Anything this session made untrue
   there (a promote done, a bug fixed, a rule changed, code a goal names
   moved) → fix it there now, in its own commit. Do not re-scope another
   track's goals; flag that to Burhan instead.
4. Tick completed items in `ROADMAP.md`, in this track's section. Bugs fixed →
   `fixed <commit> (<id>)` in BUGS.md. Log any shortcut taken this session in
   `TECHNICAL_DEBT.md` (date + risk + path to fix).
5. New env vars introduced? Confirm they exist in `.env.example` AND
   `docs/ENV_VARS.md`.
6. Commit everything on `staging` (one concern per commit if uncommitted work
   is separable). Suggest `/promote` only if the session hit a demoable
   milestone.
7. End with the ≤10-line human summary: shipped / blocked / paste-next. The
   paste-next names the track file and its `/session-start <track> <id>`. If
   another track is the focus in STATE.md, name that one too.
8. **After the ritual, the window is still live.** If Burhan changes scope,
   focus or priorities before it closes, write it into STATE.md and the
   affected prompt file(s) and commit it at once. On 2026-10-10 a pivot said
   after the ritual died with the window (D-051).
````

### `/idea` (`.claude/commands/idea.md`)

````markdown
---
description: Park an idea in IDEAS.md without breaking session scope-lock
argument-hint: <the idea>
---

Append this idea to `IDEAS.md` as a single crisp line (sharpen the phrasing if
needed, keep the intent): $ARGUMENTS

Then immediately return to the current session's scope-locked work. Do NOT
design, estimate, or start implementing the idea — that's the whole point of
this command (CLAUDE.md rule 6). If the idea would actually change the CURRENT
session's correctness (not just its ambition), say so in one sentence and let
the human decide.
````

### `/bug` (`.claude/commands/bug.md`)

````markdown
---
description: Log a bug in BUGS.md without breaking session scope-lock
argument-hint: <what is broken, and where it was seen>
---

Add this bug to `BUGS.md` as a new entry: $ARGUMENTS

- Give it the next free id (`B-<nnn>`, one higher than the last entry). Fill
  the entry's fields the way BUGS.md's header describes: found (today's date,
  who, where), what happened, evidence, status `open`.
- **Evidence is what was observed, not a diagnosis.** A quoted answer, a log
  line, a probe record, or "seen by Burhan, not yet reproduced". If the only
  copy of the evidence lives somewhere a test run or a container restart will
  erase (a chat in Postgres, a container log), save it to a dated probe record
  in `docs/probes/` first and point at that.
- Never paste secrets, keys or tenant data into an entry (org rule).

Commit it on its own (`chore(bugs): B-<nnn> — <one line>`). Then immediately
return to the current session's scope-locked work. Do NOT diagnose or fix the
bug here; that is the bugs track's job (D-051). If the bug blocks the CURRENT
session's goal or makes its results wrong, say so in one sentence and let
Burhan decide.
````

### `/probe` (`.claude/commands/probe.md`)

````markdown
---
description: Probe a live external system and save the reality snapshot to docs/probes/ before coding against it
argument-hint: <what to probe, e.g. "NVD API delta endpoint" or "vLLM tool-call streaming">
---

Probe: $ARGUMENTS

CLAUDE.md rule 4 made executable — never code against a remembered API. Steps:

1. Identify the exact live thing to hit (endpoint, cluster, model, feed) and
   which upcoming code will depend on it.
2. Hit it for real (curl/httpx/client), using creds from `.env` via shell vars —
   never echo secret values into output or files.
3. Capture what matters: request shape, response shape (trim to the fields we'll
   consume), status/error behavior on bad input, rate-limit headers, timing.
   Probe the failure mode too, not just the happy path.
4. Save to `docs/probes/YYYY-MM-DD-<slug>.md`: what was probed, how, trimmed
   real responses, quirks discovered, and "what our code must therefore do".
   Redact any secret or personal data before saving.
5. Commit the probe file, then answer: does reality match what we assumed? Call
   out every mismatch explicitly — those are the bugs we just avoided.
````

### `/promote` (`.claude/commands/promote.md`)

````markdown
---
description: Promote staging → main (PR when remote exists, guarded merge locally) after all checks pass
---

Promote the current state of `staging` to `main` (branch model: D-010 — work
lands on `staging`; `main` is only ever updated through this command).

Preconditions — verify ALL, abort with a clear message on any failure:
0. Identity (D-011, D-059): `git config user.email` is on SESSION-RULES.md's
   "Who works here" table AND `gh auth status` shows as active the account on
   the same row (switch with `gh auth switch` if not). Remote URLs must use the
   `github-personal` SSH alias, never plain `github.com`. Work identity
   detected → stop.
1. On `staging` with a clean tree (`git status`). Uncommitted work → stop.
2. `staging` is ahead of `main` (`git log main..staging --oneline`); show the
   commit list that would promote.
3. Full check suite green, run fresh: `./ci.sh` (lint + tests) AND
   `docker compose up -d --build` then hit `/api/health/ready` until 200 (or
   30s timeout). Any red → stop, report, do not promote.

Then promote:
- **Remote exists** (`git remote -v` non-empty): push staging, open a PR
  staging → main via `gh pr create` titled `promote: <one-line summary of the
  commit range>`, body = the commit list + check results, ending with the
  standard PR footer. Wait for CI (`gh pr checks --watch`); merge with
  `gh pr merge --squash` only when green.
- **No remote yet**: `git checkout main && git merge --no-ff staging
  -m "promote: <summary>"`, then `git checkout staging`.

After promoting:
- **Back-merge (squash workflow):** the squash gives `main` a commit staging
  doesn't have, which makes the NEXT promote PR conflict. Immediately run, on
  `staging`: `git merge -X ours origin/main -m "merge: back-merge main after
  promote"`, verify the tree is unchanged (`git diff <pre-merge-sha> HEAD
  --stat` is empty), and push. If the PR itself reports "not mergeable" before
  merging, do this same reconciliation first, push, then merge.
- Confirm `main` still passes `docker compose up` + `/api/health/ready`
  (always-demoable invariant), then report what was promoted in one short
  list. Never force-push, never promote with skipped checks, never promote
  from any branch other than staging.
````

### `/briefing` (`.claude/commands/briefing.md`)

````markdown
---
description: Plain-language briefing of a session's work — built / fixed / blocked / your move
argument-hint: "[session number, commit range, or blank for this session]"
---

Give a plain-language briefing of the work in scope: $ARGUMENTS
(blank = this session — the commits since the last `promote:` on `main`, i.e.
`git log $(git describe --tags --match 'promote*' 2>/dev/null || git merge-base HEAD main)..HEAD`;
if that's empty, use the commits since the last `chore(state): S* session-end`).

First gather reality — don't summarize from memory:
- `git log --oneline` over the range, and `git diff --stat` over it.
- Read the top of `STATE.md` (Tracks / Where we are / Blockers) and the Step 0
  of the track prompt the session ran from (`NEXT-SESSION-BE.md`,
  `NEXT-SESSION-FE.md` or `NEXT-SESSION-BUGS.md`, D-051).
- Note whether the work is on `staging` only or already promoted to `main`.

Then write the briefing for a smart person who doesn't read code — the human who
paid for the work and wants to know what they got. Under ~250 words, four
headers, complete sentences (no bullets-of-fragments, no file paths, no class
names, no acronyms without a plain gloss the first time):

- **What we built** — the new capability in terms of what it does for a user
  ("the platform can now read a pasted phishing email and decide how dangerous
  it is"), not the module names.
- **What we fixed** — the bugs patched, each as "the problem → why it mattered →
  now". Lead with the one that mattered most. If a fix closed a security gap,
  say what someone could have done before and can't now.
- **What's blocked** — anything red or stuck, in real-world terms. If nothing is
  blocked, say so plainly ("nothing is blocked").
- **Your move** — exactly what, if anything, is needed from the human: a
  decision, a paste, an approval, a credential. If nothing is needed, say the
  work is done and safe to leave, and name the single thing to paste next
  session (the prompt file of the track STATE.md calls the focus).

Rules: honesty over polish — if a fix is only partial or a risk remains, say so
(name it the way STATE.md / TECHNICAL_DEBT.md does, in plain words). Never invent
work that isn't in the git range. If the range is ambiguous, state what you
briefed on. Follow the SIRP brand voice for any customer-facing phrasing (the
product is "the platform" / "Auspex", never the underlying model name).
````

### `/review-issue` (`.claude/commands/review-issue.md`)

````markdown
---
description: Deep-review a GitHub issue — reproduce, root-cause with file:line, propose a fix plan
argument-hint: <issue number or URL> [--comment]
---

Review issue $ARGUMENTS with engineering rigor. Follow CLAUDE.md rules (reality
over memory — run things, don't guess).

1. Fetch it: `gh issue view <n> --comments`. If there's no git remote yet, say so
   and ask for the issue text instead.
2. Reproduce before theorizing: find the code paths involved, run the relevant
   tests or a minimal repro (docker compose service if needed). If you cannot
   reproduce, say "NOT REPRODUCED" prominently and list what you tried.
3. Root-cause with evidence: cite exact `file:line`, show the failing
   input → wrong output chain. Distinguish *defect* from *symptom*.
4. Classify: severity (critical/high/medium/low), blast radius (which
   workspaces/features), regression or day-one bug, security-relevant? (If
   security-relevant: does it break workspace isolation? Flag loudly.)
5. Propose: the minimal fix, the test that pins it, and any adjacent debt worth
   logging in TECHNICAL_DEBT.md. Estimate size (S/M/L).
6. Output a structured review: **Verdict · Repro · Root cause · Fix plan ·
   Tests · Risks**. Do NOT start implementing — this command reviews only.
7. Only if `--comment` was passed: post the review as an issue comment via
   `gh issue comment`. Otherwise never write to GitHub.
````

### `/explain-issue` (`.claude/commands/explain-issue.md`)

````markdown
---
description: Summarize a GitHub issue in plain, non-technical language
argument-hint: <issue number or URL>
---

Explain issue $ARGUMENTS in plain terms, as if to a smart person who doesn't
code. Fetch it with `gh issue view <n> --comments` (if no remote exists, ask
for the pasted text).

Produce, in under 150 words total:
- **What's broken** — one or two sentences, zero jargon (no stack traces, no
  class names; "the login button" not "the OAuth callback handler").
- **Who feels it** — which users/situations hit this, and how often.
- **How bad** — real-world consequence, not severity labels ("you could see
  someone else's data" beats "P1").
- **Status** — what's known, what's being done, what's still unknown.
- **Analogy** (optional) — one everyday comparison if it genuinely clarifies.

Rules: no code snippets, no file paths, no acronyms without expansion. If the
issue thread is contradictory or unclear, say what's ambiguous instead of
smoothing over it.
````
