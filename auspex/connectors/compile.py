"""A manifest action compiles to today's `ActionSpec` (S32, D-064, spec decision 5).

A connector action is not a second kind of action. It becomes the same `ActionSpec` a
built-in is, so it meets the same contract (D-023), the same D-014 gate and the same
execute-time re-check (D-024), with `validate_spec` passing UNCHANGED: no connector-shaped
exception in the approvals core.

What makes that possible is that the handlers are closures over `dispatch`, a coroutine the
caller provides (S33: enqueue the job, await its validated result). dry_run, execute, undo
and observe are four DISTINCT function objects even though they share their code, because
validate_spec's identity rules (a dry run that is the execute, an undo that is the dry run,
an observe that is any of them) are how the contract tells them apart, and a single shared
callable would be refused, rightly.

What the model and the approver read is composed HERE from the manifest's typed fields and
capped at the manifest's own limit (D-064). Measuring customer text against the output rail
is S34's (TD-044).
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from auspex_sdk.manifest import MAX_DESCRIPTION, Action, Manifest
from auspex_sdk.vocab import MAX_PREFIX, MAX_TOOL_NAME, WIRE_NAME

from auspex.actions.types import (
    ActionOutcome,
    ActionParam,
    ActionRisk,
    ActionScope,
    ActionSpec,
    ConnectorOrigin,
    ParamType,
    UndoSpec,
)
from auspex.connectors.jobs import CONNECTOR_KINDS, ConnectorJobPayload

# The integration prefix is the first half of the wire name `<prefix>__<action>`, capped
# (MAX_PREFIX, from the SDK's vocab) so the whole name stays a valid tool name (spec
# decision 5). The manifest caps the action name to fit; the composed name is checked
# again here, whatever built the manifest.

# The kind each handler role dispatches, looked up from the one declared list.
_KIND = {k.rsplit(".", 1)[1]: k for k in CONNECTOR_KINDS if k.startswith("connector.action.")}


class Dispatch(Protocol):
    """Run one connector job and return its result: the SDK's action envelope for
    dry_run, execute and undo, a count for observe."""

    async def __call__(self, kind: str, payload: ConnectorJobPayload) -> Any: ...


class ConnectorResultError(ValueError):
    """A connector's result is not the shape the platform turns into an outcome. Raised
    rather than coerced: a malformed `would` is the sentence a human approves."""


def _text(value: str) -> str:
    """One line, capped. A newline in customer text would read as structure to the model."""
    line = " ".join(value.split())
    if len(line) > MAX_DESCRIPTION:
        line = line[: MAX_DESCRIPTION - 1].rstrip() + "…"
    return line


def _outcome(kind: str, result: Any) -> ActionOutcome:
    """The SDK action envelope (`would`, `affects`, `reversible`, `detail`) as an
    ActionOutcome. Checked key by key; the output schema over `detail` is S33's (D-062)."""
    if not isinstance(result, dict) or set(result) != {"would", "affects", "reversible", "detail"}:
        raise ConnectorResultError(
            f"{kind}: expected an envelope with would, affects, reversible and detail"
        )
    would, affects = result["would"], result["affects"]
    if not isinstance(would, str):
        raise ConnectorResultError(f"{kind}: would must be a string")
    if not isinstance(affects, list) or not all(isinstance(a, str) for a in affects):
        raise ConnectorResultError(f"{kind}: affects must be a list of strings")
    if not isinstance(result["reversible"], bool):
        raise ConnectorResultError(f"{kind}: reversible must be a boolean")
    if not isinstance(result["detail"], dict):
        raise ConnectorResultError(f"{kind}: detail must be an object")
    return ActionOutcome(
        would=_text(would),
        affects=tuple(affects),
        reversible=result["reversible"],
        detail=_flatten(result["detail"]),
    )


def _flatten(value: Any) -> Any:
    """Every string in a result's `detail`, one line and capped like `would`: it reaches
    the approval card and the model, so connector text gets no structure of its own."""
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, dict):
        return {k: _flatten(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_flatten(v) for v in value]
    return value


def _count(kind: str, result: Any) -> int:
    # bool is an int subclass and is not a count (same rule as settlement's observe check).
    if type(result) is not int or result < 0:
        raise ConnectorResultError(f"{kind}: observe returns a count of effects, got {result!r}")
    return result


def _find(manifest: Manifest, name: str) -> Action:
    for a in manifest.actions:
        if a.name == name:
            return a
    raise ValueError(f"{manifest.id} declares no action {name!r}")


def compile_action(
    manifest: Manifest,
    action: str,
    *,
    content_hash: str,
    prefix: str,
    integration_id: UUID,
    dispatch: Dispatch,
) -> ActionSpec:
    """The `ActionSpec` for one action of one integration of one connector package.

    `integration_id` is in the signature because every job payload carries it (the job
    row's claim is scoped by it) and the handlers build those payloads: `dispatch` alone
    cannot supply it without the payload being built half-empty and patched afterwards.
    """
    if not isinstance(prefix, str) or not WIRE_NAME.fullmatch(prefix) or len(prefix) > MAX_PREFIX:
        raise ValueError(
            f"prefix {prefix!r} must be a wire identifier of at most {MAX_PREFIX} characters"
        )
    a = _find(manifest, action)
    name = f"{prefix}__{a.name}"
    if len(name) > MAX_TOOL_NAME:
        raise ValueError(
            f"tool name {name!r} is longer than {MAX_TOOL_NAME} characters, the wire's limit"
        )

    # The workspace is the job row's, not the payload's (S33 enqueues under it).
    def payload(command: str, proposal_id, idempotency_key, arguments: dict):
        return ConnectorJobPayload(
            integration_id=integration_id,
            content_hash=content_hash,
            command=command,
            action=a.name,
            arguments=arguments,
            proposal_id=None if proposal_id is None else UUID(str(proposal_id)),
            idempotency_key=idempotency_key,
            cursor=None,
            limit=None,
        )

    # A factory, called once per role, so each role gets its own function object.
    def handler(command: str):
        kind = _KIND[command]

        async def run(*, workspace_id=None, proposal_id=None, idempotency_key=None,
                      **arguments) -> ActionOutcome:
            job = payload(command, proposal_id, idempotency_key, arguments)
            return _outcome(kind, await dispatch(kind, job))

        return run

    def probe():
        kind = _KIND["observe"]

        async def look(*, workspace_id=None, proposal_id=None, idempotency_key=None,
                       **arguments) -> int:
            job = payload("observe", proposal_id, idempotency_key, arguments)
            return _count(kind, await dispatch(kind, job))

        return look

    undo = None
    if a.undo is not None:
        undo = UndoSpec(
            description=_text(f"{manifest.name} reverses {a.name}"),
            handler=handler("undo"),
            restores=_text(a.undo.restores),
            cannot_restore=tuple(_text(c) for c in a.undo.cannot_restore),
        )
    risk = ActionRisk(a.risk)
    return ActionSpec(
        name=name,
        description=_text(f"{manifest.name}: {a.description}"),
        risk=risk,
        scope=(ActionScope(system=manifest.id, writes=risk is not ActionRisk.READ,
                           detail=prefix),),
        params=tuple(
            ActionParam(
                name=p.name,
                type=ParamType(p.type),
                description=_text(p.description),
                required=p.required,
                enum=tuple(p.values or ()),
            )
            for p in a.params
        ),
        dry_run=handler("dry_run"),
        execute=handler("execute"),
        undo=undo,
        observe=probe() if a.observe is not None else None,
        origin=ConnectorOrigin(manifest.id, content_hash),
    )


__all__ = ["ConnectorResultError", "Dispatch", "compile_action"]
