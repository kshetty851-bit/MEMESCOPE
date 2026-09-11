"""Swings, clusters and the daily statistics — with known answers, and the
no-hindsight property that makes the whole record usable later."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest

from app.labs.breakout import config
from app.labs.breakout.candles import Candle
from app.labs.breakout.levels import (
    Swing,
    atr,
    build_clusters,
    cluster_swings,
    compute,
    nearest_resistance,
    swing_highs,
    true_ranges,
)

DAY0 = datetime(2026, 1, 1, tzinfo=UTC)


def bar(i: int, *, high: float, low: float | None = None, close: float | None = None,
        open_: float | None = None, volume: float = 1000.0) -> Candle:
    low = high * 0.9 if low is None else low
    close = (high + low) / 2 if close is None else close
    open_ = close if open_ is None else open_
    return Candle(
        mint="M", pool_address="P", timeframe="day",
        open_time=DAY0 + timedelta(days=i),
        open=Decimal(str(open_)), high=Decimal(str(high)), low=Decimal(str(low)),
        close=Decimal(str(close)), volume_usd=Decimal(str(volume)),
        close_time=DAY0 + timedelta(days=i + 1),
    )


def series(highs: list[float], **kw) -> list[Candle]:
    return [bar(i, high=h, **kw) for i, h in enumerate(highs)]


# --- swing highs ----------------------------------------------------------------

def test_a_peak_with_three_lower_bars_each_side_is_a_swing_high() -> None:
    #                          0  1  2  3*  4  5  6
    candles = series([1, 2, 3, 9, 3, 2, 1])
    (swing,) = swing_highs(candles, lookback=3)
    assert swing.index == 3
    assert swing.price == 9


def test_the_last_lookback_bars_can_never_be_a_swing_high() -> None:
    """The bars that would confirm them have not closed. This one `range()`
    bound is the entire no-hindsight guarantee."""
    candles = series([1, 2, 3, 4, 5, 6, 99])
    assert swing_highs(candles, lookback=3) == []


def test_a_tie_is_not_a_swing_high() -> None:
    """`>` not `>=`: a shelf of equal highs has no single seller's price."""
    assert swing_highs(series([1, 2, 5, 5, 5, 2, 1]), lookback=2) == []


def test_a_series_shorter_than_the_window_yields_nothing() -> None:
    assert swing_highs(series([1, 2, 3]), lookback=3) == []
    assert swing_highs(series([5, 1, 5]), lookback=0) == []


def test_two_separated_peaks_are_two_swings() -> None:
    candles = series([1, 2, 8, 2, 1, 2, 1, 2, 7, 2, 1, 2])
    assert [s.index for s in swing_highs(candles, lookback=2)] == [2, 8]


# --- clustering -----------------------------------------------------------------

def swing(price: float, index: int = 0, volume: float = 1.0) -> Swing:
    return Swing(index=index, price=price, at=DAY0 + timedelta(days=index), volume=volume)


def test_prices_within_the_cluster_pct_become_one_group() -> None:
    groups = cluster_swings([swing(100), swing(102), swing(101)], pct=0.03)
    assert len(groups) == 1 and len(groups[0]) == 3


def test_a_price_outside_the_pct_starts_a_new_group() -> None:
    groups = cluster_swings([swing(100), swing(140)], pct=0.03)
    assert [len(g) for g in groups] == [1, 1]


def test_the_level_is_the_volume_weighted_mean() -> None:
    """100 at weight 1 and 102 at weight 3 -> 101.5, not 101."""
    candles = series([1] * 10)
    clusters = build_clusters(candles, [swing(100, 0, 1.0), swing(102, 1, 3.0)], pct=0.03)
    assert clusters[0].level == pytest.approx(101.5)
    assert clusters[0].touches == 2


def test_a_group_with_no_volume_falls_back_to_the_plain_mean() -> None:
    """Weighting by zero would make the level NaN and poison every comparison."""
    candles = series([1] * 10)
    clusters = build_clusters(candles, [swing(100, 0, 0.0), swing(104, 1, 0.0)], pct=0.05)
    assert clusters[0].level == pytest.approx(102.0)


def test_clusters_come_back_ascending_by_level() -> None:
    candles = series([1] * 20)
    clusters = build_clusters(
        candles, [swing(300, 0), swing(100, 1), swing(200, 2)], pct=0.01)
    assert [c.level for c in clusters] == [100, 200, 300]


@pytest.mark.parametrize("prices", [
    [100, 103, 106, 109],                       # an even ladder
    [100, 100.5, 101, 150, 151, 152],           # two tight shelves far apart
    [10, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6],   # a continuous drift
    [5, 5, 5, 5],                               # identical prices
])
def test_no_two_clusters_ever_end_up_within_the_cluster_pct(prices) -> None:
    """The invariant the "merge duplicates" decision was actually asking for.

    There is no merge pass, because with this grouping there is nothing to
    merge — a new group opens only when the previous group's mean is final and
    already further than `pct` away. This asserts that directly, so the day
    someone changes `cluster_swings` the guarantee does not vanish silently.
    """
    candles = series([1] * 20)
    swings = [swing(p, i) for i, p in enumerate(prices)]
    clusters = build_clusters(candles, swings, pct=0.03)
    for lower, higher in pairwise(clusters):
        gap = (higher.level - lower.level) / lower.level
        assert gap > 0.03, f"{lower.level} and {higher.level} are {gap:.3%} apart"
    assert sum(c.touches for c in clusters) == len(prices), "no swing lost"


def test_a_level_breaks_only_on_a_close_above_it_after_the_last_touch() -> None:
    """Taken literally, "any daily close above it" lets a cluster break
    itself: the level is a volume-weighted mean, so a constituent swing can
    have closed above it."""
    # The swing bar itself closes at 100 — above the 99 level — and must not
    # break it. Bar 6 closes at 120 and must.
    candles = [bar(i, high=10, close=10) for i in range(10)]
    candles[2] = bar(2, high=101, low=90, close=100)
    clusters = build_clusters(candles, [Swing(2, 99.0, candles[2].open_time, 1.0)])
    assert clusters[0].broken is False

    candles[6] = bar(6, high=130, low=100, close=120)
    clusters = build_clusters(candles, [Swing(2, 99.0, candles[2].open_time, 1.0)])
    assert clusters[0].broken is True


def test_nearest_resistance_is_the_lowest_unbroken_level_above_the_close() -> None:
    candles = series([1] * 20)
    swings = [swing(50, 0), swing(150, 1), swing(250, 2)]
    clusters = build_clusters(candles, swings, pct=0.001)
    assert nearest_resistance(clusters, close=100) == 150
    assert nearest_resistance(clusters, close=300) is None, "nothing above"
    assert nearest_resistance(clusters, close=10) == 50


def test_a_broken_level_is_not_resistance() -> None:
    candles = [bar(i, high=10, close=10) for i in range(10)]
    candles[8] = bar(8, high=200, low=10, close=199)
    clusters = build_clusters(candles, [Swing(2, 150.0, candles[2].open_time, 1.0)])
    assert clusters[0].broken is True
    assert nearest_resistance(clusters, close=100) is None


# --- ATR ------------------------------------------------------------------------

def test_true_range_is_the_widest_of_the_three_definitions() -> None:
    candles = [bar(0, high=10, low=9, close=9.5), bar(1, high=12, low=11, close=11.5)]
    # h-l = 1; |h - prev_close| = 2.5; |l - prev_close| = 1.5  ->  2.5
    assert true_ranges(candles) == [pytest.approx(2.5)]


def test_atr_seeds_on_the_mean_then_smooths_the_wilder_way() -> None:
    """Hand-computed: a constant true range of 1 gives an ATR of exactly 1
    whatever the period, and Wilder's recursion preserves it."""
    candles = [bar(i, high=10 + i, low=9 + i, close=9.5 + i) for i in range(30)]
    ranges = true_ranges(candles)
    assert all(r == pytest.approx(ranges[0]) for r in ranges)
    assert atr(candles, 14) == pytest.approx(ranges[0])


def test_atr_is_none_without_enough_bars() -> None:
    assert atr(series([1, 2, 3]), 14) is None
    assert atr(series([1] * 30), 0) is None


# --- compute --------------------------------------------------------------------

def test_a_token_with_too_few_daily_bars_is_skipped_not_an_error() -> None:
    assert compute(series([1] * (config.MIN_DAILY_BARS - 1))) is None


def test_compute_fills_every_daily_statistic() -> None:
    highs = [10, 12, 11, 20, 11, 12, 10, 11, 13, 12, 11, 14, 12, 11, 13, 12,
             11, 12, 13, 12, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    levels = compute(series(highs))
    assert levels is not None
    assert levels.bars == len(highs)
    assert levels.atr is not None and levels.atr > 0
    assert levels.atr_fast is not None and levels.atr_slow is not None
    assert levels.volume_mean == pytest.approx(1000.0)
    assert levels.high_range == max(highs[-config.RANGE_DAYS:])
    assert levels.close == pytest.approx(float(series(highs)[-1].close))


# --- the property that matters --------------------------------------------------

@pytest.mark.parametrize("lookback", [1, 2, 3, 5])
def test_levels_computed_on_a_prefix_equal_those_the_full_series_had_then(
    lookback,
) -> None:
    """**No hindsight, asserted on every prefix bar.**

    The clusters computed over bars 0..i must be exactly the clusters that
    were computed over 0..i when the series was that long — otherwise every
    row in `bo_episodes` was written with knowledge of the future and the
    table is worthless as a backtest.

    Swings are compared rather than whole `compute()` output because `broken`
    legitimately changes as later bars close through a level; the swing set is
    the thing that must never be revised.
    """
    highs = [10, 14, 11, 9, 17, 12, 8, 13, 19, 11, 7, 15, 22, 10, 9,
             16, 12, 25, 11, 8, 14, 20, 9, 13, 18, 10, 11, 24, 12, 9]
    full = series(highs)
    for i in range(len(full)):
        prefix = full[:i + 1]
        from_prefix = swing_highs(prefix, lookback=lookback)
        from_full = [s for s in swing_highs(full, lookback=lookback)
                     if s.index + lookback <= i]
        assert [(s.index, s.price) for s in from_prefix] == \
               [(s.index, s.price) for s in from_full], f"prefix {i}"


def test_a_swing_appears_exactly_lookback_bars_after_it_happened() -> None:
    """Not earlier — which would be hindsight — and not later, which would
    make the lab permanently behind the market."""
    full = series([1, 2, 3, 9, 3, 2, 1, 1, 1])
    assert swing_highs(full[:6], lookback=3) == []
    assert len(swing_highs(full[:7], lookback=3)) == 1
