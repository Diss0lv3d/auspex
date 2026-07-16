"""Env-driven configuration.

Every variable read here MUST be documented in `.env.example` and
`docs/ENV_VARS.md` (CLAUDE.md rule 5 — no invented env vars).
Secrets never get literal defaults in code (rule 9).
"""

import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    # Fail closed: default is "prod" so a deployment that forgets APP_ENV does NOT
    # expose dev-only surfaces (dev-login, /api/docs). The local docker-compose sets
    # APP_ENV=dev explicitly in the app service's `environment:` block.
    app_env: str = "prod"  # dev | prod

    # Path to a gitignored JSON file listing dev endpoints for the INTERNAL model
    # switcher (D-016). Loaded only when app_env=dev; empty ⇒ switcher off. Keys
    # are referenced by env-var name inside that file, never inlined.
    dev_llm_registry_file: str = ""

    # --- Postgres (transactional truth; D-001) ---
    database_url: str = "postgresql://auspex:auspex@postgres:5432/auspex"

    # --- OpenSearch (own container; D-009 — never SARA's cluster) ---
    opensearch_url: str = "http://opensearch:9200"
    opensearch_user: str = ""
    opensearch_pass: str = ""

    # --- LLM (customer-supplied, OpenAI-compatible; D-005). Unused until S2. ---
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""

    # --- Auth ---
    secret_key: str = ""  # JWT signing key; required in prod, ephemeral fallback in dev
    jwt_ttl_minutes: int = 720
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    def model_post_init(self, __context: object) -> None:
        if self.app_env not in ("dev", "prod"):
            raise RuntimeError(f"APP_ENV must be 'dev' or 'prod', got {self.app_env!r}")
        if not self.secret_key:
            if self.app_env == "prod":
                raise RuntimeError("SECRET_KEY is required when APP_ENV=prod")
            # Dev-only ephemeral key: tokens die with the process, nothing leaks.
            self.secret_key = secrets.token_hex(32)

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
