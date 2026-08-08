"""Temporary private-alpha access API."""

from __future__ import annotations

from httpx import AsyncClient

from app.core.config import settings

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


async def test_alpha_logout_clears_cookie(client: AsyncClient) -> None:
    await client.post(f"{API}/alpha/unlock", json={"code": "619554"})

    response = await client.post(f"{API}/alpha/logout")

    assert response.status_code == 200
    assert response.json()["message"] == "Alpha access cleared."
    assert settings.ALPHA_ACCESS_COOKIE_NAME in response.headers["set-cookie"]
