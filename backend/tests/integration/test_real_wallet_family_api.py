"""The user wallets' endpoints through the real routes: Karthik's alone.

(The family password and its tokens went on 2026-09-27; the own-wallet switch
is tested in `test_family_wallet_trading.py`.)"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.real_wallet_family import RealWalletFamilyMember
from app.models.user import UserRole
from app.real_wallet import family

pytestmark = pytest.mark.integration

URL = f"{settings.API_V1_PREFIX}/real-wallet/family"


async def test_nobody_but_the_admin_opens_a_user_wallet(app, db_session):
    viewer = SimpleNamespace(role=UserRole.USER, email="friend@example.com", is_active=True)
    app.dependency_overrides[get_current_user] = lambda: viewer
    withdraw = {"sol_amount": "0.1", "confirmation_phrase": "WITHDRAW_TO_KARTHIK"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        # Signed in, but not the admin: every route refuses.
        assert (await client.get(URL)).status_code == 403
        assert (await client.get(f"{URL}/user1")).status_code == 403
        settings_body = {"enabled": True, "ticket_usd": "20"}
        assert (await client.post(f"{URL}/user1/own-settings",
                                  json=settings_body)).status_code == 403
        assert (await client.post(f"{URL}/user1/withdraw", json=withdraw)).status_code == 403

        # (A refused request rolls the test's transaction back, so the rows
        # go in after the refusals.)
        db_session.add_all(RealWalletFamilyMember(name=n) for n in family.MEMBERS)
        await db_session.flush()
        viewer.role = UserRole.ADMIN
        listed = await client.get(URL)
        assert listed.status_code == 200, listed.text
        assert listed.json()["members"][9] == {"member": "USER10", "label": "USER 10"}
        view = await client.get(f"{URL}/user7")
        assert view.status_code == 200, view.text
        assert (view.json()["member"], view.json()["label"]) == ("USER7", "USER 7")
        assert (await client.get(f"{URL}/user11")).status_code == 404
