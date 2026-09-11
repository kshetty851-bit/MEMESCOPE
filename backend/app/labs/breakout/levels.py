"""Daily candles -> resistance levels. Pure; no I/O, no clock.

A level here is a CLUSTER of confirmed swing highs that sit within
`CLUSTER_PCT` of each other. One swing high is a price somebody sold at once;
three within a few percent is a price somebody sells at, and that is what a
breakout has to get through.

**Nothing in this module may look forward.** A swing high is confirmed only
once the bar `SWING_LOOKBACK` bars after it has closed, so the level set
computed over bars 0..i is the same one that will be computed over the whole
series when it reaches i. `test_levels.py` asserts that bit for bit on every
prefix — it is the property that makes `bo_episodes` usable as a backtest
later, and it is very easy to lose.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from app.labs.breakout import config
from app.labs.breakout.candles import Candle


@dataclass(frozen=True, slots=True)
class Cluster:
    """One resistance level: where it sits, how often it was hit, and whether
    price has since closed through it."""

    level: float
    touches: int
    first: datetime
    last: datetime
    broken: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "touches": self.touches,
            "first": self.first.isoformat(),
            "last": self.last.isoformat(),
            "broken": self.broken,
        }


@dataclass(frozen=True, slots=True)
class Levels:
    """Everything the momentum score and the state machine read off the daily
    series. `nearest_resistance` is None when there is nothing unbroken above
    the close — which means no setup, not an error."""

    clusters: tuple[Cluster, ...]
    nearest_resistance: float | None
    atr: float | None
    atr_fast: float | None
    atr_slow: float | None
    volume_mean: float | None
    high_range: float | None
    low_range: float | None
    close: float
    bars: int


# --- swings -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Swing:
    index: int
    price: float
    at: datetime
    volume: float


def swing_highs(
    candles: Sequence[Candle], lookback: int = config.SWING_LOOKBACK,
) -> list[Swing]:
    """Confirmed swing highs, oldest first.

    Bar `i` is a swing high when its high is STRICTLY above every high within
    `lookback` bars on each side. The right-hand side must exist — the last
    `lookback` bars of the series can never produce one, because the bars that
    would confirm them have not closed. That is the whole no-hindsight
    guarantee, and it is one `range()` bound.
    """
    if lookback < 1 or len(candles) < 2 * lookback + 1:
        return []
    found: list[Swing] = []
    for i in range(lookback, len(candles) - lookback):
        high = float(candles[i].high)
        window = range(i - lookback, i + lookback + 1)
        if all(float(candles[j].high) < high for j in window if j != i):
            found.append(Swing(i, high, candles[i].open_time,
                               float(candles[i].volume_usd or 0.0)))
    return found


# --- clusters -----------------------------------------------------------------

def cluster_swings(
    swings: Sequence[Swing], pct: float = config.CLUSTER_PCT,
) -> list[list[Swing]]:
    """Group swing highs whose prices sit within `pct` of the group's running
    volume-weighted mean. Sorted by price, so grouping is deterministic and
    independent of the order the swings were found in."""
    groups: list[list[Swing]] = []
    for swing in sorted(swings, key=lambda s: s.price):
        if groups and abs(swing.price - _vw_mean(groups[-1])) / _vw_mean(groups[-1]) <= pct:
            groups[-1].append(swing)
        else:
            groups.append([swing])
    return groups


def _vw_mean(swings: Sequence[Swing]) -> float:
    """Volume-weighted mean price. Falls back to the plain mean when no swing
    in the group carries a volume — a level with unknown volume is still a
    level, and weighting by zero would make it NaN."""
    total = sum(s.volume for s in swings)
    if total <= 0:
        return sum(s.price for s in swings) / len(swings)
    return sum(s.price * s.volume for s in swings) / total


def build_clusters(
    candles: Sequence[Candle], swings: Sequence[Swing], pct: float = config.CLUSTER_PCT,
) -> list[Cluster]:
    """Swing groups -> clusters, ascending by level, duplicates merged.

    **`broken` means a daily bar closed above the level AFTER the cluster's
    last touch.** The brief says "any daily close above it"; taken literally a
    cluster can be broken by one of its own constituent bars, because the
    level is a volume-weighted mean and a swing above that mean may have
    closed above it too. Restricting the search to bars after the last touch
    removes that self-break, and it is the conservative reading: fewer levels
    are called broken, so more of them stay standing as resistance and fewer
    breakouts are claimed.

    **There is no separate merge pass, and none is reachable.** The decision
    list asks for duplicate clusters to be merged after rounding. With this
    grouping they cannot arise: `cluster_swings` walks the swings in ascending
    price and opens a new group only when the previous group's mean — which is
    final at that moment, since every remaining swing is higher — is already
    more than `pct` away. So no two clusters can end up within `pct` of each
    other, and a fold over them would never fire. `test_levels.py` asserts the
    invariant directly instead, which is what the decision was actually for.
    """
    clusters: list[Cluster] = []
    for group in cluster_swings(swings, pct):
        level = _vw_mean(group)
        last_index = max(s.index for s in group)
        broken = any(float(c.close) > level for c in candles[last_index + 1:])
        clusters.append(Cluster(
            level=level,
            touches=len(group),
            first=min(s.at for s in group),
            last=max(s.at for s in group),
            broken=broken,
        ))
    clusters.sort(key=lambda c: c.level)
    return clusters


def nearest_resistance(clusters: Sequence[Cluster], close: float) -> float | None:
    """The lowest unbroken level above `close`, or None."""
    above = [c.level for c in clusters if not c.broken and c.level > close]
    return min(above) if above else None


# --- daily statistics ---------------------------------------------------------

def true_ranges(candles: Sequence[Candle]) -> list[float]:
    """`max(h-l, |h-prev_close|, |l-prev_close|)`, one per bar after the first."""
    ranges = []
    for previous, current in pairwise(candles):
        close = float(previous.close)
        high, low = float(current.high), float(current.low)
        ranges.append(max(high - low, abs(high - close), abs(low - close)))
    return ranges


def atr(candles: Sequence[Candle], period: int) -> float | None:
    """Wilder's ATR at the last bar, or None without enough history.

    Wilder rather than a simple mean because every reference implementation of
    ATR is Wilder's, and a number that does not match the chart the user is
    looking at is worse than no number.
    """
    ranges = true_ranges(candles)
    if period < 1 or len(ranges) < period:
        return None
    value = sum(ranges[:period]) / period
    for current in ranges[period:]:
        value = (value * (period - 1) + current) / period
    return value


def compute(
    candles: Sequence[Candle], *, min_bars: int = config.MIN_DAILY_BARS,
) -> Levels | None:
    """The whole daily read for one token, or None when it is too young.

    `candles` must be closed daily bars, OLDEST FIRST — the order `data.py`
    returns them in.
    """
    if len(candles) < min_bars:
        return None
    close = float(candles[-1].close)
    swings = swing_highs(candles)
    clusters = build_clusters(candles, swings)
    recent = candles[-config.RANGE_DAYS:]
    volumes = [float(c.volume_usd) for c in candles[-config.VOLUME_MEAN_DAYS:]
               if c.volume_usd is not None]
    return Levels(
        clusters=tuple(clusters),
        nearest_resistance=nearest_resistance(clusters, close),
        atr=atr(candles, config.DAILY_ATR_PERIOD),
        atr_fast=atr(candles, config.ATR_FAST_DAYS),
        atr_slow=atr(candles, config.ATR_SLOW_DAYS),
        volume_mean=sum(volumes) / len(volumes) if volumes else None,
        high_range=max(float(c.high) for c in recent),
        low_range=min(float(c.low) for c in recent),
        close=close,
        bars=len(candles),
    )
