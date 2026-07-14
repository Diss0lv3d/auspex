"""Test env is pinned BEFORE any auspex import: pydantic-settings gives real env
vars priority over .env, and .env points at compose-internal hostnames that
don't resolve from the host. Tests talk to the host-mapped ports instead."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://auspex:auspex@localhost:55432/auspex")
os.environ.setdefault("OPENSEARCH_URL", "http://localhost:9200")
os.environ.setdefault("APP_ENV", "dev")

import asyncio  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from auspex.app import create_app  # noqa: E402
from auspex.config import get_settings  # noqa: E402

# Emails the suite provisions. Deleting these users cascades to their api_keys and
# chat_sessions (ON DELETE CASCADE), so the persistent dev DB doesn't accumulate rows.
TEST_EMAILS = ["analyst@auspex.dev", "victim@auspex.dev"]


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def client():
    """App with real lifespan: pool + idempotent migration run at startup."""
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session", autouse=True)
def _purge_test_rows(settings):
    """Leave the live dev DB as we found it: delete test users at session end."""
    yield

    async def _purge() -> None:
        conn = await asyncpg.connect(settings.database_url)
        try:
            await conn.execute("DELETE FROM users WHERE email = ANY($1::text[])", TEST_EMAILS)
        finally:
            await conn.close()

    asyncio.run(_purge())
