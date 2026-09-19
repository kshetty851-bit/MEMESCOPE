"""One momentum candle through the whole book: judged once, bought on the NEXT
price, stopped, pulled back into, and timed out — against a real database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.labs.momentum import api, config
from app.labs.momentum.lab import MomentumLab
from app.labs.momentum.models import MomCandle, MomClose, MomPair, MomPosition
from app.labs.momentum.sources import PairRow

B = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
FIVE = timedelta(minutes=5)
PAIR = "Pair1111111111111111111111111111111111111111"
MINT = "Mint111111111111111111111111111111111111111"
D = Decimal


class FakeFeeds:
    """The next price for the pool, fetched one second into the tick."""

    def __init__(self) -> None:
        self.calls = {"dex": 0, "jup": 0}
        self.failures = 0
        self.price = D("1.05")
        self.now = B

    async def pairs(self, addresses):
        self.calls["dex"] += 1
        return {PAIR: PairRow(
            pair_address=PAIR, base_mint=MINT, quote_mint=config.WSOL_MINT,
            symbol="MOMO", dex_id="raydium", price_usd=self.price,
            price_native=self.price / 100, liquidity=D(500_000), volume_m5=D(5_000),
            volume_h1=D(20_000), volume_h24=D(288_000), buys_m5=30, sells_m5=10,
            change_m5=D(5), change_h1=D(1), change_h24=D(5), market_cap=D(10_000_000),
            created_at=B - timedelta(days=60), fetched_at=self.now + timedelta(seconds=1))}


async def _seed(session) -> None:
    session.add(MomPair(pair_address=PAIR, mint=MINT, symbol="MOMO", dex_id="raydium",
                        quote_mint=config.WSOL_MINT, born_at=B - timedelta(days=60),
                        status="active", admitted_at=B - timedelta(days=1),
                        listed_at=B, last_price=D("1.05"),
                        last_sample_at=B + FIVE - timedelta(seconds=1)))
    price = D(1)
    for i in range(48, 0, -1):
        close = price * (D("1.002") if i % 2 else D("0.998"))
        session.add(MomCandle(pair_address=PAIR, start=B - i * FIVE, open=price,
                              high=max(price, close), low=min(price, close), close=close,
                              volume_usd=D(1_000), buys=10, sells=10, volume_h24=D(288_000),
                              liquidity_usd=D(500_000), change_h24=D(5), samples=10))
        price = close
    # THE momentum candle: +5% on 5x volume, closing at its high, 3 buys a sell.
    session.add(MomCandle(pair_address=PAIR, start=B, open=price, high=price * D("1.05"),
                          low=price * D("0.995"), close=price * D("1.05"),
                          volume_usd=D(5_000), buys=30, sells=10, volume_h24=D(288_000),
                          liquidity_usd=D(500_000), change_h24=D(5), samples=10))
    await session.commit()


async def _tick(session, feeds: FakeFeeds, at: datetime, price: str) -> dict:
    feeds.now, feeds.price = at, D(price)
    result = await MomentumLab(session, feeds=feeds, now=at).tick()
    await session.commit()
    return result


async def _positions(session) -> dict[str, MomPosition]:
    rows = (await session.scalars(select(MomPosition))).all()
    return {p.arm: p for p in rows}


async def test_a_momentum_candle_through_the_book(session, monkeypatch) -> None:
    monkeypatch.setenv("LAB_MOMENTUM_ENABLED", "true")
    await _seed(session)
    feeds = FakeFeeds()
    t1 = B + FIVE + timedelta(seconds=config.FEED_LAG_S + 3)

    # --- tick 1: the 5m bar at B has closed; every rule it meets decides -----
    first = await _tick(session, feeds, t1, "1.05")
    assert first["judged"]["5m"]["eligible"] == 1
    book = await _positions(session)
    for arm in ("M5_BASE", "M5_BREAKOUT", "M5_FIRST", "M5_TREND", "M5_LIQ_M",
                "M5_AGE_6M", "X5_HOLD3", "X5_MID_2R", "X5_TRAIL5",
                "R5_SAME", "R5_TIME", "R5_GREEN", "CATCH_4"):
        assert book[arm].status == "pending", arm
        assert book[arm].opened_at is None, "never filled on the price it decided on"
    assert book["M5_PULLBACK"].status == "armed"
    for arm in ("M5_HUGE", "M5_VOL6", "M5_SECOND", "M5_COUNTER", "M5_LIQ_S",
                "M5_AGE_1M", "M5_CONFIRM", "DIP5", "CATCH_8"):
        assert arm not in book, arm
    closes = (await session.execute(select(MomClose.fired).where(
        MomClose.tf == "5m", MomClose.start == B))).scalar_one()
    assert closes["M5_BASE"] == 1

    # --- tick 2: filled at THIS price; the bar is not judged twice ---------------
    t2 = t1 + timedelta(seconds=30)
    second = await _tick(session, feeds, t2, "1.06")
    assert "5m" not in second["judged"]
    book = await _positions(session)
    base = book["M5_BASE"]
    assert base.status == "open" and base.open_price == D("1.06")
    assert base.open_fill > D("1.06"), "fees and impact on the way in"
    assert base.opened_at == t2 + timedelta(seconds=1 - config.FEED_LAG_S)
    assert book["M5_PULLBACK"].status == "armed", "1.06 is above the midpoint"
    assert (await session.scalar(select(func.count()).select_from(MomPosition)
                                 .where(MomPosition.arm == "CATCH_4"))) == 1, \
        "one position per pool per strategy"

    # --- tick 3: under the candle's midpoint -------------------------------------
    t3 = t2 + timedelta(seconds=30)
    await _tick(session, feeds, t3, "1.02")
    book = await _positions(session)
    assert book["X5_MID_2R"].status == "closing"
    assert book["X5_MID_2R"].exit_reason == "stop"
    assert book["X5_LOW_2R"].status == "open", "the low is further down"
    assert book["M5_PULLBACK"].status == "pending", "dipped to the midpoint"

    # --- tick 4: the stop sells on the NEXT price, the pullback buys on it -------
    t4 = t3 + timedelta(seconds=30)
    await _tick(session, feeds, t4, "1.00")
    book = await _positions(session)
    stopped = book["X5_MID_2R"]
    assert stopped.status == "closed" and stopped.close_price == D("1.00")
    assert stopped.net_return < D("-0.05")
    assert book["M5_PULLBACK"].status == "open"
    assert book["M5_PULLBACK"].open_price == D("1.00")
    assert book["X5_TRAIL5"].status == "closing", "5% off the 1.06 high"

    # --- tick 5: thirty minutes after the fill, the clock sells ------------------
    t5 = t2 + timedelta(minutes=31)
    await _tick(session, feeds, t5, "1.10")
    book = await _positions(session)
    base = book["M5_BASE"]
    assert base.status == "closed" and base.exit_reason == "time"
    gross = D("1.10") / D("1.06") - 1
    assert gross - D("0.009") < base.net_return < gross - D("0.006"), "the toll, both legs"
    assert book["X5_HOLD12"].status == "open", "an hour has not passed"

    board = await api.leaderboard(db=session)
    rows = {r.name: r for r in board.arms}
    assert len(rows) == 50
    assert rows["M5_BASE"].trades == 1
    assert rows["M5_BASE"].wallet.end == pytest.approx(
        1000 + float(base.net_return) * 100, abs=0.01)
    assert rows["X5_MID_2R"].wallet.end < 1000
