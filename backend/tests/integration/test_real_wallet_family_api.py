"""The user wallets' endpoints through the real routes: Karthik's alone.

(USER 1-7 need the family investment password, USER 8-10 and the fees the
users password; the own-wallet switch is tested in
`test_family_wallet_trading.py`.)"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_optional_user
from app.core.config import settings
from app.models.real_wallet_family import RealWalletFamilyMember
from app.models.user import UserRole
from app.real_wallet import family

pytestmark = pytest.mark.integration

URL = f"{settings.API_V1_PREFIX}/real-wallet/family"
COLLECT = {"confirmation_phrase": "COLLECT_FEE"}


@pytest.fixture(autouse=True)
def _password(monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_USERS_PASSWORD_HASH",
                        family.hash_password("right horse", salt=b"s" * 16))
    monkeypatch.setattr(settings, "REAL_WALLET_INVESTMENT_PASSWORD_HASH",
                        family.hash_password("family seven", salt=b"f" * 16))
    monkeypatch.setattr(family, "THROTTLE", family.Throttle(limit=3, window=600))


async def test_the_password_opens_the_view_but_only_the_admin_moves_money(app, db_session):
    """Karthik, 2026-09-30: JUPITER from any browser, signed in or not. The
    password opens the view; every money action still needs the admin."""
    viewer = SimpleNamespace(role=UserRole.USER, email="friend@example.com", is_active=True)
    app.dependency_overrides[get_current_user] = lambda: viewer
    app.dependency_overrides[get_optional_user] = lambda: None     # not signed in at all
    withdraw = {"sol_amount": "0.1", "confirmation_phrase": "WITHDRAW_TO_KARTHIK"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        # The closed box is there for anyone; nothing in it without the password.
        listed = await client.get(URL)
        assert listed.status_code == 200 and listed.json()["members"] == []
        assert (await client.get(f"{URL}/user1")).status_code == 401
        # Money: the admin only, password or not.
        settings_body = {"enabled": True, "ticket_usd": "20"}
        assert (await client.post(f"{URL}/user1/own-settings",
                                  json=settings_body)).status_code == 403
        assert (await client.post(f"{URL}/user1/withdraw", json=withdraw)).status_code == 403
        assert (await client.post(f"{URL}/user2/collect-fee",
                                  json=COLLECT)).status_code == 403

        # (A refused request rolls the test's transaction back, so the rows
        # go in after the refusals.)
        db_session.add_all(RealWalletFamilyMember(name=n) for n in family.MEMBERS)
        await db_session.flush()
        # Not signed in, with the JUPITER password: USER 1-7 open to look at.
        opened = await client.post(f"{URL}/unlock", json={"password": "family seven"})
        assert opened.status_code == 200, opened.text
        seen = {"X-Users-Token": opened.json()["token"]}
        assert [m["member"] for m in (await client.get(URL, headers=seen)).json()["members"]] \
            == [f"USER{i}" for i in range(1, 8)]
        assert (await client.get(f"{URL}/user1", headers=seen)).status_code == 200
        assert (await client.post(f"{URL}/user1/own-settings", json=settings_body,
                                  headers=seen)).status_code == 403
        family.THROTTLE = family.Throttle(limit=3, window=600)
        viewer.role = UserRole.ADMIN
        # Signed in as the admin, but without either password: nothing.
        listed = await client.get(URL)
        assert listed.status_code == 200, listed.text
        assert listed.json()["members"] == []
        assert "fees" not in listed.json() and listed.json()["locked_count"] == 10
        assert (await client.get(f"{URL}/user1")).status_code == 401
        assert (await client.get(f"{URL}/user7")).status_code == 401
        assert (await client.post(f"{URL}/user7/collect-fee",
                                  json=COLLECT)).status_code == 401

        # Wrong passwords are refused, then throttled.
        for _ in range(3):
            wrong = await client.post(f"{URL}/unlock", json={"password": "nope"})
            assert wrong.status_code == 401
        assert (await client.post(f"{URL}/unlock",
                                  json={"password": "right horse"})).status_code == 429
        family.THROTTLE = family.Throttle(limit=3, window=600)

        # The users password: USER 8-10 and the fees, still not USER 1-7.
        opened = await client.post(f"{URL}/unlock", json={"password": "right horse"})
        headers = {"X-Users-Token": opened.json()["token"]}
        listed = await client.get(URL, headers=headers)
        assert [m["member"] for m in listed.json()["members"]] == ["USER8", "USER9", "USER10"]
        assert "collected_usd" in listed.json()["fees"]
        assert (await client.get(f"{URL}/user9", headers=headers)).status_code == 200
        assert (await client.get(f"{URL}/user1", headers=headers)).status_code == 401

        # Then the family investment password, on the same tab: both open.
        opened = await client.post(f"{URL}/unlock", json={"password": "family seven"},
                                   headers=headers)
        assert opened.json()["scopes"] == ["investment", "users"]
        headers = {"X-Users-Token": opened.json()["token"]}
        listed = await client.get(URL, headers=headers)
        assert listed.json()["members"][9]["label"] == "USER 10"
        assert listed.json()["investment_unlocked"] is True
        view = await client.get(f"{URL}/user7", headers=headers)
        assert view.status_code == 200, view.text
        assert (view.json()["member"], view.json()["label"]) == ("USER7", "USER 7")
        assert (await client.get(f"{URL}/user11", headers=headers)).status_code == 404


async def test_wallets_are_compared_side_by_side_today_and_since_start(db_session):
    """Karthik, 2026-10-01: each wallet's results next to the others."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal as D

    from app.models.real_wallet_execution import RealWalletPosition
    from app.real_wallet import views

    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)                 # 16:00 Dubai

    def closed(wallet, opened, pnl):
        return RealWalletPosition(
            mint_address=f"M{opened.timestamp()}{wallet[:4]}", status="CLOSED",
            quantity=D(100), entry_price_usd=D("0.5"), opened_at=opened,
            closed_at=opened + timedelta(minutes=5), wallet_public_key=wallet,
            realised_gross_pnl_usd=D(pnl), realised_net_pnl_usd=D(pnl))
    db_session.add_all([
        closed("MainWallet", now - timedelta(hours=1), "1.50"),
        closed("MainWallet", now - timedelta(days=2), "2.00"),       # before today
        closed("UserOne", now - timedelta(hours=1), "1.00"),
        closed("UserOne", now - timedelta(minutes=30), "-0.40"),
    ])
    await db_session.flush()
    rows = await views.wallet_results(
        db_session, [("Main wallet", "MainWallet"), ("USER 1", "UserOne"),
                     ("USER 2", "NeverTraded")], now)
    main, one, two = rows
    assert (main["today_trades"], main["today_pnl_usd"], main["today_avg_pct"]) == (1, "1.50", "3.00")
    assert (main["all_trades"], main["all_pnl_usd"]) == (2, "3.50")
    assert (one["today_trades"], one["today_won"], one["today_pnl_usd"]) == (2, 1, "0.60")
    assert (two["today_trades"], two["all_pnl_usd"], two["today_avg_pct"]) == (0, "0.00", None)
