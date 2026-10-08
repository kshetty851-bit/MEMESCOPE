"""USER wallets' daily boxes count every closed trade, not the latest 100
(Karthik, 2026-10-08: the boxes showed only the two newest days)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.real_wallet_execution import RealWalletPosition
from app.real_wallet.family_api import _own_book

pytestmark = pytest.mark.integration

WALLET = "UserOneWallet"


def closed(mint: str, at: datetime) -> RealWalletPosition:
    return RealWalletPosition(
        mint_address=mint, status="CLOSED", quantity=Decimal(100),
        entry_price_usd=Decimal("0.1"), opened_at=at - timedelta(minutes=5), closed_at=at,
        wallet_public_key=WALLET, entry_actual_input_amount=Decimal("0.05"),
        exit_actual_output_amount=Decimal("0.051"), realised_net_pnl_usd=Decimal("0.10"))


async def test_the_days_count_every_trade_not_the_latest_hundred(db_session):
    today = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0)
    db_session.add_all([closed(f"D{d}-{i}", today - timedelta(days=d, minutes=i))
                        for d in range(3) for i in range(60)])  # 180 trades, 3 days
    await db_session.flush()
    days = (await _own_book(db_session, "USER1", WALLET))["days"]
    assert sum(d["trades"] for d in days) == 180
    assert [d["trades"] for d in days[-2:]] == [60, 60]
