"""The graduation arm, through the real driver, on a $100 wallet.

A fixed $100 ticket against a 0.01 SOL fee reserve meant a wallet funded with
exactly $100 refused every entry. These drive a real decision through a real
tick and check the size the wallet actually asks for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.labs.graduation import live_decisions
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.real_wallet.autotrade import AutotradeSwitchService
from app.real_wallet.driver import RealWalletDriver

pytestmark = pytest.mark.integration

WALLET = "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9"
MINT = "9oizAnSAGradSizingTestMint1111111111111pump"


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    async def _price(self, now):
        return Decimal("100")

    monkeypatch.setattr(RealWalletDriver, "_sol_usd", _price)
    for name, value in (
        ("REAL_WALLET_PUBLIC_KEY", WALLET),
        ("REAL_WALLET_ENTRY_SIZE_USD", Decimal("100")),
        ("REAL_WALLET_MAX_TRADE_USD", Decimal("100")),
        ("REAL_WALLET_MAX_TOTAL_EXPOSURE_USD", Decimal("600")),
        ("REAL_WALLET_MAX_DAILY_NOTIONAL_USD", Decimal("10000")),
        ("REAL_WALLET_BALANCE_CEILING_ENABLED", False),
        ("REAL_WALLET_MIN_SOL_FEE_RESERVE", Decimal("0.01")),
    ):
        monkeypatch.setattr(settings, name, value)


def _funded(monkeypatch, sol: str) -> None:
    async def _lamports(self, wallet):
        return int(Decimal(sol) * 1_000_000_000)

    monkeypatch.setattr(RealWalletDriver, "_wallet_lamports", _lamports)


async def _signal(session, now: datetime) -> None:
    await live_decisions.record(session, [live_decisions.Mirrored(
        mint=MINT, opened_at=now - timedelta(seconds=5),
        liquidity_usd=Decimal("250000"), impact=None,
        price_native=Decimal("0.000001"))])
    await AutotradeSwitchService(session).start(
        actor="op@x.com", reason="graduation sizing test",
        strategy_id="G-B3-5M", at=now)


async def test_a_hundred_dollar_wallet_buys_what_the_reserve_leaves(db_session, monkeypatch):
    _funded(monkeypatch, "1")
    now = datetime.now(UTC)
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert out.created == 1, out
    intent = (await db_session.execute(select(RealWalletLiveIntent))).scalars().one()
    assert intent.requested_usd == Decimal("99.00")
    # 0.99 SOL: exactly the 0.01 SOL reserve stays behind.
    assert intent.actual_input_amount_raw == 990_000_000


async def test_a_wallet_under_the_floor_stops_like_the_board(db_session, monkeypatch):
    _funded(monkeypatch, "0.5")
    now = datetime.now(UTC)
    await _signal(db_session, now)
    out = await RealWalletDriver(db_session).tick(now=now)
    assert (out.created, out.skipped) == (0, "entry_not_fundable")
    assert (await db_session.execute(select(RealWalletLiveIntent))).first() is None
