"""Temporary private-alpha access API."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.alpha_session import AlphaSession

API = settings.API_V1_PREFIX


async def test_alpha_session_starts_anonymous(client: AsyncClient) -> None:
    response = await client.get(f"{API}/alpha/session")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "expires_at": None}


async def test_alpha_unlock_rejects_wrong_code(client: AsyncClient) -> None:
    response = await client.post(f"{API}/alpha/unlock", json={"code": "000000"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "alpha_access_denied"
    assert settings.ALPHA_ACCESS_COOKIE_NAME not in response.cookies


async def test_alpha_unlock_sets_http_only_cookie(client: AsyncClient) -> None:
    response = await client.post(f"{API}/alpha/unlock", json={"code": "619554"})

    assert response.status_code == 201
    assert response.json()["authenticated"] is True
    cookie = response.headers["set-cookie"]
    assert settings.ALPHA_ACCESS_COOKIE_NAME in cookie
    assert "HttpOnly" in cookie
    assert "SameSite" in cookie

    session = await client.get(f"{API}/alpha/session")
    assert session.status_code == 200
    assert session.json()["authenticated"] is True


async def test_unlock_creates_anonymous_session_without_persisting_code(
    client: AsyncClient, db_session
) -> None:
    configured_code = settings.ALPHA_ACCESS_CODE.get_secret_value()
    response = await client.post(f"{API}/alpha/unlock", json={"code": configured_code})
    assert response.status_code == 201

    row = await db_session.scalar(select(AlphaSession))
    assert row is not None
    assert row.current_path == "/"
    assert configured_code not in str(row.__dict__)
    assert "user_agent" not in row.__dict__
    assert "ip_address" not in row.__dict__
    assert "fingerprint" not in row.__dict__
    assert "device_id" not in row.__dict__
    assert "location" not in row.__dict__


async def test_heartbeat_updates_route_and_activity(client: AsyncClient, db_session) -> None:
    await client.post(
        f"{API}/alpha/unlock", json={"code": settings.ALPHA_ACCESS_CODE.get_secret_value()}
    )
    response = await client.post(f"{API}/alpha/activity", json={"path": "/wallet?ignored=yes"})
    assert response.status_code == 204
    row = await db_session.scalar(select(AlphaSession))
    assert row is not None
    assert row.current_path == "/wallet"


async def test_independent_alpha_unlocks_create_independent_anonymous_sessions(
    client: AsyncClient, db_session
) -> None:
    first = await client.post(
        f"{API}/alpha/unlock", json={"code": settings.ALPHA_ACCESS_CODE.get_secret_value()}
    )
    assert first.status_code == 201

    # Clearing the client cookie jar models a separate browser with no shared
    # alpha session. It must receive a different anonymous server-side ID.
    client.cookies.clear()
    second = await client.post(
        f"{API}/alpha/unlock", json={"code": settings.ALPHA_ACCESS_CODE.get_secret_value()}
    )
    assert second.status_code == 201

    rows = list((await db_session.scalars(select(AlphaSession))).all())
    assert len(rows) == 2
    assert len({row.session_id for row in rows}) == 2


async def test_activity_read_requires_account_admin(client: AsyncClient) -> None:
    await client.post(
        f"{API}/alpha/unlock", json={"code": settings.ALPHA_ACCESS_CODE.get_secret_value()}
    )
    response = await client.get(f"{API}/alpha/activity")
    assert response.status_code == 401


async def test_alpha_logout_clears_cookie(client: AsyncClient) -> None:
    await client.post(f"{API}/alpha/unlock", json={"code": "619554"})

    response = await client.post(f"{API}/alpha/logout")

    assert response.status_code == 200
    assert response.json()["message"] == "Alpha access cleared."
    assert settings.ALPHA_ACCESS_COOKIE_NAME in response.headers["set-cookie"]
