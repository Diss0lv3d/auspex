"""The connector manifest v1: its types, its parser and `validate_manifest` (S32, D-064).

This module is the contract a customer writes a connector against. It is pure: stdlib only,
and it never imports the core. The vocabularies come from `auspex_sdk.vocab`.

The JSON shape (every key not marked optional is required; unknown keys are refused):

    {
      "schema_version": 1,                      # must be the integer 1
      "id": "ibm.qradar",                       # CONNECTOR_ID: dotted, lowercase
      "version": "1.2.0",                       # semver
      "name": "QRadar",
      "description": "...",                     # <= MAX_DESCRIPTION chars
      "sdk_version": "0.1.0",                   # optional, informational (default "")
      "config": [                               # optional, default []
        {"name": "base_url", "label": "QRadar URL",
         "type": "string|integer|boolean|url|enum|secret|tls",
         "required": false,                     # optional, default false
         "default": ...,                        # optional; never for a secret
         "values": ["a", "b"]}                  # enum only, non-empty
      ],
      "hosts": ["https://{base_url}", "https://api.vendor.example:8443"],   # optional
      "commands": {
        "test": {"handler": "pkg.module:function"},   # handler: required
        "fetch": {"handler": "pkg.module:function",   # optional command; handler required
                  "serves_many_clients": false}
      },
      "actions": [                              # optional, default []
        {"name": "close_offense", "description": "...",
         "risk": "read|write|destructive",
         "params": [{"name": "offense_id", "type": "string|integer|number|boolean",
                     "description": "...", "required": false,
                     "values": ["fp", "tp"]}],  # values: optional, string params only
         "dry_run": "pkg.module:function",      # a handler reference; required
         "undo": {"handler": "pkg.module:function", "restores": "...",
                  "cannot_restore": ["..."]},   # required for destructive; refused on read
         "observe": "pkg.module:function",      # optional, read-only
         "output": [{"name": "status", "type": "string|integer|number|boolean|string[]",
                     "required": false}],       # covers the envelope's `detail` only
         "targets": "offense_id"}               # optional: names one of the params
      ]
    }

Config values by type. `secret` is a NAME the agent resolves (D-063): the manifest can never
hold a value. `tls` has three forms at integration time (`parse_tls_value`): "verify", a pinned
`{"ca_pem": ...}`, or a pinned `{"cert_sha256": "<64 hex>"}`. There is no off, in any
spelling. In the manifest a `tls` field may declare only its default, and that is "verify".

Hosts. Each entry is `https://` plus a literal host (an optional `:port`, no wildcard, no
path) or exactly `{field}` naming a declared `url` config field. A `url` field no entry uses
is refused. Handler references are `module:function` strings; the build (`auspex_sdk.build`)
checks that they exist and take the declared parameters.

`validate_manifest` raises on the FIRST violation, checking in this order: schema_version, id,
version, name and description, config (in order), hosts, command handlers, actions (in
order), then url fields no host uses. `ManifestError.rule` is one of `RULES`; `.path` is a
dotted/indexed path such as `actions[0].undo`.
"""

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from auspex_sdk.vocab import CONNECTOR_ID, PARAM_TYPES, PLATFORM_KEYWORDS, RISKS, WIRE_NAME

SCHEMA_VERSION = 1
MAX_DESCRIPTION = 2000  # chars; every description and label
MAX_NAME = 64  # chars; action, param, output and config-field names
MAX_RAW_BYTES = 64 * 1024  # a fetch item's `raw` (checked by the runtime, not by manifests)

CONFIG_TYPES: tuple[str, ...] = ("string", "integer", "boolean", "url", "enum", "secret", "tls")
OUTPUT_TYPES: tuple[str, ...] = (*PARAM_TYPES, "string[]")

# Every rule a ManifestError can carry. `unknown_key` and `bad_type` come from the parser
# (and from shape checks in `validate_manifest`); `undo_on_read` is the one rule beyond the
# spec's list, because an undo on a read action is as meaningless as it is misleading.
RULES: tuple[str, ...] = (
    "destructive_without_undo",
    "undo_on_read",
    "undeclared_host",
    "tls_off",
    "missing_dry_run",
    "shared_fetch_without_routing_key",
    "bad_name",
    "unknown_type",
    "secret_with_default",
    "schema_version",
    "duplicate_name",
    "http_url_default",
    "description_too_long",
    "unknown_key",
    "bad_type",
)

_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?"
)
_HANDLER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*")
_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
_LITERAL_HOST = re.compile(rf"https://{_LABEL}(\.{_LABEL})*(?::(?P<port>[0-9]{{1,5}}))?")
_PLACEHOLDER_HOST = re.compile(r"https://\{([^{}/:]*)\}")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_PEM_CERT = "-----BEGIN CERTIFICATE-----"
_TLS_OFF_WORDS = frozenset({"off", "none", "insecure", "false", "no", "disable", "disabled"})


class ManifestError(ValueError):
    """A manifest violates the contract: `.rule` says which rule, `.path` says where."""

    def __init__(self, rule: str, path: str, message: str) -> None:
        self.rule = rule
        self.path = path
        self.message = message
        super().__init__(f"{rule} at {path or '<manifest>'}: {message}")


@dataclass(frozen=True)
class Tls:
    """A `tls` config value at integration time. Exactly one form; there is no off."""

    ca_pem: str | None = None  # the chain must lead to this CA; the hostname is checked
    cert_sha256: str | None = None  # the leaf's DER hash; replaces chain and hostname checks

    # neither set means "verify": system trust, chain and hostname checked

    def __post_init__(self) -> None:
        # The HTTP client (auspex_sdk.http) acts on a Tls value as given, so one built in code
        # rather than by parse_tls_value must still hold exactly one well-formed form (S32,
        # carried from Task 2's review). The messages never echo the value.
        if self.ca_pem is not None and self.cert_sha256 is not None:
            raise ManifestError("bad_type", "tls", "a tls value is a CA PEM or a pin, not both")
        if self.ca_pem is not None and (
            not isinstance(self.ca_pem, str) or _PEM_CERT not in self.ca_pem
        ):
            raise ManifestError("bad_type", "tls", f"ca_pem must contain {_PEM_CERT}")
        if self.cert_sha256 is not None and (
            not isinstance(self.cert_sha256, str) or not _SHA256.fullmatch(self.cert_sha256)
        ):
            raise ManifestError("bad_type", "tls", "cert_sha256 must be 64 hex characters")


@dataclass(frozen=True)
class ConfigField:
    name: str
    label: str
    type: str
    required: bool = False
    default: Any = None
    values: tuple[str, ...] | None = None  # enum only


@dataclass(frozen=True)
class Param:
    name: str
    type: str
    description: str
    required: bool = False
    values: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Undo:
    handler: str
    restores: str
    cannot_restore: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutputField:
    name: str
    type: str
    required: bool = False


@dataclass(frozen=True)
class Action:
    name: str
    description: str
    risk: str
    params: tuple[Param, ...] = ()
    dry_run: str = ""  # empty means "not declared": validate_manifest refuses it
    undo: Undo | None = None
    observe: str | None = None
    output: tuple[OutputField, ...] = ()
    targets: str | None = None


@dataclass(frozen=True)
class Fetch:
    serves_many_clients: bool = False
    handler: str = ""  # empty means "not declared": validate_manifest refuses it


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    id: str
    version: str
    name: str
    description: str
    sdk_version: str = ""
    config: tuple[ConfigField, ...] = ()
    hosts: tuple[str, ...] = ()
    fetch: Fetch | None = None
    actions: tuple[Action, ...] = ()
    test_handler: str = ""  # commands.test.handler; empty is refused by validate_manifest


# --- parsing ------------------------------------------------------------------------------


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _obj(data: Any, path: str, keys: set[str], required: set[str]) -> dict:
    if not isinstance(data, dict):
        raise ManifestError("bad_type", path, "expected a JSON object")
    for k in data:
        if k not in keys:
            raise ManifestError("unknown_key", _join(path, str(k)), "not a manifest key")
    for k in sorted(required):
        if k not in data:
            raise ManifestError("bad_type", _join(path, k), "required key is missing")
    return data


def _str(data: dict, key: str, path: str, default: str | None = None) -> str:
    v = data.get(key, default)
    if not isinstance(v, str):
        raise ManifestError("bad_type", _join(path, key), "expected a string")
    return v


def _bool(data: dict, key: str, path: str, default: bool = False) -> bool:
    v = data.get(key, default)
    if not isinstance(v, bool):
        raise ManifestError("bad_type", _join(path, key), "expected true or false")
    return v


def _list(data: dict, key: str, path: str) -> list:
    v = data.get(key, [])
    if not isinstance(v, list):
        raise ManifestError("bad_type", _join(path, key), "expected a list")
    return v


def _strs(v: Any, path: str) -> tuple[str, ...]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ManifestError("bad_type", path, "expected a list of strings")
    return tuple(v)


def _opt_str(data: dict, key: str, path: str) -> str | None:
    return _str(data, key, path) if key in data else None


def _parse_config(data: Any, path: str) -> ConfigField:
    d = _obj(
        data,
        path,
        {"name", "label", "type", "required", "default", "values"},
        {"name", "label", "type"},
    )
    return ConfigField(
        name=_str(d, "name", path),
        label=_str(d, "label", path),
        type=_str(d, "type", path),
        required=_bool(d, "required", path),
        default=d.get("default"),
        values=_strs(d["values"], _join(path, "values")) if "values" in d else None,
    )


def _parse_param(data: Any, path: str) -> Param:
    d = _obj(
        data,
        path,
        {"name", "type", "description", "required", "values"},
        {"name", "type", "description"},
    )
    return Param(
        name=_str(d, "name", path),
        type=_str(d, "type", path),
        description=_str(d, "description", path),
        required=_bool(d, "required", path),
        values=_strs(d["values"], _join(path, "values")) if "values" in d else None,
    )


def _parse_undo(data: Any, path: str) -> Undo:
    d = _obj(data, path, {"handler", "restores", "cannot_restore"}, {"handler", "restores"})
    cannot = (
        _strs(d["cannot_restore"], _join(path, "cannot_restore")) if "cannot_restore" in d else ()
    )
    return Undo(
        handler=_str(d, "handler", path), restores=_str(d, "restores", path), cannot_restore=cannot
    )


def _parse_output(data: Any, path: str) -> OutputField:
    d = _obj(data, path, {"name", "type", "required"}, {"name", "type"})
    return OutputField(
        name=_str(d, "name", path), type=_str(d, "type", path), required=_bool(d, "required", path)
    )


def _parse_action(data: Any, path: str) -> Action:
    d = _obj(
        data,
        path,
        {
            "name",
            "description",
            "risk",
            "params",
            "dry_run",
            "undo",
            "observe",
            "output",
            "targets",
        },
        {"name", "description", "risk"},
    )
    return Action(
        name=_str(d, "name", path),
        description=_str(d, "description", path),
        risk=_str(d, "risk", path),
        params=tuple(
            _parse_param(p, f"{path}.params[{i}]") for i, p in enumerate(_list(d, "params", path))
        ),
        dry_run=_str(d, "dry_run", path, default=""),
        undo=_parse_undo(d["undo"], _join(path, "undo")) if "undo" in d else None,
        observe=_opt_str(d, "observe", path),
        output=tuple(
            _parse_output(o, f"{path}.output[{i}]") for i, o in enumerate(_list(d, "output", path))
        ),
        targets=_opt_str(d, "targets", path),
    )


def parse_manifest(data: dict) -> Manifest:
    """Build a Manifest from decoded JSON. Refuses unknown keys and wrong JSON types.

    Structure only: the rules (`validate_manifest`) are separate, so a manifest that parses
    can still be refused with an exact reason.
    """
    d = _obj(
        data,
        "",
        {
            "schema_version",
            "id",
            "version",
            "name",
            "description",
            "sdk_version",
            "config",
            "hosts",
            "commands",
            "actions",
        },
        {"schema_version", "id", "version", "name", "description", "commands"},
    )
    sv = d["schema_version"]
    if isinstance(sv, bool) or not isinstance(sv, int):
        raise ManifestError("bad_type", "schema_version", "expected an integer")
    cmds = _obj(d["commands"], "commands", {"test", "fetch"}, {"test"})
    t = _obj(cmds["test"], "commands.test", {"handler"}, {"handler"})
    fetch = None
    if "fetch" in cmds:
        f = _obj(
            cmds["fetch"], "commands.fetch", {"serves_many_clients", "handler"}, {"handler"}
        )
        fetch = Fetch(
            serves_many_clients=_bool(f, "serves_many_clients", "commands.fetch"),
            handler=_str(f, "handler", "commands.fetch"),
        )
    return Manifest(
        schema_version=sv,
        id=_str(d, "id", ""),
        version=_str(d, "version", ""),
        name=_str(d, "name", ""),
        description=_str(d, "description", ""),
        sdk_version=_str(d, "sdk_version", "", default=""),
        config=tuple(
            _parse_config(c, f"config[{i}]") for i, c in enumerate(_list(d, "config", ""))
        ),
        hosts=_strs(d["hosts"], "hosts") if "hosts" in d else (),
        fetch=fetch,
        actions=tuple(
            _parse_action(a, f"actions[{i}]") for i, a in enumerate(_list(d, "actions", ""))
        ),
        test_handler=_str(t, "handler", "commands.test"),
    )


# --- TLS ------------------------------------------------------------------------------------


def _is_tls_off(v: Any) -> bool:
    if v is False:
        return True
    if isinstance(v, str):
        return v.strip().lower() in _TLS_OFF_WORDS
    if isinstance(v, dict) and "verify" in v:
        flag = v["verify"]
        return flag is False or flag is None or flag == 0 or _is_tls_off(flag)
    return False


def parse_tls_value(v: Any, path: str = "tls") -> Tls:
    """Read a `tls` value: "verify", {"ca_pem": ...} or {"cert_sha256": ...}. Never off."""
    if _is_tls_off(v):
        raise ManifestError(
            "tls_off",
            path,
            "TLS verification cannot be turned off; use "
            "'verify', a pinned CA PEM or a pinned certificate SHA-256",
        )
    if v == "verify":
        return Tls()
    if isinstance(v, dict) and len(v) == 1:
        if isinstance(v.get("ca_pem"), str) and _PEM_CERT in v["ca_pem"]:
            return Tls(ca_pem=v["ca_pem"])
        pin = v.get("cert_sha256")
        if isinstance(pin, str) and _SHA256.fullmatch(pin):
            return Tls(cert_sha256=pin.lower())
    raise ManifestError(
        "bad_type", path, "expected 'verify', {'ca_pem': ...} or {'cert_sha256': '<64 hex>'}"
    )


# --- the rules ------------------------------------------------------------------------------


def _literal_host_ok(entry: str) -> bool:
    """`https://host[:port]` as a literal hosts entry may be: no IPv6 literal, port 1-65535."""
    lit = _LITERAL_HOST.fullmatch(entry)
    return bool(lit) and (lit.group("port") is None or 1 <= int(lit.group("port")) <= 65535)


def _check_name(name: str, path: str, *, keyword: bool = False) -> None:
    if len(name) > MAX_NAME or not WIRE_NAME.fullmatch(name):
        raise ManifestError(
            "bad_name",
            path,
            f"{name!r} is not a wire-safe name "
            f"(letters, digits, underscore; at most {MAX_NAME} chars)",
        )
    if keyword and name in PLATFORM_KEYWORDS:
        raise ManifestError(
            "bad_name", path, f"{name!r} is reserved: the platform passes it itself"
        )


def _check_text(text: str, path: str, *, required: bool = True) -> None:
    if len(text) > MAX_DESCRIPTION:
        raise ManifestError("description_too_long", path, f"at most {MAX_DESCRIPTION} characters")
    if required and not text.strip():
        raise ManifestError("bad_type", path, "must not be empty")


def _check_handler(ref: str, path: str) -> None:
    if not _HANDLER.fullmatch(ref):
        raise ManifestError("bad_type", path, f"{ref!r} is not a 'module:function' reference")


def _check_unique(names: list[str], paths: list[str]) -> None:
    seen: set[str] = set()
    for n, p in zip(names, paths, strict=True):
        if n in seen:
            raise ManifestError("duplicate_name", p, f"{n!r} is declared twice")
        seen.add(n)


def _check_default(f: ConfigField, path: str) -> None:
    d = f.default
    p = _join(path, "default")
    if f.type == "secret":
        if d is not None:
            raise ManifestError(
                "secret_with_default", p, "a secret is a name the agent resolves; it has no default"
            )
        return
    if f.type == "tls":
        if d is None:
            return
        if _is_tls_off(d):
            raise ManifestError("tls_off", p, "TLS verification cannot be turned off")
        if d != "verify":
            raise ManifestError("bad_type", p, "a tls field may declare only the default 'verify'")
        return
    if d is None:
        return
    if f.type == "string":
        ok = isinstance(d, str)
    elif f.type == "integer":
        ok = isinstance(d, int) and not isinstance(d, bool)
    elif f.type == "boolean":
        ok = isinstance(d, bool)
    elif f.type == "enum":
        ok = isinstance(d, str) and d in (f.values or ())
    else:  # url
        if not isinstance(d, str):
            raise ManifestError("bad_type", p, "expected a string")
        parts = urlsplit(d)
        if parts.scheme != "https" or not parts.netloc:
            raise ManifestError("http_url_default", p, "a url default must be an https:// URL")
        if "@" in parts.netloc:
            raise ManifestError(
                "secret_with_default",
                p,
                "a url default must not carry credentials; a secret is a name the agent resolves",
            )
        if not _literal_host_ok("https://" + parts.netloc):
            raise ManifestError(
                "http_url_default",
                p,
                "a url default's host must be a literal name[:port] (port 1-65535), as in hosts",
            )
        return
    if not ok:
        raise ManifestError("bad_type", p, f"does not match the field's type {f.type!r}")


def _check_config(m: Manifest) -> None:
    for i, f in enumerate(m.config):
        path = f"config[{i}]"
        _check_name(f.name, f"{path}.name")
        _check_text(f.label, f"{path}.label")
        if f.type not in CONFIG_TYPES:
            raise ManifestError(
                "unknown_type",
                f"{path}.type",
                f"{f.type!r} is not one of {', '.join(CONFIG_TYPES)}",
            )
        _check_unique(
            [c.name for c in m.config[: i + 1]], [f"config[{j}].name" for j in range(i + 1)]
        )
        if f.type == "enum":
            if not f.values or len(set(f.values)) != len(f.values):
                raise ManifestError(
                    "bad_type",
                    f"{path}.values",
                    "an enum needs a non-empty list of distinct values",
                )
        elif f.values is not None:
            raise ManifestError("bad_type", f"{path}.values", "only an enum declares values")
        _check_default(f, path)


def _check_hosts(m: Manifest) -> None:
    fields = {f.name: f for f in m.config}
    used: set[str] = set()
    for i, h in enumerate(m.hosts):
        path = f"hosts[{i}]"
        ph = _PLACEHOLDER_HOST.fullmatch(h)
        if ph:
            f = fields.get(ph.group(1))
            if f is None or f.type != "url":
                raise ManifestError(
                    "undeclared_host", path, f"{{{ph.group(1)}}} names no declared url config field"
                )
            used.add(f.name)
        else:
            if _literal_host_ok(h):
                continue
            raise ManifestError(
                "undeclared_host",
                path,
                f"{h!r} is not https://host[:port] or https://{{field}}; no wildcards, no paths",
            )
    for i, f in enumerate(m.config):
        if f.type == "url" and f.name not in used:
            raise ManifestError(
                "undeclared_host", f"config[{i}]", f"url field {f.name!r} is used by no host entry"
            )


def _check_action(a: Action, path: str) -> None:
    _check_name(a.name, f"{path}.name", keyword=True)
    _check_text(a.description, f"{path}.description")
    if a.risk not in RISKS:
        raise ManifestError(
            "bad_type", f"{path}.risk", f"{a.risk!r} is not one of {', '.join(RISKS)}"
        )
    for j, p in enumerate(a.params):
        pp = f"{path}.params[{j}]"
        _check_name(p.name, f"{pp}.name", keyword=True)
        if p.type not in PARAM_TYPES:
            raise ManifestError(
                "unknown_type", f"{pp}.type", f"{p.type!r} is not one of {', '.join(PARAM_TYPES)}"
            )
        _check_unique(
            [q.name for q in a.params[: j + 1]], [f"{path}.params[{k}].name" for k in range(j + 1)]
        )
        _check_text(p.description, f"{pp}.description")
        if p.values is not None and (
            p.type != "string" or not p.values or len(set(p.values)) != len(p.values)
        ):
            raise ManifestError(
                "bad_type",
                f"{pp}.values",
                "values are a non-empty list of distinct strings, on a string param",
            )
    if not a.dry_run:
        raise ManifestError(
            "missing_dry_run",
            f"{path}.dry_run",
            "every action declares a dry run: what it would do, changing nothing",
        )
    _check_handler(a.dry_run, f"{path}.dry_run")
    if a.risk == "destructive" and a.undo is None:
        raise ManifestError(
            "destructive_without_undo",
            f"{path}.undo",
            "a destructive action declares its undo, restores and cannot_restore",
        )
    if a.risk == "read" and a.undo is not None:
        raise ManifestError("undo_on_read", f"{path}.undo", "a read action changes nothing to undo")
    if a.undo is not None:
        _check_handler(a.undo.handler, f"{path}.undo.handler")
        _check_text(a.undo.restores, f"{path}.undo.restores")
        for k, c in enumerate(a.undo.cannot_restore):
            _check_text(c, f"{path}.undo.cannot_restore[{k}]")
    if a.observe is not None:
        _check_handler(a.observe, f"{path}.observe")
    for j, o in enumerate(a.output):
        op = f"{path}.output[{j}]"
        _check_name(o.name, f"{op}.name")
        if o.type not in OUTPUT_TYPES:
            raise ManifestError(
                "unknown_type", f"{op}.type", f"{o.type!r} is not one of {', '.join(OUTPUT_TYPES)}"
            )
        _check_unique(
            [q.name for q in a.output[: j + 1]], [f"{path}.output[{k}].name" for k in range(j + 1)]
        )
    if a.targets is not None and a.targets not in {p.name for p in a.params}:
        raise ManifestError(
            "bad_name", f"{path}.targets", f"{a.targets!r} names none of the action's params"
        )


def validate_manifest(m: Manifest) -> None:
    """Raise ManifestError on the first rule the manifest breaks, in a fixed order."""
    if isinstance(m.schema_version, bool) or m.schema_version != SCHEMA_VERSION:
        raise ManifestError(
            "schema_version",
            "schema_version",
            f"this SDK reads schema_version {SCHEMA_VERSION}, got {m.schema_version!r}",
        )
    if not CONNECTOR_ID.fullmatch(m.id):
        raise ManifestError(
            "bad_name", "id", f"{m.id!r} is not a dotted lowercase id like ibm.qradar"
        )
    if not _SEMVER.fullmatch(m.version):
        raise ManifestError("bad_name", "version", f"{m.version!r} is not a semver like 1.2.0")
    _check_text(m.name, "name")
    _check_text(m.description, "description")
    _check_config(m)
    _check_hosts(m)
    _check_handler(m.test_handler, "commands.test.handler")
    if m.fetch is not None:
        _check_handler(m.fetch.handler, "commands.fetch.handler")
    _check_unique(
        [a.name for a in m.actions], [f"actions[{i}].name" for i in range(len(m.actions))]
    )
    for i, a in enumerate(m.actions):
        _check_action(a, f"actions[{i}]")


def check_fetch_item(m: Manifest, item: dict) -> None:
    """A manifest that serves many clients needs a routing key on every fetched item.

    The manifest cannot show this; items exist only at runtime, so `collect` (Task 4) calls this.
    """
    if not isinstance(item, dict):
        raise ManifestError("bad_type", "", "a fetch item is a JSON object")
    raw = item.get("raw")
    if raw is not None:
        if not isinstance(raw, str):
            raise ManifestError("bad_type", "raw", "raw is a string")
        if len(raw.encode("utf-8")) > MAX_RAW_BYTES:
            raise ManifestError(
                "description_too_long", "raw", f"raw is at most {MAX_RAW_BYTES} bytes of UTF-8"
            )
    if m.fetch is not None and m.fetch.serves_many_clients:
        rk = item.get("routing_key")
        if not isinstance(rk, str) or not rk:
            raise ManifestError(
                "shared_fetch_without_routing_key",
                "routing_key",
                "this connector serves many clients; every item needs a routing_key",
            )


# --- serialising ----------------------------------------------------------------------------


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def manifest_to_dict(m: Manifest) -> dict:
    commands: dict = {"test": {"handler": m.test_handler}}
    if m.fetch is not None:
        commands["fetch"] = {
            "serves_many_clients": m.fetch.serves_many_clients,
            "handler": m.fetch.handler,
        }
    return {
        "schema_version": m.schema_version,
        "id": m.id,
        "version": m.version,
        "name": m.name,
        "description": m.description,
        "sdk_version": m.sdk_version,
        "config": [
            _drop_none(
                {
                    "name": f.name,
                    "label": f.label,
                    "type": f.type,
                    "required": f.required,
                    "default": f.default,
                    "values": list(f.values) if f.values is not None else None,
                }
            )
            for f in m.config
        ],
        "hosts": list(m.hosts),
        "commands": commands,
        "actions": [
            _drop_none(
                {
                    "name": a.name,
                    "description": a.description,
                    "risk": a.risk,
                    "params": [
                        _drop_none(
                            {
                                "name": p.name,
                                "type": p.type,
                                "description": p.description,
                                "required": p.required,
                                "values": list(p.values) if p.values is not None else None,
                            }
                        )
                        for p in a.params
                    ],
                    "dry_run": a.dry_run,
                    "undo": None
                    if a.undo is None
                    else {
                        "handler": a.undo.handler,
                        "restores": a.undo.restores,
                        "cannot_restore": list(a.undo.cannot_restore),
                    },
                    "observe": a.observe,
                    "output": [
                        {"name": o.name, "type": o.type, "required": o.required} for o in a.output
                    ],
                    "targets": a.targets,
                }
            )
            for a in m.actions
        ],
    }


def manifest_to_json(m: Manifest) -> bytes:
    """Canonical bytes: sorted keys, compact, UTF-8, trailing newline (it is hashed, S32)."""
    text = json.dumps(
        manifest_to_dict(m), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return (text + "\n").encode("utf-8")
