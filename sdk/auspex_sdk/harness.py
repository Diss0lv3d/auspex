"""`auspex-sdk run`: one command of a connector against recorded HTTP exchanges (S32).

An author runs `test`, `fetch` or one step of an action (`<action>.<dry_run|execute|undo|observe>`)
with no network: every request the handler makes is answered from a fixture file,

    {"exchanges": [{"request": {"method": "GET", "url": "https://host/path?a=1"},
                    "response": {"status": 200, "headers": {...}, "json": ... | "text": "..."}}]}

The fixture is an `httpx.MockTransport` plugged into `ConnectorHttp`, which wraps ANY transport
in the host-bound one, so the declared-host check runs before the fixture is consulted: a
connector that reaches an undeclared host fails here the way it would in production. A request
matches on method and the full URL (query order does not matter); each exchange answers one
request. A request nothing matches raises `HarnessError` naming it; exchanges left unused are
not an error.

The result is validated against the same contract the core enforces later (D-062) and returned
as the decoded canonical JSON: `test` is {ok, detail}; `fetch` is {items, next_cursor} with every
item through `check_fetch_item`; an action step is the envelope {would, affects, reversible,
detail} with `detail` held to the action's declared `output`; `observe` is a non-negative int.

The handler's `ctx.config` is a frozen dataclass built from the manifest's config fields, the
same for both authoring forms, so a YAML connector (which has no config class) runs too.
"""

import dataclasses
import json
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, urlsplit

import httpx

from auspex_sdk import validate
from auspex_sdk.build import BuildError, import_source_module, importable, load_manifest
from auspex_sdk.http import HostNotDeclared
from auspex_sdk.manifest import Action, Manifest, Tls
from auspex_sdk.results import ResultError, encode_result
from auspex_sdk.runtime import Context, Secret, Url, connector, load_config

STEPS = ("dry_run", "execute", "undo", "observe")
DEFAULT_LIMIT = 100


class HarnessError(ValueError):
    """The run cannot proceed or its result breaks the contract. The message says why."""


# --- the fixture -----------------------------------------------------------------------------


def _key(method: str, url: str) -> tuple[str, str, str, int | None, str, tuple]:
    parts = urlsplit(url)
    port = parts.port
    if port is None:
        port = {"https": 443, "http": 80}.get(parts.scheme)
    query = tuple(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return (method.upper(), parts.scheme, (parts.hostname or "").lower(), port, parts.path, query)


def _load_exchanges(fixture: Path) -> list[tuple[tuple, httpx.Response]]:
    try:
        data = json.loads(Path(fixture).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HarnessError(f"fixture {fixture}: cannot be read as JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("exchanges"), list):
        raise HarnessError('fixture: expected {"exchanges": [...]}')
    out = []
    for i, ex in enumerate(data["exchanges"]):
        where = f"fixture exchanges[{i}]"
        try:
            req, resp = ex["request"], ex["response"]
            method, url = req["method"], req["url"]
            status = resp["status"]
        except (KeyError, TypeError) as e:
            raise HarnessError(
                f"{where}: needs request.method, request.url, response.status"
            ) from e
        if not isinstance(method, str) or not isinstance(url, str) or not isinstance(status, int):
            raise HarnessError(f"{where}: method and url are strings, status an integer")
        if "json" in resp and "text" in resp:
            raise HarnessError(f"{where}: a response has json or text, not both")
        headers = resp.get("headers") or {}
        if not isinstance(headers, dict):
            raise HarnessError(f"{where}: headers is an object")
        if "json" in resp:
            response = httpx.Response(status, headers=headers, json=resp["json"])
        else:
            response = httpx.Response(status, headers=headers, text=resp.get("text", ""))
        out.append((_key(method, url), response))
    return out


def _transport(fixture: Path) -> httpx.MockTransport:
    pending = _load_exchanges(fixture)

    def serve(request: httpx.Request) -> httpx.Response:
        key = _key(request.method, str(request.url))
        for i, (k, response) in enumerate(pending):
            if k == key:
                del pending[i]  # each recorded exchange answers one request
                return response
        raise HarnessError(f"no recorded exchange for {request.method} {request.url}")

    return httpx.MockTransport(serve)


# --- the config object -----------------------------------------------------------------------

_CONFIG_PY = {"string": str, "integer": int, "boolean": bool, "url": Url, "secret": Secret}


def config_class(m: Manifest) -> type:
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


# --- running ---------------------------------------------------------------------------------


def _bind(a: Action, arguments: dict) -> dict:
    declared = {p.name: p for p in a.params}
    for name in arguments:
        if name not in declared:
            raise HarnessError(f"{a.name}: argument {name!r} is not a declared param")
    for name, p in declared.items():
        if p.required and arguments.get(name) is None:
            raise HarnessError(f"{a.name}: param {name!r} is required")
    return {name: arguments.get(name) for name in declared}  # an omitted optional arrives as None


def _resolve(m: Manifest, command: str) -> tuple[str, Action | None, str | None]:
    """(handler reference, the action, the step) for a command name."""
    if command == "test":
        return m.test_handler, None, None
    if command == "fetch":
        if m.fetch is None:
            raise HarnessError("this connector declares no fetch command")
        return m.fetch.handler, None, None
    name, _, step = command.rpartition(".")
    action = next((a for a in m.actions if a.name == name), None)
    if action is None or step not in STEPS:
        raise HarnessError(
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
        raise HarnessError(f"action {name!r} declares no {step}")
    return ref, action, step


def run_command(
    source_dir: Path,
    command: str,
    *,
    config: dict,
    secrets: dict,
    fixture: Path,
    arguments: dict | None = None,
) -> dict | int:
    """Run `command` against the fixture; the validated, canonical result (dict, or int for
    observe). Raises HarnessError, ManifestError, ResultError, HostNotDeclared, BuildError."""
    source_dir = Path(source_dir)
    arguments = dict(arguments or {})
    manifest = load_manifest(source_dir)
    ref, action, step = _resolve(manifest, command)
    transport = _transport(fixture)
    cfg = load_config(config_class(manifest), config, secrets)
    where = f"command {command}"
    root = source_dir.resolve()
    module_name, _, func_name = ref.partition(":")
    with importable(root):
        fn = getattr(import_source_module(module_name, root, where), func_name, None)
        if not callable(fn):
            raise BuildError(f"{where}: handler {ref!r}: {func_name!r} is not in {module_name!r}")
        ctx = Context.create(cfg, idempotency_key=f"harness-{command}", transport=transport)
        try:
            if action is not None:
                result = fn(ctx, **_bind(action, arguments))
            elif command == "fetch":
                cursor, limit = arguments.get("cursor"), arguments.get("limit", DEFAULT_LIMIT)
                result = fn(ctx, cursor, limit)
            else:
                result = fn(ctx)
        except (HarnessError, HostNotDeclared, ResultError):
            raise
        except Exception as e:  # the author's code failed; say which command, keep the cause
            raise HarnessError(f"{command}: handler raised {type(e).__name__}: {e}") from e
        finally:
            ctx.http.close()
    try:
        if command == "test":
            validate.check_test(result)
        elif command == "fetch":
            validate.check_fetch(manifest, result)
        elif step == "observe":
            validate.check_observe(action, result)  # type: ignore[arg-type]
        else:
            validate.check_envelope(action, step, result)  # type: ignore[arg-type]
    except validate.ResultInvalid as e:
        raise HarnessError(str(e)) from e
    return json.loads(encode_result(result))
