"""Shared pytest fixtures for integration tests that require live Postgres.

The ``async_session`` fixture automatically skips any test that uses it when the
configured ``DATABASE_URL`` is unreachable, so local development without Docker
running never silently fails the suite.  CI always provides Postgres via the
``services:`` block in ``.github/workflows/ci.yml``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings


@pytest_asyncio.fixture
async def async_session() -> AsyncSession:
    """Yield an AsyncSession connected to the test database.

    Before yielding, truncates the ``documents`` table (CASCADE takes care of
    ``chunks``) so every test starts with a clean slate.

    Skips automatically if Postgres is unreachable.
    """
    engine = create_async_engine(settings.database_url, echo=False)

    # Probe the connection once; skip if the DB is not available.
    # We catch the broad base class because SQLAlchemy wraps driver errors in
    # several different exception types depending on the backend and driver.
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        await engine.dispose()
        pytest.skip("Postgres not reachable — skipping DB integration test")

    async with AsyncSession(engine) as session:
        # Clean slate: cascade removes chunks that reference these documents.
        await session.execute(text("TRUNCATE documents CASCADE"))
        await session.commit()
        yield session  # type: ignore[misc]

    await engine.dispose()
