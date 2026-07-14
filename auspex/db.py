"""asyncpg pool lifecycle. One pool per app instance, created in the lifespan."""

import asyncio
import logging

import asyncpg

logger = logging.getLogger("auspex.db")


async def create_pool(database_url: str, retries: int = 10, delay: float = 1.5) -> asyncpg.Pool:
    """Create the pool, retrying while Postgres finishes booting under compose."""
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await asyncpg.create_pool(database_url, min_size=1, max_size=10)
        except (OSError, asyncpg.PostgresError) as err:
            last_err = err
            logger.warning("Postgres not ready (attempt %d/%d): %s", attempt, retries, err)
            await asyncio.sleep(delay)
    raise RuntimeError(f"Could not connect to Postgres after {retries} attempts") from last_err
