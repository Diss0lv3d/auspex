"""The docs are a shipped surface, so they get regressions like any other.

S20 added a README, a CI workflow and a demo script — the first artefacts in
this repo aimed at someone who is not Burhan. Three things about them can rot
silently, and each one has bitten a real project:

1. **The engine name leaks.** CLAUDE.md's brand rule is that the underlying
   model and provider never appear in anything customer-facing, and a docs pass
   is exactly where that slips in ("powered by …"). The app's own strings are
   already pinned against `FORBIDDEN_ENGINE_NAMES`; the docs were not.
2. **An env var is born without documentation.** The rule is that every
   variable exists in `.env.example` AND `docs/ENV_VARS.md` the moment it is
   born. Nothing enforced it.
3. **The demo drifts from the API.** A demo script that calls a route which no
   longer exists is worse than no demo, because it fails in front of someone.
"""

import re
from pathlib import Path

import pytest
from _fakes import FORBIDDEN_ENGINE_NAMES

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
DEMO = ROOT / "scripts" / "demo.sh"
ENV_EXAMPLE = ROOT / ".env.example"
ENV_DOCS = ROOT / "docs" / "ENV_VARS.md"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
STATE = ROOT / "STATE.md"

# D-051: one prompt per track, each with its own session ids and the word
# `/session-start` takes for it.
TRACK_PROMPTS = {
    "NEXT-SESSION-BE.md": ("be", "S"),
    "NEXT-SESSION-FE.md": ("fe", "F"),
    "NEXT-SESSION-BUGS.md": ("bugs", "B"),
}

# Two permitted occurrences, and only in these exact shapes.
#
# "OpenAI-compatible" is the wire protocol a customer's endpoint speaks, not a
# claim about what powers Auspex — the whole product position is that the
# customer brings their own.
#
# "CLAUDE.md" is a filename in this repository. The brand rule is about the
# ENGINE leaking into customer-facing copy, not about being unable to link to a
# file. Scoped to the literal filename so "Claude" in prose still fails.
_ALLOWED = re.compile(r"openai-compatible|CLAUDE\.md", re.IGNORECASE)


def _reader_facing(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [README, DEMO], ids=lambda p: p.name)
def test_no_engine_or_provider_name_leaks_into_reader_facing_docs(path):
    """The brand rule (CLAUDE.md), enforced on the docs the way it is already
    enforced on the app's strings."""
    text = _ALLOWED.sub("", _reader_facing(path)).lower()
    leaked = [name for name in FORBIDDEN_ENGINE_NAMES if re.search(rf"\b{name}\b", text)]
    assert not leaked, f"{path.name} names the engine/provider: {leaked}"


def test_every_env_var_in_the_example_is_documented():
    """Born in `.env.example` and `docs/ENV_VARS.md` at the same moment, or the
    next person has to read config.py to find out what a variable does."""
    declared = {
        m.group(1)
        for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE.read_text(), re.MULTILINE)
    }
    documented = ENV_DOCS.read_text()
    missing = sorted(v for v in declared if v not in documented)
    assert not missing, f"in .env.example but not docs/ENV_VARS.md: {missing}"


def test_the_readme_does_not_promise_what_the_code_does_not_do():
    """The honesty section is load-bearing: it is what a beta reader is asked to
    trust. These are the specific claims that would age into lies first, so they
    are pinned to the code that makes them true."""
    readme = README.read_text()
    settlement = (ROOT / "auspex" / "actions" / "settlement.py").read_text()

    # The blast radius the README states, read from the code that enforces it.
    assert 'EXECUTABLE_SYSTEMS = frozenset({"auspex"})' in settlement
    assert "`EXECUTABLE_SYSTEMS` is `{\"auspex\"}`" in readme

    # S26 wired the agent loop into the deep path (D-037). What the README now
    # promises about it — which turns, which endpoints, how long the narration
    # hold is — is pinned to the code that decides each one, so changing the
    # rule fails here and sends the change to the honesty section.
    chat = (ROOT / "auspex" / "routes" / "chat.py").read_text()
    loop = (ROOT / "auspex" / "agent" / "loop.py").read_text()
    assert "conversational-only" not in readme, "the deep path is wired; the README says not"
    assert "only on an endpoint measured to call them" in readme
    assert 'endpoint.agent_mode == "native_tools"' in chat
    assert "never take it" in readme
    assert "CODE_DECIDED_MODES = frozenset({Mode.ALERT_TRIAGE, Mode.PHISHING_ANALYSIS})" in chat
    assert "first 400 characters" in readme
    assert "NARRATION_HOLD_CHARS = 400" in loop

    # D-045: what the chat agent may do with an action — propose, never run.
    assert "The agent may propose; it never acts." in readme
    assert "action_proposer=request.app.state.action_proposer" in chat
    assert "if not outcome.affects:\n            raise NothingToPropose" in settlement

    # D-043: which answers are held before the analyst sees them.
    assert "A code-decided verdict is held until it passes; nothing else is." in readme
    assert "hold = mode in CODE_DECIDED_MODES and not agent_path" in chat

    # D-061 (S30): residency is a refusal by code, not routing, and the README
    # says so in the words the code makes true.
    region = (ROOT / "auspex" / "tenancy" / "region.py").read_text()
    assert "Single-region, single-tenant-per-workspace" not in readme
    assert "Residency is a refusal, not routing." in readme
    assert 'REGIONS: frozenset[str] = frozenset({GLOBAL, "ksa"})' in region
    assert "return workspace_region == GLOBAL or workspace_region == processor_region" in region


def test_the_demo_only_calls_routes_that_exist():
    """A demo that 404s in front of a stranger is worse than no demo."""
    routes = set()
    for path in (ROOT / "auspex" / "routes").glob("*.py"):
        source = path.read_text()
        prefix = re.search(r'APIRouter\([^)]*prefix="([^"]*)"', source, re.DOTALL)
        base = prefix.group(1) if prefix else ""
        for m in re.finditer(r'@router\.\w+\("([^"]*)"', source):
            routes.add(f"{base}{m.group(1)}")

    # $API already carries the /api prefix, so a captured call is relative to it.
    # Shell variables stand in for path parameters: $PID -> {id}.
    known = {re.sub(r"\{[^}]+\}", "{id}", r).rstrip("/") or "/" for r in routes}
    called = set(re.findall(r"\$API(/[A-Za-z0-9/_${}-]*)", DEMO.read_text()))
    # The assertion below passes trivially when `called` is empty, and `called`
    # goes empty the moment the demo stops spelling its base URL `$API` — a
    # rename, not a deliberate act. Mutation-tested in S21 Step 0: every other
    # docs assertion here failed when its fact was broken; this one kept
    # reporting green with its entire input removed. The floor is what makes it
    # a test rather than a formality. Raise it when the demo grows, never lower
    # it to make a change pass.
    assert len(called) >= 8, (
        f"only {len(called)} routes captured from demo.sh — the extraction has "
        "drifted (did $API get renamed?) and this test is checking nothing"
    )
    unknown = []
    for call in called:
        concrete = "/api" + re.sub(r"\$\{?\w+\}?", "{id}", call).rstrip("/")
        if concrete not in known:
            unknown.append(call)
    assert not unknown, (
        f"demo.sh calls routes that do not exist: {sorted(unknown)}\n"
        f"known: {sorted(known)}"
    )


def test_ci_runs_the_same_gate_a_developer_runs():
    """The one rule the workflow exists to keep (D-028). A workflow that
    re-listed ci.sh's steps would be a second definition of 'green', and the
    first edit to one and not the other makes the gate lie."""
    workflow = WORKFLOW.read_text()
    assert "./ci.sh" in workflow
    # None of ci.sh's actual work may be duplicated in the workflow.
    for duplicated in ("ruff check", "pytest -q", "pip install -q -e"):
        assert duplicated not in workflow, (
            f"the workflow re-implements `{duplicated}` instead of calling ci.sh"
        )


def test_the_readme_states_one_current_test_count(request):
    """The count in the README is a claim like any other, and it rotted twice.

    S20 wrote "902 tests" in two places. S22 updated one of them and missed the
    other, so the README disagreed with ITSELF for four sessions while both
    numbers drifted from the suite. Nothing counted, so nothing failed.

    Two failure modes, one test: the number must be stated consistently, and on
    a full-suite run — which is how `ci.sh` runs it, and therefore how CI does —
    it must be the number that was actually collected.
    """
    stated = {
        int(m.replace(",", "")) for m in re.findall(r"([0-9][0-9,]+) tests", README.read_text())
    }
    assert len(stated) == 1, (
        f"the README must state exactly one test count, found: {sorted(stated)}"
    )

    # A subset run collects a handful, so comparing against it would fail for a
    # reason that is about the invocation rather than the docs. Only a run with
    # no path argument collected everything.
    if [a for a in request.config.invocation_params.args if not a.startswith("-")]:
        pytest.skip("not a full-suite run — the collected count is not the suite's")

    # Bound before the assert: `stated.pop()` inside the comparison empties the
    # set, and the message then renders the number it exists to report as `[]`.
    claimed = stated.pop()
    collected = len(request.session.items)
    assert claimed == collected, (
        f"the README says {claimed} tests, the suite collected {collected}"
    )


def test_each_track_prompt_is_the_session_state_expects_next():
    """D-051 split the one session prompt into three tracks. The wrong-window
    guard compares a pasted id with the prompt's header, and the header with
    STATE.md's Tracks table. A session-end that bumps one and not the other
    makes the guard stop a correct session, or pass a stale one.

    The old single prompt must stay gone: the habit of pasting from it would
    quietly start backend work."""
    assert not (ROOT / "NEXT-SESSION.md").exists(), (
        "NEXT-SESSION.md is back; D-051 renamed it NEXT-SESSION-BE.md"
    )

    state = STATE.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\|[^|\n]+\|\s*`(NEXT-SESSION-[A-Z]+\.md)`\s*\|[^|\n]*\|\s*([SFB][0-9]+)\s*\|(.*)$",
        state,
        re.MULTILINE,
    )
    expected = {name: session for name, session, _ in rows}
    assert set(expected) == set(TRACK_PROMPTS), (
        f"STATE.md's Tracks table lists {sorted(expected)}, not the three tracks"
    )
    focus = [name for name, _, rest in rows if "**focus**" in rest]
    assert len(focus) == 1, f"exactly one track is the focus, STATE.md marks {focus}"

    for name, (word, prefix) in TRACK_PROMPTS.items():
        text = (ROOT / name).read_text(encoding="utf-8")
        header = re.match(
            r"# NEXT-SESSION-[A-Z]+ — track: [a-z ]+ · session: ([SFB][0-9]+)\n", text
        )
        assert header, (
            f"{name} lacks the `# NEXT-SESSION-<TRACK> — track: … · session: <id>` header"
        )
        session = header.group(1)
        assert session.startswith(prefix), f"{name} names {session}; its ids start with {prefix}"
        assert session == expected[name], (
            f"{name} says {session}, STATE.md expects {expected[name]}"
        )
        assert f"/session-start {word} {session}" in text, (
            f"{name}'s paste-ready prompt never says `/session-start {word} {session}`"
        )
