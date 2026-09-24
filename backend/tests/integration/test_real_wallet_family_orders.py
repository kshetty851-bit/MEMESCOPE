"""Family shares through the real driver: what the wallet actually asks to buy,
and whose money the database says is in it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.labs.graduation import live_decisions
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.models.real_wallet_family import (
    RealWalletFamilyAllocation,
    RealWalletFamilyLedger,
    RealWalletFamilyMember,
)
from app.real_wallet.autotrade import AutotradeSwitchService
from app.real_wallet.driver import RealWalletDriver

pytestmark = pytest.mark.integration

WALLET = "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9"
MINT = "FamilyShareTestMint11111111111111111111pump"


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    async def _price(self, now):
        return Decimal("100")

    monkeypatch.setattr(RealWalletDriver, "_sol_usd", _price)
    for name, value in (
        ("REAL_WALLET_PUBLIC_KEY", WALLET),
        ("REAL_WALLET_ENTRY_SIZE_USD", Decimal("100")),
        ("REAL_WALLET_MAX_TRADE_USD", Decimal("400")),
        ("REAL_WALLET_MAX_TOTAL_EXPOSURE_USD", Decimal("1000")),
        ("REAL_WALLET_MAX_DAILY_NOTIONAL_USD", Decimal("10000")),
        ("REAL_WALLET_BALANCE_CEILING_ENABLED", False),
        ("REAL_WALLET_MIN_SOL_FEE_RESERVE", Decimal("0.01")),
    ):
        monkeypatch.setattr(settings, name, value)


def _funded(monkeypatch, sol: str) -> None:
    async def _lamports(self, wallet):
        return int(Decimal(sol) * 1_000_000_000)

    monkeypatch.setattr(RealWalletDriver, "_wallet_lamports", _lamports)


async def _family(session, *, jaya: tuple[bool, str, str] | None) -> None:
    """(enabled, ticket, deposited) for Jaya; the others exist and are off."""
    for name in ("JAYA", "ASHA", "APOORVA"):
        session.add(RealWalletFamilyMember(name=name, enabled=False, ticket_usd=Decimal("25")))
    await session.flush()
    if jaya:
        on, ticket, deposit = jaya
        row = await session.get(RealWalletFamilyMember, "JAYA")
        row.enabled, row.ticket_usd = on, Decimal(ticket)
        if Decimal(deposit) > 0:
            session.add(RealWalletFamilyLedger(member="JAYA", kind="deposit",
                                               amount_usd=Decimal(deposit)))
    await session.flush()


async def _signal(session, now: datetime) -> None:
    await live_decisions.record(session, [live_decisions.Mirrored(
        strategy_id="G-QUIET", mint=MINT, opened_at=now - timedelta(seconds=5),
        liquidity_usd=Decimal("250000"), impact=None, price_native=Decimal("0.000001"))])
    await AutotradeSwitchService(session).start(
        actor="op@x.com", reason="family share test", strategy_id="G-QUIET", at=now)


async def _order(session):
    intent = (await session.execute(select(RealWalletLiveIntent))).scalars().one()
    shares = {a.member: a.amount_usd for a in (await session.execute(
        select(RealWalletFamilyAllocation))).scalars()}
    return intent, shares


async def test_a_member_who_is_on_and_funded_adds_their_ticket(db_session, monkeypatch):
    _funded(monkeypatch, "3")                      # $300: room for the whole order
    await _family(db_session, jaya=(True, "50", "100"))
    now = datetime.now(UTC)
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.created == 1, out
    intent, shares = await _order(db_session)
    assert intent.requested_usd == Decimal("150")  # the owner's $100 + Jaya's $50
    assert shares == {"JAYA": Decimal("50.00")}


async def test_nobody_on_is_the_old_order_and_writes_no_shares(db_session, monkeypatch):
    _funded(monkeypatch, "3")
    await _family(db_session, jaya=(False, "50", "100"))
    now = datetime.now(UTC)
    await _signal(db_session, now)
    assert (await RealWalletDriver(db_session).tick(now=now)).created == 1
    intent, shares = await _order(db_session)
    assert intent.requested_usd == Decimal("100")
    assert shares == {}


async def test_a_member_with_no_money_recorded_sits_out(db_session, monkeypatch):
    _funded(monkeypatch, "3")
    await _family(db_session, jaya=(True, "50", "0"))
    now = datetime.now(UTC)
    await _signal(db_session, now)
    assert (await RealWalletDriver(db_session).tick(now=now)).created == 1
    intent, shares = await _order(db_session)
    assert intent.requested_usd == Decimal("100")
    assert shares == {}


async def test_short_cash_shrinks_every_share_together(db_session, monkeypatch):
    _funded(monkeypatch, "1.2")                    # $119 spendable after the reserve
    await _family(db_session, jaya=(True, "50", "100"))
    now = datetime.now(UTC)
    await _signal(db_session, now)
    assert (await RealWalletDriver(db_session).tick(now=now)).created == 1
    intent, shares = await _order(db_session)
    assert intent.requested_usd == Decimal("119.00")
    # Jaya owned 50 of 150; she owns the same third of the smaller order.
    assert shares == {"JAYA": Decimal("39.66")}


async def test_when_the_family_order_cannot_be_funded_the_owner_still_trades(
        db_session, monkeypatch):
    # $80 spendable: under the $84 floor of a $150 order, over the $56 floor of
    # the owner's own $100. The family sits out; the owner's trade still happens.
    _funded(monkeypatch, "0.81")
    await _family(db_session, jaya=(True, "50", "100"))
    now = datetime.now(UTC)
    await _signal(db_session, now)
    assert (await RealWalletDriver(db_session).tick(now=now)).created == 1
    intent, shares = await _order(db_session)
    assert intent.requested_usd == Decimal("80.00")
    assert shares == {}
