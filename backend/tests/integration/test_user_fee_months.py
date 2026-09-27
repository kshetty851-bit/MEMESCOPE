"""Charging each user wallet's month on a real database, and the collect button's
refusals. (The signer's side is in tests/unit/test_user_fees.py.)"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from solders.keypair import Keypair

from app.core.config import settings
from app.models.real_wallet_execution import RealWalletPosition
from app.models.real_wallet_family import RealWalletFamilyMember, RealWalletUserFee
from app.real_wallet import user_fees, withdraw_service

pytestmark = pytest.mark.integration

A, B = str(Keypair().pubkey()), str(Keypair().pubkey())
D = Decimal


@pytest.fixture(autouse=True)
def _wallets(monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", str(Keypair().pubkey()))
    monkeypatch.setattr(settings, "REAL_WALLET_WITHDRAWAL_ADDRESS", str(Keypair().pubkey()))
    monkeypatch.setattr(settings, "REAL_WALLET_FAMILY_WALLETS", f"user1={A},user2={B}")


async def _setup(session) -> None:
    session.add_all([RealWalletFamilyMember(name="USER1", fee_rate=D(0)),
                     RealWalletFamilyMember(name="USER2", fee_rate=D("0.20"))])
    await session.flush()


def _closed(wallet: str, pnl: str, at: datetime, mint: str) -> RealWalletPosition:
    return RealWalletPosition(mint_address=mint, status="CLOSED", quantity=D(1),
                              entry_price_usd=D(50), opened_at=at, closed_at=at,
                              realised_net_pnl_usd=D(pnl), wallet_public_key=wallet)


async def _charge(session, *when: int) -> dict[str, RealWalletUserFee]:
    return {r.member: r for r in await user_fees.charge(session, datetime(*when, tzinfo=UTC))}


async def test_each_month_charges_only_new_profit(db_session):
    await _setup(db_session)
    sep = datetime(2026, 9, 28, tzinfo=UTC)
    db_session.add_all([_closed(A, "40", sep, "m1"), _closed(B, "40", sep, "m2"),
                        _closed(B, "-10", sep, "m3")])
    await db_session.flush()

    rows = await _charge(db_session, 2026, 10, 1, 5)
    assert (rows["USER2"].profit_usd, rows["USER2"].fee_usd, rows["USER2"].status) == (
        D("30.00"), D("6.00"), "due")
    assert (rows["USER1"].fee_usd, rows["USER1"].status) == (D("0.00"), "none")
    # Idempotent: reading the page again charges nothing new.
    assert await user_fees.charge(db_session, datetime(2026, 10, 9, tzinfo=UTC)) == []

    # October loses 20: total 10, below the 30 mark, so no fee and the mark holds.
    db_session.add(_closed(B, "-20", datetime(2026, 10, 15, tzinfo=UTC), "m4"))
    await db_session.flush()
    octo = await _charge(db_session, 2026, 11, 2)
    assert (octo["USER2"].fee_usd, octo["USER2"].hwm_after_usd) == (D(0), D("30.00"))

    # November makes 50: total 60, 30 above the mark -> 20% of 30.
    db_session.add(_closed(B, "50", datetime(2026, 11, 20, tzinfo=UTC), "m5"))
    await db_session.flush()
    nov = await _charge(db_session, 2026, 12, 1)
    assert (nov["USER2"].fee_usd, nov["USER2"].hwm_after_usd) == (D("6.00"), D("60.00"))

    summary = await user_fees.summary(db_session)
    assert (summary["collected_usd"], summary["waiting_usd"]) == ("0.00", "12.00")


async def test_collect_refuses_without_a_fee_or_while_the_wallet_trades(db_session):
    await _setup(db_session)
    with pytest.raises(withdraw_service.WithdrawError, match="no_fee_due"):
        await user_fees.collect(db_session, "USER2", sol_usd=D(100), rpc=None, signer=None)

    db_session.add(RealWalletUserFee(
        member="USER2", wallet=B, period=datetime(2026, 9, 1).date(), profit_usd=D(30),
        hwm_before_usd=D(0), hwm_after_usd=D(30), fee_rate=D("0.2"), fee_usd=D(6),
        status="due"))
    db_session.add(RealWalletPosition(mint_address="held", status="OPEN", quantity=D(1),
                                      entry_price_usd=D(1), opened_at=datetime.now(UTC),
                                      wallet_public_key=B))
    await db_session.flush()
    with pytest.raises(withdraw_service.WithdrawError, match="wallet_is_trading"):
        await user_fees.collect(db_session, "USER2", sol_usd=D(100), rpc=None, signer=None)
    row = (await db_session.execute(
        RealWalletUserFee.__table__.select().where(RealWalletUserFee.member == "USER2"))).one()
    assert row.status == "due"
