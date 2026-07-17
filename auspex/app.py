"""FastAPI app factory. Async throughout; state lives on app.state, never globals."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from auspex import __version__
from auspex.config import Settings, get_settings
from auspex.db import create_pool
from auspex.enrich import EnrichmentService
from auspex.llm.registry import load_dev_registry
from auspex.migrations import run_migrations
from auspex.routes import auth, chat, health, ui

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        # Internal model switcher (D-016): {} unless APP_ENV=dev + a registry file.
        app.state.dev_llm_registry = load_dev_registry(settings)
        # Enrichment fan-out service (S5): providers resolved from settings;
        # inert (active=False) when disabled or no providers configured.
        app.state.enrichment = EnrichmentService.from_settings(settings)
        app.state.pool = await create_pool(settings.database_url)
        # try/finally covers migrations too: a failure there must still close the pool.
        try:
            await run_migrations(app.state.pool)
            yield
        finally:
            await app.state.pool.close()
            await app.state.enrichment.aclose()

    app = FastAPI(
        title="Auspex",
        description="Security intelligence platform. The flock sees first.",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.app_env == "dev" else None,
        redoc_url=None,
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(ui.router)
    return app
