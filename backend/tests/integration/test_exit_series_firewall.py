"""A print the ingest firewall distrusts must never close a position.

Regression for the ANTFUN exit of 2026-08-25: a pair-switch print of
$0.00000025 against a $0.0418 high stopped a live position out. The firewall
had already flagged the row; the exit series handed it over anyway.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.token import DiscoveredToken
from app.repositories.market import MarketSnapshotRepository

NOW = datetime.now(UTC)


async def _seed_series(session: AsyncSession) -> str:
    mint = f"EXIT{uuid.uuid4().hex}"[:44]
    token = DiscoveredToken(
        mint_address=mint, signature=f"sig:{mint}", slot=1,
        source_program="test", block_time=NOW - timedelta(days=30), symbol="ANTFUNISH",
    )
    session.add(token)
    await session.flush()
    rows = [
        # good, good, then the pair-switch glitch the firewall caught
        (300, Decimal("0.04177"), Decimal("38711128"), False, None),
        (200, Decimal("0.04180"), Decimal("38730000"), False, None),
        (100, Decimal("0.00000025"), Decimal("7673010"), True, "price_band_low"),
    ]
    for ago, price, liq, suspect, why in rows:
        session.add(
            TokenMarketSnapshot(
                token_id=token.id, mint_address=mint,
                captured_at=NOW - timedelta(seconds=ago),
                price_usd=price, liquidity_usd=liq,
                trading_status=TradingStatus.TRADING,
                suspect=suspect, suspect_reason=why, provider="dexscreener",
            )
        )
    await session.flush()
    return mint


async def test_a_flagged_print_never_reaches_the_exit_rule(
    db_session: AsyncSession,
) -> None:
    mint = await _seed_series(db_session)
    series = await MarketSnapshotRepository(db_session).series_for_mints(
        [mint], since=NOW - timedelta(hours=1)
    )
    prices = [row.price_usd for row in series[mint]]

    assert Decimal("0.00000025") not in prices, (
        "the flagged pair-switch print reached the exit series and would stop the position out"
    )
    assert prices == [Decimal("0.04177"), Decimal("0.04180")]


async def test_the_honest_readings_still_arrive_oldest_first(
    db_session: AsyncSession,
) -> None:
    """The firewall must not cost the series its ordering — an exit is decided
    by the FIRST reading that breached, so order is part of correctness."""
    mint = await _seed_series(db_session)
    series = await MarketSnapshotRepository(db_session).series_for_mints(
        [mint], since=NOW - timedelta(hours=1)
    )
    captured = [row.captured_at for row in series[mint]]
    assert captured == sorted(captured)
