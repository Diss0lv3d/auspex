"""Host-run entry points (pytest, scripts/) share one env-pinning trick.

`.env` uses compose-internal hostnames that don't resolve from the host; real
env vars outrank `.env` in pydantic-settings, so pinning BEFORE Settings is
first constructed redirects host runs to the host-mapped ports. This module
must stay import-safe pre-pinning: stdlib only, no auspex.config import.
"""

import os


def pin_host_defaults() -> None:
    os.environ.setdefault("DATABASE_URL", "postgresql://auspex:auspex@localhost:55432/auspex")
    os.environ.setdefault("OPENSEARCH_URL", "http://localhost:9200")
    os.environ.setdefault("APP_ENV", "dev")
