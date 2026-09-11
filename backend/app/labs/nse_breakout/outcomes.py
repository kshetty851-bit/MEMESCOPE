"""What actually happened afterwards. Pure; no session, no clock.

Everything is measured from daily bars only, and from two points:

* **ref_price** — the close on `first_near_date`: what buying the setup at NEAR
  would have done.
* **breakout_price** — the close on the day the breakout confirmed: what buying
  the confirmed breakout would have done.

Both are needed because they answer different questions. Buying at NEAR is
buying an expectation and eats the false breakouts; buying the breakout is
buying a fact and pays a worse price for it. A record that only had one could
not say which.

The trailing stop is evaluated **low before high** — see `trail_result`. That
single ordering is what decides whether these numbers mean anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.labs.nse_breakout import config
from app.labs.nse_breakout.levels import Bar


@dataclass(frozen=True, slots=True)
class Outcome:
    """Returns from one measurement point, in percent.

    `returns` is keyed by horizon in trading days; a horizon the series does
    not reach is **absent**, never zero — the difference between "it went
    nowhere" and "we cannot know yet" is the whole point of a record like this.
    """

    returns: dict[int, float]
    mfe: float | None
    mae: float | None

    def get(self, horizon: int) -> float | None:
        return self.returns.get(horizon)


def _pct(entry: float, exit_price: float) -> float:
    return (exit_price - entry) / entry * 100


def returns_from(entry: float, forward: Sequence[Bar],
                 horizons: Sequence[int] = config.OUTCOME_HORIZONS) -> Outcome:
    """Returns at each horizon, plus excursions over `OUTCOME_WINDOW_DAYS`.

    `forward` is the bars AFTER the measurement bar, oldest first. Horizon `n`
    is the close of the nth of them.
    """
    if entry <= 0:
        return Outcome(returns={}, mfe=None, mae=None)
    got = {n: _pct(entry, float(forward[n - 1].close))
           for n in horizons if len(forward) >= n}
    window = forward[:config.OUTCOME_WINDOW_DAYS]
    if not window:
        return Outcome(returns=got, mfe=None, mae=None)
    return Outcome(
        returns=got,
        mfe=_pct(entry, max(float(b.high) for b in window)),
        mae=_pct(entry, min(float(b.low) for b in window)),
    )


@dataclass(frozen=True, slots=True)
class TrailResult:
    """Where a trailing stop got out, and why."""

    pct: float
    bars_held: int
    stopped: bool


def trail_result(entry: float, forward: Sequence[Bar],
                 trail_pct: float | None = None,
                 max_bars: int | None = None) -> TrailResult | None:
    """A `trail_pct` trailing stop from `entry`, **low before high**.

    On any bar that would both take the stop out and set a new high, the stop
    wins: we cannot see the order within a daily bar, so we assume the order
    that costs us. Getting this backwards is how a backtest invents money, and
    it is the single line that decides whether any of these numbers mean
    anything.

    The high-water mark is raised only AFTER the low has been checked, so a
    stop can never be lifted by a high the price reached after the stop would
    already have been hit.

    Returns None when there are no forward bars at all: an unmeasurable outcome
    is not a zero one.
    """
    if entry <= 0 or not forward:
        return None
    pct = config.TRAIL_PCT if trail_pct is None else trail_pct
    limit = config.TRAIL_MAX_DAYS if max_bars is None else max_bars
    high_water = entry
    for i, bar in enumerate(forward[:limit], start=1):
        stop = high_water * (1 - pct / 100)
        if float(bar.low) <= stop:
            return TrailResult(pct=_pct(entry, stop), bars_held=i, stopped=True)
        high_water = max(high_water, float(bar.high))
    held = forward[:limit]
    return TrailResult(pct=_pct(entry, float(held[-1].close)),
                       bars_held=len(held), stopped=False)


def relative_to_index(stock_pct: float | None, index_closes: Sequence[float],
                      horizon: int) -> float | None:
    """`stock_pct` minus the index's return over the same window.

    Pre-decided: **null, never zero**, when the index is missing for the
    window. Zero is a number and would be averaged into the statistics as
    "matched the market"; null is the absence of one.
    """
    if stock_pct is None or len(index_closes) < horizon + 1:
        return None
    start, end = index_closes[0], index_closes[horizon]
    if start <= 0:
        return None
    return stock_pct - _pct(start, end)
