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
    # Hermetic tests: keyless enrichment providers would otherwise fire LIVE
    # HTTP on every ioc_check test turn. Enriched-path tests inject a fake
    # service; a host-run live check can override with ENRICHMENT_ENABLED=true.
    os.environ.setdefault("ENRICHMENT_ENABLED", "false")
    # Hermetic tests: the KB would otherwise bootstrap (cluster settings, model
    # registry, seed ingest) against the live dev OpenSearch on every app start.
    # KB-path tests inject a fake service at app.state.kb; host-run live checks
    # can override with KB_ENABLED=true.
    os.environ.setdefault("KB_ENABLED", "false")
    # Hermetic tests: the S7 ingest scheduler would otherwise pull LIVE feeds
    # (NVD/KEV/EPSS) from every app start. Scheduler tests drive run_cycle()
    # directly with fake feeds; host-run live checks override INGEST_ENABLED=true.
    os.environ.setdefault("INGEST_ENABLED", "false")
    # No LLM_BASE_URL pin: the primary dev endpoint (Z.ai's general API, D-034)
    # is a public URL that resolves identically from host and container, so .env
    # is the single source of truth. Only if you flip .env back to the local
    # Ollama secondary (host.docker.internal) do host runs need
    # LLM_BASE_URL=http://localhost:11434/v1 — set it in your shell for that case,
    # and give scripts/llm_harness.py `--deployment-base-url
    # http://host.docker.internal:11434/v1` so its scorecard is recorded under the
    # name the container looks up (D-035).
