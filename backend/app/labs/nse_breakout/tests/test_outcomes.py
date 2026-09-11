"""The outcome arithmetic, on hand-built series where the answer is known."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from app.labs.nse_breakout import config, outcomes

D0 = date(2024, 1, 1)


@dataclass(frozen=True, slots=True)
class B:
    date: date
    high: float
    low: float
    close: float
    volume: float = 1000.0


def bars(closes: list[float], *, highs: list[float] | None = None,
         lows: list[float] | None = None) -> list[B]:
    return [B(date=D0 + timedelta(days=i + 1), high=(highs[i] if highs else c),
              low=(lows[i] if lows else c), close=c)
            for i, c in enumerate(closes)]


# --- returns --------------------------------------------------------------------

def test_returns_are_read_at_the_right_bars() -> None:
    forward = bars([101.0 + i for i in range(45)])
    result = outcomes.returns_from(100.0, forward)
    assert result.get(5) == pytest.approx(5.0)    # close of the 5th forward bar
    assert result.get(10) == pytest.approx(10.0)
    assert result.get(40) == pytest.approx(40.0)


def test_a_horizon_the_series_does_not_reach_is_absent_not_zero() -> None:
    """The difference between "it went nowhere" and "we cannot know yet" is
    the whole point of a record like this. A zero would be averaged in as a
    flat trade and would quietly drag every statistic toward nothing."""
    result = outcomes.returns_from(100.0, bars([101.0] * 12))
    assert result.get(10) is not None
    assert result.get(20) is None and 20 not in result.returns


def test_excursions_are_the_extremes_of_the_twenty_day_window() -> None:
    closes = [100.0] * 30
    highs = [100.0] * 30
    lows = [100.0] * 30
    highs[7] = 130.0      # inside the window
    lows[12] = 80.0       # inside the window
    highs[25] = 500.0     # outside it, must not count
    result = outcomes.returns_from(100.0, bars(closes, highs=highs, lows=lows))
    assert result.mfe == pytest.approx(30.0)
    assert result.mae == pytest.approx(-20.0)


def test_an_entry_of_zero_produces_nothing_rather_than_dividing_by_it() -> None:
    result = outcomes.returns_from(0.0, bars([100.0] * 40))
    assert result.returns == {} and result.mfe is None


# --- the trailing stop -----------------------------------------------------------

def test_the_trail_takes_the_low_before_the_high() -> None:
    """**The line that decides whether any of these numbers mean anything.**

    One bar runs from 100 down to 85 and up to 130. Low first, the 10% stop at
    90 is hit and the trade is out at -10%. High first, the stop would have
    ratcheted to 117 and the trade would show a profit. We cannot see the order
    inside a daily bar, so we assume the one that costs us.
    """
    result = outcomes.trail_result(100.0, bars([120.0], highs=[130.0], lows=[85.0]))
    assert result is not None
    assert result.stopped is True
    assert result.pct == pytest.approx(-10.0)
    assert result.bars_held == 1


def test_the_high_water_mark_only_rises_after_the_low_is_checked() -> None:
    """Two bars: the first sets a high of 150, the second dips to 130. The stop
    is 10% under 150, which is 135 — so the second bar takes it out. If the
    order were reversed the stop would follow the price down and never fire."""
    series = bars([150.0, 131.0], highs=[150.0, 132.0], lows=[100.0, 130.0])
    result = outcomes.trail_result(100.0, series)
    assert result is not None and result.stopped is True
    assert result.pct == pytest.approx(35.0)      # out at 135


def test_a_stop_that_never_fires_marks_out_at_the_last_close() -> None:
    result = outcomes.trail_result(100.0, bars([100.0 + i for i in range(30)]))
    assert result is not None
    assert result.stopped is False
    assert result.pct == pytest.approx(29.0)
    assert result.bars_held == 30


def test_the_trail_is_capped_so_an_outcome_always_has_an_answer() -> None:
    result = outcomes.trail_result(100.0, bars([100.0 + i * 0.1 for i in range(400)]))
    assert result is not None
    assert result.bars_held == config.TRAIL_MAX_DAYS


def test_no_forward_bars_is_none_not_zero() -> None:
    """An unmeasurable outcome is not a flat one."""
    assert outcomes.trail_result(100.0, []) is None


# --- relative to the index --------------------------------------------------------

def test_relative_return_subtracts_the_index_over_the_same_window() -> None:
    index = [100.0 + i for i in range(21)]        # +20% over 20 bars
    assert outcomes.relative_to_index(35.0, index, 20) == pytest.approx(15.0)


def test_a_missing_index_window_is_null_never_zero() -> None:
    """Pre-decided. Zero is a number and would be averaged in as "matched the
    market"; null is the absence of one."""
    assert outcomes.relative_to_index(35.0, [100.0] * 5, 20) is None
    assert outcomes.relative_to_index(None, [100.0] * 30, 20) is None
    assert outcomes.relative_to_index(35.0, [0.0] * 30, 20) is None
