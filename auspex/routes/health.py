"""Liveness + readiness. Readiness checks Postgres AND our OpenSearch container."""

import asyncio

import asyncpg
from fastapi import APIRouter, Request, Response

from auspex import __version__
from auspex.search import opensearch_ping

router = APIRouter(prefix="/api/health", tags=["health"])

READY_CHECK_TIMEOUT_SECONDS = 5.0


@router.get("")
async def health() -> dict:
    """Liveness: the process is up. No dependency checks."""
    return {"status": "ok", "service": "Auspex", "version": __version__}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict:
    """Readiness: Postgres and OpenSearch are both reachable."""
    checks: dict[str, dict] = {}

    pool: asyncpg.Pool = request.app.state.pool
    try:
        # Bounded: a partitioned/paused Postgres must yield a 503, never hang the probe.
        await asyncio.wait_for(pool.fetchval("SELECT 1"), timeout=READY_CHECK_TIMEOUT_SECONDS)
        checks["postgres"] = {"ok": True, "detail": "reachable"}
    except (TimeoutError, OSError, asyncpg.PostgresError) as err:
        checks["postgres"] = {"ok": False, "detail": f"unreachable: {err.__class__.__name__}"}

    checks["opensearch"] = await opensearch_ping(request.app.state.settings)

    all_ok = all(check["ok"] for check in checks.values())
    if not all_ok:
        response.status_code = 503
    return {"status": "ready" if all_ok else "degraded", "checks": checks}
