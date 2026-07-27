"""End-to-end auth flow against a real database."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.user import User

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX


async def test_register_returns_tokens_and_sets_cookie(client: AsyncClient) -> None:
    response = await client.post(
        f"{API}/auth/register",
        json={
            "email": "new@memescope.dev",
            "password": "SuperSecret123!",
            "display_name": "New User",
        },
    )
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "new@memescope.dev"
    assert "password" not in body["user"]

    cookie = response.cookies.get(settings.REFRESH_COOKIE_NAME)
    assert cookie, "refresh token must be delivered as a cookie"
    assert "refresh_token" not in body, "refresh token must never appear in the body"


async def test_register_rejects_duplicate_email(client: AsyncClient, user: User) -> None:
    response = await client.post(
        f"{API}/auth/register",
        json={"email": user.email, "password": "SuperSecret123!"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    response = await client.post(
        f"{API}/auth/register",
        json={"email": "weak@memescope.dev", "password": "short1"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_login_success(client: AsyncClient, user: User) -> None:
    response = await client.post(
        f"{API}/auth/login",
        json={"email": user.email, "password": "CorrectHorse123!"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(user.id)


async def test_login_with_wrong_password_is_401(client: AsyncClient, user: User) -> None:
    response = await client.post(
        f"{API}/auth/login", json={"email": user.email, "password": "not-the-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_error"


async def test_login_for_unknown_email_gives_same_error(client: AsyncClient) -> None:
    """Response must not reveal whether an account exists."""
    response = await client.post(
        f"{API}/auth/login",
        json={"email": "ghost@memescope.dev", "password": "CorrectHorse123!"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Incorrect email or password."


async def test_refresh_rotates_the_token(client: AsyncClient, user: User) -> None:
    login = await client.post(
        f"{API}/auth/login",
        json={"email": user.email, "password": "CorrectHorse123!"},
    )
    original_cookie = login.cookies[settings.REFRESH_COOKIE_NAME]

    refreshed = await client.post(f"{API}/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.cookies[settings.REFRESH_COOKIE_NAME] != original_cookie


async def test_reusing_a_rotated_refresh_token_revokes_everything(
    client: AsyncClient, user: User
) -> None:
    await client.post(
        f"{API}/auth/login",
        json={"email": user.email, "password": "CorrectHorse123!"},
    )
    stolen = client.cookies[settings.REFRESH_COOKIE_NAME]

    assert (await client.post(f"{API}/auth/refresh")).status_code == 200

    # Replay the pre-rotation token, as a thief with a stale copy would.
    client.cookies.set(settings.REFRESH_COOKIE_NAME, stolen, path=settings.REFRESH_COOKIE_PATH)
    replay = await client.post(f"{API}/auth/refresh")
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "token_reuse_detected"


async def test_refresh_without_cookie_is_401(client: AsyncClient) -> None:
    response = await client.post(f"{API}/auth/refresh")
    assert response.status_code == 401


async def test_logout_clears_the_cookie(client: AsyncClient, user: User) -> None:
    await client.post(
        f"{API}/auth/login",
        json={"email": user.email, "password": "CorrectHorse123!"},
    )
    response = await client.post(f"{API}/auth/logout")
    assert response.status_code == 200
    assert not client.cookies.get(settings.REFRESH_COOKIE_NAME)
