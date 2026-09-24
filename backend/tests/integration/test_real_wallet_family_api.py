"""The family endpoints, called directly on a real database: the password gate,
one member per token, settings, and money recorded only with the owner."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.config import settings
from app.models.real_wallet_family import RealWalletFamilyMember
from app.real_wallet import family, family_api
from app.real_wallet.family_api import LedgerIn, SettingsIn, UnlockIn

pytestmark = pytest.mark.integration

OWNER = SimpleNamespace(email="owner@example.com")


def _request(ip: str = "203.0.113.9") -> Request:
    return Request({"type": "http", "headers": [(b"x-forwarded-for", ip.encode())],
                    "client": ("127.0.0.1", 1)})


@pytest.fixture(autouse=True)
def _password(monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_FAMILY_PASSWORD_HASH",
                        family.hash_password("right horse", salt=b"s" * 16))
    monkeypatch.setattr(family, "THROTTLE", family.Throttle(limit=3, window=600))
    monkeypatch.setattr(family_api.family, "THROTTLE", family.THROTTLE)


@pytest.fixture
async def members(db_session):
    for name in family.MEMBERS:
        db_session.add(RealWalletFamilyMember(name=name, enabled=False,
                                              ticket_usd=Decimal("25")))
    await db_session.flush()


async def _token(member: str = "JAYA") -> str:
    out = await family_api.unlock(UnlockIn(member=member, password="right horse"), _request())
    return out["token"]


async def test_the_right_password_opens_one_member(members, db_session):
    token = await _token("JAYA")
    view = await family_api.member_view("jaya", db_session, x_family_token=token)
    assert view["member"] == "JAYA" and view["balance_usd"] == "0"
    with pytest.raises(HTTPException) as other:
        await family_api.member_view("ASHA", db_session, x_family_token=token)
    assert other.value.status_code == 401


async def test_no_token_and_wrong_passwords_are_refused_then_throttled(members, db_session):
    with pytest.raises(HTTPException) as none:
        await family_api.member_view("JAYA", db_session, x_family_token=None)
    assert none.value.status_code == 401
    for _ in range(3):
        with pytest.raises(HTTPException) as wrong:
            await family_api.unlock(UnlockIn(member="JAYA", password="wrong"), _request())
        assert wrong.value.status_code == 401
    # Now even the right password waits.
    with pytest.raises(HTTPException) as slow:
        await family_api.unlock(UnlockIn(member="JAYA", password="right horse"), _request())
    assert slow.value.status_code == 429
    # A different caller is unaffected.
    ok = await family_api.unlock(UnlockIn(member="JAYA", password="right horse"),
                                 _request("198.51.100.4"))
    assert ok["member"] == "JAYA"


async def test_a_member_sets_their_own_size_and_switch(members, db_session):
    token = await _token()
    out = await family_api.member_settings(
        "JAYA", SettingsIn(enabled=True, ticket_usd=Decimal("50")), db_session,
        x_family_token=token)
    assert out == {"member": "JAYA", "enabled": True, "ticket_usd": "50"}
    with pytest.raises(HTTPException) as bad:
        await family_api.member_settings(
            "JAYA", SettingsIn(enabled=True, ticket_usd=Decimal("30")), db_session,
            x_family_token=token)
    assert bad.value.status_code == 422


async def test_money_is_recorded_and_a_withdrawal_cannot_exceed_what_is_free(
        members, db_session):
    token = await _token()
    await family_api.member_ledger(
        "JAYA", LedgerIn(kind="deposit", amount_usd=Decimal("100"), note="first"),
        OWNER, db_session, x_family_token=token)
    with pytest.raises(HTTPException) as over:
        await family_api.member_ledger(
            "JAYA", LedgerIn(kind="withdrawal", amount_usd=Decimal("100.01")),
            OWNER, db_session, x_family_token=token)
    assert over.value.status_code == 422
    await family_api.member_ledger(
        "JAYA", LedgerIn(kind="withdrawal", amount_usd=Decimal("40")),
        OWNER, db_session, x_family_token=token)
    view = await family_api.member_view("JAYA", db_session, x_family_token=token)
    assert (view["deposited_usd"], view["withdrawn_usd"], view["available_usd"]) == (
        "100.00", "40.00", "60.00")
    assert [e["kind"] for e in view["ledger"]] == ["withdrawal", "deposit"]
