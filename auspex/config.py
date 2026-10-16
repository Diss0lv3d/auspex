"""Env-driven configuration.

Every variable read here MUST be documented in `.env.example` and
`docs/ENV_VARS.md` (CLAUDE.md rule 5 — no invented env vars).
Secrets never get literal defaults in code (rule 9).
"""

import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from auspex.tenancy.region import REGIONS


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
    # D-038: probe the configured endpoint once per fingerprint, in the
    # background at startup, and record the deployment's scorecard. Spends ~15
    # requests of the customer's inference once per endpoint (D-005 — so it is
    # switchable). Tests/host runs pin LLM_AUTOPROBE_ENABLED=false (hermetic).
    llm_autoprobe_enabled: bool = True

    # --- Enrichment (S5). Keyless providers (InternetDB, hashlookup, OTX) are
    # always on when enabled; key-gated ones activate when their key exists.
    # Tests/host runs pin ENRICHMENT_ENABLED=false (hermetic CI, auspex.devhost).
    enrichment_enabled: bool = True
    abusech_auth_key: str = ""  # one auth.abuse.ch key covers URLhaus + ThreatFox
    abuseipdb_api_key: str = ""
    otx_api_key: str = ""  # optional — OTX answers keyless (probed); key raises limits
    greynoise_api_key: str = ""

    # --- Residency (D-061, S30). Where this deployment's engine processes the
    # data it is sent. A workspace in another region gets no engine turn
    # (auspex/tenancy/region.py). Unset ⇒ global, which fails safe: a global
    # engine serves no ksa workspace.
    engine_region: str = "global"
    # D-069 (built at S31). Where this deployment stores its data (Postgres,
    # OpenSearch). A workspace whose region it may not hold is refused at
    # creation; one already there is named at startup. Unset ⇒ global, which
    # holds no ksa workspace (fail safe). The operator's declaration: nothing
    # verifies where the database actually runs.
    storage_region: str = "global"

    # --- Knowledge base (S6). Lives on the OpenSearch container (D-009);
    # embeddings are server-side via the ML plugin (D-018). Tests/host runs pin
    # KB_ENABLED=false (hermetic; KB mockable at app.state.kb); container
    # default is on — bootstrap is idempotent and survives a cold cluster.
    kb_enabled: bool = True

    # --- Feed ingestion (S7): NVD delta + CISA KEV + FIRST EPSS into the KB.
    # Inert unless the KB is also enabled. Tests/host runs pin
    # INGEST_ENABLED=false (hermetic — the scheduler would otherwise hit live
    # feeds); the scheduler is mockable at app.state.ingest.
    ingest_enabled: bool = True
    nvd_api_key: str = ""  # optional; raises NVD quota 5→50 req/30 s (probed)

    # --- Auth ---
    secret_key: str = ""  # JWT signing key; required in prod, ephemeral fallback in dev
    jwt_ttl_minutes: int = 720
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    def model_post_init(self, __context: object) -> None:
        if self.app_env not in ("dev", "prod"):
            raise RuntimeError(f"APP_ENV must be 'dev' or 'prod', got {self.app_env!r}")
        for var, value in (("ENGINE_REGION", self.engine_region),
                           ("STORAGE_REGION", self.storage_region)):
            if value not in REGIONS:
                raise RuntimeError(f"{var} must be one of {sorted(REGIONS)}, got {value!r}")
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
