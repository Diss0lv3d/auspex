"""`python -I -m auspex_sdk.run <package_dir>`: one connector command, in its own
process, the way an Edge Agent runs it (S33, D-062).

stdin is one JSON job, `{command, config, secrets, arguments}`:

- `config` is the integration's config as stored: plain values, and `secret:<name>`
  for each secret field (D-063);
- `secrets` maps those names to the values the agent resolved from its host, and only
  those (the agent never hands one connector another's secrets);
- `command` is `test`, `fetch` or `<action>.<step>`, as in the harness.

stdout is one JSON object, `{"result": …, "log": [...]}` or `{"error": "…", "log":
[...]}`, exit code 0 or 1. Everything the handler prints, logs or raises is captured
and redacted with the job's secrets before it is written, so nothing reaches the agent's
output unredacted. The result is checked with `auspex_sdk.validate`, the core's copy.

For tests only, `AUSPEX_SDK_RUN_FIXTURE` names a harness fixture: requests are answered
from it instead of the network (docs/ENV_VARS.md).
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from auspex_sdk import validate
from auspex_sdk.build import import_source_module, importable
from auspex_sdk.harness import DEFAULT_LIMIT, _bind, _resolve, _transport, config_class
from auspex_sdk.manifest import Manifest, parse_manifest
from auspex_sdk.redact import redacting_filter
from auspex_sdk.results import encode_result
from auspex_sdk.runtime import Context, load_config

SECRET_REF = re.compile(r"secret:([A-Za-z0-9_.-]{1,64})")
FIXTURE_ENV = "AUSPEX_SDK_RUN_FIXTURE"


class JobError(ValueError):
    """The job cannot run. The message is safe to show: it names, never reveals."""


def _job(raw: str) -> dict:
    try:
        job = json.loads(raw)
    except ValueError as e:
        raise JobError("job: stdin is not JSON") from e
    if not isinstance(job, dict) or not {"command", "config", "secrets"} <= set(job):
        raise JobError("job: expected {command, config, secrets, arguments}")
    if not isinstance(job["config"], dict) or not isinstance(job["secrets"], dict):
        raise JobError("job: config and secrets are objects")
    return job


def _resolve_secrets(m: Manifest, config: dict, secrets: dict) -> tuple[dict, dict]:
    """(plain values, {field: value}) from the stored config and the agent's secrets."""
    values, resolved = {}, {}
    kinds = {f.name: f.type for f in m.config}
    for name, value in config.items():
        if kinds.get(name) != "secret":
            values[name] = value
            continue
        ref = SECRET_REF.fullmatch(value) if isinstance(value, str) else None
        if ref is None:
            raise JobError(f"config.{name}: a secret is given as secret:<name>")
        if ref.group(1) not in secrets:
            raise JobError(f"secret {ref.group(1)!r} (for config.{name}) is not on this agent")
        resolved[name] = secrets[ref.group(1)]
    return values, resolved


def _redact(text: str, filt: logging.Filter) -> str:
    record = logging.makeLogRecord({"msg": text})
    filt.filter(record)
    return record.getMessage()


def run(package_dir: Path, raw_job: str) -> tuple[int, dict]:
    log_lines: list[str] = []
    filt: logging.Filter = redacting_filter({})
    try:
        job = _job(raw_job)
        manifest = parse_manifest(json.loads((package_dir / "manifest.json").read_text()))
        values, resolved = _resolve_secrets(manifest, job["config"], job["secrets"])
        filt = redacting_filter(resolved)
        result = _invoke(package_dir, manifest, job["command"], values, resolved,
                         dict(job.get("arguments") or {}), log_lines)
        return 0, {"result": result, "log": [_redact(x, filt) for x in log_lines]}
    except Exception as e:  # noqa: BLE001 -- every failure is an answer, redacted
        message = str(e) if isinstance(e, JobError) else f"{type(e).__name__}: {e}"
        return 1, {"error": _redact(message, filt),
                   "log": [_redact(x, filt) for x in log_lines]}


def _invoke(root: Path, manifest: Manifest, command: str, values: dict, secrets: dict,
            arguments: dict, log_lines: list[str]) -> Any:
    ref, action, step = _resolve(manifest, command)
    cfg = load_config(config_class(manifest), values, secrets)
    fixture = os.environ.get(FIXTURE_ENV)
    transport = _transport(Path(fixture)) if fixture else None
    module_name, _, func_name = ref.partition(":")
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    with importable(root.resolve()):
        fn = getattr(import_source_module(module_name, root.resolve(), f"command {command}"),
                     func_name, None)
        if not callable(fn):
            raise JobError(f"handler {ref!r} is not in the package")
        ctx = Context.create(cfg, idempotency_key=f"run-{command}", transport=transport)
        ctx.log.addHandler(handler)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                if action is not None:
                    result = fn(ctx, **_bind(action, arguments))
                elif command == "fetch":
                    result = fn(ctx, arguments.get("cursor"),
                                arguments.get("limit", DEFAULT_LIMIT))
                else:
                    result = fn(ctx)
        finally:
            ctx.log.removeHandler(handler)
            ctx.http.close()
            log_lines.extend(line for line in out.getvalue().splitlines() if line.strip())
    if command == "test":
        validate.check_test(result)
    elif command == "fetch":
        validate.check_fetch(manifest, result)
    elif step == "observe":
        validate.check_observe(action, result)  # type: ignore[arg-type]
    else:
        validate.check_envelope(action, step, result)  # type: ignore[arg-type]
    return json.loads(encode_result(result))


def main() -> int:
    if len(sys.argv) != 2:
        sys.stdout.write(json.dumps({"error": "job: usage: auspex_sdk.run <package_dir>",
                                     "log": []}))
        return 1
    code, answer = run(Path(sys.argv[1]), sys.stdin.read())
    sys.stdout.write(json.dumps(answer))
    return code


if __name__ == "__main__":
    sys.exit(main())
