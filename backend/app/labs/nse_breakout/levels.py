"""Daily bars -> resistance levels. Pure; no session, no clock, no network.

A level here is a CLUSTER of confirmed swing highs sitting within
`CLUSTER_PCT` of each other. One swing high is a price somebody sold at once;
three within two percent is a price somebody sells at, and that is what a
breakout has to get through.

**Nothing in this module may look forward.** A swing high is confirmed only
once the bar `SWING_LOOKBACK` bars after it has closed, so the level set
computed over bars 0..i is identical to the one the full series produces for
bar i. `test_levels.py` asserts that bit for bit on every prefix — it is the
property that makes the replayed episodes a backtest rather than a story, and
it is very easy to lose.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Protocol

from app.labs.nse_breakout import config


class Bar(Protocol):
    """What a daily bar has to have. `BtCandle` satisfies it, and so does any
    hand-built bar in a test — which is the point of not importing the model."""

    date: date

    @property
    def high(self) -> object: ...
    @property
    def low(self) -> object: ...
    @property
    def close(self) -> object: ...
    @property
    def volume(self) -> object: ...


@dataclass(frozen=True, slots=True)
class Cluster:
    """One resistance level: where it sits, how often it was hit, and whether
    price has since closed through it."""

    level: float
    touches: int
    first: date
    last: date
    broken: bool

    def as_dict(self) -> dict[str, object]:
        return {"level": round(self.level, 4), "touches": self.touches,
                "first": self.first.isoformat(), "last": self.last.isoformat(),
                "broken": self.broken}


@dataclass(frozen=True, slots=True)
class Levels:
    """Everything the score and the state machine read off the daily series.

    `nearest_resistance` is None when nothing unbroken sits above the close —
    which means no setup, not an error. A stock at an all-time high has no
    resistance to break, and that is a fact about it, not a gap in the data.
    """

    clusters: tuple[Cluster, ...]
    nearest_resistance: float | None
    is_52w_high: bool
    week52_high: float | None
    atr: float | None
    volume_mean: float | None
    volume_slow_mean: float | None
    range_high: float
    range_low: float
    close: float
    volume: float
    bars: int

    @property
    def distance_pct(self) -> float | None:
        """How far the close is below the nearest unbroken resistance."""
        if self.nearest_resistance is None or self.close <= 0:
            return None
        return (self.nearest_resistance - self.close) / self.close * 100

    @property
    def range_pct(self) -> float | None:
        """The 20-day range as a percentage of its own low."""
        if self.range_low <= 0:
            return None
        return (self.range_high - self.range_low) / self.range_low * 100

    @property
    def tightness(self) -> bool:
        pct = self.range_pct
        return pct is not None and pct < config.TIGHT_RANGE_PCT

    @property
    def volume_mult(self) -> float | None:
        if not self.volume_mean:
            return None
        return self.volume / self.volume_mean


# --- swings -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Swing:
    index: int
    price: float
    at: date
    volume: float


def swing_highs(bars: Sequence[Bar],
                lookback: int = config.SWING_LOOKBACK) -> list[Swing]:
    """Confirmed swing highs, oldest first.

    Bar `i` is a swing high when its high is STRICTLY above every high within
    `lookback` bars on each side. The right-hand side must exist, so the last
    `lookback` bars can never produce one — that is the whole no-hindsight
    guarantee, and it is one `range()` bound.
    """
    if lookback < 1 or len(bars) < 2 * lookback + 1:
        return []
    found: list[Swing] = []
    for i in range(lookback, len(bars) - lookback):
        high = float(bars[i].high)
        window = range(i - lookback, i + lookback + 1)
        if all(float(bars[j].high) < high for j in window if j != i):
            found.append(Swing(i, high, bars[i].date, float(bars[i].volume or 0)))
    return found


# --- clusters -----------------------------------------------------------------

def _vw_mean(swings: Sequence[Swing]) -> float:
    """Volume-weighted mean price. Falls back to the plain mean when no swing
    in the group carries volume — a level with unknown volume is still a level,
    and weighting by zero would make it NaN."""
    total = sum(s.volume for s in swings)
    if total <= 0:
        return sum(s.price for s in swings) / len(swings)
    return sum(s.price * s.volume for s in swings) / total


def cluster_swings(swings: Sequence[Swing],
                   pct: float = config.CLUSTER_PCT) -> list[list[Swing]]:
    """Group swing highs within `pct` of the group's running volume-weighted
    mean. Walked in ascending price, so grouping is deterministic and cannot
    depend on the order the swings were found in."""
    groups: list[list[Swing]] = []
    for swing in sorted(swings, key=lambda s: s.price):
        if groups and abs(swing.price - _vw_mean(groups[-1])) / _vw_mean(groups[-1]) \
                <= pct / 100:
            groups[-1].append(swing)
        else:
            groups.append([swing])
    return groups


def build_clusters(bars: Sequence[Bar], swings: Sequence[Swing],
                   pct: float = config.CLUSTER_PCT) -> list[Cluster]:
    """Swing groups -> clusters, ascending by level.

    **`broken` means a daily close cleared the level by more than
    `BREAK_CONFIRM_PCT`, on a bar AFTER the cluster's last touch.** Two things
    are deliberate there. A bare "close above" would let a cluster be broken by
    one of its own constituent bars, since the level is a volume-weighted mean
    and a swing above that mean usually closed above it too. And requiring the
    1% margin is the same rule the state machine uses to call a BREAKOUT, so a
    level cannot be broken by a move too small to be a breakout.
    """
    margin = 1 + config.BREAK_CONFIRM_PCT / 100
    clusters: list[Cluster] = []
    for group in cluster_swings(swings, pct):
        level = _vw_mean(group)
        last_index = max(s.index for s in group)
        broken = any(float(b.close) > level * margin for b in bars[last_index + 1:])
        clusters.append(Cluster(level=level, touches=len(group),
                                first=min(s.at for s in group),
                                last=max(s.at for s in group), broken=broken))
    clusters.sort(key=lambda c: c.level)
    return clusters


def nearest_resistance(clusters: Sequence[Cluster], close: float) -> float | None:
    """The lowest unbroken level above `close`, or None."""
    above = [c.level for c in clusters if not c.broken and c.level > close]
    return min(above) if above else None


# --- daily statistics ---------------------------------------------------------

def true_ranges(bars: Sequence[Bar]) -> list[float]:
    """`max(h-l, |h-prev_close|, |l-prev_close|)`, one per bar after the first."""
    ranges = []
    for previous, current in pairwise(bars):
        close = float(previous.close)
        high, low = float(current.high), float(current.low)
        ranges.append(max(high - low, abs(high - close), abs(low - close)))
    return ranges


def atr(bars: Sequence[Bar], period: int = config.ATR_PERIOD) -> float | None:
    """Wilder's ATR at the last bar, or None without enough history.

    Wilder rather than a simple mean because every reference implementation is
    Wilder's, and a number that disagrees with the chart the user is looking at
    is worse than no number.
    """
    ranges = true_ranges(bars)
    if period < 1 or len(ranges) < period:
        return None
    value = sum(ranges[:period]) / period
    for current in ranges[period:]:
        value = (value * (period - 1) + current) / period
    return value


def _mean_volume(bars: Sequence[Bar], days: int) -> float | None:
    volumes = [float(b.volume) for b in bars[-days:] if b.volume is not None]
    return sum(volumes) / len(volumes) if volumes else None


def compute(bars: Sequence[Bar],
            min_bars: int = config.MIN_BARS_FOR_LEVELS) -> Levels | None:
    """The whole daily read for one symbol, or None when it is too young.

    `bars` must be closed daily bars, OLDEST FIRST — the order `data.py`
    returns them in. Fewer than `min_bars` returns None rather than a partial
    answer: the pre-decided rule is that a short history stays in the universe
    and out of the levels.
    """
    if len(bars) < min_bars:
        return None
    close = float(bars[-1].close)
    clusters = build_clusters(bars, swing_highs(bars))
    recent = bars[-config.RANGE_DAYS:]
    year = bars[-config.WEEK52_DAYS:]
    week52 = max(float(b.high) for b in year)
    nearest = nearest_resistance(clusters, close)
    return Levels(
        clusters=tuple(clusters),
        nearest_resistance=nearest,
        # The level IS the 52-week high when it sits within a cluster width of
        # it: the level is a volume-weighted mean of several highs, so exact
        # equality with the single highest high would essentially never hold.
        is_52w_high=(nearest is not None
                     and abs(nearest - week52) / week52 <= config.CLUSTER_PCT / 100),
        week52_high=week52,
        atr=atr(bars),
        volume_mean=_mean_volume(bars, config.VOLUME_MEAN_DAYS),
        volume_slow_mean=_mean_volume(bars, config.VOLUME_SLOW_DAYS),
        range_high=max(float(b.high) for b in recent),
        range_low=min(float(b.low) for b in recent),
        close=close,
        volume=float(bars[-1].volume or 0),
        bars=len(bars),
    )
