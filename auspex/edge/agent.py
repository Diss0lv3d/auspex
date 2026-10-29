"""One Edge Agent (S33, D-062): outbound only. It long-polls the edge API for its
integrations' jobs, and for each one:

1. fetches the package by the hash the job names, and re-hashes it (`cache.unpack`);
2. reads the secrets file again and hands the command only the secrets its config
   names (`secret:<name>`, D-063), on stdin, never argv or env;
3. runs `python -I -m auspex_sdk.run` in a subprocess with a timeout and a clean
   environment (no inherited variables or proxies; egress control is the host's);
4. posts what came back: the result, or the error in words. `auspex_sdk.run` has
   already redacted the job's secrets from both; the agent redacts again anything it
   writes itself.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from auspex.edge import cache, secrets

logger = logging.getLogger("auspex.edge")

COMMAND_TIMEOUTS = {"test": 60}  # seconds; under the job's 90 s lease
# A failed result post is retried, then given up (the job's lease then expires): the
# heartbeat renews only jobs still running here, so a lost answer never holds a job
# "running" for ever (PR #51 review #1).
RETRY_DELAYS = (1, 3, 9)
DEFAULT_TIMEOUT = 60
SECRET_REF = re.compile(r"secret:([A-Za-z0-9_.-]{1,64})")
# Passed through to the subprocess only when set on the agent: tests (docs/ENV_VARS.md).
PASS_THROUGH = ("AUSPEX_SDK_RUN_FIXTURE",)


class Agent:
    def __init__(self, *, http: httpx.Client, credential: str, secrets_path: Path,
                 cache_dir: Path, wait: float = 25.0) -> None:
        self.http = http
        self.secrets_path = Path(secrets_path)
        self.cache_dir = Path(cache_dir)
        self.wait = wait
        self._auth = {"Authorization": f"Bearer {credential}"}
        self.running: set[str] = set()  # job ids the heartbeat renews
        self.cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.cache_dir, 0o700)
        secrets.load(self.secrets_path)  # refuse a loose or broken file at start

    # -- the edge API -----------------------------------------------------------------------

    def heartbeat(self) -> None:
        self.http.post("/api/edge/heartbeat", headers=self._auth,
                       json={"jobs": sorted(self.running)}).raise_for_status()

    def _claim(self) -> dict | None:
        res = self.http.post("/api/edge/claim", headers=self._auth,
                             params={"wait": self.wait}, timeout=self.wait + 10)
        if res.status_code == 204:
            return None
        res.raise_for_status()
        return res.json()["job"]

    def _post(self, job: dict, answer: dict) -> None:
        """Post the answer, retrying a transient failure with backoff. 404/409 mean the
        job is no longer this agent's to answer: said once, not retried."""
        for attempt, delay in enumerate((*RETRY_DELAYS, None)):
            try:
                res = self.http.post(f"/api/edge/jobs/{job['id']}/result",
                                     headers=self._auth,
                                     json={"token": job["token"], **answer})
                if res.status_code in (404, 409):
                    logger.warning("job %s: no longer held; its answer was not kept",
                                   job["id"])
                    return
                res.raise_for_status()
                return
            except httpx.HTTPError as err:
                if delay is None:
                    logger.warning("job %s: its answer could not be posted (%s) after %d"
                                   " tries", job["id"], type(err).__name__, attempt + 1)
                    return
                time.sleep(delay)

    # -- one job ----------------------------------------------------------------------------

    def run_once(self) -> bool:
        """Claim and run one job. False when there was none."""
        job = self._claim()
        if job is None:
            return False
        self.running.add(job["id"])
        try:
            answer = self._run(job["payload"])
            self._post(job, answer)
        finally:
            self.running.discard(job["id"])
        logger.info("job %s (%s): %s", job["id"], job["kind"],
                    "answered" if "result" in answer else "failed")
        return True

    def _package(self, content_hash: str) -> Path:
        found = cache.cached(self.cache_dir, content_hash)
        if found is not None:
            return found
        res = self.http.get(f"/api/edge/packages/{content_hash}", headers=self._auth)
        res.raise_for_status()
        return cache.unpack(self.cache_dir, content_hash, res.content)

    def _run(self, payload: dict) -> dict:
        command = payload.get("command", "")
        try:
            package_dir = self._package(payload["content_hash"])
            held = secrets.load(self.secrets_path)
        except (cache.PackageMismatch, secrets.SecretsFileRefused) as err:
            return {"error": str(err)}
        except (httpx.HTTPError, KeyError) as err:
            return {"error": f"the package could not be fetched: {type(err).__name__}"}
        config = payload.get("config") or {}
        wanted = {m.group(1) for v in config.values() if isinstance(v, str)
                  for m in [SECRET_REF.fullmatch(v)] if m}
        job = {"command": command, "config": config,
               "secrets": {k: v for k, v in held.items() if k in wanted},
               "arguments": payload.get("arguments") or {}}
        timeout = COMMAND_TIMEOUTS.get(command, DEFAULT_TIMEOUT)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        env.update({k: os.environ[k] for k in PASS_THROUGH if k in os.environ})
        try:
            proc = subprocess.run(  # noqa: S603 -- our interpreter, the SDK's runner
                [sys.executable, "-I", "-m", "auspex_sdk.run", str(package_dir)],
                input=json.dumps(job), capture_output=True, text=True, timeout=timeout,
                env=env, cwd=package_dir)
        except subprocess.TimeoutExpired:
            return {"error": f"the {command} command took longer than {timeout} s and was"
                             " stopped"}
        return _answer(proc.stdout, proc.returncode, job["secrets"])


def _answer(stdout: str, returncode: int, held: dict[str, str]) -> dict:
    """The runner's one JSON object, or an error in words. Redacted once more."""
    try:
        out: Any = json.loads(stdout)
    except ValueError:
        out = None
    if not isinstance(out, dict) or ("result" in out) == ("error" in out):
        return {"error": _scrub(f"the runner answered nothing usable (exit {returncode})",
                                held)}
    if "error" in out:
        return {"error": _scrub(str(out["error"]), held)}
    return {"result": out["result"]}


def _scrub(text: str, held: dict[str, str]) -> str:
    for value in sorted(held.values(), key=len, reverse=True):
        if value:
            text = text.replace(value, "[secret]")
    return text
