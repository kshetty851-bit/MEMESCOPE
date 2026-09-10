"""Kline parsing and gap detection. Pure; no database, no network."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.labs.crypto_trend.candles import INTERVAL_MS, find_gaps, from_ms, parse_klines, to_ms
from app.labs.crypto_trend.tests.fakes import NOW_MS, kline, klines_ending_at

H = INTERVAL_MS["1h"]


def test_the_forming_candle_is_dropped() -> None:
    rows = klines_ending_at("1h", NOW_MS, closed=3)
    assert len(rows) == 4
    candles = parse_klines("BTCUSDT", "1h", rows, now_ms=NOW_MS)
    assert len(candles) == 3
    assert all(to_ms(c.close_time) < NOW_MS for c in candles)


def test_a_candle_closing_exactly_now_is_not_closed() -> None:
    row = kline(NOW_MS - H + 1, H)  # close_time == NOW_MS
    assert parse_klines("X", "1h", [row], now_ms=NOW_MS) == []
    assert len(parse_klines("X", "1h", [row], now_ms=NOW_MS + 1)) == 1


def test_prices_round_trip_as_exact_decimals() -> None:
    row = [1789041600000, "77816.20", "77935.80", "76634.30", "76859.90", "30977.799",
           1789045199999, "2392008856.76960", 483998, "12594.564", "972575246.06600", "0"]
    (c,) = parse_klines("BTCUSDT", "1h", [row], now_ms=1789045200000)
    assert (c.open, c.high, c.low, c.close, c.volume) == (
        Decimal("77816.20"), Decimal("77935.80"), Decimal("76634.30"),
        Decimal("76859.90"), Decimal("30977.799"))
    assert c.open_time == datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    assert to_ms(c.close_time) == 1789045199999


def test_ms_round_trip_is_exact_at_the_millisecond() -> None:
    for ms in (1789045199999, 1789045200000, 0, 1):
        assert to_ms(from_ms(ms)) == ms


def test_no_gaps_in_a_contiguous_series() -> None:
    assert find_gaps([0, H, 2 * H, 3 * H], H) == []


def test_one_missing_candle_is_one_gap_of_one() -> None:
    assert find_gaps([0, H, 3 * H], H) == [(2 * H, 2 * H)]


def test_gaps_are_ranges_and_input_order_is_free() -> None:
    assert find_gaps([5 * H, 0, 9 * H, H], H) == [(2 * H, 4 * H), (6 * H, 8 * H)]


def test_duplicates_and_short_input_do_not_create_gaps() -> None:
    assert find_gaps([H, H, H], H) == []
    assert find_gaps([H], H) == []
    assert find_gaps([], H) == []
