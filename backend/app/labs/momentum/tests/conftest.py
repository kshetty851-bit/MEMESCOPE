"""A database for this lab's tables and nothing else, skipped when there is no
Postgres. The platform's `tests/conftest.py` drops and rebuilds every table;
this one only ever touches `mom_*`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.labs.momentum import models  # noqa: F401  (registers the tables)

TEST_DSN = os.getenv(
    "MOMENTUM_LAB_TEST_DATABASE_URI",
    "postgresql+asyncpg://memescope:memescope@localhost:5432/momentum_lab_test",
)
_TABLES = [t for name, t in Base.metadata.tables.items() if name.startswith("mom_")]


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    eng = create_async_engine(TEST_DSN, future=True)
    try:
        async with eng.begin() as conn:
            await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            await conn.run_sync(Base.metadata.drop_all, tables=_TABLES)
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    except Exception as exc:  # no Postgres here
        await eng.dispose()
        pytest.skip(f"no test database: {type(exc).__name__}")
    factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await eng.dispose()
