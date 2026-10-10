"""Indicator maths and the higher-timeframe mapping.

The values are checked by hand on tiny series; the property that matters for
backtest honesty is causality, checked on every indicator by truncation.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.labs.forex.indicators import atr, bollinger, ema, htf_values_at, rsi, sma
from app.labs.forex.types import Candle, Timeframe

pytestmark = pytest.mark.unit

T0 = datetime(2024, 1, 2, 9, 0, tzinfo=UTC)


def _c(minutes: int, o: float, h: float, low: float, c: float) -> Candle:
    return Candle(T0 + timedelta(minutes=minutes), o, h, low, c)


def _approx(actual: list[float | None], expected: list[float | None]) -> None:
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected, strict=True):
        if e is None:
            assert a is None
        else:
            assert a is not None
            assert a == pytest.approx(e, abs=1e-12)


def test_sma_hand_computed() -> None:
    """Warm-up is None and the rolling mean drops the oldest value."""
    _approx(sma([1, 2, 3, 4, 5], 3), [None, None, 2, 3, 4])


def test_ema_is_seeded_with_sma_and_uses_standard_alpha() -> None:
    """Seed = SMA of the first `period` values at index period-1, alpha=2/(p+1)."""
    # seed (1+2+3)/3 = 2 ; alpha = 0.5 -> 0.5*4+0.5*2 = 3 -> 0.5*5+0.5*3 = 4
    _approx(ema([1, 2, 3, 4, 5], 3), [None, None, 2, 3, 4])
    _approx(ema([10.0, 20.0, 30.0, 25.0], 2), [None, 15.0, 25.0, 25.0])


def test_rsi_wilder_hand_computed() -> None:
    """First RSI at index `period`; later values use Wilder smoothing."""
    out = rsi([1, 2, 3, 2, 3], period=2)
    # idx2: gains 1,1 losses 0,0 -> 100. idx3: gain .5 loss .5 -> 50. idx4: .75/.25 -> 75
    _approx(out, [None, None, 100.0, 50.0, 75.0])


def test_rsi_degenerate_cases() -> None:
    """No losses is 100 and no movement at all is 50, never a division error."""
    assert rsi([5.0] * 6, 3)[3:] == [50.0, 50.0, 50.0]
    assert rsi([1.0, 2.0, 3.0, 4.0], 3)[3] == 100.0
    assert rsi([4.0, 3.0, 2.0, 1.0], 3)[3] == 0.0


def test_atr_wilder_uses_previous_close() -> None:
    """TR is undefined at 0; seed = mean TR[1..period] at index `period`."""
    candles = [
        _c(0, 10, 10, 10, 10),
        _c(5, 10, 12, 9, 11),  # TR = max(3, 2, 1) = 3
        _c(10, 11, 13, 11, 12),  # TR = max(2, 2, 0) = 2
        _c(15, 12, 12, 8, 9),  # TR = max(4, 0, 4) = 4
        _c(20, 9, 20, 9, 10),  # TR = max(11, 11, 0) = 11
    ]
    out = atr(candles, 2)
    _approx(out, [None, None, 2.5, 3.25, 7.125])


def test_atr_counts_the_gap_from_previous_close() -> None:
    """A bar entirely above the prior close has TR from the gap, not high-low."""
    candles = [_c(0, 10, 10, 10, 10), _c(5, 15, 16, 15, 16)]
    out = atr(candles, 1)
    assert out == [None, 6.0]


def test_bollinger_population_std() -> None:
    """ddof=0: closes [1,3] have std 1, [1,2,3] have std sqrt(2/3)."""
    mid, up, lo = bollinger([1.0, 3.0], period=2, num_std=2.0)
    _approx(mid, [None, 2.0])
    _approx(up, [None, 4.0])
    _approx(lo, [None, 0.0])

    mid, up, lo = bollinger([1.0, 2.0, 3.0], period=3, num_std=1.0)
    std = math.sqrt(2 / 3)
    _approx(up, [None, None, 2 + std])
    _approx(lo, [None, None, 2 - std])


def test_short_input_is_all_none() -> None:
    """Fewer bars than the warm-up never yields a fabricated value."""
    assert sma([1.0, 2.0], 3) == [None, None]
    assert ema([1.0, 2.0], 3) == [None, None]
    assert rsi([1.0, 2.0, 3.0], 3) == [None, None, None]
    assert atr([_c(0, 1, 1, 1, 1)], 14) == [None]
    assert bollinger([1.0], 20) == ([None], [None], [None])


def test_invalid_period_rejected() -> None:
    with pytest.raises(ValueError):
        sma([1.0], 0)


def _walk(n: int) -> list[Candle]:
    state = 12345
    price = 1.1
    out: list[Candle] = []
    for i in range(n):
        state = (1103515245 * state + 12345) % 2**31
        step = (state / 2**31 - 0.5) * 0.0010
        o, c = price, price + step
        out.append(
            Candle(T0 + timedelta(minutes=5 * i), o, max(o, c) + 0.0002, min(o, c) - 0.0002, c)
        )
        price = c
    return out


def test_all_indicators_are_causal() -> None:
    """The value at i must not change when later bars are removed.

    If any indicator peeked forward, a backtest would trade on information it
    could not have had; truncation exposes that for every index at once.
    """
    candles = _walk(300)
    closes = [c.close for c in candles]
    for k in (40, 101, 299):
        sub = candles[:k]
        sub_closes = closes[:k]
        assert sma(closes, 20)[:k] == sma(sub_closes, 20)
        assert ema(closes, 20)[:k] == ema(sub_closes, 20)
        assert rsi(closes, 14)[:k] == rsi(sub_closes, 14)
        assert atr(candles, 14)[:k] == atr(sub, 14)
        full = bollinger(closes, 20, 2.0)
        part = bollinger(sub_closes, 20, 2.0)
        for f, p in zip(full, part, strict=True):
            assert f[:k] == p


def _htf(first_open: datetime, n: int, minutes: int = 15) -> list[Candle]:
    return [
        Candle(first_open + timedelta(minutes=minutes * i), 1.0, 1.0, 1.0, 1.0)
        for i in range(n)
    ]


def _exec(first_open: datetime, n: int, minutes: int = 5) -> list[Candle]:
    return _htf(first_open, n, minutes)


def test_htf_five_minute_bar_sees_only_closed_fifteen_minute_candle() -> None:
    """The 5m bar closing 10:10 sees the 15m candle that closed at 10:00.

    The 15m candle opening 10:00 closes at 10:15 and contains prices from after
    this bar; reading it would be look-ahead. Its value only becomes visible to
    the bar that closes at 10:15.
    """
    htf = _htf(datetime(2024, 1, 2, 9, 30, tzinfo=UTC), 3)  # opens 09:30, 09:45, 10:00
    values: list[float | None] = [1.0, 2.0, 3.0]
    ex = [
        Candle(datetime(2024, 1, 2, h, m, tzinfo=UTC), 0, 0, 0, 0)
        for h, m in [(9, 25), (9, 40), (9, 55), (10, 0), (10, 5), (10, 10)]
    ]
    out = htf_values_at(ex, Timeframe.M5, htf, Timeframe.M15, values)
    # 09:25 bar closes 09:30: nothing closed yet. 09:40 closes 09:45: 09:30 candle.
    # 09:55 closes 10:00: 09:45 candle. 10:00/10:05/10:10 bars close 10:05..10:15.
    assert out == [None, 1.0, 2.0, 2.0, 2.0, 3.0]


def test_htf_value_becomes_visible_exactly_at_close() -> None:
    """Boundary: HTF close time == exec close time is already visible."""
    htf = _htf(datetime(2024, 1, 2, 10, 0, tzinfo=UTC), 1)
    ex = [
        Candle(datetime(2024, 1, 2, 10, 5, tzinfo=UTC), 0, 0, 0, 0),
        Candle(datetime(2024, 1, 2, 10, 10, tzinfo=UTC), 0, 0, 0, 0),
    ]
    out = htf_values_at(ex, Timeframe.M5, htf, Timeframe.M15, [7.0])
    assert out == [None, 7.0]


def test_htf_warmup_none_values_pass_through() -> None:
    """A None HTF value (indicator warm-up) stays None on the exec bars."""
    htf = _htf(datetime(2024, 1, 2, 10, 0, tzinfo=UTC), 2)
    ex = _exec(datetime(2024, 1, 2, 10, 0, tzinfo=UTC), 6)
    out = htf_values_at(ex, Timeframe.M5, htf, Timeframe.M15, [None, 5.0])
    assert out == [None, None, None, None, None, 5.0]


def test_htf_empty_inputs() -> None:
    ex = _exec(datetime(2024, 1, 2, 10, 0, tzinfo=UTC), 3)
    assert htf_values_at(ex, Timeframe.M5, [], Timeframe.M15, []) == [None, None, None]
    assert htf_values_at([], Timeframe.M5, [], Timeframe.M15, []) == []


def test_htf_misaligned_values_rejected() -> None:
    htf = _htf(datetime(2024, 1, 2, 10, 0, tzinfo=UTC), 2)
    with pytest.raises(ValueError):
        htf_values_at([], Timeframe.M5, htf, Timeframe.M15, [1.0])


def test_htf_hourly_over_five_minute_never_leaks_forming_candle() -> None:
    """Across a whole hour every 5m bar sees the previous hour, until the last
    bar of the hour closes exactly when the hourly candle does."""
    htf = [Candle(datetime(2024, 1, 2, h, 0, tzinfo=UTC), 0, 0, 0, 0) for h in (8, 9)]
    ex = _exec(datetime(2024, 1, 2, 9, 0, tzinfo=UTC), 12)
    out = htf_values_at(ex, Timeframe.M5, htf, Timeframe.H1, [8.0, 9.0])
    assert out[:11] == [8.0] * 11
    assert out[11] == 9.0
