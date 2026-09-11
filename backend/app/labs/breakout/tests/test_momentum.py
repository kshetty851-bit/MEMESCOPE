"""The five momentum components and how they combine, with hand-computed
values and the identities a weighted score has to satisfy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.breakout import config
from app.labs.breakout.candles import Candle
from app.labs.breakout.levels import Levels
from app.labs.breakout.momentum import (
    compression_component,
    hourly_component,
    position_component,
    score,
    structure_component,
    volume_component,
)

DAY0 = datetime(2026, 1, 1, tzinfo=UTC)


def daily(i: int, *, high=10.0, low=9.0, close=9.5, open_=9.5, volume=1000.0) -> Candle:
    return Candle("M", "P", "day", DAY0 + timedelta(days=i), Decimal(str(open_)),
                  Decimal(str(high)), Decimal(str(low)), Decimal(str(close)),
                  Decimal(str(volume)), DAY0 + timedelta(days=i + 1))


def hourly(i: int, *, close: float, open_: float) -> Candle:
    return Candle("M", "P", "hour", DAY0 + timedelta(hours=i), Decimal(str(open_)),
                  Decimal(str(max(open_, close))), Decimal(str(min(open_, close))),
                  Decimal(str(close)), Decimal("100"), DAY0 + timedelta(hours=i + 1))


def levels(**kw) -> Levels:
    base = {"clusters": (), "nearest_resistance": None, "atr": 1.0, "atr_fast": 1.0,
            "atr_slow": 1.0, "volume_mean": 1000.0, "high_range": 20.0,
            "low_range": 10.0, "close": 15.0, "bars": 30}
    return Levels(**(base | kw))


# --- volume ---------------------------------------------------------------------

def test_volume_scores_full_marks_at_the_cap_and_zero_with_no_history() -> None:
    """Two days at 3x the mean is 3x -> the cap -> 1.0. Hand-computed:
    (3000 + 3000) / (2 * 1000) = 3.0, and 3.0 / VOLUME_RATIO_CAP = 1.0."""
    bars = [daily(0, volume=3000), daily(1, volume=3000)]
    assert volume_component(bars, 1000.0) == pytest.approx(1.0)
    assert volume_component(bars, None) == 0.0
    assert volume_component(bars, 0.0) == 0.0
    assert volume_component([], 1000.0) == 0.0


def test_volume_at_the_mean_scores_one_over_the_cap() -> None:
    bars = [daily(0, volume=1000), daily(1, volume=1000)]
    assert volume_component(bars, 1000.0) == pytest.approx(1 / config.VOLUME_RATIO_CAP)


def test_volume_above_the_cap_is_clamped_not_extrapolated() -> None:
    bars = [daily(0, volume=99_000), daily(1, volume=99_000)]
    assert volume_component(bars, 1000.0) == 1.0


def test_a_missing_volume_scores_zero_rather_than_guessing() -> None:
    bars = [daily(0, volume=3000), daily(1)]
    bars[1] = Candle("M", "P", "day", DAY0, Decimal("1"), Decimal("1"), Decimal("1"),
                     Decimal("1"), None, DAY0)
    assert volume_component(bars, 1000.0) == 0.0


# --- structure ------------------------------------------------------------------

def test_structure_counts_rising_lows_over_the_last_three_bars() -> None:
    rising = [daily(i, low=9 + i) for i in range(4)]
    assert structure_component(rising) == pytest.approx(1.0)
    falling = [daily(i, low=9 - i) for i in range(4)]
    assert structure_component(falling) == 0.0
    mixed = [daily(0, low=9), daily(1, low=10), daily(2, low=9), daily(3, low=11)]
    assert structure_component(mixed) == pytest.approx(2 / 3)


def test_structure_needs_one_bar_more_than_it_compares() -> None:
    assert structure_component([daily(0), daily(1), daily(2)]) == 0.0


def test_an_equal_low_is_not_a_rising_low() -> None:
    flat = [daily(i, low=9) for i in range(4)]
    assert structure_component(flat) == 0.0


# --- position -------------------------------------------------------------------

def test_position_is_where_the_close_sits_in_the_ten_day_range() -> None:
    assert position_component(levels(close=20.0)) == pytest.approx(1.0)
    assert position_component(levels(close=10.0)) == pytest.approx(0.0)
    assert position_component(levels(close=15.0)) == pytest.approx(0.5)
    assert position_component(levels(close=17.0)) == pytest.approx(0.7), "top 30% edge"


def test_a_degenerate_range_scores_zero_rather_than_dividing_by_it() -> None:
    assert position_component(levels(high_range=10.0, low_range=10.0)) == 0.0
    assert position_component(levels(high_range=None)) == 0.0


# --- compression ----------------------------------------------------------------

def test_compression_rewards_a_tightening_range() -> None:
    assert compression_component(levels(atr_fast=0.5, atr_slow=1.0)) == pytest.approx(0.5)
    assert compression_component(levels(atr_fast=1.0, atr_slow=1.0)) == 0.0
    assert compression_component(levels(atr_fast=2.0, atr_slow=1.0)) == 0.0, "expanding"
    assert compression_component(levels(atr_fast=0.1, atr_slow=1.0)) == pytest.approx(0.9)


def test_compression_is_zero_when_either_atr_is_missing() -> None:
    assert compression_component(levels(atr_fast=None)) == 0.0
    assert compression_component(levels(atr_slow=None)) == 0.0
    assert compression_component(levels(atr_slow=0.0)) == 0.0


# --- hourly ---------------------------------------------------------------------

def test_hourly_is_half_slope_and_half_share_green() -> None:
    up_and_green = [hourly(i, open_=10 + i, close=10.5 + i) for i in range(12)]
    assert hourly_component(up_and_green) == pytest.approx(1.0)
    down_and_red = [hourly(i, open_=20 - i, close=19.5 - i) for i in range(12)]
    assert hourly_component(down_and_red) == pytest.approx(0.0)


def test_hourly_scores_half_for_a_rising_series_of_red_bars() -> None:
    """Gapping up each hour and closing below the open: the slope is there,
    the participation is not."""
    bars = [hourly(i, open_=10 + i, close=9.9 + i) for i in range(12)]
    assert hourly_component(bars) == pytest.approx(0.5)


def test_hourly_is_none_not_zero_when_there_are_too_few_bars() -> None:
    """None is "we could not see"; zero is "we saw nothing happening". They
    must not render the same, because one of them caps the score."""
    assert hourly_component([hourly(i, open_=10, close=11) for i in range(11)]) is None
    assert hourly_component([]) is None


# --- the score ------------------------------------------------------------------

def test_a_perfect_setup_scores_one_hundred() -> None:
    bars = [daily(i, low=9 + i, volume=3000) for i in range(21)]
    hours = [hourly(i, open_=10 + i, close=10.5 + i) for i in range(12)]
    momentum = score(levels(close=20.0, atr_fast=0.0001, atr_slow=1.0), bars, hours)
    assert momentum.score == 100
    assert momentum.hourly_missing is False


def test_a_dead_token_scores_zero() -> None:
    bars = [daily(i, low=9 - i * 0.1, volume=0) for i in range(21)]
    hours = [hourly(i, open_=20 - i, close=19.5 - i) for i in range(12)]
    momentum = score(levels(close=10.0, atr_fast=2.0, atr_slow=1.0), bars, hours)
    assert momentum.score == 0


def test_the_weights_sum_to_one_so_the_score_can_reach_a_hundred() -> None:
    assert sum(config.MOMENTUM_WEIGHTS.values()) == pytest.approx(1.0)


def test_missing_hourly_renormalises_the_other_four_and_caps_the_score() -> None:
    """Scoring the absent component zero would punish us for our own data gap;
    leaving the weights alone would quietly score out of 85. Neither.
    """
    bars = [daily(i, low=9 + i, volume=3000) for i in range(21)]
    perfect = levels(close=20.0, atr_fast=0.0001, atr_slow=1.0)
    momentum = score(perfect, bars, [])
    assert momentum.hourly_missing is True
    assert momentum.hourly is None
    assert momentum.score == config.HOURLY_MISSING_SCORE_CAP
    assert momentum.score < score(
        perfect, bars, [hourly(i, open_=10 + i, close=10.5 + i) for i in range(12)]).score


def test_a_half_seen_token_never_outranks_a_fully_seen_one_at_the_same_quality() -> None:
    bars = [daily(i, low=9 + i, volume=3000) for i in range(21)]
    perfect = levels(close=20.0, atr_fast=0.0001, atr_slow=1.0)
    hours = [hourly(i, open_=10 + i, close=10.5 + i) for i in range(12)]
    assert score(perfect, bars, []).score <= score(perfect, bars, hours).score


def test_every_component_comes_back_with_the_score() -> None:
    bars = [daily(i, low=9 + i, volume=1500) for i in range(21)]
    hours = [hourly(i, open_=10 + i, close=10.5 + i) for i in range(12)]
    momentum = score(levels(), bars, hours)
    parts = momentum.components()
    assert set(parts) == {"volume", "structure", "position", "compression", "hourly"}
    assert all(v is None or 0.0 <= v <= 1.0 for v in parts.values())
    assert 0 <= momentum.score <= 100
