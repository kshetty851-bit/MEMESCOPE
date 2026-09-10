"""Ranking a universe as of a past date, on fixed fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.labs.crypto_trend.candles import to_ms
from app.labs.crypto_trend.models import CtCandle, CtUniverseSnapshot
from app.labs.crypto_trend.replay import load_dataset
from app.labs.crypto_trend.snapshots import SnapshotService, cap_at, rank_snapshot
from app.labs.crypto_trend.tests.fakes import NOW, NOW_MS, FakeSource, klines_ending_at

AS_OF = datetime(2026, 3, 28, tzinfo=UTC)
AS_OF_MS = to_ms(AS_OF)
DAY = 86_400_000


def market(cid, ticker, cap_today):
    return {"id": cid, "symbol": ticker, "name": cid.title(), "market_cap": cap_today,
            "market_cap_rank": 1}


def chart(cap_march, cap_today):
    """Daily points: `cap_march` around the as-of date, `cap_today` now."""
    return [[AS_OF_MS - 2 * DAY, cap_march * 0.9], [AS_OF_MS, cap_march],
            [AS_OF_MS + DAY, cap_march * 1.1], [NOW_MS, cap_today]]


MARKETS = [
    market("bitcoin", "btc", 1500), market("tether", "usdt", 180),
    market("ethereum", "eth", 300), market("newcoin", "new", 250),
    market("oldcoin", "old", 20), market("nolist", "nol", 100),
]
CHARTS = {
    "bitcoin": chart(1200, 1500), "ethereum": chart(200, 300),
    "newcoin": [[NOW_MS, 250]],            # did not exist in March
    "oldcoin": chart(400, 20),             # big in March, small now
    "nolist": chart(500, 100),             # no Binance perp
}
PERPS = {"BTCUSDT", "ETHUSDT", "NEWUSDT", "OLDUSDT"}


def test_cap_at_takes_the_last_point_on_or_before_the_day() -> None:
    points = chart(100, 999)
    assert cap_at(points, AS_OF_MS) == 100
    assert cap_at(points, AS_OF_MS - DAY) == 90  # the day before: the earlier point
    assert cap_at(points, AS_OF_MS - 3 * DAY) is None
    assert cap_at([[AS_OF_MS, 0], [AS_OF_MS - DAY, 5]], AS_OF_MS) == 5  # a zero is no cap


def test_ranking_is_by_the_cap_on_the_as_of_date() -> None:
    coins, skipped = rank_snapshot(MARKETS, CHARTS, PERPS, as_of_ms=AS_OF_MS, size=20)
    assert [c.symbol for c in coins] == ["BTCUSDT", "OLDUSDT", "ETHUSDT"]
    assert [c.rank for c in coins] == [1, 2, 3]
    assert coins[1].market_cap_usd == 400  # March's cap, not today's 20
    assert {s["coingecko_id"]: s["why"] for s in skipped} == {
        "newcoin": "no market cap on as_of", "nolist": "no Binance perp NOLUSDT"}
    # tether never reached the ranking at all
    seen = {c.coingecko_id for c in coins} | {s["coingecko_id"] for s in skipped}
    assert "tether" not in seen


def test_size_caps_the_snapshot() -> None:
    coins, _ = rank_snapshot(MARKETS, CHARTS, PERPS, as_of_ms=AS_OF_MS, size=2)
    assert [c.symbol for c in coins] == ["BTCUSDT", "OLDUSDT"]


@pytest.mark.integration
async def test_create_stores_the_snapshot_and_backfills_new_symbols(lab_session) -> None:
    source = FakeSource(markets=MARKETS, perps=PERPS, charts=CHARTS, klines={
        (s, tf): klines_ending_at(tf, NOW_MS, closed=n)
        for s in ("BTCUSDT", "ETHUSDT", "OLDUSDT") for tf, n in (("4h", 120), ("1h", 480))})
    # BTC and ETH are already stored, as the live universe would leave them
    from app.labs.crypto_trend.candles import parse_klines
    from app.labs.crypto_trend.service import CryptoTrendService
    data = CryptoTrendService(lab_session, source)
    for s in ("BTCUSDT", "ETHUSDT"):
        for tf in ("1h", "4h"):
            await data.upsert_candles(parse_klines(s, tf, source.klines_by[(s, tf)],
                                                   now_ms=NOW_MS))

    result = await SnapshotService(lab_session, source).create(name="oos_test", as_of=AS_OF,
                                                               now=NOW)

    assert result["symbols"] == ["BTCUSDT", "OLDUSDT", "ETHUSDT"]
    assert result["new_symbols"] == ["OLDUSDT"]
    row = (await lab_session.execute(select(CtUniverseSnapshot))).scalar_one()
    assert row.name == "oos_test" and row.as_of == AS_OF
    assert [e["symbol"] for e in row.symbols] == ["BTCUSDT", "OLDUSDT", "ETHUSDT"]
    # only the candidates' charts were fetched, never the stablecoin's
    charted = [c[1] for c in source.calls if c[0] == "chart"]
    assert "tether" not in charted and "bitcoin" in charted
    days = {c[2] for c in source.calls if c[0] == "chart"}
    assert days == {(NOW.date() - AS_OF.date()).days + 2}
    # the new symbol has both timeframes, and 1h reaches the 4h start
    n4 = await lab_session.scalar(select(CtCandle.open_time).where(
        CtCandle.symbol == "OLDUSDT", CtCandle.timeframe == "4h").order_by(CtCandle.open_time))
    n1 = await lab_session.scalar(select(CtCandle.open_time).where(
        CtCandle.symbol == "OLDUSDT", CtCandle.timeframe == "1h").order_by(CtCandle.open_time))
    assert n4 is not None and n1 == n4

    # the replay can load it by name
    dataset = await load_dataset(lab_session, end=NOW, universe="oos_test")
    assert dataset.universe == ["BTCUSDT", "OLDUSDT", "ETHUSDT"]
    assert dataset.universe_name == "oos_test"
    with pytest.raises(ValueError, match="no universe snapshot"):
        await load_dataset(lab_session, end=NOW, universe="nope")

    # re-creating under the same name replaces, never duplicates
    await SnapshotService(lab_session, source).create(name="oos_test",
                                                      as_of=AS_OF - timedelta(days=1), now=NOW)
    lab_session.expire_all()  # the upsert bypassed the identity map
    rows = (await lab_session.execute(select(CtUniverseSnapshot))).scalars().all()
    assert len(rows) == 1 and rows[0].as_of == AS_OF - timedelta(days=1)


async def test_as_of_beyond_the_public_history_is_refused() -> None:
    service = SnapshotService(None, FakeSource())
    with pytest.raises(ValueError, match="365"):
        await service.create(name="x", as_of=NOW - timedelta(days=400), now=NOW)
    with pytest.raises(ValueError, match="past"):
        await service.create(name="x", as_of=NOW, now=NOW)
