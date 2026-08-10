"""`@action` — S17. Declaring an action, in code, at import time.

The decorator does two things and refuses to do a third:

* It builds the `ActionSpec` and validates it IMMEDIATELY. An illegal action is
  an ImportError, not a runtime surprise and not a review comment — the earliest
  and loudest place to find out that a destructive action has no undo is the
  moment someone writes it.
* It ATTACHES the spec to the function and returns the function unchanged, so the
  action stays an ordinary callable that a test can call directly. A decorator
  that swallowed the function into an opaque object would make the SDK's own unit
  tests go through the registry to reach the code they are testing.

It does NOT register. Import-time side effects into a global registry would make
what the planner can propose a function of which modules happened to be imported
(auspex/agent/registry.py: "Registration is explicit and duplicate-safe" — the
same reasoning, and the S15 sink-order defect is what implicit ordering costs).
Registration is a call someone makes, at `auspex/actions/registry.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from auspex.actions.types import (
    ActionHandler,
    ActionParam,
    ActionRisk,
    ActionScope,
    ActionSpec,
    UndoSpec,
)

# Where the spec is parked on the decorated function. Read by the registry and
# by anything that wants to ask a plain function what it declares about itself.
SPEC_ATTR = "__auspex_action__"


def action(
    *,
    name: str,
    description: str,
    risk: ActionRisk,
    scope: Sequence[ActionScope],
    dry_run: ActionHandler,
    params: Sequence[ActionParam] = (),
    undo: UndoSpec | None = None,
) -> Callable[[ActionHandler], ActionHandler]:
    """Declare a function as an Auspex action.

    Every argument is keyword-only. Positionally, `risk` and `scope` would sit
    next to each other as short values whose order nobody can remember, and a
    silently swapped pair is how a destructive action gets registered as a read.

    `dry_run` is required here, not defaulted, and must not be `execute` — see
    auspex/actions/types.py. `undo` is required when `risk` is destructive, and
    that is enforced by construction rather than checked by a reviewer.
    """

    def decorate(fn: ActionHandler) -> ActionHandler:
        spec = ActionSpec(
            name=name,
            description=description,
            risk=risk,
            scope=tuple(scope),
            params=tuple(params),
            dry_run=dry_run,
            execute=fn,
            undo=undo,
        )
        setattr(fn, SPEC_ATTR, spec)
        return fn

    return decorate


def spec_of(fn: object) -> ActionSpec | None:
    """The spec a function declared, or None if it is not an action."""
    spec = getattr(fn, SPEC_ATTR, None)
    return spec if isinstance(spec, ActionSpec) else None


__all__ = ["SPEC_ATTR", "action", "spec_of"]
