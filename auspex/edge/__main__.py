"""`python -m auspex.edge`: run one Edge Agent until stopped (S33, D-062).

Environment (docs/ENV_VARS.md):
- `AUSPEX_URL` — the Auspex the agent calls out to (outbound only);
- `AUSPEX_AGENT_TOKEN` or `AUSPEX_AGENT_TOKEN_FILE` — an enrollment token (`ape_…`,
  spent once, on the first start) or the agent's credential (`apa_…`). After enrolling,
  the credential is kept in the cache directory, mode 0600, and used from then on;
- `AUSPEX_SECRETS_FILE` — the host's secrets file (JSON, mode 0600, D-063);
- `AUSPEX_AGENT_CACHE` — where packages and the credential live (default ./agent-cache).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

import httpx

from auspex.edge.agent import Agent

logger = logging.getLogger("auspex.edge")
HEARTBEAT_SECONDS = 20


class AgentConfigError(ValueError):
    pass


def _token(env: dict) -> str:
    if env.get("AUSPEX_AGENT_TOKEN"):
        return env["AUSPEX_AGENT_TOKEN"].strip()
    if env.get("AUSPEX_AGENT_TOKEN_FILE"):
        return Path(env["AUSPEX_AGENT_TOKEN_FILE"]).read_text().strip()
    raise AgentConfigError("set AUSPEX_AGENT_TOKEN or AUSPEX_AGENT_TOKEN_FILE")


def credential(http: httpx.Client, env: dict, cache_dir: Path) -> str:
    """The agent's credential: kept from an earlier enrollment, given, or enrolled now."""
    kept = cache_dir / "credential"
    if kept.exists():
        return kept.read_text().strip()
    token = _token(env)
    if not token.startswith("ape_"):
        return token
    res = http.post("/api/edge/enroll", json={"token": token})
    if res.status_code != 200:
        raise AgentConfigError(f"enrollment refused: {res.json().get('detail', res.text)}")
    value = res.json()["credential"]
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    kept.write_text(value)
    kept.chmod(0o600)
    logger.info("enrolled as agent %s", res.json()["agent_id"])
    return value


def _refused(err: httpx.HTTPError) -> bool:
    return isinstance(err, httpx.HTTPStatusError) and err.response.status_code == 401


def main(env: dict | None = None) -> int:
    env = dict(os.environ if env is None else env)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    missing = [k for k in ("AUSPEX_URL", "AUSPEX_SECRETS_FILE") if not env.get(k)]
    if missing:
        logger.error("set %s", ", ".join(missing))
        return 2
    cache_dir = Path(env.get("AUSPEX_AGENT_CACHE", "agent-cache"))
    with httpx.Client(base_url=env["AUSPEX_URL"], trust_env=False, timeout=40) as http:
        while True:  # once more only after a refused credential is replaced (review #6)
            try:
                agent = Agent(http=http, credential=credential(http, env, cache_dir),
                              secrets_path=Path(env["AUSPEX_SECRETS_FILE"]),
                              cache_dir=cache_dir)
            except (AgentConfigError, ValueError, OSError) as err:
                logger.error("%s", err)
                return 2
            outcome = _serve(agent)
            if outcome != "refused":
                return outcome
            # PR #51 review #6, with the fresh review's I3: a 401 is the credential
            # refused only if a second authenticated call is refused too (a proxy or a
            # half-deployed backend can answer one 401). Then, with no new enrollment
            # token, say so and stop, the credential kept; with one, set the old
            # credential aside, enroll, and drop it only once that succeeded.
            if not _confirmed_refused(agent):
                logger.warning("one refused call, not repeated; carrying on")
                continue
            if not _token_is_enrollment(env):
                logger.error("this agent's credential was refused (revoked?). Create a new"
                             " agent and start this one with its enrollment token.")
                return 3
            kept, aside = cache_dir / "credential", cache_dir / "credential.refused"
            if kept.exists():
                kept.replace(aside)
            try:
                credential(http, env, cache_dir)
            except (AgentConfigError, OSError, httpx.HTTPError) as err:
                if aside.exists():
                    aside.replace(kept)
                logger.error("this agent's credential was refused and enrolling again"
                             " failed (%s); the old credential is kept", err)
                return 3
            aside.unlink(missing_ok=True)
            logger.warning("this agent's credential was refused; enrolled again")


def _confirmed_refused(agent: Agent) -> bool:
    try:
        agent.heartbeat()
    except httpx.HTTPError as err:
        return _refused(err)
    return False


def _token_is_enrollment(env: dict) -> bool:
    try:
        return _token(env).startswith("ape_")
    except (AgentConfigError, OSError):
        return False


def _serve(agent: Agent) -> int | str:
    """Run jobs until stopped (0) or the credential is refused ("refused")."""
    stop = threading.Event()

    def beat() -> None:
        while not stop.is_set():
            try:
                agent.heartbeat()
            except httpx.HTTPError as err:
                logger.warning("heartbeat failed: %s", type(err).__name__)
            stop.wait(HEARTBEAT_SECONDS)

    threading.Thread(target=beat, daemon=True, name="heartbeat").start()
    try:
        while True:
            try:
                agent.run_once()
            except httpx.HTTPError as err:
                if _refused(err):
                    return "refused"
                logger.warning("edge API unreachable (%s); retrying", type(err).__name__)
                time.sleep(5)
            except Exception:  # noqa: BLE001 -- one job's failure never ends the agent
                logger.exception("a job failed in the agent itself; carrying on")
                time.sleep(5)
    except KeyboardInterrupt:
        return 0
    finally:
        stop.set()


if __name__ == "__main__":
    sys.exit(main())
