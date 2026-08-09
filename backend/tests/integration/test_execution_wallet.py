"""Admin boundary for the read-only execution-wallet surface."""

from __future__ import annotations

from httpx import AsyncClient

from app.core.config import settings
from app.models.user import User, UserRole

API = settings.API_V1_PREFIX


async def test_normal_alpha_or_account_user_cannot_read_execution_wallet(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{API}/real-wallet/status")
    assert response.status_code == 401


async def test_admin_can_read_status_without_secret(
    client: AsyncClient, user: User, db_session
) -> None:
    user.role = UserRole.ADMIN
    await db_session.flush()
    login = await client.post(
        f"{API}/auth/login", json={"email": user.email, "password": "CorrectHorse123!"}
    )
    assert login.status_code == 200

    response = await client.get(
        f"{API}/real-wallet/status",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] in {"disabled", "dry_run"}
    assert body["execution_enabled"] is False
    assert body["autotrade_enabled"] is False
    encoded = str(body).lower()
    assert "secret_file" not in encoded
    assert "private_key" not in encoded
