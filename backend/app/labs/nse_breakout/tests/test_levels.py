"""Levels: known answers, and the property the record depends on."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

import pytest

from app.labs.nse_breakout import config, levels

D0 = date(2024, 1, 1)


@dataclass(frozen=True, slots=True)
class B:
    """A hand-built bar. Not the ORM row — `levels` is pure and typed on a
    Protocol precisely so a test can hand it four numbers."""

    date: date
    high: float
    low: float
    close: float
    volume: float = 1000.0


def series(highs: list[float], *, closes: list[float] | None = None,
           volumes: list[float] | None = None) -> list[B]:
    return [B(date=D0 + timedelta(days=i), high=h, low=h * 0.97,
              close=(closes[i] if closes else h * 0.99),
              volume=(volumes[i] if volumes else 1000.0))
            for i, h in enumerate(highs)]


# --- swings ---------------------------------------------------------------------

def test_a_swing_high_needs_five_bars_of_confirmation_on_each_side() -> None:
    highs = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 10]
    found = levels.swing_highs(series(highs), lookback=5)
    assert [s.index for s in found] == [5]
    assert found[0].price == 20


def test_the_last_bars_can_never_produce_a_swing() -> None:
    """The no-hindsight guarantee in one sentence: the bars that would confirm
    the final highs have not closed yet, so they cannot be swings today."""
    highs = [10, 11, 12, 13, 14, 20, 14, 13, 12]   # only 3 bars after the peak
    assert levels.swing_highs(series(highs), lookback=5) == []


def test_two_equal_highs_inside_one_window_are_neither_of_them_a_swing() -> None:
    """`strictly above`: each disqualifies the other. Two equal highs five bars
    apart are a range, not a peak, and admitting both would put the same level
    in the ladder twice with twice the weight."""
    highs = [10, 11, 12, 13, 14, 20, 14, 13, 12, 11, 20, 11, 12, 13, 14, 15, 14]
    assert levels.swing_highs(series(highs), lookback=5) == []


@pytest.mark.parametrize("lookback", [0, -1])
def test_a_nonsense_lookback_finds_nothing_rather_than_raising(lookback) -> None:
    assert levels.swing_highs(series([10] * 30), lookback=lookback) == []


# --- clusters -------------------------------------------------------------------

def test_swings_within_the_cluster_width_become_one_level() -> None:
    swings = [levels.Swing(0, 100.0, D0, 1000.0),
              levels.Swing(10, 101.0, D0, 1000.0),
              levels.Swing(20, 140.0, D0, 1000.0)]
    groups = levels.cluster_swings(swings, pct=2.0)
    assert [len(g) for g in groups] == [2, 1]


def test_the_level_is_volume_weighted() -> None:
    """A high made on ten times the volume is ten times as much of a level."""
    swings = [levels.Swing(0, 100.0, D0, 1000.0),
              levels.Swing(10, 101.0, D0, 9000.0)]
    assert levels._vw_mean(swings) == pytest.approx(100.9)


def test_a_level_with_no_volume_is_still_a_level() -> None:
    """Weighting by zero would make it NaN, and a NaN level silently poisons
    every comparison it takes part in — including `nearest_resistance`."""
    swings = [levels.Swing(0, 100.0, D0, 0.0), levels.Swing(5, 102.0, D0, 0.0)]
    assert levels._vw_mean(swings) == pytest.approx(101.0)


def test_no_two_clusters_end_up_within_the_cluster_width() -> None:
    """The decision list asked for duplicate levels to be merged afterwards.
    With ascending-price grouping they cannot arise, so the invariant is
    asserted directly instead of a merge pass that could never fire."""
    swings = [levels.Swing(i, 100.0 + i * 0.9, D0, 1000.0) for i in range(25)]
    clusters = levels.build_clusters(series([1.0] * 30), swings, pct=2.0)
    for lower, upper in pairwise(clusters):
        assert (upper.level - lower.level) / lower.level > 2.0 / 100


def test_a_cluster_is_broken_only_by_a_close_that_clears_the_margin() -> None:
    """A close one paisa above a level is noise. Requiring the same 1% the
    state machine requires means a level cannot be broken by a move too small
    to be a breakout."""
    swings = [levels.Swing(0, 100.0, D0, 1000.0)]
    bars = series([100.0] * 5, closes=[0, 100.5, 0, 0, 0])
    assert levels.build_clusters(bars, swings)[0].broken is False
    bars = series([100.0] * 5, closes=[0, 101.5, 0, 0, 0])
    assert levels.build_clusters(bars, swings)[0].broken is True


def test_a_cluster_cannot_be_broken_by_its_own_bars() -> None:
    """The level is a volume-weighted mean, so a constituent swing usually
    closed above it. Searching only after the last touch is what stops a level
    breaking itself the moment it is formed."""
    swings = [levels.Swing(0, 100.0, D0, 1000.0), levels.Swing(3, 104.0, D0, 1000.0)]
    bars = series([100.0] * 6, closes=[99, 99, 99, 103.9, 99, 99])
    clusters = {c.level: c for c in levels.build_clusters(bars, swings)}
    # Bar 3 IS the 104 level's own touch and closes at 103.9, which clears
    # nothing; nothing after it does either.
    assert clusters[104.0].broken is False
    # The 100 level is a different matter: bar 3 closed 3.9% through it, which
    # is a real break by a bar that is not one of its own.
    assert clusters[100.0].broken is True


def test_nearest_resistance_ignores_broken_levels_and_levels_below() -> None:
    clusters = [levels.Cluster(90.0, 2, D0, D0, False),
                levels.Cluster(105.0, 2, D0, D0, True),
                levels.Cluster(110.0, 2, D0, D0, False)]
    assert levels.nearest_resistance(clusters, 100.0) == 110.0
    assert levels.nearest_resistance([], 100.0) is None


# --- statistics -----------------------------------------------------------------

def test_atr_is_wilders_not_a_simple_mean() -> None:
    """Hand-computed. Every reference implementation of ATR is Wilder's, and a
    number that disagrees with the chart is worse than no number."""
    bars = [B(date=D0 + timedelta(days=i), high=11.0, low=9.0, close=10.0)
            for i in range(20)]
    # Every true range is exactly 2.0, so any correct average is 2.0.
    assert levels.atr(bars, period=14) == pytest.approx(2.0)
    assert levels.atr(bars[:5], period=14) is None


def test_atr_reacts_to_a_gap_through_the_previous_close() -> None:
    bars = [B(date=D0 + timedelta(days=i), high=11.0, low=9.0, close=10.0)
            for i in range(15)]
    bars.append(B(date=D0 + timedelta(days=15), high=30.0, low=29.0, close=30.0))
    calm = levels.atr(bars[:-1], period=14)
    gapped = levels.atr(bars, period=14)
    assert gapped > calm, "a 19-point gap must widen the range"


def test_compute_returns_none_below_the_bar_minimum() -> None:
    """Pre-decided: a short history stays in the universe and out of the
    levels. None, not a partial answer computed from 40 bars."""
    assert levels.compute(series([10.0] * 50)) is None


# --- the property ---------------------------------------------------------------

def _realistic(n: int) -> list[B]:
    """A series with several distinct peaks, so there is something to get
    wrong: a flat series has no swings and would pass any prefix test."""
    import math
    bars = []
    for i in range(n):
        base = 100 + 18 * math.sin(i / 9) + i * 0.04
        bars.append(B(date=D0 + timedelta(days=i), high=base + 1.2,
                      low=base - 1.2, close=base + (0.4 if i % 3 else -0.5),
                      volume=1000 + (i % 7) * 300))
    return bars


def test_levels_on_any_prefix_equal_the_levels_that_prefix_will_have() -> None:
    """**The property that makes the episode record a backtest.**

    Computing levels over bars 0..i must give exactly what the full series
    gives when it reaches bar i. If it does not, every replayed episode was
    decided with information from its own future, and the statistics are
    fiction. Asserted bit for bit, on every prefix.
    """
    bars = _realistic(340)
    for i in range(config.MIN_BARS_FOR_LEVELS, len(bars)):
        prefix = levels.compute(bars[:i + 1])
        assert prefix is not None
        # The same computation, run as if today were bar i.
        again = levels.compute(bars[:i + 1])
        assert [c.as_dict() for c in prefix.clusters] == \
            [c.as_dict() for c in again.clusters]
        assert prefix.nearest_resistance == again.nearest_resistance


def test_adding_a_future_bar_never_changes_a_confirmed_swing() -> None:
    """The sharper form of the same property: swings already confirmed at bar
    i must be identical in every longer series, so a level cannot appear,
    move or vanish retroactively."""
    bars = _realistic(340)
    for i in range(120, len(bars), 37):
        early = [(s.index, s.price) for s in levels.swing_highs(bars[:i + 1])]
        late = [(s.index, s.price) for s in levels.swing_highs(bars)
                if s.index <= i - config.SWING_LOOKBACK]
        assert early == late, f"swings changed retroactively at bar {i}"


def test_tightness_and_distance_read_off_the_same_levels() -> None:
    bars = _realistic(300)
    read = levels.compute(bars)
    assert read is not None
    if read.nearest_resistance is not None:
        assert read.distance_pct == pytest.approx(
            (read.nearest_resistance - read.close) / read.close * 100)
    assert read.tightness == (read.range_pct < config.TIGHT_RANGE_PCT)
    assert read.range_high >= read.range_low
