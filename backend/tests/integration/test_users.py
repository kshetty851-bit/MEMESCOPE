"""Protected profile routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.user import User

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX


async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get(f"{API}/users/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_error"


async def test_me_rejects_a_garbage_token(client: AsyncClient) -> None:
    response = await client.get(
        f"{API}/users/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


async def test_me_returns_the_current_user(
    client: AsyncClient, user: User, auth_headers: dict[str, str]
) -> None:
    response = await client.get(f"{API}/users/me", headers=auth_headers)
    assert response.status_code == 200

    body = response.json()
    assert body["email"] == user.email
    assert body["role"] == "user"
    assert "hashed_password" not in body


async def test_update_profile(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.patch(
        f"{API}/users/me", headers=auth_headers, json={"display_name": "Degen Prime"}
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Degen Prime"


async def test_change_password_requires_the_current_one(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        f"{API}/users/me/password",
        headers=auth_headers,
        json={"current_password": "wrong", "new_password": "BrandNewPass123!"},
    )
    assert response.status_code == 401
