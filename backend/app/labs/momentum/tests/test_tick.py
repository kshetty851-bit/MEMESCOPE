"""One momentum candle through the whole book: judged once, bought on the NEXT
price, taken at the take profit and timed out — against a real database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update

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
        self.buys, self.sells = 30, 10
        self.dex = "raydium"

    async def pairs(self, addresses):
        self.calls["dex"] += 1
        return {PAIR: PairRow(
            pair_address=PAIR, base_mint=MINT, quote_mint=config.WSOL_MINT,
            symbol="MOMO", dex_id="raydium", price_usd=self.price,
            price_native=self.price / 100, liquidity=D(500_000), volume_m5=D(5_000),
            volume_h1=D(20_000), volume_h24=D(288_000), buys_m5=self.buys, sells_m5=self.sells,
            change_m5=D(5), change_h1=D(1), change_h24=D(5), market_cap=D(10_000_000),
            created_at=B - timedelta(days=60), fetched_at=self.now + timedelta(seconds=1))}


async def _seed(session, *, buys: int = 30, sells: int = 10) -> None:
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
                          volume_usd=D(5_000), buys=buys, sells=sells, volume_h24=D(288_000),
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
    assert set(first["judged"]) == {"5m"}, "run 2 judges 5m bars only"
    book = await _positions(session)
    for arm in ("BASE_60", "BASE_TP15", "RND_60", "RND_TP15"):
        assert book[arm].status == "pending", arm
        assert book[arm].opened_at is None, "never filled on the price it decided on"
    # 5% is not the quiet end, $500k is not a deep pool, the coin is UP on the
    # day, and the candle is green — so four arms and one control stand off.
    for arm in ("QUIET_60", "QUIET_TP15", "DEEP_60", "DEEP_TP15",
                "DOWN_60", "DOWN_TP15", "SNAP_60", "SNAP_6H", "RND_DOWN"):
        assert arm not in book, arm
    closes = (await session.execute(select(MomClose.fired).where(
        MomClose.tf == "5m", MomClose.start == B))).scalar_one()
    assert closes["BASE_60"] == 1

    # --- tick 2: filled at THIS price; the bar is not judged twice ---------------
    t2 = t1 + timedelta(seconds=30)
    second = await _tick(session, feeds, t2, "1.06")
    assert "5m" not in second["judged"]
    book = await _positions(session)
    base = book["BASE_60"]
    assert base.status == "open" and base.open_price == D("1.06")
    assert base.open_fill > D("1.06"), "fees and impact on the way in"
    assert base.opened_at == t2 + timedelta(seconds=1 - config.FEED_LAG_S)
    assert (await session.scalar(select(func.count()).select_from(MomPosition)
                                 .where(MomPosition.arm == "BASE_60"))) == 1, \
        "one position per pool per strategy"

    # the open book values what is held, at what selling it now would fetch
    book_now = await api.open_book(db=session)
    held = {r.arm: r for r in book_now.positions}
    assert held["BASE_60"].value_usd is not None
    assert held["BASE_60"].value_usd < float(config.TICKET_USD), "the toll, on the way out"
    assert held["BASE_60"].move_pct == pytest.approx(0.0, abs=0.01), "1.06 is the fill"
    assert held["BASE_60"].due_at == base.opened_at + timedelta(minutes=60)
    assert held["BASE_TP15"].target_pct == 15
    assert book_now.staked_usd == pytest.approx(4 * float(config.TICKET_USD)), \
        "two strategies and two controls are holding"
    assert book_now.value_usd < book_now.staked_usd

    # --- tick 3: +18%, so the take profit decides and the hour arm runs on -------
    t3 = t2 + timedelta(seconds=30)
    await _tick(session, feeds, t3, "1.25")
    book = await _positions(session)
    assert book["BASE_TP15"].status == "closing"
    assert book["BASE_TP15"].exit_reason == "take_profit"
    assert book["BASE_60"].status == "open", "its only exit is the clock"

    # --- tick 4: the sale fills on the NEXT price, never the one that decided ----
    t4 = t3 + timedelta(seconds=30)
    await _tick(session, feeds, t4, "1.24")
    book = await _positions(session)
    sold = book["BASE_TP15"]
    assert sold.status == "closed" and sold.close_price == D("1.24")
    gross = D("1.24") / D("1.06") - 1
    assert gross - D("0.009") < sold.net_return < gross - D("0.006"), "the toll, both legs"

    # --- tick 5: an hour after the fill, the clock sells ------------------------
    t5 = t2 + timedelta(minutes=61)
    await _tick(session, feeds, t5, "1.10")
    book = await _positions(session)
    base = book["BASE_60"]
    assert base.status == "closed" and base.exit_reason == "time"
    gross = D("1.10") / D("1.06") - 1
    assert gross - D("0.009") < base.net_return < gross - D("0.006"), "the toll, both legs"

    board = await api.leaderboard(db=session)
    rows = {r.name: r for r in board.arms}
    assert len(rows) == 13
    assert rows["BASE_60"].trades == 1
    start, ticket = float(config.START_USD), float(config.TICKET_USD)
    assert rows["BASE_60"].wallet.end == pytest.approx(
        start + float(base.net_return) * ticket, abs=0.01)
    assert rows["BASE_TP15"].wallet.end > start


async def test_an_expensive_pool_is_never_judged(session, monkeypatch) -> None:
    """pump.fun's AMM charged 185 bps a round trip in run 1 and its coins fell
    more. The gate sits before the judging, so the controls cannot draw from
    there either — both still trade one population."""
    monkeypatch.setenv("LAB_MOMENTUM_ENABLED", "true")
    await _seed(session)
    await session.execute(update(MomPair).values(dex_id="pumpswap"))
    await session.commit()
    feeds = FakeFeeds()
    feeds.dex = "pumpswap"
    first = await _tick(session, feeds, B + FIVE + timedelta(seconds=config.FEED_LAG_S + 3),
                        "1.05")
    assert first["judged"]["5m"]["eligible"] == 0
    assert (await session.scalar(select(func.count()).select_from(MomPosition))) == 0


async def test_a_candle_made_by_two_buyers_is_not_momentum(session, monkeypatch) -> None:
    """The lab's first live trade: +9.5% on two buys. Same candle, same price
    move, same volume multiple - but two trades, so nothing may judge it, the
    controls included, and the rolling rule may not buy the window either."""
    monkeypatch.setenv("LAB_MOMENTUM_ENABLED", "true")
    await _seed(session, buys=2, sells=0)
    feeds = FakeFeeds()
    feeds.buys, feeds.sells = 2, 0
    first = await _tick(session, feeds, B + FIVE + timedelta(seconds=config.FEED_LAG_S + 3),
                        "1.05")
    assert first["judged"]["5m"]["eligible"] == 0
    assert (await session.scalar(select(func.count()).select_from(MomPosition))) == 0
