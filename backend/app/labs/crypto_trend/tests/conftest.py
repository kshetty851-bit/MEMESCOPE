"""Database fixtures for the lab's own integration tests.

Deliberately its OWN engine fixture rather than the repo's, exactly as the
Rafiq lab does it: the repo's `tests/conftest.py` DROPS and recreates the
platform schema on every session; this one only ever creates what is missing.

Marked `integration`: it needs Postgres, and is skipped cleanly without one.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base
from app.labs.crypto_trend import models  # noqa: F401 — registers ct_* on Base

_prefix, _, _ = settings.DATABASE_URI.rpartition("/")
TEST_DATABASE_URI = os.getenv(
    "TEST_DATABASE_URI",
    f"{_prefix}/{os.getenv('TEST_POSTGRES_DB', f'{settings.POSTGRES_DB}_test')}",
)


@pytest.fixture(scope="session")
async def lab_engine() -> AsyncGenerator:
    try:
        engine = create_async_engine(TEST_DATABASE_URI, poolclass=None, future=True)
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment, not logic
        pytest.skip(f"no test database available: {exc}")
    yield engine
    await engine.dispose()


@pytest.fixture
async def lab_session(lab_engine) -> AsyncGenerator[AsyncSession]:
    """Bound to an outer transaction that is ALWAYS rolled back."""
    connection = await lab_engine.connect()
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
def lab_enabled(monkeypatch) -> None:
    monkeypatch.setenv("CRYPTO_TREND_LAB_ENABLED", "true")
