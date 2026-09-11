"""The readiness score: each component on its own, and the whole."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from app.labs.nse_breakout import config, score
from app.labs.nse_breakout.levels import Cluster, Levels

D0 = date(2024, 1, 1)


@dataclass(frozen=True, slots=True)
class B:
    date: date
    high: float
    low: float
    close: float
    volume: float = 1000.0


def flat(n: int, close: float = 100.0, volume: float = 1000.0) -> list[B]:
    return [B(date=D0 + timedelta(days=i), high=close, low=close, close=close,
              volume=volume) for i in range(n)]


def read(close: float, *, resistance: float | None = 100.0, touches: int = 3,
         range_pct: float = 10.0, volume_mean: float = 1000.0,
         volume: float = 1000.0) -> Levels:
    low = close * (1 - range_pct / 200)
    return Levels(
        clusters=(Cluster(resistance or 0.0, touches, D0, D0, False),),
        nearest_resistance=resistance, is_52w_high=False, week52_high=resistance,
        atr=1.0, volume_mean=volume_mean, volume_slow_mean=volume_mean,
        range_high=low * (1 + range_pct / 100), range_low=low, close=close,
        volume=volume, bars=300)


# --- components ------------------------------------------------------------------

def test_proximity_is_one_on_the_level_and_zero_a_watch_width_away() -> None:
    assert score.proximity_component(read(100.0)) == pytest.approx(1.0)
    assert score.proximity_component(read(100.0 / 1.10)) == pytest.approx(0.0,
                                                                         abs=1e-9)
    assert 0.4 < score.proximity_component(read(94.5)) < 0.6


def test_a_stock_with_nothing_above_it_scores_zero_for_proximity() -> None:
    """Not one. A stock with no resistance is not ready to break out — it has
    already broken out of everything, which is a different thing and must not
    be the top of the board."""
    assert score.proximity_component(read(100.0, resistance=None)) == 0.0


def test_compression_rewards_a_narrow_range() -> None:
    assert score.compression_component(read(97.0, range_pct=0.0)) == \
        pytest.approx(1.0)
    assert score.compression_component(
        read(97.0, range_pct=config.TIGHT_RANGE_PCT)) == pytest.approx(1.0)
    assert score.compression_component(
        read(97.0, range_pct=2 * config.TIGHT_RANGE_PCT)) == pytest.approx(0.0)


def test_trend_needs_both_a_price_above_the_mean_and_a_rising_mean() -> None:
    """Half each. A stock above a falling mean is bouncing; a stock below a
    rising one has stopped participating. The setup wants both."""
    days = config.SCORE_TREND_DAYS
    rising = flat(days, close=90.0) + flat(days, close=100.0)
    for i, b in enumerate(rising):
        rising[i] = B(date=D0 + timedelta(days=i), high=b.high, low=b.low,
                      close=b.close)
    assert score.trend_component(rising, read(110.0)) == pytest.approx(1.0)
    assert score.trend_component(flat(2 * days), read(100.0)) == \
        pytest.approx(0.0, abs=1e-9)


def test_trend_is_zero_without_enough_history_rather_than_guessed() -> None:
    assert score.trend_component(flat(40), read(100.0)) == 0.0


def test_volume_saturates_at_twice_the_twenty_day_mean() -> None:
    bars = flat(30, volume=2000.0)
    assert score.volume_component(bars, read(97.0, volume_mean=1000.0)) == \
        pytest.approx(1.0)
    assert score.volume_component(flat(30, volume=1000.0),
                                  read(97.0, volume_mean=1000.0)) == \
        pytest.approx(0.0, abs=1e-9)


def test_touches_saturate_at_four() -> None:
    assert score.touches_component(read(97.0, touches=1)) == pytest.approx(0.0)
    assert score.touches_component(read(97.0, touches=4)) == pytest.approx(1.0)
    assert score.touches_component(read(97.0, touches=9)) == pytest.approx(1.0)


# --- the whole ---------------------------------------------------------------------

def test_the_score_is_the_weighted_sum_of_its_five_parts() -> None:
    """Asserted against the weights themselves, so a weight that changes
    without the documentation changing is caught here."""
    bars = flat(120, close=100.0, volume=1000.0)
    reading = read(97.0)
    result = score.compute(bars, reading)
    expected = sum(result.components()[name] * weight
                   for name, weight in config.SCORE_WEIGHTS.items()) * 100
    assert result.score == round(expected)
    assert sum(config.SCORE_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_component_is_reported_beside_the_score() -> None:
    """A score nobody can take apart is a number nobody can argue with — and
    the decile table exists to ask which of the five, if any, predicted
    anything."""
    result = score.compute(flat(120), read(97.0))
    assert set(result.components()) == set(config.SCORE_WEIGHTS)
    assert all(0.0 <= v <= 1.0 for v in result.components().values())
    assert 0 <= result.score <= 100
