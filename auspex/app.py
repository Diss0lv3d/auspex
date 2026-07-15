"""FastAPI app factory. Async throughout; state lives on app.state, never globals."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from auspex import __version__
from auspex.config import Settings, get_settings
from auspex.db import create_pool
from auspex.migrations import run_migrations
from auspex.routes import auth, chat, health

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.pool = await create_pool(settings.database_url)
        # try/finally covers migrations too: a failure there must still close the pool.
        try:
            await run_migrations(app.state.pool)
            yield
        finally:
            await app.state.pool.close()

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
    return app
