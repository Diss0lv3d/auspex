"""FastAPI app factory. Async throughout; state lives on app.state, never globals."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from auspex import __version__
from auspex.actions import ActionRegistry
from auspex.actions.builtin import build_builtin_actions
from auspex.actions.expiry import EXPIRE, EXPIRE_SCHEDULE
from auspex.actions.settlement import action_proposer
from auspex.config import Settings, get_settings
from auspex.connectors import routes as connectors
from auspex.db import create_pool
from auspex.enrich import EnrichmentService
from auspex.ingest import IngestScheduler
from auspex.jobs.worker import JobWorker
from auspex.kb import KnowledgeService
from auspex.llm.autoprobe import keep_scorecard_fresh
from auspex.llm.registry import load_dev_registry
from auspex.migrations import run_migrations
from auspex.routes import (
    auth,
    chat,
    health,
    investigations,
    proposals,
    retrohunt,
    timeline,
    ui,
    watchers,
    workspace,
)
from auspex.tenancy.admin import misplaced_workspaces

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


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
            # D-069 (Burhan's call, S31): a workspace this deployment's storage
            # may not hold (made before the rule, or by SQL) is named, not refused.
            for name, region in await misplaced_workspaces(app.state.pool,
                                                           settings.storage_region):
                log.warning("D-069: workspace %r must keep its data in region %s, and this"
                            " deployment stores its data in region %s (STORAGE_REGION)",
                            name, region, settings.storage_region)
            # Actions (S17 contract, S18 execution). Registered after migrations
            # because the only executable action writes to a table they create,
            # and built from a single place so the loop's manifest and the
            # approval surface's executor can never hold different registries —
            # which would let a model propose an action the executor cannot find.
            app.state.action_registry = ActionRegistry()
            app.state.action_registry.register_all(build_builtin_actions(app.state.pool))
            app.state.action_proposer = action_proposer(app.state.pool)
            # Feed ingestion (S7): one background task owns KB bootstrap +
            # watermark catch-up + the hourly cycle. Inert (bootstrap-only)
            # when INGEST_ENABLED=false or the KB is off.
            app.state.ingest = IngestScheduler.from_settings(settings, app.state.kb, app.state.pool)
            app.state.ingest_task = asyncio.create_task(app.state.ingest.run())
            # D-065 (S31): the in-app jobs worker, beside the ingest task. Its
            # only kind today expires proposals nobody decided within 24 h.
            # Host/test runs pin JOBS_WORKER_ENABLED=false (auspex.devhost).
            app.state.jobs_worker = JobWorker(
                app.state.pool, (EXPIRE,), (EXPIRE_SCHEDULE,),
                enabled=settings.jobs_worker_enabled,
            )
            app.state.jobs_task = asyncio.create_task(app.state.jobs_worker.run())
            # D-038: measure the configured endpoint once per fingerprint, in the
            # background — the port binds now and deep turns stay on the safe
            # default ("unknown") until the scorecard lands. D-042: and again
            # whenever the measurement gets old, for as long as the app runs.
            if settings.llm_autoprobe_enabled and settings.llm_base_url:
                app.state.autoprobe_task = asyncio.create_task(
                    keep_scorecard_fresh(app.state.pool, settings)
                )
            yield
        finally:
            probing = getattr(app.state, "autoprobe_task", None)
            if probing is not None:
                probing.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await probing
            jobs = getattr(app.state, "jobs_task", None)
            if jobs is not None:
                jobs.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await jobs
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
    app.include_router(proposals.router)
    app.include_router(retrohunt.router)
    app.include_router(watchers.router)
    app.include_router(timeline.router)
    app.include_router(workspace.router)
    app.include_router(connectors.router)
    app.include_router(ui.router)
    return app
