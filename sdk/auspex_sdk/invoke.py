"""One way to run one connector command and check what it returns (TD-077, S34).

The harness (`auspex-sdk run`, against recorded exchanges) and the Edge Agent's runner
(`python -m auspex_sdk.run`) both call `invoke`: it resolves the command to its
handler, builds `ctx.config` from the manifest (the same for both authoring forms),
imports and calls the handler with the right arguments, and checks the result with
`auspex_sdk.validate`. The callers differ only in what they wrap around it: the
harness turns failures into `HarnessError`; the runner captures and redacts output.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx

from auspex_sdk import validate
from auspex_sdk.build import import_source_module, importable
from auspex_sdk.manifest import Action, Manifest, Tls
from auspex_sdk.results import encode_result
from auspex_sdk.runtime import Context, Secret, Url, connector, load_config

STEPS = ("dry_run", "execute", "undo", "observe")
DEFAULT_LIMIT = 100

_CONFIG_PY = {"string": str, "integer": int, "boolean": bool, "url": Url, "secret": Secret}


class CommandError(ValueError):
    """The command cannot be run as named. The message says why."""


def config_class(m: Manifest) -> type:
    """`ctx.config`'s class, from the manifest's config fields (both authoring forms)."""
    fields = []
    for f in m.config:
        t: Any = Literal[f.values] if f.type == "enum" and f.values else _CONFIG_PY.get(f.type, Tls)
        field: Any = (f.name, Annotated[t, f.label])
        if not f.required:
            default = Tls() if f.type == "tls" else f.default
            field = (*field, dataclasses.field(default=default))
        fields.append(field)
    cls = dataclasses.make_dataclass("Config", fields, frozen=True, kw_only=True)
    many = m.fetch is not None and m.fetch.serves_many_clients
    return connector(m.id, m.version, m.name, m.description, many, m.hosts)(cls)


def bind(a: Action, arguments: dict) -> dict:
    declared = {p.name: p for p in a.params}
    for name in arguments:
        if name not in declared:
            raise CommandError(f"{a.name}: argument {name!r} is not a declared param")
    for name, p in declared.items():
        if p.required and arguments.get(name) is None:
            raise CommandError(f"{a.name}: param {name!r} is required")
    return {name: arguments.get(name) for name in declared}  # an omitted optional is None


def resolve(m: Manifest, command: str) -> tuple[str, Action | None, str | None]:
    """(handler reference, the action, the step) for a command name."""
    if command == "test":
        return m.test_handler, None, None
    if command == "fetch":
        if m.fetch is None:
            raise CommandError("this connector declares no fetch command")
        return m.fetch.handler, None, None
    name, _, step = command.rpartition(".")
    action = next((a for a in m.actions if a.name == name), None)
    if action is None or step not in STEPS:
        raise CommandError(
            f"{command!r}: expected test, fetch or <action>.<{'|'.join(STEPS)}> "
            f"with an action of {', '.join(a.name for a in m.actions) or 'none'}"
        )
    ref = {
        "dry_run": action.dry_run,
        "execute": action.execute,
        "undo": action.undo.handler if action.undo else None,
        "observe": action.observe,
    }[step]
    if not ref:
        raise CommandError(f"action {name!r} declares no {step}")
    return ref, action, step


def check(manifest: Manifest, command: str, result: Any) -> None:
    """The command's result against its contract (`auspex_sdk.validate`)."""
    _, action, step = resolve(manifest, command)
    if command == "test":
        validate.check_test(result)
    elif command == "fetch":
        validate.check_fetch(manifest, result)
    elif step == "observe":
        validate.check_observe(action, result)  # type: ignore[arg-type]
    else:
        validate.check_envelope(action, step, result)  # type: ignore[arg-type]


def invoke(
    root: Path,
    manifest: Manifest,
    command: str,
    *,
    values: dict,
    secrets: dict,
    arguments: dict,
    transport: httpx.BaseTransport | None,
    idempotency_key: str,
    missing: Callable[[str], Exception],
    wrap: Callable[[Exception], Exception] | None = None,
    capture: io.StringIO | None = None,
) -> Any:
    """Run `command` and return its checked, canonical result.

    `missing(message)` is raised when the handler is not in the package; `wrap(e)`, when
    given, replaces an exception the handler itself raised; `capture`, when given,
    receives everything the handler prints or logs."""
    ref, action, _ = resolve(manifest, command)
    # The caller's arguments, checked before the handler runs: a missing or undeclared
    # one is the caller's mistake, never reported as the handler's (PR #53 review s2).
    bound = bind(action, arguments) if action is not None else None
    cfg = load_config(config_class(manifest), values, secrets)
    where = f"command {command}"
    root = Path(root).resolve()
    module_name, _, func_name = ref.partition(":")
    with importable(root):
        fn = getattr(import_source_module(module_name, root, where), func_name, None)
        if not callable(fn):
            raise missing(f"{where}: handler {ref!r}: {func_name!r} is not in {module_name!r}")
        ctx = Context.create(cfg, idempotency_key=idempotency_key, transport=transport)
        handler = logging.StreamHandler(capture) if capture is not None else None
        if handler is not None:
            ctx.log.addHandler(handler)
        quiet = (contextlib.ExitStack() if capture is None else
                 _redirected(capture))
        try:
            with quiet:
                try:
                    if action is not None:
                        result = fn(ctx, **bound)
                    elif command == "fetch":
                        result = fn(ctx, arguments.get("cursor"),
                                    arguments.get("limit", DEFAULT_LIMIT))
                    else:
                        result = fn(ctx)
                except Exception as e:
                    if wrap is None:
                        raise
                    raise wrap(e) from e
        finally:
            if handler is not None:
                ctx.log.removeHandler(handler)
            ctx.http.close()
    check(manifest, command, result)
    return json.loads(encode_result(result))


@contextlib.contextmanager
def _redirected(capture: io.StringIO):
    with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
        yield
