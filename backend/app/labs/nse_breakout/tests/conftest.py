"""Database fixtures for the tracker's own integration tests.

Its OWN engine fixture rather than the repo's, exactly as the other labs do:
the repo's `tests/conftest.py` DROPS and recreates the platform schema on every
session; this one only ever touches tables whose name starts with `bt_`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base
from app.labs.nse_breakout import models  # noqa: F401 — registers bt_* on Base

_prefix, _, _ = settings.DATABASE_URI.rpartition("/")
TEST_DATABASE_URI = os.getenv(
    "TEST_DATABASE_URI",
    f"{_prefix}/{os.getenv('TEST_POSTGRES_DB', f'{settings.POSTGRES_DB}_test')}")


@pytest.fixture(scope="session")
async def tracker_engine() -> AsyncGenerator:
    try:
        engine = create_async_engine(TEST_DATABASE_URI, poolclass=None, future=True)
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            own = [t for t in Base.metadata.sorted_tables if t.name.startswith("bt_")]
            # Table-by-table, NOT `Base.metadata.drop_all(tables=own)`: the
            # metadata-level call also visits sequences declared anywhere on
            # `Base`, so merely importing `app.main` in a test made this
            # fixture try to drop an unrelated wallet's sequence and skip the
            # whole suite. `bt_` means `bt_`.
            await conn.run_sync(lambda c: [t.drop(c, checkfirst=True)
                                           for t in reversed(own)])
            await conn.run_sync(lambda c: [t.create(c, checkfirst=True)
                                           for t in own])
    except Exception as exc:  # pragma: no cover - environment, not logic
        pytest.skip(f"no test database available: {exc}")
    yield engine
    await engine.dispose()


@pytest.fixture
async def tracker_session(tracker_engine) -> AsyncGenerator[AsyncSession]:
    """Bound to an outer transaction that is ALWAYS rolled back."""
    connection = await tracker_engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(bind=connection, expire_on_commit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture
def tracker_enabled(monkeypatch) -> None:
    monkeypatch.setenv("NSE_BREAKOUT_ENABLED", "true")
