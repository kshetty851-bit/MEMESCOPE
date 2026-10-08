"""The range strategy's decision.

Each test builds a window whose range, efficiency and touches are known by
construction, so the expected call is stated rather than discovered by running
the code under test.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.labs.btc_range.engine import detect_range, evaluate
from app.labs.btc_range.types import Call, Reason, Regime, Signal
from tests.unit.labs.btc_range.builders import (
    LOOKBACK,
    candle,
    cfg,
    flat,
    ranging_window,
    trend,
    with_price,
)

pytestmark = pytest.mark.unit

#: Prices on the standard 60,000-61,000 window (W = 1,000).
NEAR_SUPPORT = 60100  # position 0.10
NEAR_RESISTANCE = 60900  # position 0.90
MIDDLE = 60500  # position 0.50


def _evaluate(price: int | str, **overrides: object) -> Signal:
    return evaluate(with_price(ranging_window(), price), cfg(**overrides))


def _assert_no_levels(signal: Signal) -> None:
    assert signal.entry is None
    assert signal.take_profit is None
    assert signal.stop_loss is None
    assert signal.reward_risk is None


def test_near_support_is_a_long_with_levels_derived_from_the_range() -> None:
    """Levels are fractions of W from the boundary, so they can be re-derived."""
    signal = _evaluate(NEAR_SUPPORT)

    assert signal.call is Call.LONG
    assert signal.reasons == (Reason.NEAR_SUPPORT,)
    assert signal.entry == Decimal(NEAR_SUPPORT)
    assert signal.take_profit == Decimal(60500)  # S + 0.50 W
    assert signal.stop_loss == Decimal(59850)  # S - 0.15 W
    assert signal.reward_risk == Decimal("1.6000")  # 400 / 250
    assert signal.range is not None
    assert signal.range.regime is Regime.RANGE


def test_near_resistance_is_a_short_mirrored() -> None:
    signal = _evaluate(NEAR_RESISTANCE)

    assert signal.call is Call.SHORT
    assert signal.reasons == (Reason.NEAR_RESISTANCE,)
    assert signal.take_profit == Decimal(60500)  # R - 0.50 W
    assert signal.stop_loss == Decimal(61150)  # R + 0.15 W
    assert signal.reward_risk == Decimal("1.6000")


def test_the_signal_is_stamped_with_the_evaluated_candles_open_time() -> None:
    candles = with_price(ranging_window(), NEAR_SUPPORT)
    assert evaluate(candles, cfg()).at == candles[-1].open_time


def test_mid_range_waits_and_states_no_levels() -> None:
    """Nothing is entered, so nothing is estimated."""
    signal = _evaluate(MIDDLE)

    assert signal.call is Call.WAIT
    assert signal.reasons[0] is Reason.MID_RANGE
    _assert_no_levels(signal)
    assert signal.range is not None
    assert signal.confidence == signal.range.confidence


def test_close_above_the_range_is_a_breakout_not_a_short() -> None:
    """The last candle is outside its own window, so a break cannot hide inside it."""
    signal = _evaluate(61100)

    assert signal.call is Call.WAIT
    assert signal.reasons[0] is Reason.BREAKOUT_UP
    assert signal.range is not None
    assert signal.range.regime is Regime.BREAKOUT_UP
    assert signal.range.position > 1
    _assert_no_levels(signal)


def test_close_below_the_range_is_a_breakout_not_a_long() -> None:
    signal = _evaluate(59900)

    assert signal.call is Call.WAIT
    assert signal.reasons[0] is Reason.BREAKOUT_DOWN
    assert signal.range is not None
    assert signal.range.position < 0
    _assert_no_levels(signal)


def test_a_boundary_close_is_still_inside_the_range() -> None:
    """Breakout means strictly beyond the extreme; touching it is a SHORT zone."""
    signal = _evaluate(61000)
    assert signal.range is not None
    assert signal.range.regime is Regime.RANGE
    assert signal.call is Call.SHORT


def test_a_directional_window_is_trending_even_when_price_is_in_the_zone() -> None:
    """A strong trend never qualifies, wherever price sits inside its span."""
    window = trend(LOOKBACK)
    signal = evaluate(with_price(window, window[-1].close - 5), cfg())

    assert signal.call is Call.WAIT
    assert signal.reasons[0] is Reason.TRENDING
    assert signal.range is not None
    assert signal.range.regime is Regime.TRENDING
    assert signal.range.trend_efficiency > Decimal("0.35")
    _assert_no_levels(signal)


def test_insufficient_data_waits_with_no_range_and_zero_confidence() -> None:
    candles = with_price(ranging_window(n=LOOKBACK - 1), NEAR_SUPPORT)
    assert len(candles) == LOOKBACK

    signal = evaluate(candles, cfg())

    assert signal.call is Call.WAIT
    assert signal.reasons == (Reason.INSUFFICIENT_DATA,)
    assert signal.range is None
    assert signal.confidence == 0
    _assert_no_levels(signal)


def test_exactly_lookback_plus_one_candles_is_enough() -> None:
    signal = evaluate(with_price(ranging_window(), NEAR_SUPPORT), cfg())
    assert signal.reasons != (Reason.INSUFFICIENT_DATA,)


def test_extra_history_before_the_window_is_ignored() -> None:
    """Only the `lookback` candles before the last count, however many are passed."""
    base = with_price(ranging_window(), NEAR_SUPPORT)
    # Wild older history, reindexed so times stay ascending.
    noise = [candle(k, 1, 900000, 1, 5) for k in range(7)]
    shifted = [candle(7 + k, c.open, c.high, c.low, c.close) for k, c in enumerate(base)]
    assert evaluate([*noise, *shifted], cfg()).call == evaluate(base, cfg()).call
    assert evaluate([*noise, *shifted], cfg()).range == evaluate(base, cfg()).range


def test_a_zero_width_window_is_insufficient_not_a_range() -> None:
    """Position and width are undefined at zero width; reporting 0 would be invented."""
    signal = evaluate(with_price(flat(LOOKBACK), 60000), cfg())

    assert signal.call is Call.WAIT
    assert signal.reasons == (Reason.INSUFFICIENT_DATA,)
    assert signal.range is None
    assert detect_range(flat(LOOKBACK), Decimal(60000), cfg()) is None


def test_empty_candles_are_refused_loudly() -> None:
    with pytest.raises(ValueError):
        evaluate([], cfg())


def test_a_side_that_is_disabled_waits_and_says_which_side() -> None:
    long_off = _evaluate(NEAR_SUPPORT, allow_long=False)
    short_off = _evaluate(NEAR_RESISTANCE, allow_short=False)

    assert long_off.call is Call.WAIT
    assert long_off.reasons == (Reason.SIDE_DISABLED, Reason.NEAR_SUPPORT)
    _assert_no_levels(long_off)
    assert short_off.reasons == (Reason.SIDE_DISABLED, Reason.NEAR_RESISTANCE)
    # The enabled side is unaffected.
    assert _evaluate(NEAR_RESISTANCE, allow_long=False).call is Call.SHORT


def test_poor_reward_risk_waits() -> None:
    """1.6 offered against a required 3.0."""
    signal = _evaluate(NEAR_SUPPORT, min_reward_risk=Decimal(3))

    assert signal.call is Call.WAIT
    assert signal.reasons == (Reason.POOR_REWARD_RISK, Reason.NEAR_SUPPORT)
    _assert_no_levels(signal)


def test_a_target_already_behind_price_is_poor_reward_risk() -> None:
    """With the target at the boundary, a long inside the zone has no reward left."""
    signal = _evaluate(NEAR_SUPPORT, tp_target=Decimal("0.05"))

    assert signal.call is Call.WAIT
    assert signal.reasons[0] is Reason.POOR_REWARD_RISK


def test_costs_that_exceed_the_target_wait() -> None:
    """Reward 400 on 60,100 is 0.67%; a 52 bps fill on each side costs 1.04%."""
    signal = _evaluate(NEAR_SUPPORT, fee_bps=Decimal(50))

    assert signal.call is Call.WAIT
    assert signal.reasons == (Reason.COSTS_EXCEED_TARGET, Reason.NEAR_SUPPORT)
    _assert_no_levels(signal)


def test_the_cost_test_turns_on_the_round_trip_not_one_side() -> None:
    """Reward/entry is 0.6656%; a round trip costs 0.67% at 31.5 bps fees, 0.66% at 31."""
    assert _evaluate(NEAR_SUPPORT, fee_bps=Decimal("31.5")).call is Call.WAIT
    assert _evaluate(NEAR_SUPPORT, fee_bps=Decimal("31")).call is Call.LONG


def test_a_range_that_is_too_narrow_waits() -> None:
    window = ranging_window(support=Decimal(60000), resistance=Decimal(60100))
    signal = evaluate(with_price(window, 60010), cfg())

    assert signal.call is Call.WAIT
    assert signal.reasons[0] is Reason.RANGE_TOO_NARROW
    assert signal.range is not None
    assert signal.range.width_pct < Decimal("0.8")


def test_a_range_that_is_too_wide_waits() -> None:
    window = ranging_window(support=Decimal(60000), resistance=Decimal(66000))
    signal = evaluate(with_price(window, 60300), cfg())

    assert signal.call is Call.WAIT
    assert signal.reasons[0] is Reason.RANGE_TOO_WIDE


def test_low_confidence_waits_and_keeps_the_range() -> None:
    signal = _evaluate(NEAR_SUPPORT, min_confidence=99)

    assert signal.call is Call.WAIT
    assert signal.reasons == (Reason.LOW_CONFIDENCE,)
    assert signal.range is not None
    assert signal.confidence == signal.range.confidence < 99


def test_a_breakout_is_decided_before_everything_after_it() -> None:
    """Order matters: the first gate that fails is reasons[0], however many would."""
    signal = _evaluate(61100, min_confidence=100, allow_short=False)
    assert signal.reasons[0] is Reason.BREAKOUT_UP


def test_confidence_is_the_documented_sum() -> None:
    """3+3 touches (40) + ER 0.0526 over 0.35 (29.74) + width in band (25) = 94.74."""
    state = detect_range(ranging_window(), Decimal(NEAR_SUPPORT), cfg())

    assert state is not None
    assert state.touches_support == 3
    assert state.touches_resistance == 3
    assert state.trend_efficiency == Decimal("0.0526")
    assert state.confidence == 95


def test_confidence_loses_touch_credit_when_a_side_was_touched_once() -> None:
    """One touch of two required, on both sides, halves the 40 touch points: 74.74."""
    window = ranging_window(support_touches=(2,), resistance_touches=(5,))
    state = detect_range(window, Decimal(NEAR_SUPPORT), cfg())

    assert state is not None
    assert (state.touches_support, state.touches_resistance) == (1, 1)
    assert state.confidence == 75


def test_confidence_loses_width_credit_outside_the_band() -> None:
    narrow = ranging_window(support=Decimal(60000), resistance=Decimal(60100))
    state = detect_range(narrow, Decimal(60010), cfg())

    assert state is not None
    assert state.confidence == 70  # 95 - 25


def test_touches_count_episodes_not_candles() -> None:
    """Six consecutive candles on support are one test of the level."""
    consecutive = ranging_window(support_touches=(2, 3, 4, 5, 6, 7), resistance_touches=(15,))
    state = detect_range(consecutive, Decimal(NEAR_SUPPORT), cfg())

    assert state is not None
    assert state.touches_support == 1


def test_touch_tolerance_is_a_fraction_of_the_width() -> None:
    """A low 40 above support (0.04 W) touches at the 0.05 default, not at 0.03."""
    window = ranging_window(support_touches=(2,))
    # Raise every low but one so the tolerance decides.
    window[9] = candle(9, window[9].open, window[9].high, 60040, window[9].close)
    window[14] = candle(14, window[14].open, window[14].high, 60040, window[14].close)

    wide = detect_range(window, Decimal(NEAR_SUPPORT), cfg(touch_tolerance=Decimal("0.05")))
    tight = detect_range(window, Decimal(NEAR_SUPPORT), cfg(touch_tolerance=Decimal("0.03")))

    assert wide is not None and tight is not None
    assert wide.touches_support == 3
    assert tight.touches_support == 1


def test_range_state_figures_are_exact_and_quantized() -> None:
    state = detect_range(ranging_window(), Decimal(NEAR_SUPPORT), cfg())

    assert state is not None
    assert state.support == Decimal("60000.00")
    assert state.resistance == Decimal("61000.00")
    assert state.mid == Decimal("60500.00")
    assert state.width == Decimal("1000.00")
    assert state.width_pct == Decimal("1.6529")
    assert state.position == Decimal("0.1000")


def test_efficiency_is_zero_when_closes_never_move() -> None:
    window = [candle(k, 60000, 60010 + k, 59990 - k, 60000) for k in range(LOOKBACK)]
    state = detect_range(window, Decimal(60000), cfg())

    assert state is not None
    assert state.trend_efficiency == Decimal("0.0000")


def test_evaluate_is_deterministic() -> None:
    candles = with_price(ranging_window(), NEAR_SUPPORT)
    assert evaluate(candles, cfg()) == evaluate(candles, cfg())


@pytest.mark.parametrize("price", range(60000, 61001, 50))
def test_a_qualified_call_always_has_all_levels_and_a_wait_never_does(price: int) -> None:
    """The invariant over every price in the range, not just hand-picked ones."""
    signal = _evaluate(price)

    levels = (signal.entry, signal.take_profit, signal.stop_loss, signal.reward_risk)
    if signal.call is Call.WAIT:
        assert all(level is None for level in levels)
    else:
        assert all(level is not None for level in levels)
        assert len(signal.reasons) == 1
    if signal.call is Call.LONG:
        assert signal.range is not None and signal.range.position <= Decimal("0.20")
    if signal.call is Call.SHORT:
        assert signal.range is not None and signal.range.position >= Decimal("0.80")
