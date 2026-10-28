"""The Actions SDK contract — S17 (Phase 4, the first session that is not
Living Verdicts).

Auspex's pitch is "an AI co-analyst with SOAR-grade action capabilities built
in". Everything through S16 READS: enrichment, the KB, verdicts, retro-hunts,
watchers, the timeline. This module is the contract that lets it ACT, and the
contract IS the deliverable — nothing here touches a real external system, and
nothing here executes anything (proposals and approvals are S18).

Three commitments, all of them structural rather than documented:

1. **The spec is the source of truth (D-007, "specs over prompts").** An action
   declares what it does, what it needs, and what it can break, in code. The
   planner directive, the parameter schema on the wire, and the human-facing
   approval text are all COMPILED from that declaration — the same relationship
   `auspex/modes/contract.py` has between a mode and its prompt+validator. We do
   not hand-write a prompt describing an action and hope it matches the code.

2. **Destructive ⇒ undo, and it is a registration error, not a review note.**
   S14, S15 and S16 each spent their Step 0 on the same lesson: a rail that holds
   because everyone remembers it is not a rail (the trail head decided by
   transaction start, the falsifies link surviving on sink order, a checker
   counted only when someone thought to). An action that can destroy something
   and cannot say how to put it back cannot be registered at all.

3. **`dry_run` is required of everything, with no defaulting.** An action must be
   able to say what it WOULD do without doing it. A default — "reads don't need
   one", "reuse execute if absent" — would make the guarantee a convention again,
   and a convention is what D-006 says not to rely on for safety-critical
   behaviour.

Risk reuses `auspex.agent.registry.ToolLevel` rather than introducing a second
vocabulary. That enum is what the D-014 permission gate already reads to decide
allow-vs-propose, and an action carrying its own parallel notion of danger would
be a second opinion about whether a human must approve it — the exact class of
drift S16's staleness module exists to prevent for aging.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum

from auspex.agent.registry import ToolLevel
from auspex.llm.client import tool_spec

# Both an action's name and a parameter's name are identifiers a MODEL has to
# reproduce exactly on the wire. ASCII only and explicitly, because `str.isalnum`
# is true for 'π' and every other unicode letter — the check that was here read
# like it excluded them and did not.
_WIRE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# An action's risk IS its permission level. Same enum, same gate, one decision.
ActionRisk = ToolLevel

# What a dry run and an execution return. Both are plain dicts on the wire (the
# proposal record in S18 is jsonb), so the SDK stays serialisable end to end.
ActionHandler = Callable[..., Awaitable["ActionOutcome"]]
# How many of ONE proposal's effects exist right now (TD-028b). Called with the
# same keyword arguments as `execute` (workspace_id, proposal_id, the action's
# params). 0 means "looked, and nothing of this proposal's is there".
EffectsProbe = Callable[..., Awaitable[int]]

# The keywords the platform passes every handler (S31): an action parameter of
# the same name would collide with them on the call.
class RefusedBeforeDispatch(Exception):
    """A handler refused before it sent anything anywhere, so nothing of it can have
    landed. The settlement records that as `failed` with effects `none`, without asking
    `observe` (which would refuse for the same reason and read as "unknown"). Raised by
    a compiled connector role called for a workspace that does not own its integration
    (review of PR #43's fixes, I1)."""


PLATFORM_KEYWORDS = frozenset({"workspace_id", "proposal_id", "idempotency_key"})


def _takes_keyword(fn: Callable, name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        p.kind is p.VAR_KEYWORD
        or (p.name == name and p.kind in (p.KEYWORD_ONLY, p.POSITIONAL_OR_KEYWORD))
        for p in params
    )


class ParamType(StrEnum):
    """The JSON-schema primitives an action parameter may declare.

    Deliberately small. Every value here survives a round trip through an
    OpenAI-compatible `parameters` schema on any endpoint the capability probe
    has measured, and a type this list cannot express is a signal the action
    wants a structured argument the S2 harness already found models mangle
    (docs/probes/2026-07-15-ollama-endpoint.md: short ids, never raw 64-char
    strings).
    """

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class ActionParam:
    """One typed input. Compiles to a JSON-schema property AND to the line the
    planner reads about it — one declaration, both consumers."""

    name: str
    type: ParamType
    description: str
    required: bool = True
    # A closed value set, checked in code before anything is proposed. Same
    # device as ContractField.allowed_values: an enum the model is TOLD about and
    # that is also VERIFIED, because being told is not an enforcement mechanism.
    enum: tuple[str, ...] = ()

    def schema(self) -> dict:
        out: dict[str, object] = {"type": self.type.value, "description": self.description}
        if self.enum:
            out["enum"] = list(self.enum)
        return out


@dataclass(frozen=True)
class UndoSpec:
    """How an action is put back, declared by the author who wrote the action.

    `restores` is prose an approver reads; `cannot_restore` is the honest part.
    An undo that silently fails to restore something is worse than no undo,
    because the approval it unlocked was granted on the strength of it — so what
    the undo does NOT cover is part of the declaration rather than a caveat
    someone discovers afterwards.

    An undo claiming to restore nothing is refused at registration: that is not
    an undo, it is a second action.
    """

    description: str  # what running the undo does, in one line
    handler: ActionHandler
    restores: str  # the state the undo genuinely puts back
    cannot_restore: tuple[str, ...] = ()  # named, not implied


@dataclass(frozen=True)
class ActionScope:
    """What the action needs to reach, and how hard it touches it.

    `system` is the external thing (an EDR, a ticketing system, a firewall);
    `writes` says whether this action changes state there. Scope is not
    decoration: it is what a workspace's operator grants, and what an approval
    card names when it asks a human to consent to something happening in a
    system the platform does not own.
    """

    system: str
    writes: bool
    detail: str = ""


@dataclass(frozen=True)
class ConnectorOrigin:
    """Which connector, and which exact package of it, an action was compiled from
    (S32, D-064). Built-in actions have none.

    Part of the declaration an approver relies on, so it is in the fingerprint
    (proposal.canonical_spec, v2): a human who approved "close this alert" against
    one build of a connector did not approve whatever a later upload of the same
    id does. The content hash is what the agent must run (D-062), so naming it here
    makes a re-upload a changed action rather than the same one.
    """

    connector_id: str
    content_hash: str


class ActionSpecError(ValueError):
    """A spec that cannot be honoured as written. Raised at DECLARATION time
    (the decorator) and again at registration, because the two entry points must
    not be able to disagree about what a legal action is."""


@dataclass(frozen=True)
class ActionOutcome:
    """The result of a dry run or of an execution.

    `would` is the sentence a human approves or rejects — generated by the
    action from its real inputs, never by the model describing its own intent.
    D-014 in the shape it takes here: model-asserted completion is not
    execution, and model-asserted INTENT is not a proposal either.
    """

    would: str
    affects: tuple[str, ...] = ()
    reversible: bool = True
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ActionSpec:
    """Everything declared about one action. Compiles to the wire schema, the
    planner directive and the approval text; validates itself on construction."""

    name: str
    description: str
    risk: ActionRisk
    scope: tuple[ActionScope, ...]
    params: tuple[ActionParam, ...]
    dry_run: ActionHandler
    execute: ActionHandler
    undo: UndoSpec | None = None
    # TD-028b: lets the platform check, after `execute` raised, whether any of
    # this proposal's effects landed. Without it a failure cannot be called
    # clean, so it is recorded as `incomplete` rather than `failed` — the
    # honest default for an action that cannot look. A handler, so it is not
    # part of the declaration's fingerprint (proposal.canonical_spec).
    observe: EffectsProbe | None = None
    # S32: the connector package this spec was compiled from (auspex.connectors),
    # or None for a built-in. Declared, so it IS part of the fingerprint (v2).
    origin: ConnectorOrigin | None = None

    def __post_init__(self) -> None:
        validate_spec(self)

    # ── compiled artefacts (one declaration, three consumers) ────────────────

    @property
    def parameters(self) -> dict[str, dict]:
        return {p.name: p.schema() for p in self.params}

    @property
    def required(self) -> list[str]:
        return [p.name for p in self.params if p.required]

    @property
    def wire_spec(self) -> dict:
        """The OpenAI function envelope, built with the SAME builder the S3 tool
        registry and the capability probe use — an action must not arrive on the
        wire in a shape the probe never measured."""
        return tool_spec(self.name, self.planner_description, self.parameters, self.required)

    @property
    def planner_description(self) -> str:
        """What the model is told this action is. Assembled from the spec so it
        cannot drift from what the action actually declares, and it states the
        approval requirement inline: a planner that believes it can execute a
        destructive action directly will write plans that read as done."""
        bits = [self.description.rstrip(".") + "."]
        if self.risk is not ActionRisk.READ:
            bits.append(
                f"RISK {self.risk.value}: requires human approval before it runs "
                "(you may propose it, never perform it)."
            )
        systems = ", ".join(
            f"{s.system} ({'writes' if s.writes else 'reads'})" for s in self.scope
        )
        if systems:
            bits.append(f"Touches: {systems}.")
        if self.undo is not None:
            bits.append(f"Undo: {self.undo.description.rstrip('.')}.")
            if self.undo.cannot_restore:
                bits.append(f"Undo does NOT restore: {', '.join(self.undo.cannot_restore)}.")
        elif self.risk is ActionRisk.DESTRUCTIVE:  # pragma: no cover — refused earlier
            raise ActionSpecError(
                f"{self.name}: destructive action reached the planner with no undo"
            )
        return " ".join(bits)

    @property
    def reversible(self) -> bool:
        """Whether the platform can put this back. `False` is not a blocker for a
        write — plenty of legitimate writes (a posted comment) are one-way — but
        a DESTRUCTIVE action can never reach here as False, because registration
        refuses one without an undo."""
        return self.undo is not None and not self.undo.cannot_restore


def validate_spec(spec: ActionSpec) -> None:
    """The rules that make the contract a rail instead of a style guide.

    Every one of these is a registration ERROR rather than a warning, and every
    one is here rather than in the registry so that constructing an illegal spec
    is impossible — the registry re-runs them so a spec built by any other route
    meets the same bar.
    """
    if not _WIRE_NAME.fullmatch(spec.name or ""):
        raise ActionSpecError(
            f"action name {spec.name!r} must be a wire identifier — ASCII letters, "
            "digits and underscore, not starting with a digit (it is a tool name "
            "on the wire)"
        )
    if not spec.description.strip():
        raise ActionSpecError(f"{spec.name}: an action must say what it does")
    if not callable(spec.execute):
        raise ActionSpecError(f"{spec.name}: execute must be callable")

    # dry_run, of everything, with no defaulting. See the module docstring.
    if not callable(spec.dry_run):
        raise ActionSpecError(
            f"{spec.name}: dry_run is required for every action — an action that "
            "cannot say what it would do without doing it cannot be approved"
        )
    if spec.dry_run is spec.execute:
        raise ActionSpecError(
            f"{spec.name}: dry_run and execute are the same callable — a dry run "
            "that performs the action is not a dry run"
        )

    # The rule this session exists to make cheap.
    if spec.risk is ActionRisk.DESTRUCTIVE and spec.undo is None:
        raise ActionSpecError(
            f"{spec.name}: destructive actions require an undo. Declare one, or "
            "declare the action write-risk if it does not actually destroy state"
        )
    if spec.undo is not None:
        if spec.risk is ActionRisk.READ:
            raise ActionSpecError(
                f"{spec.name}: a read action declared an undo — nothing to undo, so "
                "the risk level is probably wrong"
            )
        if not callable(spec.undo.handler):
            raise ActionSpecError(f"{spec.name}: undo.handler must be callable")
        if not spec.undo.restores.strip():
            raise ActionSpecError(
                f"{spec.name}: undo must say what it restores — an undo that restores "
                "nothing is a second action, not a reversal"
            )
        if spec.undo.handler is spec.execute:
            raise ActionSpecError(f"{spec.name}: undo cannot be the action itself")
        # S18 Step 0, executed: `undo.handler is execute` was the ONLY guard on
        # the undo slot, so an undo that was the action's own dry_run registered
        # happily, reported `reversible=True`, and put the approval text "Undo:
        # ..." in front of a human — then restored nothing when run, because a
        # dry run's whole job is to not do anything. That is the failure
        # UndoSpec's own docstring calls worse than having no undo at all: the
        # approval was granted on the strength of it. Same family as the
        # `dry_run=another_action` case S17 found by RUNNING the contract.
        if spec.undo.handler is spec.dry_run:
            raise ActionSpecError(
                f"{spec.name}: undo.handler is this action's dry_run — a preview "
                "restores nothing, and the approval was granted on the undo's strength"
            )

    if spec.observe is not None:
        # S26 review of D-041, reproduced: `observe=execute` registered, and when
        # a run failed the platform's "look" ran the action a second time,
        # unapproved. The look must be its own callable — not the run, not the
        # preview (which would always say nothing landed), not the put-back.
        if not callable(spec.observe):
            raise ActionSpecError(f"{spec.name}: observe must be callable")
        undo_handler = spec.undo.handler if spec.undo is not None else None
        if spec.observe in (spec.execute, spec.dry_run) or spec.observe is undo_handler:
            raise ActionSpecError(
                f"{spec.name}: observe is this action's own execute, dry_run or undo — "
                "a look that runs, previews or reverts is not a look"
            )

    # TD-025 (S31): every attempt hands its handlers the operation's idempotency
    # key. A handler that cannot take it would fail at run time, after a human
    # approved; refuse it at registration instead.
    undo_fn = spec.undo.handler if spec.undo is not None else None
    for role, fn in (("execute", spec.execute), ("undo.handler", undo_fn),
                     ("observe", spec.observe)):
        if fn is not None and not _takes_keyword(fn, "idempotency_key"):
            raise ActionSpecError(
                f"{spec.name}: {role} must accept an idempotency_key keyword — every "
                "attempt hands it one (TD-025)"
            )

    if not spec.scope:
        raise ActionSpecError(
            f"{spec.name}: declare at least one scope — an approver is consenting to "
            "something happening in a named system"
        )
    for s in spec.scope:
        if not s.system.strip():
            raise ActionSpecError(f"{spec.name}: a scope must name its system")
        if s.writes and spec.risk is ActionRisk.READ:
            raise ActionSpecError(
                f"{spec.name}: risk is read but scope {s.system!r} writes — "
                "the gate reads risk, so this would auto-execute a write (D-014)"
            )

    seen: set[str] = set()
    for p in spec.params:
        # S18 Step 0, executed: the action NAME was checked because "it is a tool
        # name on the wire" — and a parameter name is a JSON-schema property key
        # on the SAME wire, checked by nothing. `''`, `'   '`, `'host id'`,
        # `'host-id'` and `'π'` all reached `wire_spec`, landing in both
        # `properties` and `required`. A model cannot reliably emit an argument
        # named `''`, so the action would be approved and then uncallable — and
        # S2's harness already measured that models mangle unusual identifiers
        # (docs/probes/2026-07-15-ollama-endpoint.md).
        if not _WIRE_NAME.fullmatch(p.name or ""):
            raise ActionSpecError(
                f"{spec.name}: parameter name {p.name!r} must be a wire identifier — "
                "ASCII letters, digits and underscore, not starting with a digit "
                "(it is a JSON-schema property the model has to name)"
            )
        if p.name in PLATFORM_KEYWORDS:
            raise ActionSpecError(
                f"{spec.name}: parameter {p.name!r} is a name the platform passes every "
                "handler itself"
            )
        if p.name in seen:
            raise ActionSpecError(f"{spec.name}: duplicate parameter {p.name!r}")
        seen.add(p.name)
        if not p.description.strip():
            raise ActionSpecError(f"{spec.name}.{p.name}: a parameter must describe itself")
        if p.enum and p.type is not ParamType.STRING:
            raise ActionSpecError(
                f"{spec.name}.{p.name}: enum is only meaningful on a string parameter"
            )


__all__ = [
    "PLATFORM_KEYWORDS",
    "ActionHandler",
    "ActionOutcome",
    "ActionParam",
    "ActionRisk",
    "ActionScope",
    "ActionSpec",
    "ActionSpecError",
    "ConnectorOrigin",
    "ParamType",
    "UndoSpec",
    "validate_spec",
    "RefusedBeforeDispatch",
]
