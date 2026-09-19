"""Candles and what a strategy may read off one. Pure: no session, no clock.

A candle is judged only once it has CLOSED, and only against the bars that
closed before it. Nothing here can see a later bar, which is what keeps every
rule causal — `tests/test_rules.py::test_features_never_read_the_future` holds it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median

from app.labs.momentum import config


def bucket(ts: datetime, seconds: int) -> datetime:
    """The start of the `seconds`-long bar `ts` falls in, on the UTC grid."""
    epoch = int(ts.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC)


@dataclass(frozen=True, slots=True)
class Bar:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    buys: int | None
    sells: int | None
    volume_h24: float | None
    liquidity: float | None
    change_h24: float | None
    samples: int
    #: How many 5m bars built it (1 for a 5m bar).
    parts: int = 1


def bars_per_day(seconds: int) -> int:
    return 86_400 // seconds


def vol_x(bar: Bar, seconds: int) -> float | None:
    """This bar's volume against the pool's average bar over the last day.

    The day is DexScreener's own rolling 24h figure as of the bar's close, so
    the ratio is available from the first bar a token is watched and never
    borrows a later bar's volume.
    """
    if bar.volume is None or not bar.volume_h24 or bar.volume_h24 <= 0:
        return None
    return bar.volume / (bar.volume_h24 / bars_per_day(seconds))


def ret(bar: Bar) -> float:
    return bar.close / bar.open - 1 if bar.open > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Features:
    """Everything a rule may read, measured at the close of `bar`."""

    bar: Bar
    ret: float
    #: Where in its range it closed: 1.0 at the high, 0.0 at the low.
    clv: float
    #: |return| over the token's median |return| of the previous bars.
    body_x: float | None
    vol_x: float | None
    #: Buys per sell inside the bar.
    buy_ratio: float | None
    #: Highest high of the previous `LOOKBACK_BARS` bars.
    prior_high: float | None
    #: Mean close of the previous `TREND_BARS` bars, when that many exist.
    sma: float | None
    #: How many of the previous 12 bars were themselves impulses
    #: (return >= `impulse_ret` on 3x volume), and whether none of the
    #: previous 24 was.
    recent_impulses: int
    quiet: bool
    history: int

    @property
    def green(self) -> bool:
        return self.bar.close > self.bar.open

    @property
    def breakout(self) -> bool:
        return self.prior_high is not None and self.bar.close > self.prior_high

    def as_json(self) -> dict[str, float | int | None]:
        """What a position records about the candle that opened it."""
        def r(v: float | None, n: int = 4) -> float | None:
            return None if v is None else round(v, n)
        return {
            "ret": r(self.ret), "clv": r(self.clv, 3), "body_x": r(self.body_x, 2),
            "vol_x": r(self.vol_x, 2), "buy_ratio": r(self.buy_ratio, 2),
            "volume": r(self.bar.volume, 2), "liquidity": r(self.bar.liquidity, 0),
            "change_h24": r(self.bar.change_h24, 2), "breakout": int(self.breakout),
            "recent_impulses": self.recent_impulses, "history": self.history,
        }


def features(bar: Bar, prior: Sequence[Bar], seconds: int, *,
             impulse_ret: float) -> Features:
    """Measure `bar` against the bars that closed before it.

    `prior` must be in time order and end BEFORE `bar` starts; bars at or
    after `bar.start` are ignored rather than trusted.
    """
    prior = [p for p in prior if p.start < bar.start]
    window = prior[-config.LOOKBACK_BARS:]
    bodies = [abs(ret(p)) for p in window]
    # A floor under the median: a token that printed the same price for two
    # hours has a median body of zero, and any move at all would read as an
    # infinitely large candle.
    base_body = max(median(bodies), 0.001) if bodies else None
    r = ret(bar)
    span = bar.high - bar.low
    clv = (bar.close - bar.low) / span if span > 0 else 0.5
    ratio = None
    if bar.buys is not None and bar.sells is not None:
        ratio = bar.buys / max(bar.sells, 1)
    trend = prior[-config.TREND_BARS:]
    sma = (sum(p.close for p in trend) / len(trend)
           if len(trend) >= int(config.TREND_BARS * 0.8) else None)

    def impulse(p: Bar) -> bool:
        v = vol_x(p, seconds)
        return ret(p) >= impulse_ret and v is not None and v >= 3

    return Features(
        bar=bar, ret=r, clv=clv,
        body_x=abs(r) / base_body if base_body else None,
        vol_x=vol_x(bar, seconds), buy_ratio=ratio,
        prior_high=max(p.high for p in window) if window else None,
        sma=sma,
        recent_impulses=sum(1 for p in prior[-12:] if impulse(p)),
        quiet=not any(impulse(p) for p in window),
        history=len(window),
    )

