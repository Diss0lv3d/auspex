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

import io
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from auspex_sdk.harness import _transport
from auspex_sdk.invoke import invoke
from auspex_sdk.manifest import Manifest, parse_manifest
from auspex_sdk.redact import redacting_filter

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


def _redact_value(value: Any, filt: logging.Filter) -> Any:
    """Every string of a result, keys and values, at any depth, redacted with the same
    forms as the logs: a connector that echoes a SIEM's error body, or its key, sends
    nothing of the secret (PR #51 review #3)."""
    if isinstance(value, str):
        return _redact(value, filt)
    if isinstance(value, dict):
        return {_redact_value(k, filt): _redact_value(v, filt) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v, filt) for v in value]
    return value


def run(package_dir: Path, raw_job: str) -> tuple[int, dict]:
    log_lines: list[str] = []
    filt: logging.Filter = redacting_filter({})
    try:
        job = _job(raw_job)
        manifest = parse_manifest(json.loads((package_dir / "manifest.json").read_text()))
        values, resolved = _resolve_secrets(manifest, job["config"], job["secrets"])
        filt = redacting_filter(resolved)
        fixture = os.environ.get(FIXTURE_ENV)
        out = io.StringIO()
        try:
            result = invoke(
                package_dir, manifest, job["command"], values=values, secrets=resolved,
                arguments=dict(job.get("arguments") or {}),
                transport=_transport(Path(fixture)) if fixture else None,
                idempotency_key=str(job.get("idempotency_key") or f"run-{job['command']}"),
                missing=JobError, capture=out)
        finally:
            log_lines.extend(x for x in out.getvalue().splitlines() if x.strip())
        return 0, {"result": _redact_value(result, filt),
                   "log": [_redact(x, filt) for x in log_lines]}
    except Exception as e:  # noqa: BLE001 -- every failure is an answer, redacted
        message = str(e) if isinstance(e, JobError) else f"{type(e).__name__}: {e}"
        return 1, {"error": _redact(message, filt),
                   "log": [_redact(x, filt) for x in log_lines]}


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
