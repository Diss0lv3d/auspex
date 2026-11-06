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

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx

from auspex_sdk import validate
from auspex_sdk.build import BuildError, load_manifest
from auspex_sdk.http import HostNotDeclared
from auspex_sdk.invoke import (  # noqa: F401 -- re-exported: the runner's and tests' names
    DEFAULT_LIMIT,
    STEPS,
    CommandError,
    bind,
    config_class,
    invoke,
    resolve,
)
from auspex_sdk.results import ResultError


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

# --- running ---------------------------------------------------------------------------------


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
    manifest = load_manifest(source_dir)

    def wrap(e: Exception) -> Exception:
        if isinstance(e, HarnessError | HostNotDeclared | ResultError):
            return e
        return HarnessError(f"{command}: handler raised {type(e).__name__}: {e}")

    try:
        return invoke(source_dir, manifest, command, values=config, secrets=secrets,
                      arguments=dict(arguments or {}), transport=_transport(fixture),
                      idempotency_key=f"harness-{command}", missing=BuildError, wrap=wrap)
    except (CommandError, validate.ResultInvalid) as e:
        raise HarnessError(str(e)) from e
