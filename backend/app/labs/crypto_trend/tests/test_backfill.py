"""Deep backfill: paging with startTime until the gap before the earliest
stored candle is filled, against a fake exchange with a long history."""

from __future__ import annotations

from itertools import pairwise

import pytest
from sqlalchemy import func, select

from app.labs.crypto_trend import config
from app.labs.crypto_trend.candles import INTERVAL_MS, parse_klines, to_ms
from app.labs.crypto_trend.models import CtCandle
from app.labs.crypto_trend.service import CryptoTrendService
from app.labs.crypto_trend.tests.fakes import NOW, NOW_MS, FakeSource, klines_ending_at

pytestmark = pytest.mark.integration

H, H4 = INTERVAL_MS["1h"], INTERVAL_MS["4h"]


def exchange() -> FakeSource:
    """3,500 closed hourly candles and 800 closed 4h candles, both ending now."""
    return FakeSource(klines={
        ("BTCUSDT", "1h"): klines_ending_at("1h", NOW_MS, closed=3500),
        ("BTCUSDT", "4h"): klines_ending_at("4h", NOW_MS, closed=800),
    })


async def span(session, tf):
    lo, hi, n = (await session.execute(
        select(func.min(CtCandle.open_time), func.max(CtCandle.close_time), func.count())
        .where(CtCandle.symbol == "BTCUSDT", CtCandle.timeframe == tf))).one()
    return to_ms(lo), to_ms(hi), n


async def seed_like_the_tick(session, source) -> CryptoTrendService:
    """What the tick leaves behind: the newest 1,000 of each timeframe."""
    service = CryptoTrendService(session, source)
    for tf in config.TIMEFRAMES:
        rows = source.klines_by[("BTCUSDT", tf)][-1001:]
        await service.upsert_candles(parse_klines("BTCUSDT", tf, rows, now_ms=NOW_MS))
    return service


async def test_backfill_pages_until_1h_covers_the_4h_start(lab_session) -> None:
    source = exchange()
    service = await seed_like_the_tick(lab_session, source)
    lo4, _, _ = await span(lab_session, "4h")
    lo1_before, _, n1_before = await span(lab_session, "1h")
    assert lo1_before > lo4 and n1_before == 1000
    source.calls.clear()

    result = await service.backfill_to_match(["BTCUSDT"], timeframe="1h", reference="4h",
                                             now=NOW)

    lo1, hi1, n1 = await span(lab_session, "1h")
    assert lo1 == lo4  # coverage now matches the 4h start exactly
    assert n1 == 800 * 4  # every hour of the 4h history, no duplicates
    (report,) = result["symbols"]
    # 3,200 - 1,000 = 2,200 missing hours = three pages of 1,000
    assert report["requests"] == 3 and result["requests"] == 3
    starts = [c[3] for c in source.calls if c[0] == "klines"]
    assert starts[0] == lo4
    assert all(b > a for a, b in pairwise(starts))
    # the page that overlapped the already-stored candles changed nothing
    assert hi1 == NOW_MS - 1 - (NOW_MS % H)


async def test_a_second_run_costs_nothing(lab_session) -> None:
    source = exchange()
    service = await seed_like_the_tick(lab_session, source)
    await service.backfill_to_match(["BTCUSDT"], timeframe="1h", reference="4h", now=NOW)
    again = await service.backfill_to_match(["BTCUSDT"], timeframe="1h", reference="4h",
                                            now=NOW)
    assert again["requests"] == 0 and again["symbols"][0]["covered"] is True


async def test_a_symbol_without_reference_candles_is_skipped(lab_session) -> None:
    service = CryptoTrendService(lab_session, exchange())
    result = await service.backfill_to_match(["NOPEUSDT"], timeframe="1h", reference="4h",
                                             now=NOW)
    assert result["symbols"] == [{"symbol": "NOPEUSDT", "skipped": "no 4h candles"}]


async def test_paging_stops_on_a_short_page_and_never_spins(lab_session) -> None:
    source = FakeSource(klines={("BTCUSDT", "1h"): klines_ending_at("1h", NOW_MS, closed=250)})
    service = CryptoTrendService(lab_session, source)
    r = await service.backfill_candles("BTCUSDT", "1h", from_ms=0, until_ms=NOW_MS,
                                       now_ms=NOW_MS)
    assert r["requests"] == 1 and r["candles"] == 250
    empty = FakeSource()
    r = await CryptoTrendService(lab_session, empty).backfill_candles(
        "BTCUSDT", "1h", from_ms=0, until_ms=NOW_MS, now_ms=NOW_MS)
    assert r == {"symbol": "BTCUSDT", "timeframe": "1h", "requests": 1, "candles": 0}


async def test_the_prune_keeps_the_deep_window(lab_session) -> None:
    """The point of a per-timeframe window: the tick must not throw the
    backfill away."""
    source = exchange()
    service = await seed_like_the_tick(lab_session, source)
    await service.backfill_to_match(["BTCUSDT"], timeframe="1h", reference="4h", now=NOW)
    assert await service.prune_candles() == 0
    _, _, n1 = await span(lab_session, "1h")
    assert n1 == 3200 <= config.CANDLE_WINDOW_1H
