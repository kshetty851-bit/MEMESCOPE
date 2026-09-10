"""Per-coin state on synthetic series, the strength formula, and verdicts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.labs.crypto_trend import config
from app.labs.crypto_trend.indicators import (
    Swing,
    SwingStructure,
    atr,
    find_swings,
    known_swings,
)
from app.labs.crypto_trend.tests.fakes import (
    NOW,
    downtrend_closes,
    sideways_closes,
    synthetic_candles,
    then_dip,
    uptrend_closes,
    with_pullback,
)
from app.labs.crypto_trend.trend import (
    DOWN,
    FLAT,
    LONG_BIAS,
    NEUTRAL,
    SHORT_BIAS,
    UP,
    TrendState,
    coin_verdict,
    compute_trend_state,
    direction,
    raw_direction,
    strength,
    structure_veto,
)


def state(closes, timeframe="4h", symbol="BTCUSDT"):
    return compute_trend_state(symbol, timeframe,
                               synthetic_candles(closes, symbol=symbol, timeframe=timeframe),
                               computed_at=NOW)


# --- the rule -------------------------------------------------------------------

def test_raw_direction_needs_the_three_gates() -> None:
    assert raw_direction(101, 100.5, 100, 25) == UP
    assert raw_direction(99.5, 100.5, 100, 25) == FLAT   # close below EMA_slow
    assert raw_direction(101, 99.5, 100, 25) == FLAT     # fast below slow
    assert raw_direction(101, 100.5, 100, 19.9) == FLAT  # ADX under the floor
    assert raw_direction(101, 100.5, 100, config.ADX_MIN) == UP  # floor is inclusive
    assert raw_direction(99, 99.5, 100, 25) == DOWN
    assert raw_direction(99, 100.5, 100, 25) == FLAT     # mixed averages


def swings(highs, lows) -> SwingStructure:
    hs = tuple(Swing(i, p) for i, p in highs)
    ls = tuple(Swing(i, p) for i, p in lows)
    return SwingStructure(hs, ls, "MIXED")


def test_a_deep_lower_low_vetoes_up_and_a_shallow_one_does_not() -> None:
    # ATR 2 -> threshold 1.0. Most recent swing is the low at index 30.
    deep = swings(highs=[(10, 110), (25, 115)], lows=[(5, 100), (30, 98.9)])
    shallow = swings(highs=[(10, 110), (25, 115)], lows=[(5, 100), (30, 99.1)])
    exact = swings(highs=[(10, 110), (25, 115)], lows=[(5, 100), (30, 99.0)])
    assert structure_veto(UP, deep, 2.0) is True
    assert structure_veto(UP, shallow, 2.0) is False
    # "more than": a gap of exactly the threshold passes
    assert structure_veto(UP, exact, 2.0) is False
    assert direction(101, 100.5, 100, 25, deep, 2.0) == (FLAT, True)
    assert direction(101, 100.5, 100, 25, shallow, 2.0) == (UP, False)


def test_a_break_answered_by_a_later_swing_does_not_veto() -> None:
    """The deep lower low at 30 was followed by a confirmed higher high at
    40: the most recent swing is a high, and the break is history."""
    answered = swings(highs=[(10, 110), (40, 120)], lows=[(5, 100), (30, 90)])
    assert structure_veto(UP, answered, 2.0) is False


def test_the_veto_mirrors_for_down() -> None:
    deep = swings(highs=[(5, 100), (30, 101.1)], lows=[(10, 90), (25, 85)])
    shallow = swings(highs=[(5, 100), (30, 100.9)], lows=[(10, 90), (25, 85)])
    assert structure_veto(DOWN, deep, 2.0) is True
    assert structure_veto(DOWN, shallow, 2.0) is False
    assert structure_veto(UP, deep, 2.0) is False  # a higher high is no threat to UP


def test_flat_and_thin_structures_are_never_vetoed() -> None:
    deep = swings(highs=[(10, 110), (25, 115)], lows=[(5, 100), (30, 90)])
    assert structure_veto(FLAT, deep, 2.0) is False
    assert structure_veto(UP, swings(highs=[(10, 110)], lows=[(30, 90)]), 2.0) is False
    assert structure_veto(UP, swings(highs=[], lows=[]), 2.0) is False


def test_the_veto_multiple_is_configurable(monkeypatch) -> None:
    deep = swings(highs=[(10, 110), (25, 115)], lows=[(5, 100), (30, 98.9)])  # gap 1.1, ATR 2
    monkeypatch.setattr(config, "STRUCTURE_VETO_ATR", 0.6)  # threshold 1.2
    assert structure_veto(UP, deep, 2.0) is False
    monkeypatch.setattr(config, "STRUCTURE_VETO_ATR", 0.5)  # threshold 1.0
    assert structure_veto(UP, deep, 2.0) is True


# --- synthetic series -------------------------------------------------------------

def test_an_uptrend_is_up_with_higher_highs_and_lows() -> None:
    s = state(uptrend_closes(200))
    assert s is not None
    assert s.direction == UP
    assert s.structure == "HH_HL"
    assert s.structure_veto is False
    assert s.adx >= config.ADX_MIN
    assert s.ema_fast > s.ema_slow and s.close > s.ema_slow
    assert s.slope > 0
    assert s.ema_trend is not None  # 200 bars: the long average exists
    assert 0 < s.strength <= 100
    assert s.atr_pct > 0
    candles = synthetic_candles(uptrend_closes(200), timeframe="4h")
    assert s.bar_close_time == candles[-1].close_time


def test_a_downtrend_is_the_mirror() -> None:
    s = state(downtrend_closes(200))
    assert s is not None
    assert s.direction == DOWN
    assert s.structure == "LH_LL"
    assert s.ema_fast < s.ema_slow and s.close < s.ema_slow
    assert s.slope < 0


def test_sideways_is_flat_by_adx_not_by_veto() -> None:
    s = state(sideways_closes(200))
    assert s is not None
    assert s.direction == FLAT
    assert s.structure_veto is False
    assert s.adx < config.ADX_MIN
    assert s.structure == "MIXED"
    assert abs(s.slope) < 0.5


# --- the pullback scenarios (Phase 2.1) ---------------------------------------------

def pullback(delta_atr: float, *, rebound: int = 8) -> list[float]:
    """The uptrend, then a pullback whose trough undercuts the prior swing
    low by `delta_atr` ATRs, then `rebound` rising bars."""
    base = uptrend_closes(200)
    # The base's last trough (bar 195) is confirmed only once five more bars
    # exist, so read it off a slightly longer series.
    _, lows = find_swings(synthetic_candles(uptrend_closes(206), timeframe="4h"),
                          config.SWING_LOOKBACK)
    prior_low = lows[-1].price
    a = atr(synthetic_candles(base, timeframe="4h"), config.ATR_PERIOD)[-1]
    # A trough bar is a down bar, whose low sits 0.3 under its close.
    return with_pullback(base, dip_to=prior_low - delta_atr * a + 0.3, rebound=rebound)


def lows_of(closes):
    candles = synthetic_candles(closes, timeframe="4h")
    return known_swings(candles, config.SWING_LOOKBACK)[-1].lows


def test_a_shallow_lower_low_reads_up_not_flat() -> None:
    """The Phase 2.1 case: EMAs aligned, ADX strong, and a pullback under the
    prior swing low by a quarter of an ATR. The hard gate called this FLAT."""
    closes = pullback(0.25)
    prev, last = lows_of(closes)
    assert 0 < prev.price - last.price < config.STRUCTURE_VETO_ATR  # a lower low, shallow
    s = state(closes)
    assert s.direction == UP
    assert s.structure_veto is False
    assert s.structure == "MIXED"  # a lower low under a higher high
    assert s.adx >= config.ADX_MIN and s.close > s.ema_slow and s.ema_fast > s.ema_slow


def test_the_threshold_is_the_boundary() -> None:
    just_under, just_over = state(pullback(0.5 - 0.01)), state(pullback(0.5 + 0.01))
    assert (just_under.direction, just_under.structure_veto) == (UP, False)
    assert (just_over.direction, just_over.structure_veto) == (FLAT, True)


def test_a_deep_lower_low_is_vetoed_and_says_so() -> None:
    s = state(pullback(1.5))
    assert (s.direction, s.structure_veto) == (FLAT, True)
    # The averages still read UP; only the structure refused it.
    assert raw_direction(s.close, s.ema_fast, s.ema_slow, s.adx) == UP
    assert s.strength > 0  # strength is a magnitude and is still reported


def test_a_deep_break_answered_by_a_new_high_is_up_again() -> None:
    closes = then_dip(pullback(1.5, rebound=20), 5)
    ks = known_swings(synthetic_candles(closes, timeframe="4h"), config.SWING_LOOKBACK)[-1]
    assert ks.highs[-1].index > ks.lows[-1].index  # the most recent swing is a high
    s = state(closes)
    assert (s.direction, s.structure_veto) == (UP, False)


def test_a_veto_is_only_ever_on_a_flat_state() -> None:
    for closes in (uptrend_closes(200), downtrend_closes(200), sideways_closes(200),
                   pullback(0.25), pullback(1.5)):
        s = state(closes)
        assert not (s.structure_veto and s.direction != FLAT)


def test_the_long_average_is_null_before_200_bars() -> None:
    s = state(uptrend_closes(150))
    assert s is not None and s.ema_trend is None


def test_too_little_history_is_no_state() -> None:
    assert state(uptrend_closes(config.MIN_BARS - 1)) is None
    assert state(uptrend_closes(config.MIN_BARS)) is not None


def test_bars_in_state_counts_back_one_bar_per_candle() -> None:
    closes = uptrend_closes(200)
    full, shorter = state(closes), state(closes[:-1])
    assert full.direction == shorter.direction == UP
    assert full.bars_in_state == shorter.bars_in_state + 1


def test_bars_in_state_resets_when_the_direction_changes() -> None:
    """An uptrend that turns: the last bars are no longer UP, and the count
    restarts at the turn rather than reaching back into the climb."""
    closes = uptrend_closes(200) + downtrend_closes(60, start=uptrend_closes(200)[-1])
    s = state(closes)
    assert s.direction != UP
    assert s.bars_in_state <= 60


def test_state_is_deterministic() -> None:
    closes = uptrend_closes(200)
    assert state(closes) == state(closes)


# --- strength ---------------------------------------------------------------------

def test_strength_formula_by_hand() -> None:
    # ADX 25 -> 0.5; spread 1 ATR of a 2-ATR ceiling -> 0.5; close at the
    # upper edge with the averages leaning up -> 1.0; structure agrees -> 1.0
    # 100 * (0.3*0.5 + 0.2*0.5 + 0.3*1.0 + 0.2*1.0) = 100 * 0.75 = 75
    assert strength(adx_value=25, ema_fast=101, ema_slow=100, atr_value=1,
                    close=110, upper=110, lower=90, direction=UP, structure="HH_HL") == 75


def test_mixed_structure_adds_nothing() -> None:
    # same but structure MIXED: 100 * (0.15 + 0.10 + 0.30) = 55
    assert strength(adx_value=25, ema_fast=101, ema_slow=100, atr_value=1,
                    close=110, upper=110, lower=90, direction=UP, structure="MIXED") == 55


def test_a_flat_state_never_earns_the_structure_component() -> None:
    assert strength(adx_value=25, ema_fast=101, ema_slow=100, atr_value=1,
                    close=110, upper=110, lower=90, direction=FLAT, structure="HH_HL") == 55
    # and the wrong structure for the direction is worth nothing either
    assert strength(adx_value=25, ema_fast=101, ema_slow=100, atr_value=1,
                    close=110, upper=110, lower=90, direction=UP, structure="LH_LL") == 55


def test_strength_scores_zero_for_a_close_on_the_wrong_side() -> None:
    # close BELOW the midpoint while the averages lean up: 100 * (0.15 + 0.10 + 0 + 0.20) = 45
    assert strength(adx_value=25, ema_fast=101, ema_slow=100, atr_value=1,
                    close=95, upper=110, lower=90, direction=UP, structure="HH_HL") == 45


def test_strength_clamps_each_component() -> None:
    assert strength(adx_value=80, ema_fast=110, ema_slow=100, atr_value=1,
                    close=200, upper=110, lower=90, direction=UP, structure="HH_HL") == 100


def test_strength_survives_a_zero_atr_and_a_flat_channel() -> None:
    assert strength(adx_value=0, ema_fast=100, ema_slow=100, atr_value=0,
                    close=100, upper=100, lower=100, direction=FLAT, structure="MIXED") == 0


def test_the_weights_sum_to_one() -> None:
    assert abs(sum(config.STRENGTH_WEIGHTS) - 1.0) < 1e-9


# --- verdict -----------------------------------------------------------------------

def _s(d: str, tf: str) -> TrendState:
    return TrendState("X", tf, NOW, NOW, d, 50, 0.0, 1.0, 3, 1, 1, None, 25, "MIXED", False, 1)


@pytest.mark.parametrize("d4, d1, verdict, reason", [
    (UP, UP, LONG_BIAS, "4h UP, 1h UP"),
    (UP, FLAT, LONG_BIAS, "4h UP, 1h FLAT"),
    (UP, DOWN, NEUTRAL, "4h UP against 1h DOWN"),
    (DOWN, DOWN, SHORT_BIAS, "4h DOWN, 1h DOWN"),
    (DOWN, FLAT, SHORT_BIAS, "4h DOWN, 1h FLAT"),
    (DOWN, UP, NEUTRAL, "4h DOWN against 1h UP"),
    (FLAT, UP, NEUTRAL, "4h FLAT, 1h UP"),
    (FLAT, None, NEUTRAL, "4h FLAT, 1h missing"),
    (UP, None, NEUTRAL, "4h UP, 1h missing"),
    (None, UP, NEUTRAL, "no 4h state"),
])
def test_coin_verdict(d4, d1, verdict, reason) -> None:
    v = coin_verdict("X", _s(d4, "4h") if d4 else None, _s(d1, "1h") if d1 else None)
    assert (v.verdict, v.reason) == (verdict, reason)


def test_verdict_time_is_utc_aware() -> None:
    assert NOW.tzinfo is UTC and isinstance(NOW, datetime)
