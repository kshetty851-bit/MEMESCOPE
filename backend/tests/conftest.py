"""Shared test fixtures.

Integration tests run against a real Postgres and Redis (the `test-db` and
`redis` services in docker-compose). Each test gets a transaction that is rolled
back afterwards, so tests never see each other's rows and can run in any order.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Settings are imported lazily so pytest-env has applied the test environment.
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models import User

# Swap only the trailing database name. A plain `.replace()` would also rewrite
# the username when it happens to match the database name.
_dsn_prefix, _, _ = settings.DATABASE_URI.rpartition("/")
TEST_DATABASE_URI = os.getenv(
    "TEST_DATABASE_URI",
    f"{_dsn_prefix}/{os.getenv('TEST_POSTGRES_DB', f'{settings.POSTGRES_DB}_test')}",
)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
async def engine() -> AsyncGenerator:
    eng = create_async_engine(TEST_DATABASE_URI, poolclass=None, future=True)
    async with eng.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession]:
    """A session bound to an outer transaction that is always rolled back."""
    connection = await engine.connect()
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
async def test_session_factory(engine, monkeypatch: pytest.MonkeyPatch):
    """Point modules that open their own sessions at the *test* database.

    Workers deliberately create sessions via `SessionFactory` rather than
    receiving one, so without this they would read and write the development
    database — where a live worker is also running and competing for the same
    rows. Patching the factory keeps those tests isolated and deterministic.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    # Each module that imports `SessionFactory` by name binds it at import time,
    # so patching `app.db.session` alone leaves those bindings pointing at the
    # development database. Every such module has to be patched explicitly.
    monkeypatch.setattr("app.services.market.worker.SessionFactory", factory)
    monkeypatch.setattr("app.workers.scoring_tasks.SessionFactory", factory)
    monkeypatch.setattr("app.opportunities.scheduler.SessionFactory", factory)
    monkeypatch.setattr("app.db.session.SessionFactory", factory)
    return factory


@pytest.fixture
async def app(db_session: AsyncSession):
    """App instance with the DB dependency pointed at the test transaction."""
    application = create_app()

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_db] = _override_get_db
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient]:
    """HTTP client that drives the ASGI app in-process (no network, no server).

    `LifespanManager`-free: we initialise Redis explicitly instead, so a test
    that does not need Redis is not slowed down by full app startup.
    """
    from app.core.redis import close_redis, init_redis

    await init_redis()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=True
    ) as async_client:
        yield async_client
    await close_redis()


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    entity = User(
        email="trader@memescope.dev",
        hashed_password=hash_password("CorrectHorse123!"),
        display_name="Test Trader",
        is_verified=True,
    )
    db_session.add(entity)
    await db_session.flush()
    await db_session.refresh(entity)
    return entity


@pytest.fixture
async def auth_headers(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post(
        f"{settings.API_V1_PREFIX}/auth/login",
        json={"email": user.email, "password": "CorrectHorse123!"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
