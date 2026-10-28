"""The connector runtime: decorators and `collect`, the typed context, log redaction and safe
results (S32, task 4)."""

import base64
import importlib
import io
import logging
import math
import sys
import textwrap
import uuid
from urllib.parse import quote

import httpx
import pytest
from auspex_sdk.http import ConnectorHttp
from auspex_sdk.manifest import (
    ManifestError,
    Tls,
    manifest_to_dict,
    parse_manifest,
    validate_manifest,
)
from auspex_sdk.redact import redacting_filter
from auspex_sdk.results import ResultError, encode_result
from auspex_sdk.runtime import ConfigError, Context, Secret, collect, load_config

SAMPLE = '''
"""A sample Python-first connector."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from auspex_sdk.manifest import OutputField, Undo
from auspex_sdk.runtime import Context, Secret, Tls, Url, action, command, connector


@connector(
    id="example.sample",
    version="1.0.0",
    name="Sample",
    description="A sample connector.",
    hosts=("https://{base_url}",),
)
@dataclass(frozen=True)
class Config:
    base_url: Annotated[Url, "Service URL"]
    api_token: Annotated[Secret, "API token"]
    tls: Annotated[Tls, "TLS"] = Tls()
    mode: Literal["fast", "full"] = "fast"
    page: int = 50


@command("test")
def check(ctx: Context) -> dict:
    return {"ok": True, "detail": "reachable"}


@command("fetch")
def pull(ctx: Context, cursor: str | None, limit: int) -> dict:
    return {"items": [], "next_cursor": None}


def close_dry(ctx: Context, alert_id: str, reason: str = "fp") -> dict:
    return {"would": "close", "affects": [alert_id], "reversible": True, "detail": {}}


def reopen(ctx: Context, alert_id: str, reason: str = "fp") -> dict:
    return {"would": "reopen", "affects": [alert_id], "reversible": True, "detail": {}}


def close_observe(ctx: Context, alert_id: str, reason: str = "fp") -> dict:
    return {"landed": 1}


@action(
    "close_alert",
    risk="write",
    dry_run=close_dry,
    undo=Undo(handler=reopen, restores="The alert status.", cannot_restore=("notes",)),
    observe=close_observe,
    targets="alert_id",
    output=(OutputField(name="status", type="string", required=True),),
)
def close_alert(
    ctx: Context,
    alert_id: Annotated[str, "The alert to close."],
    reason: Annotated[Literal["fp", "tp"], "Why."] = "fp",
) -> dict:
    """Close an alert."""
    return {"would": "closed", "affects": [alert_id], "reversible": True, "detail": {}}
'''


@pytest.fixture
def load(tmp_path, monkeypatch):
    """Write source as a fresh module on sys.path and import it."""
    monkeypatch.syspath_prepend(str(tmp_path))

    def _load(source: str):
        name = f"conn_{uuid.uuid4().hex[:8]}"
        (tmp_path / f"{name}.py").write_text(textwrap.dedent(source))
        importlib.invalidate_caches()
        return importlib.import_module(name)

    yield _load


def expected(module_name: str) -> dict:
    return {
        "schema_version": 1,
        "id": "example.sample",
        "version": "1.0.0",
        "name": "Sample",
        "description": "A sample connector.",
        "sdk_version": "",
        "config": [
            {"name": "base_url", "label": "Service URL", "type": "url", "required": True},
            {"name": "api_token", "label": "API token", "type": "secret", "required": True},
            {"name": "tls", "label": "TLS", "type": "tls", "required": False, "default": "verify"},
            {
                "name": "mode",
                "label": "mode",
                "type": "enum",
                "required": False,
                "default": "fast",
                "values": ["fast", "full"],
            },
            {"name": "page", "label": "page", "type": "integer", "required": False, "default": 50},
        ],
        "hosts": ["https://{base_url}"],
        "commands": {
            "test": {"handler": f"{module_name}:check"},
            "fetch": {"serves_many_clients": False, "handler": f"{module_name}:pull"},
        },
        "actions": [
            {
                "name": "close_alert",
                "description": "Close an alert.",
                "risk": "write",
                "params": [
                    {
                        "name": "alert_id",
                        "type": "string",
                        "description": "The alert to close.",
                        "required": True,
                    },
                    {
                        "name": "reason",
                        "type": "string",
                        "description": "Why.",
                        "required": False,
                        "values": ["fp", "tp"],
                    },
                ],
                "execute": f"{module_name}:close_alert",
                "dry_run": f"{module_name}:close_dry",
                "undo": {
                    "handler": f"{module_name}:reopen",
                    "restores": "The alert status.",
                    "cannot_restore": ["notes"],
                },
                "observe": f"{module_name}:close_observe",
                "output": [{"name": "status", "type": "string", "required": True}],
                "targets": "alert_id",
            }
        ],
    }


# --- collect ---------------------------------------------------------------------------------


def test_collect_builds_the_manifest_from_the_decorators(load):
    mod = load(SAMPLE)
    m = collect(mod)
    validate_manifest(m)
    assert manifest_to_dict(m) == manifest_to_dict(parse_manifest(expected(mod.__name__)))


def test_collect_refuses_a_module_without_a_connector(load):
    mod = load("from auspex_sdk.runtime import command\n@command('test')\ndef t(ctx): ...\n")
    with pytest.raises(ManifestError, match="@connector"):
        collect(mod)


def test_collect_refuses_a_connector_without_a_test_command(load):
    mod = load(SAMPLE.replace('@command("test")\n', ""))
    with pytest.raises(ManifestError) as ei:
        collect(mod)
    assert ei.value.path == "commands.test"


def test_collect_runs_validate_manifest(load):
    # destructive with no undo: the manifest rule, with its path, comes out of collect
    src = SAMPLE.replace('risk="write"', 'risk="destructive"').replace(
        'undo=Undo(handler=reopen, restores="The alert status.", cannot_restore=("notes",)),', ""
    )
    with pytest.raises(ManifestError) as ei:
        collect(load(src))
    assert (ei.value.rule, ei.value.path) == ("destructive_without_undo", "actions[0].undo")


def test_collect_refuses_a_param_without_a_wire_type(load):
    src = SAMPLE.replace(
        'alert_id: Annotated[str, "The alert to close."],',
        'alert_id: Annotated[list, "The alert to close."],',
    )
    with pytest.raises(ManifestError) as ei:
        collect(load(src))
    assert (ei.value.rule, ei.value.path) == ("unknown_type", "actions[0].params[0].type")


def test_collect_refuses_a_fetch_with_the_wrong_parameters(load):
    src = SAMPLE.replace("cursor: str | None, limit: int", "page: int")
    with pytest.raises(ManifestError) as ei:
        collect(load(src))
    assert ei.value.path == "commands.fetch"


def test_collect_refuses_a_handler_that_is_not_module_level(load):
    src = SAMPLE.replace("dry_run=close_dry,", "dry_run=lambda ctx, alert_id, reason='fp': {},")
    with pytest.raises(ManifestError) as ei:
        collect(load(src))
    assert ei.value.path == "actions[0].dry_run"


def test_collect_refuses_serves_many_clients_without_fetch(load):
    src = SAMPLE.replace(
        'hosts=("https://{base_url}",),',
        'hosts=("https://{base_url}",), serves_many_clients=True,',
    ).replace('@command("fetch")\n', "")
    with pytest.raises(ManifestError) as ei:
        collect(load(src))
    assert ei.value.path == "commands.fetch"


# --- config and the context -----------------------------------------------------------------

TOKEN = "tok-placeholder-0123456789"  # noqa: S105 -- a placeholder, not a credential


def sample_config(mod, **values):
    base = {"base_url": "https://svc.example:9443/api"}
    return load_config(mod.Config, {**base, **values}, {"api_token": TOKEN})


def test_load_config_types_values_and_resolves_secrets(load):
    mod = load(SAMPLE)
    cfg = sample_config(mod, tls={"cert_sha256": "ab" * 32})
    assert cfg.api_token == TOKEN and isinstance(cfg.api_token, Secret)
    assert TOKEN not in repr(cfg)  # a config's repr never shows a secret
    assert cfg.tls == Tls(cert_sha256="ab" * 32)
    assert cfg.mode == "fast" and cfg.page == 50
    assert sample_config(mod).tls == Tls()


@pytest.mark.parametrize(
    ("values", "secrets", "field"),
    [
        ({"base_url": "https://a.example", "api_token": "x" * 8}, {}, "api_token"),  # in config
        ({"base_url": "http://a.example"}, {"api_token": TOKEN}, "base_url"),
        ({"base_url": "https://user:pw@a.example"}, {"api_token": TOKEN}, "base_url"),
        ({}, {"api_token": TOKEN}, "base_url"),  # required
        ({"base_url": "https://a.example"}, {}, "api_token"),  # required secret
        ({"base_url": "https://a.example", "tls": "off"}, {"api_token": TOKEN}, "tls"),
        ({"base_url": "https://a.example", "mode": "slow"}, {"api_token": TOKEN}, "mode"),
        ({"base_url": "https://a.example", "page": "50"}, {"api_token": TOKEN}, "page"),
        ({"base_url": "https://a.example", "page": True}, {"api_token": TOKEN}, "page"),
        ({"base_url": "https://a.example", "other": 1}, {"api_token": TOKEN}, "other"),
        ({"base_url": "https://a.example"}, {"api_token": TOKEN, "nope": TOKEN}, "nope"),
    ],
)
def test_load_config_refuses(load, values, secrets, field):
    mod = load(SAMPLE)
    with pytest.raises(ConfigError) as ei:
        load_config(mod.Config, values, secrets)
    assert ei.value.field == field
    assert TOKEN not in str(ei.value) and "x" * 8 not in str(ei.value)


def test_the_context_passes_the_idempotency_key_through(load):
    mod = load(SAMPLE)
    cfg = sample_config(mod)
    http = ConnectorHttp(["https://svc.example:9443"], Tls(), transport=httpx.MockTransport(None))
    ctx = Context(cfg, http, logging.getLogger("t.idem"), idempotency_key="op-123")
    assert ctx.idempotency_key == "op-123"
    assert ctx.config is cfg and ctx.http is http
    assert Context(cfg, http, logging.getLogger("t.idem2")).idempotency_key is None


def test_context_create_binds_http_to_the_resolved_hosts_and_tls(load):
    mod = load(SAMPLE)
    cfg = sample_config(mod, tls={"cert_sha256": "cd" * 32})
    ctx = Context.create(cfg, idempotency_key="k", transport=httpx.MockTransport(None))
    assert ctx.http.allowed_hosts == frozenset({("svc.example", 9443)})
    assert ctx.http.tls == Tls(cert_sha256="cd" * 32)


def test_context_create_logs_redacted_to_the_connector_logger(load):
    mod = load(SAMPLE)
    parent = logging.getLogger("auspex.connector.example.sample")
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    parent.addHandler(handler)
    try:
        ctx = Context.create(sample_config(mod), transport=httpx.MockTransport(None))
        ctx.log.warning("token %s", TOKEN)
    finally:
        parent.removeHandler(handler)
    assert out.getvalue().strip() == "token [secret:api_token]"
    assert not parent.filters  # the filter lives on the per-run logger, not the shared one


def test_a_secret_too_short_to_redact_is_refused_at_context_construction(load):
    mod = load(SAMPLE)
    cfg = load_config(mod.Config, {"base_url": "https://a.example"}, {"api_token": "abc"})
    http = ConnectorHttp(["https://a.example"], Tls())
    with pytest.raises(ValueError, match="api_token") as ei:
        Context(cfg, http, logging.getLogger("t.short"))
    assert "abc" not in str(ei.value)


# --- redaction (Review Focus 4) -------------------------------------------------------------


def capture(
    secrets: dict[str, str], fmt: str = "%(message)s"
) -> tuple[logging.Logger, io.StringIO]:
    log = logging.getLogger(f"t.redact.{uuid.uuid4().hex}")
    log.propagate = False
    log.setLevel(logging.DEBUG)
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setFormatter(logging.Formatter(fmt))
    log.addHandler(handler)
    log.addFilter(redacting_filter(secrets))
    return log, out


def test_secrets_are_redacted_in_the_message_and_its_args():
    log, out = capture({"api_token": TOKEN})
    log.info(f"token is {TOKEN}")
    log.info("token is %s and %r", TOKEN, {"t": TOKEN})
    text = out.getvalue()
    assert TOKEN not in text
    assert text.count("[secret:api_token]") == 3


def test_secrets_are_redacted_in_exception_text():
    log, out = capture({"api_token": TOKEN})
    try:
        raise RuntimeError(f"auth failed for {TOKEN}")
    except RuntimeError:
        log.exception("call failed")
    text = out.getvalue()
    assert TOKEN not in text
    assert "RuntimeError: auth failed for [secret:api_token]" in text


def test_secrets_are_redacted_in_extra_fields():
    log, out = capture({"api_token": TOKEN}, "%(message)s|%(detail)s|%(payload)s")
    log.info("x", extra={"detail": f"Bearer {TOKEN}", "payload": {"headers": {"a": TOKEN}}})
    text = out.getvalue()
    assert TOKEN not in text
    assert text.count("[secret:api_token]") == 2


def test_encoded_forms_of_a_secret_are_redacted():
    secret = "p@ss w/rd+1"  # noqa: S105 -- a placeholder
    log, out = capture({"password": secret})
    log.info("q=%s", quote(secret, safe=""))
    log.info("b=%s", base64.b64encode(secret.encode()).decode())
    log.info("r=%r", secret)
    text = out.getvalue()
    assert quote(secret, safe="") not in text and secret not in text
    assert base64.b64encode(secret.encode()).decode() not in text
    assert text.count("[secret:password]") == 3


def test_a_secret_in_a_url_path_is_redacted_as_httpx_writes_it():
    """httpx encodes a path only partly (spaces and non-ASCII, not `/` or `;`), so an
    error naming the URL carries a form neither raw nor fully quoted (S32 final review)."""
    secret = "a b/\u00e9;cd"  # noqa: S105 -- a placeholder
    url = str(httpx.URL(f"https://siem.example/v1/{secret}/x"))
    log, out = capture({"path_key": secret})
    log.info("GET %s failed", url)
    text = out.getvalue()
    assert "[secret:path_key]" in text
    assert "%C3%A9;cd" not in text


def test_a_short_secret_is_refused_by_the_filter():
    with pytest.raises(ValueError, match="pin") as ei:
        redacting_filter({"pin": "123"})
    assert "123" not in str(ei.value)


def test_the_longest_secret_wins_when_one_contains_another():
    log, out = capture({"short": "abcd", "long": "abcd-efgh"})
    log.info("abcd-efgh abcd")
    assert out.getvalue().strip() == "[secret:long] [secret:short]"


# --- results ---------------------------------------------------------------------------------


def test_encode_result_is_canonical_and_turns_tuples_into_lists():
    assert encode_result({"b": (1, 2), "a": "é"}) == '{"a":"é","b":[1,2]}'.encode()


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_encode_result_refuses_nan_and_infinity(bad):
    with pytest.raises(ResultError) as ei:
        encode_result({"items": [{"score": bad}]})
    assert ei.value.path == "$.items[0].score"


def test_encode_result_refuses_nul_with_its_path():
    with pytest.raises(ResultError) as ei:
        encode_result({"items": [{"title": "a\x00b"}]})
    assert ei.value.path == "$.items[0].title"
    with pytest.raises(ResultError) as ei:
        encode_result({"detail": {"k\x00": 1}})
    assert ei.value.path.startswith("$.detail")


@pytest.mark.parametrize(
    "bad",
    [{1: "a"}, {"s": {1, 2}}, {"b": b"x"}, {"o": object()}, {"s": "\ud800"}],
)
def test_encode_result_refuses_what_json_cannot_carry(bad):
    with pytest.raises(ResultError):
        encode_result(bad)


def test_encode_result_refuses_a_cycle():
    a: list = []
    a.append(a)
    with pytest.raises(ResultError):
        encode_result(a)


def test_sdk_runtime_never_imports_the_core():
    import auspex_sdk.runtime  # noqa: F401

    for name in (
        "auspex_sdk.runtime",
        "auspex_sdk.http",
        "auspex_sdk.redact",
        "auspex_sdk.results",
    ):
        src = open(sys.modules[name].__file__).read()
        assert "from auspex." not in src and "import auspex\n" not in src


# --- str/int/float subclasses are read by their plain value (fix round 1) -------------------


def test_encode_result_reads_enum_members_by_value():
    import enum

    class State(str, enum.Enum):  # noqa: UP042 -- the probe: StrEnum would hide the bug
        OPEN = "open"

    class Level(enum.IntEnum):
        HIGH = 3

    assert encode_result({"s": State.OPEN, "n": Level.HIGH}) == b'{"n":3,"s":"open"}'


def test_encode_result_is_not_fooled_by_a_str_subclass_hiding_nul():
    class Sneaky(str):
        def __contains__(self, item):
            return False

        def __str__(self):
            return "clean"

    with pytest.raises(ResultError) as ei:
        encode_result({"s": Sneaky("a\x00b")})
    assert ei.value.path == "$.s"
    with pytest.raises(ResultError):
        encode_result({Sneaky("k\x00"): 1})


def test_encode_result_refuses_a_float_subclass_that_is_nan():
    class F(float):
        def __float__(self):
            return math.nan

    # the plain value is what is written: 1.0, whatever __float__ claims
    assert encode_result({"x": F(1.0)}) == b'{"x":1.0}'
    with pytest.raises(ResultError) as ei:
        encode_result({"x": F("nan")})
    assert ei.value.path == "$.x"


def test_a_secret_in_a_request_url_is_redacted_on_httpx_s_own_logger(load):
    """PR #43 review #9: the filter was on `ctx.log` only, and httpx logs every
    request's URL on its own logger, so a secret in a query string reached the log
    as is. The library's loggers redact whatever secrets a live context holds, with
    one shared filter (not one per run on a shared logger)."""
    mod = load(SAMPLE)
    lib = logging.getLogger("httpx")
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    level = lib.level
    lib.addHandler(handler)
    lib.setLevel(logging.INFO)
    try:
        ctx = Context.create(sample_config(mod),
                             transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        ctx.http.request("GET", f"https://svc.example:9443/api/x?token={TOKEN}")
        ctx2 = Context.create(sample_config(mod),
                              transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        ctx2.http.request("GET", f"https://svc.example:9443/api/y?token={TOKEN}")
    finally:
        lib.removeHandler(handler)
        lib.setLevel(level)
    text = out.getvalue()
    assert "HTTP Request" in text and TOKEN not in text
    assert "[secret:api_token]" in text
    assert len(lib.filters) <= 1  # one shared filter, however many contexts ran


def test_every_logger_the_http_library_writes_to_is_covered():
    """Review of PR #43's fixes, M1: a filter on one logger does not reach a sibling,
    so each name httpx and httpcore log on is listed (httpcore.socks was missing)."""
    import pathlib
    import re

    import httpcore
    from auspex_sdk.redact import LIBRARY_LOGGERS

    root = pathlib.Path(httpcore.__file__).parent
    used = {m for f in root.rglob("*.py")
            for m in re.findall(r'getLogger\(\s*"([^"]+)"\s*\)', f.read_text())}
    assert used <= set(LIBRARY_LOGGERS), used - set(LIBRARY_LOGGERS)
    assert "httpx" in LIBRARY_LOGGERS
