"""One tick against a real database, with every network call faked.

Everything here runs inside a transaction that is rolled back, so the test
database is left exactly as it was found.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.labs.crypto_trend import config
from app.labs.crypto_trend.candles import INTERVAL_MS, Candle, from_ms, to_ms
from app.labs.crypto_trend.data import data_health, get_candles, get_funding, get_universe
from app.labs.crypto_trend.models import CtCandle, CtFunding, CtRun, CtUniverseMember
from app.labs.crypto_trend.service import CryptoTrendService
from app.labs.crypto_trend.tests.fakes import (
    NOW,
    NOW_MS,
    FakeSource,
    klines_ending_at,
    premium,
)

pytestmark = pytest.mark.integration

H = INTERVAL_MS["1h"]


def full_source(**kwargs) -> FakeSource:
    """Two tradeable coins, three closed candles each on both timeframes, and
    funding for both plus one symbol outside the universe."""
    klines = {(s, tf): klines_ending_at(tf, NOW_MS, closed=3)
              for s in ("BTCUSDT", "ETHUSDT") for tf in config.TIMEFRAMES}
    return FakeSource(klines=klines,
                      premium_rows=[premium("BTCUSDT"), premium("ETHUSDT"),
                                    premium("SOLUSDT")],
                      **kwargs)


async def count(session, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for k, v in where.items():
        stmt = stmt.where(getattr(model, k) == v)
    return await session.scalar(stmt)


# --- the tick -----------------------------------------------------------------

async def test_first_tick_ranks_backfills_funds_and_records(lab_session) -> None:
    source = full_source()
    result = await CryptoTrendService(lab_session, source).tick(now=NOW)

    universe = await get_universe(lab_session)
    assert [c.binance_symbol for c in universe] == ["BTCUSDT", "ETHUSDT"]
    assert [c.rank for c in universe] == [1, 2]
    # Tether excluded; the HELOC token has no perp and is reported, not stored.
    assert result["skipped"] == [{"coingecko_id": "figure-heloc", "ticker": "FIGR_HELOC",
                                  "tried": "FIGR_HELOCUSDT"}]
    assert await count(lab_session, CtUniverseMember) == 2

    # 2 symbols x 2 timeframes x 3 closed candles; the forming one is not stored.
    assert result["candles_upserted"] == 12
    assert await count(lab_session, CtCandle) == 12
    newest = await lab_session.scalar(select(func.max(CtCandle.close_time)))
    assert to_ms(newest) < NOW_MS

    # Funding only for members: SOLUSDT was in the response and is not stored.
    assert result["funding_upserted"] == 2
    assert await count(lab_session, CtFunding) == 2
    assert await get_funding(lab_session, "BTCUSDT") == pytest.approx(0.0001)
    assert await get_funding(lab_session, "SOLUSDT") is None

    run = (await lab_session.execute(select(CtRun))).scalar_one()
    assert run.universe_refreshed is True
    assert run.candles_upserted == 12
    assert run.errors is None
    assert run.requests == source.requests
    assert result["errors"] == []


async def test_a_quiet_minute_sends_no_candle_request(lab_session) -> None:
    source = full_source()
    service = CryptoTrendService(lab_session, source)
    await service.tick(now=NOW)
    before = len([c for c in source.calls if c[0] == "klines"])

    await service.tick(now=NOW + timedelta(minutes=1))

    assert len([c for c in source.calls if c[0] == "klines"]) == before
    assert source.calls.count("markets") == 1  # the universe is a minute old, not a day
    assert await count(lab_session, CtCandle) == 12
    assert await count(lab_session, CtRun) == 2


async def test_the_next_tick_after_a_close_fetches_only_that_candle(lab_session) -> None:
    source = full_source()
    service = CryptoTrendService(lab_session, source)
    await service.tick(now=NOW)
    source.calls.clear()

    later = NOW + timedelta(hours=1)  # 13:00:30 — the 12:00 hourly has closed
    result = await service.tick(now=later)

    klines_calls = [c for c in source.calls if c[0] == "klines"]
    # One request per symbol on the 1h timeframe; the 4h candle has not closed.
    assert sorted((c[1], c[2]) for c in klines_calls) == [("BTCUSDT", "1h"), ("ETHUSDT", "1h")]
    last_close_before = (NOW_MS // H) * H - 1
    assert all(c[3] == last_close_before + 1 for c in klines_calls)
    assert result["candles_upserted"] == 2
    assert await count(lab_session, CtCandle, timeframe="1h") == 8


async def test_the_universe_is_re_ranked_once_a_day(lab_session) -> None:
    source = full_source()
    service = CryptoTrendService(lab_session, source)
    await service.tick(now=NOW)
    await service.tick(now=NOW + timedelta(hours=23, minutes=59))
    assert source.calls.count("markets") == 1
    result = await service.tick(now=NOW + timedelta(hours=24))
    assert source.calls.count("markets") == 2
    assert result["universe_refreshed"] is True


# --- upserts ----------------------------------------------------------------------

def three_candles() -> list[Candle]:
    return [Candle("BTCUSDT", "1h", from_ms(i * H), Decimal("1"), Decimal("2"), Decimal("0.5"),
                   Decimal("1.5"), Decimal("10"), from_ms(i * H + H - 1)) for i in range(3)]


async def test_candle_upsert_is_idempotent(lab_session) -> None:
    service = CryptoTrendService(lab_session, FakeSource())
    assert await service.upsert_candles(three_candles()) == 3
    assert await service.upsert_candles(three_candles()) == 3
    assert await count(lab_session, CtCandle) == 3

    revised = three_candles()
    revised[1] = Candle(
        "BTCUSDT", "1h", from_ms(H), Decimal("1"), Decimal("9"), Decimal("0.5"),
        Decimal("7"), Decimal("10"), from_ms(2 * H - 1))
    await service.upsert_candles(revised)
    assert await count(lab_session, CtCandle) == 3
    stored = await get_candles(lab_session, "BTCUSDT", "1h")
    assert [c.close for c in stored] == [Decimal("1.5"), Decimal("7"), Decimal("1.5")]
    assert stored[1].high == Decimal("9")


async def test_funding_upsert_is_one_row_per_interval(lab_session) -> None:
    service = CryptoTrendService(lab_session, FakeSource())
    interval_a, interval_b = NOW_MS + 3_600_000, NOW_MS + 4 * 3_600_000
    await service.upsert_funding([premium("BTCUSDT", "0.0001", interval_a)], NOW)
    await service.upsert_funding([premium("BTCUSDT", "0.0003", interval_a)],
                                 NOW + timedelta(minutes=1))
    assert await count(lab_session, CtFunding) == 1
    assert await get_funding(lab_session, "BTCUSDT") == pytest.approx(0.0003)

    await service.upsert_funding([premium("BTCUSDT", "0.0007", interval_b)], NOW)
    assert await count(lab_session, CtFunding) == 2
    assert await get_funding(lab_session, "BTCUSDT") == pytest.approx(0.0007)


async def test_a_symbol_without_a_funding_time_is_ignored(lab_session) -> None:
    service = CryptoTrendService(lab_session, FakeSource())
    row = premium("BTCUSDT")
    row["nextFundingTime"] = 0
    assert await service.upsert_funding([row], NOW) == 0


# --- re-ranking ---------------------------------------------------------------

def markets(*pairs):
    return [{"id": cid, "symbol": tk, "name": cid, "market_cap": 1, "market_cap_rank": i + 1}
            for i, (cid, tk) in enumerate(pairs)]


async def test_rerank_records_removals_and_readmissions(lab_session) -> None:
    source = FakeSource(markets=markets(("bitcoin", "btc"), ("ethereum", "eth")))
    service = CryptoTrendService(lab_session, source)
    await service.refresh_universe(NOW)

    source.markets = markets(("bitcoin", "btc"), ("solana", "sol"))
    day2 = NOW + timedelta(days=1)
    await service.refresh_universe(day2)
    assert [c.binance_symbol for c in await get_universe(lab_session)] == [
        "BTCUSDT", "SOLUSDT"]
    eth = (await lab_session.execute(
        select(CtUniverseMember).where(CtUniverseMember.coingecko_id == "ethereum")
    )).scalar_one()
    assert eth.removed_at == day2
    assert eth.added_at == NOW  # the record of the first membership survives

    source.markets = markets(("bitcoin", "btc"), ("ethereum", "eth"))
    day3 = NOW + timedelta(days=2)
    await service.refresh_universe(day3)
    await lab_session.refresh(eth)
    assert eth.removed_at is None
    assert eth.added_at == day3  # a new membership, not a continuation
    assert eth.rank == 2
    btc = (await lab_session.execute(
        select(CtUniverseMember).where(CtUniverseMember.coingecko_id == "bitcoin")
    )).scalar_one()
    assert btc.added_at == NOW  # never left, so never re-added
    assert btc.refreshed_at == day3


async def test_an_empty_ranking_never_empties_the_universe(lab_session) -> None:
    source = full_source()
    service = CryptoTrendService(lab_session, source)
    await service.tick(now=NOW)

    source.markets = []
    result = await service.tick(now=NOW + timedelta(days=1))

    assert result["universe_refreshed"] is False
    assert any(e.startswith("universe:") for e in result["errors"])
    assert len(await get_universe(lab_session)) == 2
    run = (await lab_session.execute(
        select(CtRun).order_by(CtRun.started_at.desc()).limit(1))).scalar_one()
    assert run.errors and run.errors[0].startswith("universe:")


# --- containment and housekeeping ------------------------------------------------

async def test_one_symbol_failing_costs_only_that_symbol(lab_session) -> None:
    source = full_source(fail_symbols={"ETHUSDT"})
    result = await CryptoTrendService(lab_session, source).tick(now=NOW)
    assert await count(lab_session, CtCandle, symbol="BTCUSDT") == 6
    assert await count(lab_session, CtCandle, symbol="ETHUSDT") == 0
    assert sorted(result["errors"]) == [
        "ETHUSDT 1h: RuntimeError('simulated failure for ETHUSDT')",
        "ETHUSDT 4h: RuntimeError('simulated failure for ETHUSDT')"]
    assert result["funding_upserted"] == 2  # funding still ran
    assert await count(lab_session, CtRun) == 1


async def test_the_rolling_window_keeps_the_newest(lab_session, monkeypatch) -> None:
    monkeypatch.setattr(config, "CANDLE_WINDOW", 5)
    service = CryptoTrendService(lab_session, FakeSource())
    candles = [Candle("BTCUSDT", "1h", from_ms(i * H), Decimal(1), Decimal(1), Decimal(1),
                      Decimal(i), Decimal(1), from_ms(i * H + H - 1)) for i in range(8)]
    await service.upsert_candles(candles)
    # Another symbol's window is its own.
    await service.upsert_candles([Candle("ETHUSDT", "1h", from_ms(0), Decimal(1), Decimal(1),
                                         Decimal(1), Decimal(1), Decimal(1), from_ms(H - 1))])
    assert await service.prune_candles() == 3
    kept = await get_candles(lab_session, "BTCUSDT", "1h")
    assert [int(c.close) for c in kept] == [3, 4, 5, 6, 7]
    assert await count(lab_session, CtCandle, symbol="ETHUSDT") == 1


async def test_run_history_is_bounded(lab_session, monkeypatch) -> None:
    monkeypatch.setattr(config, "RUN_HISTORY", 3)
    service = CryptoTrendService(lab_session, full_source())
    for i in range(5):
        await service.tick(now=NOW + timedelta(minutes=i))
    assert await count(lab_session, CtRun) == 3
    newest = await lab_session.scalar(select(func.max(CtRun.started_at)))
    assert newest == NOW + timedelta(minutes=4)


# --- the read interface --------------------------------------------------------

async def test_get_candles_is_oldest_first_and_limited(lab_session) -> None:
    service = CryptoTrendService(lab_session, FakeSource())
    await service.upsert_candles([
        Candle("BTCUSDT", "1h", from_ms(i * H), Decimal(1), Decimal(1), Decimal(1), Decimal(i),
               Decimal(1), from_ms(i * H + H - 1)) for i in range(6)])
    newest_four = await get_candles(lab_session, "BTCUSDT", "1h", limit=4)
    assert [int(c.close) for c in newest_four] == [2, 3, 4, 5]
    assert await get_candles(lab_session, "BTCUSDT", "4h") == []


async def test_health_is_off_without_the_flag(lab_session, monkeypatch) -> None:
    monkeypatch.delenv("CRYPTO_TREND_LAB_ENABLED", raising=False)
    assert await data_health(lab_session) == {"running": False}


async def test_health_reports_ages_gaps_and_the_last_run(lab_session, lab_enabled) -> None:
    source = full_source()
    service = CryptoTrendService(lab_session, source)
    await service.tick(now=NOW)
    # Knock a hole in BTC's hourly series: drop the middle of the three.
    stored = await get_candles(lab_session, "BTCUSDT", "1h")
    await lab_session.execute(
        CtCandle.__table__.delete().where(CtCandle.open_time == stored[1].open_time))

    health = await data_health(lab_session, now=NOW + timedelta(minutes=5))

    assert health["running"] is True
    assert health["universe"]["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert health["universe"]["stale"] is False
    btc_1h = health["candles"]["BTCUSDT"]["1h"]
    assert btc_1h["count"] == 2
    assert btc_1h["gaps"] == 1
    assert btc_1h["missing_candles"] == 1
    assert btc_1h["gap_ranges"] == [(stored[1].open_time.isoformat(),
                                     stored[1].open_time.isoformat())]
    assert btc_1h["stale"] is False
    assert 300 < btc_1h["age_seconds"] < 2 * 3600
    assert health["candles"]["ETHUSDT"]["4h"]["gaps"] == 0
    assert health["funding"]["BTCUSDT"]["rate"] == pytest.approx(0.0001)
    assert health["last_run"]["candles_upserted"] == 12
    assert health["last_run"]["errors"] == []
    assert health["last_run"]["skipped"][0]["coingecko_id"] == "figure-heloc"


async def test_health_marks_a_symbol_the_poll_has_lost(lab_session, lab_enabled) -> None:
    service = CryptoTrendService(lab_session, full_source())
    await service.tick(now=NOW)
    health = await data_health(lab_session, now=NOW + timedelta(hours=3))
    assert health["candles"]["BTCUSDT"]["1h"]["stale"] is True
    assert health["candles"]["BTCUSDT"]["4h"]["stale"] is False
