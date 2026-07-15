"""Dev-only endpoint registry for the internal model switcher (D-016 feature 2).

INTERNAL INFRASTRUCTURE ONLY. Per org policy, multi-LLM / bring-your-own-LLM is
never a customer-facing feature — this registry is loaded solely when
APP_ENV=dev and is invisible + inert in prod (see auspex/app.py, /api/models,
and the chat handler's dev gate). It exists so we can A/B real endpoints
(Scout / qwen3 / llama3.1) during development.

Secrets never live here: an entry names the ENV VAR that holds its key
(`api_key_env`), never the key itself, so the registry JSON carries no secret
and can have a committed `.example`. The resolved key is read from the
environment only at client-build time and never serialized.
"""

import json
import logging
import os

from pydantic import BaseModel

from auspex.config import Settings
from auspex.llm.client import LLMClient

logger = logging.getLogger("auspex.llm.registry")


class DevEndpoint(BaseModel):
    """One selectable dev endpoint. `label` is brand-safe (never an engine name);
    it is the only user-visible string. `api_key_env` is the NAME of the env var
    holding the key (or None for keyless endpoints like local Ollama)."""

    id: str
    label: str
    base_url: str
    model: str
    api_key_env: str | None = None
    native_reasoning: bool = False

    def build_client(self) -> LLMClient:
        api_key = os.environ.get(self.api_key_env, "") if self.api_key_env else ""
        return LLMClient(self.base_url, self.model, api_key)


def load_dev_registry(settings: Settings) -> dict[str, DevEndpoint]:
    """Return {id: DevEndpoint} for the configured dev endpoints, or {} when the
    switcher is off. Fail-safe: any problem (prod, unset path, unreadable/invalid
    file, missing key env) yields {} or drops the offending entry — never raises,
    so a bad dev config can't break startup or leak into prod."""
    if settings.app_env != "dev" or not settings.dev_llm_registry_file:
        return {}
    try:
        raw = json.loads(open(settings.dev_llm_registry_file, encoding="utf-8").read())
        entries = raw.get("endpoints", []) if isinstance(raw, dict) else []
    except (OSError, ValueError) as err:
        logger.warning("dev LLM registry unreadable (%s); switcher disabled", err)
        return {}

    registry: dict[str, DevEndpoint] = {}
    for entry in entries:
        try:
            endpoint = DevEndpoint(**entry)
        except (TypeError, ValueError) as err:
            logger.warning("skipping malformed dev endpoint %r: %s", entry, err)
            continue
        # An entry that names a key env var which isn't set is unusable — drop it
        # rather than serve requests that would 401.
        if endpoint.api_key_env and not os.environ.get(endpoint.api_key_env):
            logger.warning(
                "dev endpoint %r names api_key_env=%s which is unset; skipping",
                endpoint.id, endpoint.api_key_env,
            )
            continue
        registry[endpoint.id] = endpoint
    return registry
