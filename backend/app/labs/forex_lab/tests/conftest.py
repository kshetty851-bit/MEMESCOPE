"""A database for this lab's tables and nothing else.

The platform's own `tests/conftest.py` builds the entire schema, which means a
lab test would depend on every model in the repo staying importable. This lab
creates its own two tables in its own database instead — which is the same
independence the package claims everywhere else, held in the test harness too.

Skips rather than fails when no Postgres is reachable: the engine tests are the
ones that gate the sweep, and they need no database at all.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.labs.forex_lab.models import FxCandle, FxIngestHour  # noqa: F401

TEST_DSN = os.getenv(
    "FOREX_LAB_TEST_DATABASE_URI",
    "postgresql+asyncpg://memescope:memescope@localhost:5432/forex_lab_test",
)
_TABLES = [Base.metadata.tables["fx_candles"], Base.metadata.tables["fx_ingest_hours"]]


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    eng = create_async_engine(TEST_DSN, future=True)
    try:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all, tables=_TABLES)
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    except Exception as exc:  # no Postgres here
        await eng.dispose()
        pytest.skip(f"no test database: {type(exc).__name__}")
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await eng.dispose()


@pytest.fixture
def session_factory():
    """A factory the loader can open its own short transactions from."""
    eng = create_async_engine(TEST_DSN, future=True)
    yield async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
