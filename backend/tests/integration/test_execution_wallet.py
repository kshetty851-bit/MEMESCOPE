"""Who may use the execution wallet's page.

Decided by the operator on 2026-09-16: reading the wallet, STOP and withdrawing
need only the site code; START and clearing a kill switch need the
administrator account, because they are the only controls a stranger could use
to put the money at risk. Account emails stay with the administrator.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.user import User, UserRole
from app.real_wallet import api as wallet_api
from app.real_wallet.autotrade import AutotradeSwitchService
from app.real_wallet.live_repository import LiveIntentRepository

API = settings.API_V1_PREFIX


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """No price source and no chain: the routes answer from what they have."""
    class NoPrice:
        async def current(self, *, now):
            return None

    async def no_usd(now):
        return None

    monkeypatch.setattr(wallet_api, "JupiterSolUsdPriceSource", NoPrice)
    monkeypatch.setattr(wallet_api, "sol_usd_now", no_usd)


async def _admin_headers(client: AsyncClient, user: User, db_session) -> dict[str, str]:
    user.role = UserRole.ADMIN
    await db_session.flush()
    login = await client.post(
        f"{API}/auth/login", json={"email": user.email, "password": "CorrectHorse123!"}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_the_wallet_can_be_read_without_an_account(client: AsyncClient) -> None:
    for path in ("status", "autotrade", "funding-readiness"):
        response = await client.get(f"{API}/real-wallet/{path}")
        assert response.status_code == 200, (path, response.text)
    body = (await client.get(f"{API}/real-wallet/autotrade")).json()
    assert body["strategy"]["id"] == "G-B3-5M"
    assert body["strategy"]["hold_minutes"] == 5
    assert body["can_start"] is False


async def test_the_site_code_still_guards_every_wallet_route(
    client: AsyncClient, monkeypatch
) -> None:
    """With the gate on, as in production, no cookie means no wallet."""
    monkeypatch.setattr(settings, "ALPHA_ACCESS_REQUIRED", True)
    for path in ("status", "autotrade", "funding-readiness"):
        response = await client.get(f"{API}/real-wallet/{path}")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "alpha_access_required"
    stop = await client.post(f"{API}/real-wallet/autotrade/stop", json={"reason": "x" * 5})
    assert stop.status_code == 401


async def test_starting_needs_the_administrator(client: AsyncClient, db_session) -> None:
    anonymous = await client.post(
        f"{API}/real-wallet/autotrade/start",
        json={"strategy_id": "G-B3-5M", "reason": "no account"},
    )
    assert anonymous.status_code == 401
    assert not (await AutotradeSwitchService(db_session).state()).enabled


async def test_stopping_needs_no_account_and_says_so(client: AsyncClient) -> None:
    response = await client.post(
        f"{API}/real-wallet/autotrade/stop", json={"reason": "from my phone"})
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    assert response.json()["stopped_by"] == "site visitor"


async def test_clearing_a_kill_switch_needs_the_administrator(
    client: AsyncClient, db_session
) -> None:
    # Refused before the route runs; the request's rollback takes the switch
    # with it, so the status code is the evidence.
    await LiveIntentRepository(db_session).activate_kill_switch(
        kind="manual", reason="test", at=datetime.now(UTC), actor="owner@x.com")
    response = await client.post(
        f"{API}/real-wallet/kill-switches/manual/clear",
        json={"confirmation_phrase": "CLEAR_REAL_WALLET_KILL_SWITCH",
              "reason": "no account here"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_error"


async def test_an_email_is_shown_to_the_administrator_only(
    client: AsyncClient, user: User, db_session
) -> None:
    await AutotradeSwitchService(db_session).stop(
        actor="owner@x.com", reason="earlier", at=datetime.now(UTC))
    await db_session.flush()

    anonymous = (await client.get(f"{API}/real-wallet/autotrade")).json()
    assert anonymous["stopped_by"] == "signed-in user"
    assert "owner@x.com" not in str(anonymous)

    headers = await _admin_headers(client, user, db_session)
    owner = (await client.get(f"{API}/real-wallet/autotrade", headers=headers)).json()
    assert owner["stopped_by"] == "owner@x.com"
    assert owner["can_start"] is True


async def test_the_administrator_can_start_the_wallet_strategy(
    client: AsyncClient, user: User, db_session
) -> None:
    headers = await _admin_headers(client, user, db_session)
    response = await client.post(
        f"{API}/real-wallet/autotrade/start", headers=headers,
        json={"strategy_id": "G-B3-5M", "reason": "test start"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["nominated_strategy"] == "G-B3-5M"


async def test_phase_two_manual_devnet_endpoints_require_admin(client: AsyncClient) -> None:
    response = await client.get(f"{API}/real-wallet/devnet/intents")
    assert response.status_code == 401

    response = await client.post(
        f"{API}/real-wallet/devnet/quotes/native-transfer",
        json={"destination_public_key": "11111111111111111111111111111111", "lamports": 1},
    )
    assert response.status_code == 401


async def test_status_carries_no_secret_and_states_today(
    client: AsyncClient, user: User, db_session
) -> None:
    headers = await _admin_headers(client, user, db_session)
    response = await client.get(f"{API}/real-wallet/status", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] in {"disabled", "dry_run"}
    assert body["execution_enabled"] is False
    assert body["autotrade_enabled"] is False
    assert body["network"] == "devnet"
    assert body["rpc"]["verified"] is False
    assert body["today"]["buys"] == 0
    assert Decimal(body["today"]["realised_pnl_usd"]) == 0
    assert body["today"]["loss_limit_hit"] is False
    encoded = str(body).lower()
    assert "secret_file" not in encoded
    assert "private_key" not in encoded
    assert "keypair" not in encoded


async def test_readiness_says_what_a_trade_needs(client: AsyncClient, monkeypatch) -> None:
    async def usd(now):
        return Decimal("100")

    monkeypatch.setattr(wallet_api, "sol_usd_now", usd)
    monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal("100"))
    body = (await client.get(f"{API}/real-wallet/funding-readiness")).json()
    # 0.01 SOL reserve plus $56 or $100 at $100 a SOL.
    assert body["min_trade_sol"] == "0.570"
    assert body["full_trade_sol"] == "1.010"
    checks = {c["key"]: c for c in body["checks"]}
    assert checks["strategy_signals"]["detail"] == "no buy signal recorded yet"
    assert checks["real_round_trip"]["status"] == "BLOCKED"
    assert body["proven"] is False
