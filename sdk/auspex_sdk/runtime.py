"""The Python-first connector runtime: decorators, `collect`, config and the context (S32).

A connector author writes one module:

    @connector(id="example.mock_siem", version="1.0.0", name="Mock SIEM",
               description="...", hosts=("https://{base_url}",))
    @dataclass(frozen=True)
    class Config:
        base_url: Annotated[Url, "SIEM URL"]          # the string is the label
        api_token: Annotated[Secret, "API token"]
        tls: Annotated[Tls, "TLS"] = Tls()            # Tls() is "verify"
        mode: Literal["fast", "full"] = "fast"         # an enum
        page: int = 50                                 # str/int/bool: string/integer/boolean

    @command("test")
    def check(ctx: Context) -> dict: ...              # -> {ok, detail}

    @command("fetch")
    def pull(ctx: Context, cursor: str | None, limit: int) -> dict: ...

    @action("close_alert", risk="write", dry_run=close_dry, undo=Undo(handler=reopen, ...),
            observe=close_observe, targets="alert_id", output=(OutputField(...),))
    def close_alert(ctx: Context, alert_id: Annotated[str, "The alert."]) -> dict:
        '''Close an alert.'''                          # the docstring is the description

Field and param types: `str`, `int`, `bool` (and `float` for params: number); `Literal[...]`
of strings (an enum field, or a string param with values); `Url`, `Secret`, `Tls` for config.
`X | None` is allowed and changes nothing in the manifest. A field or param with no default is
required. An action's params are its execute function's parameters after `ctx`.

`collect(module)` reads the decorated objects of one module into a `Manifest` and runs
`validate_manifest` on it, so every refusal carries the manifest rule and path. Handler
references are `"<module>:<function>"` and must be module-level functions. `collect` checks
the command signatures (`test(ctx)`, `fetch(ctx, cursor, limit)`); the build (Task 5) checks
the other handlers' parameters. Decorators only record (`__auspex__` on the object); they never
change what they decorate.

At run time `load_config` builds the config object from integration values plus the secrets
the agent resolved (D-063), and `Context` gives each handler the config, a `ConnectorHttp`
bound to the declared hosts and TLS, a logger that redacts every secret, and the job's
`idempotency_key` (spec "Idempotency and the SDK version").
"""

import dataclasses
import inspect
import logging
import sys
import types
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal, Union, get_args, get_origin, get_type_hints
from urllib.parse import urlsplit

import httpx

from auspex_sdk.http import ConnectorHttp, resolve_hosts
from auspex_sdk.manifest import (
    SCHEMA_VERSION,
    Action,
    ConfigField,
    Fetch,
    Manifest,
    ManifestError,
    OutputField,
    Param,
    Tls,
    Undo,
    _literal_host_ok,
    parse_tls_value,
    validate_manifest,
)
from auspex_sdk.redact import MIN_SECRET_LEN, redacting_filter

__all__ = [
    "ConfigError",
    "Context",
    "Secret",
    "Tls",
    "Url",
    "action",
    "collect",
    "command",
    "connector",
    "load_config",
]

_ATTR = "__auspex__"
COMMANDS: tuple[str, ...] = ("test", "fetch")
_COMMAND_PARAMS = {"test": (), "fetch": ("cursor", "limit")}


class Secret(str):
    """A config field the agent resolves (D-063). Its value is a plain str; its repr hides it."""

    def __repr__(self) -> str:
        return "Secret('[redacted]')"


class Url(str):
    """A config field holding an https URL; a `hosts` entry may name it (`https://{field}`)."""


Handler = Callable[..., Any] | str


@dataclasses.dataclass(frozen=True)
class _ConnectorSpec:
    id: str
    version: str
    name: str
    description: str
    serves_many_clients: bool
    hosts: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class _CommandSpec:
    name: str


@dataclasses.dataclass(frozen=True)
class _ActionSpec:
    name: str
    risk: str
    dry_run: Handler | None
    undo: Undo | None
    observe: Handler | None
    targets: str | None
    output: tuple[OutputField, ...]


# --- decorators ------------------------------------------------------------------------------


def connector(
    id: str,
    version: str,
    name: str,
    description: str,
    serves_many_clients: bool = False,
    hosts: tuple[str, ...] = (),
) -> Callable[[type], type]:
    """Mark a config dataclass as the connector. `hosts` is the manifest's `hosts` list."""

    def mark(cls: type) -> type:
        if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
            raise TypeError("@connector decorates a dataclass (put @dataclass under it)")
        spec = _ConnectorSpec(id, version, name, description, serves_many_clients, tuple(hosts))
        setattr(cls, _ATTR, spec)
        return cls

    return mark


def command(name: str) -> Callable[[Callable], Callable]:
    """Mark the handler of a fixed command: "test" -> {ok, detail}; "fetch" -> {items, ...}."""
    if name not in COMMANDS:
        raise ValueError(f"command is one of {', '.join(COMMANDS)}, not {name!r}")

    def mark(fn: Callable) -> Callable:
        setattr(fn, _ATTR, _CommandSpec(name))
        return fn

    return mark


def action(
    name: str,
    risk: str,
    dry_run: Handler | None,
    undo: Undo | None = None,
    observe: Handler | None = None,
    targets: str | None = None,
    output: tuple[OutputField, ...] = (),
) -> Callable[[Callable], Callable]:
    """Mark an action's execute handler. `dry_run`, `observe` and `undo.handler` are
    module-level functions (or `module:function` strings); every action declares a dry run."""

    def mark(fn: Callable) -> Callable:
        setattr(fn, _ATTR, _ActionSpec(name, risk, dry_run, undo, observe, targets, tuple(output)))
        return fn

    return mark


def _spec_of(obj: Any) -> Any:
    # Own attribute only: a subclass of a config class is not a second connector.
    try:
        return vars(obj).get(_ATTR)
    except TypeError:
        return None


# --- types -----------------------------------------------------------------------------------


def _unwrap(t: Any) -> tuple[Any, str | None]:
    """(the type without Annotated and `| None`, the first string in Annotated or None)."""
    text = None
    if get_origin(t) is Annotated:
        t, *meta = get_args(t)
        text = next((m for m in meta if isinstance(m, str)), None)
    if get_origin(t) in (Union, types.UnionType):
        args = [a for a in get_args(t) if a is not type(None)]
        if len(args) == 1:
            t = args[0]
    return t, text


def _literal_values(t: Any) -> tuple[str, ...] | None:
    if get_origin(t) is Literal and all(isinstance(v, str) for v in get_args(t)):
        return tuple(get_args(t))
    return None


def _config_type(t: Any) -> tuple[str | None, tuple[str, ...] | None]:
    values = _literal_values(t)
    if values is not None:
        return "enum", values
    for py, name in ((Secret, "secret"), (Url, "url"), (Tls, "tls"), (bool, "boolean")):
        if t is py:
            return name, None
    return {int: "integer", str: "string"}.get(t), None


def _param_type(t: Any) -> tuple[str | None, tuple[str, ...] | None]:
    values = _literal_values(t)
    if values is not None:
        return "string", values
    return {bool: "boolean", int: "integer", float: "number", str: "string"}.get(t), None


@dataclasses.dataclass(frozen=True)
class _Field:
    name: str
    label: str
    type: str | None
    required: bool
    default: Any
    values: tuple[str, ...] | None
    annotation: Any


def _config_fields(cls: type) -> list[_Field]:
    hints = get_type_hints(cls, include_extras=True)
    out = []
    for i, f in enumerate(dataclasses.fields(cls)):
        t, label = _unwrap(hints[f.name])
        ctype, values = _config_type(t)
        if f.default_factory is not dataclasses.MISSING:
            raise ManifestError(
                "bad_type", f"config[{i}].default", "a config field's default is a plain value"
            )
        required = f.default is dataclasses.MISSING
        default = None if required else f.default
        if ctype == "tls" and isinstance(default, Tls):
            default = "verify" if default == Tls() else dataclasses.asdict(default)
        out.append(_Field(f.name, label or f.name, ctype, required, default, values, t))
    return out


# --- collect ---------------------------------------------------------------------------------


def _ref(h: Handler, path: str) -> str:
    """`module:function` for a module-level function (a string passes through as written)."""
    if isinstance(h, str):
        return h
    mod, name = getattr(h, "__module__", None), getattr(h, "__name__", None)
    ok = (
        callable(h)
        and isinstance(mod, str)
        and isinstance(name, str)
        and getattr(h, "__qualname__", None) == name
        and getattr(sys.modules.get(mod), name, None) is h
    )
    if not ok:
        raise ManifestError("bad_type", path, "a handler is a module-level function")
    return f"{mod}:{name}"


def _handler_params(fn: Callable, path: str) -> list[inspect.Parameter]:
    params = list(inspect.signature(fn).parameters.values())
    if not params or params[0].kind not in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ):
        raise ManifestError("bad_type", path, "a handler takes the context first")
    rest = params[1:]
    for p in rest:
        if p.kind not in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
            raise ManifestError("bad_type", path, f"parameter {p.name!r} must be passable by name")
    return rest


def _params(fn: Callable, path: str) -> tuple[Param, ...]:
    hints = get_type_hints(fn, include_extras=True)
    out = []
    for j, p in enumerate(_handler_params(fn, path)):
        t, text = _unwrap(hints.get(p.name, p.annotation))
        ptype, values = _param_type(t)
        if ptype is None:
            raise ManifestError(
                "unknown_type",
                f"{path}.params[{j}].type",
                f"{p.name}: {t!r} is not str, int, float, bool or a Literal of strings",
            )
        out.append(
            Param(
                name=p.name,
                type=ptype,
                description=text or "",
                required=p.default is inspect.Parameter.empty,
                values=values,
            )
        )
    return tuple(out)


def _action(fn: Callable, spec: _ActionSpec, path: str) -> Action:
    undo = None
    if spec.undo is not None:
        undo = Undo(
            handler=_ref(spec.undo.handler, f"{path}.undo.handler"),
            restores=spec.undo.restores,
            cannot_restore=tuple(spec.undo.cannot_restore),
        )
    return Action(
        name=spec.name,
        description=inspect.getdoc(fn) or "",
        risk=spec.risk,
        params=_params(fn, path),
        execute=_ref(fn, f"{path}.execute"),
        dry_run=_ref(spec.dry_run, f"{path}.dry_run") if spec.dry_run is not None else "",
        undo=undo,
        observe=_ref(spec.observe, f"{path}.observe") if spec.observe is not None else None,
        output=spec.output,
        targets=spec.targets,
    )


def collect(module: types.ModuleType) -> Manifest:
    """The manifest a Python-first connector module declares, validated (ManifestError)."""
    seen: set[int] = set()
    objs = []
    for obj in vars(module).values():
        if _spec_of(obj) is not None and id(obj) not in seen:
            seen.add(id(obj))
            objs.append(obj)
    classes = [o for o in objs if isinstance(_spec_of(o), _ConnectorSpec)]
    if len(classes) != 1:
        raise ManifestError(
            "bad_type",
            "",
            f"a connector module has exactly one @connector class, not {len(classes)}",
        )
    cls = classes[0]
    spec: _ConnectorSpec = _spec_of(cls)
    commands: dict[str, Callable] = {}
    for fn in (o for o in objs if isinstance(_spec_of(o), _CommandSpec)):
        name = _spec_of(fn).name
        path = f"commands.{name}"
        if name in commands:
            raise ManifestError("duplicate_name", path, f"@command({name!r}) is declared twice")
        got = tuple(p.name for p in _handler_params(fn, path))
        if got != _COMMAND_PARAMS[name]:
            want = ", ".join(("ctx", *_COMMAND_PARAMS[name]))
            raise ManifestError("bad_type", path, f"the {name} handler's signature is ({want})")
        commands[name] = fn
    if "test" not in commands:
        raise ManifestError("bad_type", "commands.test", "a connector declares @command('test')")
    if spec.serves_many_clients and "fetch" not in commands:
        raise ManifestError(
            "bad_type", "commands.fetch", "serves_many_clients is declared on @command('fetch')"
        )
    config = []
    for i, f in enumerate(_config_fields(cls)):
        if f.type is None:
            raise ManifestError(
                "unknown_type",
                f"config[{i}].type",
                f"{f.name}: {f.annotation!r} is not str, int, bool, Url, Secret, Tls or a Literal",
            )
        config.append(ConfigField(f.name, f.label, f.type, f.required, f.default, f.values))
    actions = [
        _action(fn, _spec_of(fn), f"actions[{i}]")
        for i, fn in enumerate(o for o in objs if isinstance(_spec_of(o), _ActionSpec))
    ]
    m = Manifest(
        schema_version=SCHEMA_VERSION,
        id=spec.id,
        version=spec.version,
        name=spec.name,
        description=spec.description,
        config=tuple(config),
        hosts=spec.hosts,
        fetch=(
            Fetch(spec.serves_many_clients, _ref(commands["fetch"], "commands.fetch.handler"))
            if "fetch" in commands
            else None
        ),
        actions=tuple(actions),
        test_handler=_ref(commands["test"], "commands.test.handler"),
    )
    validate_manifest(m)
    return m


# --- config ----------------------------------------------------------------------------------


class ConfigError(ValueError):
    """An integration's config does not fit the connector. `.field` names it; never a value."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"{field}: {message}")


def _connector_spec(cls: type) -> _ConnectorSpec:
    spec = _spec_of(cls)
    if not isinstance(spec, _ConnectorSpec):
        raise TypeError(f"{cls!r} is not a @connector config class")
    return spec


def _check_value(f: _Field, v: Any) -> Any:
    if f.type == "tls":
        try:
            return parse_tls_value(v, f.name)
        except ManifestError as exc:
            raise ConfigError(f.name, exc.message) from None
    if f.type == "url":
        parts = urlsplit(v) if isinstance(v, str) else None
        if parts is None or parts.scheme != "https" or not parts.netloc:
            raise ConfigError(f.name, "expected an https:// URL")
        if "@" in parts.netloc:
            raise ConfigError(f.name, "a URL must not carry credentials; use a secret")
        if not _literal_host_ok("https://" + parts.netloc):
            raise ConfigError(f.name, "the URL's host must be name[:port] (port 1-65535)")
        return Url(v)
    if f.type == "enum":
        if v not in (f.values or ()):
            raise ConfigError(f.name, f"expected one of {', '.join(f.values or ())}")
        return v
    ok = {
        "string": isinstance(v, str),
        "integer": isinstance(v, int) and not isinstance(v, bool),
        "boolean": isinstance(v, bool),
    }.get(f.type or "", False)
    if not ok:
        raise ConfigError(f.name, f"expected a {f.type}")
    return v


def load_config(cls: type, values: Mapping[str, Any], secrets: Mapping[str, str]) -> Any:
    """The connector's config object from an integration's values and resolved secrets.

    `secrets` maps a secret field's name to the value the agent resolved (D-063). A secret in
    `values`, an unknown key, a missing required field or a value of the wrong type is refused.
    """
    _connector_spec(cls)
    fields = {f.name: f for f in _config_fields(cls)}
    for key in values:
        if key not in fields:
            raise ConfigError(key, "not a config field of this connector")
        if fields[key].type == "secret":
            raise ConfigError(key, "a secret's value comes from the agent, never the config")
    for key in secrets:
        if key not in fields or fields[key].type != "secret":
            raise ConfigError(key, "not a secret field of this connector")
    kwargs: dict[str, Any] = {}
    for name, f in fields.items():
        source = secrets if f.type == "secret" else values
        if name not in source or source[name] is None:
            if f.required:
                raise ConfigError(name, "required")
            if f.type == "tls" and f.default is None:
                kwargs[name] = Tls()
            continue
        if f.type == "secret":
            if not isinstance(source[name], str):
                raise ConfigError(name, "a resolved secret is a string")
            kwargs[name] = Secret(source[name])
        else:
            kwargs[name] = _check_value(f, source[name])
    return cls(**kwargs)


# --- the context -----------------------------------------------------------------------------


class Context:
    """What every handler receives: the config, the HTTP client, a redacting logger, and the
    job's idempotency key (so a connector can de-duplicate on the vendor's side)."""

    def __init__(
        self,
        config: Any,
        http: ConnectorHttp,
        log: logging.Logger,
        idempotency_key: str | None = None,
    ) -> None:
        cls = type(config)
        _connector_spec(cls)
        secrets: dict[str, str] = {}
        for f in _config_fields(cls):
            v = getattr(config, f.name)
            if f.type == "secret" and v is not None:
                if len(v) < MIN_SECRET_LEN:
                    raise ValueError(
                        f"secret {f.name!r} is shorter than {MIN_SECRET_LEN} characters: "
                        "too short to redact from logs safely"
                    )
                secrets[f.name] = str(v)
        self.redactor = redacting_filter(secrets)
        log.addFilter(self.redactor)
        self.config = config
        self.http = http
        self.log = log
        self.idempotency_key = idempotency_key

    @classmethod
    def create(
        cls,
        config: Any,
        *,
        log: logging.Logger | None = None,
        idempotency_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> "Context":
        """A context whose HTTP client is bound to the manifest's hosts, resolved from this
        config, and to its tls field (`verify` when the connector declares none)."""
        spec = _connector_spec(type(config))
        fields = _config_fields(type(config))
        values = {f.name: getattr(config, f.name) for f in fields if f.type == "url"}
        tls_fields = [f.name for f in fields if f.type == "tls"]
        if len(tls_fields) > 1:
            raise ValueError(f"a connector has at most one tls field, not {tls_fields}")
        tls = getattr(config, tls_fields[0]) if tls_fields else Tls()
        http = ConnectorHttp(resolve_hosts(spec.hosts, values), tls, transport=transport)
        if log is None:
            # A per-run logger, not registered with logging's manager: its redacting filter
            # dies with it instead of piling up on a process-wide logger across jobs. It
            # propagates (already redacted) to `auspex.connector.<id>` and up.
            log = logging.Logger(f"auspex.connector.{spec.id}.run")
            log.parent = logging.getLogger(f"auspex.connector.{spec.id}")
        return cls(config, http, log, idempotency_key=idempotency_key)
