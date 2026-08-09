"""FastAPI app factory. Async throughout; state lives on app.state, never globals."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from auspex import __version__
from auspex.config import Settings, get_settings
from auspex.db import create_pool
from auspex.enrich import EnrichmentService
from auspex.ingest import IngestScheduler
from auspex.kb import KnowledgeService
from auspex.llm.registry import load_dev_registry
from auspex.migrations import run_migrations
from auspex.routes import auth, chat, health, investigations, retrohunt, ui, watchers

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
        # Knowledge base (S6): bootstrap is idempotent and never raises — a cold
        # or unreachable OpenSearch leaves the service up with the deferred rail
        # answering honestly. Since S7 it runs INSIDE the ingest scheduler's
        # background task (TD-008 resolved): the port binds immediately and KB
        # turns during warm-up get the honest "didn't answer this turn" copy.
        app.state.kb = KnowledgeService.from_settings(settings)
        app.state.pool = await create_pool(settings.database_url)
        # try/finally covers migrations too: a failure there must still close the pool.
        try:
            await run_migrations(app.state.pool)
            # Feed ingestion (S7): one background task owns KB bootstrap +
            # watermark catch-up + the hourly cycle. Inert (bootstrap-only)
            # when INGEST_ENABLED=false or the KB is off.
            app.state.ingest = IngestScheduler.from_settings(settings, app.state.kb, app.state.pool)
            app.state.ingest_task = asyncio.create_task(app.state.ingest.run())
            yield
        finally:
            task = getattr(app.state, "ingest_task", None)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                await app.state.ingest.aclose()
            await app.state.pool.close()
            await app.state.enrichment.aclose()
            await app.state.kb.aclose()

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
    app.include_router(investigations.router)
    app.include_router(retrohunt.router)
    app.include_router(watchers.router)
    app.include_router(ui.router)
    return app
