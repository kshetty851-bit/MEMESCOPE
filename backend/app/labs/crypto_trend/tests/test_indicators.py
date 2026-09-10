"""Indicator maths against hand-computed values and analytic identities.

The hand examples use period 2 so every intermediate step fits in a comment
and can be checked with a pencil. The identities (a constant series, a
monotonic series) pin the exact values the definitions must produce.
"""

from __future__ import annotations

from types import SimpleNamespace as C

import pytest

from app.labs.crypto_trend.indicators import (
    Swing,
    adx,
    atr,
    classify,
    donchian,
    ema,
    find_swings,
    structure_series,
    swing_structure,
    true_range,
)


def approx_list(values, places=4):
    return [None if v is None else round(v, places) for v in values]


# --- EMA ----------------------------------------------------------------------

def test_ema_hand_computed_period_2() -> None:
    # seed = mean(10, 11) = 10.5 at index 1; k = 2/3
    # idx2: 13*2/3 + 10.5/3 = 8.6667 + 3.5      = 12.1667
    # idx3: 12*2/3 + 12.1667/3 = 8 + 4.0556     = 12.0556
    # idx4: 14*2/3 + 12.0556/3 = 9.3333 + 4.0185 = 13.3519
    assert approx_list(ema([10, 11, 13, 12, 14], 2)) == [None, 10.5, 12.1667, 12.0556, 13.3519]


def test_ema_of_a_linear_series_is_the_series_shifted() -> None:
    # seed = mean(1,2,3) = 2 at idx 2; k = 0.5; then 3, 4, 5.
    assert ema([1, 2, 3, 4, 5, 6], 3) == [None, None, 2.0, 3.0, 4.0, 5.0]


def test_ema_of_a_constant_is_the_constant() -> None:
    assert ema([7.5] * 30, 10)[9:] == [7.5] * 21


def test_ema_lags_a_ramp_by_half_the_period_minus_one() -> None:
    """Steady state of an EMA on x_i = i is i - (period - 1) / 2."""
    ramp = list(range(300))
    out = ema(ramp, 5)
    assert abs((299 - out[299]) - 2.0) < 1e-9


def test_ema_short_input_and_bad_period() -> None:
    assert ema([1, 2], 3) == [None, None]
    with pytest.raises(ValueError):
        ema([1, 2, 3], 0)


# --- ATR ----------------------------------------------------------------------

def test_true_range_uses_the_previous_close() -> None:
    candles = [C(high=10, low=8, close=9), C(high=11, low=9, close=10),
               C(high=12, low=9, close=11), C(high=11, low=10, close=10.5)]
    # TR0 = 10-8 = 2 (no previous close)
    # TR1 = max(11-9, |11-9|, |9-9|)   = max(2, 2, 0) = 2
    # TR2 = max(12-9, |12-10|, |9-10|) = max(3, 2, 1) = 3
    # TR3 = max(11-10, |11-11|, |10-11|) = max(1, 0, 1) = 1
    assert true_range(candles) == [2, 2, 3, 1]


def test_atr_hand_computed_period_2() -> None:
    candles = [C(high=10, low=8, close=9), C(high=11, low=9, close=10),
               C(high=12, low=9, close=11), C(high=11, low=10, close=10.5)]
    # ATR1 = mean(2, 2) = 2; ATR2 = (2*1 + 3)/2 = 2.5; ATR3 = (2.5*1 + 1)/2 = 1.75
    assert atr(candles, 2) == [None, 2.0, 2.5, 1.75]


def test_atr_of_constant_range_without_gaps_is_the_range() -> None:
    candles = [C(high=101, low=99, close=100)] * 40
    assert atr(candles, 14)[13:] == [2.0] * 27


# --- ADX ----------------------------------------------------------------------

def test_adx_hand_computed_period_2() -> None:
    candles = [C(high=10, low=8, close=9), C(high=12, low=9, close=11),
               C(high=11, low=7, close=8), C(high=13, low=10, close=12),
               C(high=14, low=12, close=13), C(high=13, low=11, close=12)]
    # per candle (from 1):   +DM   -DM   TR
    #   1: up=2   down=-1     2     0    max(3, |12-9|, |9-9|)   = 3
    #   2: up=-1  down=2      0     2    max(4, |11-11|, |7-11|) = 4
    #   3: up=2   down=-3     2     0    max(3, |13-8|, |10-8|)  = 5
    #   4: up=1   down=-2     1     0    max(2, |14-12|, |12-12|)= 2
    #   5: up=-1  down=1      0     1    max(2, |13-13|, |11-13|)= 2
    # Wilder sums (period 2), first at index 2 = candles 1+2:
    #   S_TR: 7, 8.5, 6.25, 5.125     S+: 2, 3, 2.5, 1.25     S-: 2, 1, 0.5, 1.25
    # DI = 100*S/S_TR:
    #   idx2 +28.5714 -28.5714 DX 0 | idx3 +35.2941 -11.7647 DX 50
    #   idx4 +40 -8 DX 66.6667      | idx5 +24.3902 -24.3902 DX 0
    # ADX: seed mean(DX2, DX3) = 25 at idx3; then (25 + 66.6667)/2 = 45.8333;
    #      then (45.8333 + 0)/2 = 22.9167
    plus_di, minus_di, adx_out = adx(candles, 2)
    assert approx_list(plus_di) == [None, None, 28.5714, 35.2941, 40.0, 24.3902]
    assert approx_list(minus_di) == [None, None, 28.5714, 11.7647, 8.0, 24.3902]
    assert approx_list(adx_out) == [None, None, None, 25.0, 45.8333, 22.9167]


def test_adx_of_a_perfectly_monotonic_series_is_100() -> None:
    """Every bar higher by one, closing at its high: TR = +DM = 1, -DM = 0,
    so +DI = 100, -DI = 0, DX = 100 and ADX = 100 exactly."""
    candles = [C(high=10 + i, low=9 + i, close=10 + i) for i in range(40)]
    plus_di, minus_di, adx_out = adx(candles, 14)
    assert plus_di[14:] == [100.0] * 26
    assert minus_di[14:] == [0.0] * 26
    assert adx_out[:27] == [None] * 27  # first ADX on candle 2*period - 1
    assert adx_out[27:] == [100.0] * 13


def test_adx_of_flat_candles_is_zero_not_a_division_error() -> None:
    candles = [C(high=10, low=10, close=10)] * 40
    plus_di, minus_di, adx_out = adx(candles, 14)
    assert plus_di[-1] == 0.0 and minus_di[-1] == 0.0 and adx_out[-1] == 0.0


def test_adx_needs_period_plus_one_candles() -> None:
    assert adx([C(high=1, low=0, close=0.5)] * 3, 3) == ([None] * 3, [None] * 3, [None] * 3)


# --- Donchian -----------------------------------------------------------------

def test_donchian_is_the_windowed_extremes() -> None:
    candles = [C(high=hi, low=lo, close=0) for hi, lo in
               [(10, 5), (12, 6), (11, 4), (15, 7), (9, 8)]]
    upper, lower = donchian(candles, 3)
    assert upper == [None, None, 12, 15, 15]
    assert lower == [None, None, 4, 4, 4]


# --- swings -------------------------------------------------------------------

def zigzag(points: list[float]):
    """Candles whose highs and lows both follow `points`, wick 0."""
    return [C(high=p, low=p, close=p) for p in points]


def test_find_swings_needs_strictly_lower_neighbours_on_both_sides() -> None:
    #           0  1  2  3  4  5  6  7  8
    candles = zigzag([1, 2, 3, 2, 1, 2, 3, 3, 1])
    highs, lows = find_swings(candles, 2)
    assert highs == [Swing(2, 3)]      # index 6 and 7 tie: a plateau is not a swing
    assert lows == [Swing(4, 1)]       # index 0 and 8 have no neighbours on one side


def test_classify_the_three_structures() -> None:
    assert classify([Swing(0, 10), Swing(5, 12)], [Swing(2, 8), Swing(7, 9)]) == "HH_HL"
    assert classify([Swing(0, 12), Swing(5, 10)], [Swing(2, 9), Swing(7, 8)]) == "LH_LL"
    assert classify([Swing(0, 10), Swing(5, 12)], [Swing(2, 9), Swing(7, 8)]) == "MIXED"
    assert classify([Swing(0, 10)], [Swing(2, 9), Swing(7, 8)]) == "MIXED"


def test_structure_series_counts_a_swing_only_once_it_is_confirmed() -> None:
    """Higher highs and higher lows with lookback 1: the swing at index i is
    known on index i + 1, never on i itself."""
    #            0  1  2  3  4  5  6  7  8
    candles = zigzag([1, 3, 2, 4, 3, 5, 4, 6, 5])
    # swing highs: 1(3), 3(4), 5(5), 7(6); swing lows: 2(2), 4(3), 6(4)
    series = structure_series(candles, 1)
    # two highs are known at index 4 (3+1), two lows at index 5 (4+1)
    assert series[:5] == ["MIXED"] * 5
    assert series[5:] == ["HH_HL"] * 4
    assert swing_structure(candles, 1).structure == "HH_HL"
    assert swing_structure(candles, 1).highs == (Swing(5, 5), Swing(7, 6))
    assert swing_structure(candles, 1).lows == (Swing(4, 3), Swing(6, 4))
